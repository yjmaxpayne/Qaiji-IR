# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""R1-R4 保持性裁决流水线：一次变换是否保持算符相等？

分类（registry.py）回答的是"这个操作对测量统计做了什么"；本模块回答的是另一个
问题 —— "变换后电路的算符是否仍与原电路相等（可差一个全局相位）"。二者是共存而非
冲突的关系：RZ(2*pi) 在分类上是 IDENTITY（测量统计分桶），而本模块判定它为
UP_TO_PHASE（代数上差一个 -1 因子），因为这是两条正交的 L4 坐标轴。
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any

from qaiji.core.circuit import (
    _ROTATION_GATES,
    Circuit,
    Gate,
    GateType,
    _node_eq,
    _tau_multiple_exponent,
)
from qaiji.core.classical import Conditional, Measure
from qaiji.core.gate_matrix import _Matrix, source_operator
from qaiji.core.loop import BoundedLoop, ConditionalTemplate, GateTemplate, LoopedCircuit
from qaiji.core.semantics.region import regions_of
from qaiji.core.semantics.registry import annotate_circuit
from qaiji.core.semantics.types import EquivLevel, MorphismType
from qaiji.exceptions import LoopNotExpandedError, UnsupportedEquivLevelError

__all__ = ["PreservationSummary", "check_preservation"]

_KNOWN_STAGES = frozenset({"canonicalize", "codec_roundtrip", "unspecified_transform"})
_STATUS_VALUES = frozenset({"passed", "warning", "failed", "unsupported", "planned"})

MAX_LOCAL_QUBITS = 6
"""按 region 判定时，一个实例两侧作用比特并集的上限（含）。"""
MAX_LOCAL_GATES = 256
"""按 region 判定时，目标 region 全部实例两侧门数总和的上限（含）。"""
MAX_LOCAL_RESIDUAL = 1e-10
"""按 region 判定时的残差阈值：W 与（相位）单位阵的逐元偏差，以及各单比特切分的
归一化第二奇异值，都须不超过此值。"""

_JACOBI_RELATIVE_TOLERANCE = 1e-15
_JACOBI_MAX_SWEEPS = 30
_LEVEL_STRENGTH = (EquivLevel.EXACT, EquivLevel.UP_TO_PHASE, EquivLevel.UP_TO_LOCAL)
_UNSUPPORTED: tuple[str, EquivLevel | None] = ("unsupported", None)

_MORPHISM_DOMINANCE = (
    MorphismType.MEASUREMENT,
    MorphismType.UNITARY,
    MorphismType.PERMUTATION,
    MorphismType.PHASE,
    MorphismType.IDENTITY,
    MorphismType.CLASSICAL_CTRL,
)
"""仅用于诊断的聚合优先级顺序；CLASSICAL_CTRL 优先级最低，因此一个纯 Conditional
构成的电路报告的是其体内的态射，而不是它的控制外形。
"""


@dataclass(frozen=True, slots=True)
class PreservationSummary:
    """针对一次受检变换的裁决，沿用上游的 8 字段形状。

    Example:
        >>> from qaiji.core.semantics.preservation import PreservationSummary
        >>> from qaiji.core.semantics.types import EquivLevel
        >>> PreservationSummary(status="passed", equiv_level=EquivLevel.EXACT).status
        'passed'
    """

    stage: str = "unspecified_transform"
    status: str = "planned"
    diagnostic_count: int = 0
    failed_gate_indices: tuple[int, ...] = ()
    equiv_level: EquivLevel | None = None
    original_morphism: MorphismType | None = None
    lowered_morphism: MorphismType | None = None
    pass_trace_ref: str | None = None

    def __post_init__(self) -> None:
        """归一化下标，并拒绝白名单之外的 stage / status 取值。"""
        object.__setattr__(self, "failed_gate_indices", tuple(self.failed_gate_indices))

        if self.stage not in _KNOWN_STAGES:
            raise ValueError(f"stage must be one of {sorted(_KNOWN_STAGES)}, got {self.stage!r}")
        if self.status not in _STATUS_VALUES:
            raise ValueError(f"status must be one of {sorted(_STATUS_VALUES)}, got {self.status!r}")


def _dominant_morphism(circuit: Circuit) -> MorphismType | None:
    """仅用于诊断的聚合态射，按 _MORPHISM_DOMINANCE 的优先级得出。"""
    present = {annotation.morphism for annotation in annotate_circuit(circuit)}
    for candidate in _MORPHISM_DOMINANCE:
        if candidate in present:
            return candidate
    return None


def _top_level_measures(circuit: Circuit) -> list[tuple[int, Measure]]:
    return [(index, op) for index, op in enumerate(circuit.gates) if isinstance(op, Measure)]


def _first_measure_mismatch(
    original_measures: list[tuple[int, Measure]],
    transformed_measures: list[tuple[int, Measure]],
) -> int:
    """两个 measure 序列按前缀对齐后首次分叉的位置。

    走到较短序列的末尾仍未发现分叉时，把该长度本身算作失配点：这正是尾部增删所
    产生的边界，也是唯一一种原电路侧无需归咎任何节点的情形。
    """
    for position, (original, transformed) in enumerate(
        zip(original_measures, transformed_measures, strict=False)
    ):
        if not _node_eq(original[1], transformed[1]):
            return position
    return min(len(original_measures), len(transformed_measures))


def _same_node_kind(
    left: Gate | Measure | Conditional, right: Gate | Measure | Conditional
) -> bool:
    return (
        (isinstance(left, Gate) and isinstance(right, Gate))
        or (isinstance(left, Measure) and isinstance(right, Measure))
        or (isinstance(left, Conditional) and isinstance(right, Conditional))
    )


def _gate_diff_exponent(left: Gate, right: Gate) -> int | None:
    """按 R1-R4 对一组门配对做分类；返回 None 表示该配对超出判定范围。"""
    if _node_eq(left, right):  # R1：结构相等，k=0。
        return 0
    if (  # R2：CNOT/CX 别名，作用比特相同，k=0。
        {left.gate_type, right.gate_type} == {GateType.CNOT, GateType.CX}
        and left.qubits == right.qubits
    ):
        return 0
    if (  # R3：同一旋转轴与同一比特，delta = 2*pi*k。
        left.gate_type is right.gate_type
        and left.gate_type in _ROTATION_GATES
        and left.qubits == right.qubits
    ):
        return _tau_multiple_exponent(right.params[0] - left.params[0])
    for rotation, identity in ((left, right), (right, left)):  # R4：rotation<->I，theta = 2*pi*k。
        if (
            rotation.gate_type in _ROTATION_GATES
            and identity.gate_type is GateType.I
            and rotation.qubits == identity.qubits
        ):
            return _tau_multiple_exponent(rotation.params[0])
    return None


_Instance = tuple[tuple[Gate, ...], tuple[Gate, ...]]
_Columns = list[list[complex]]


def _top_nodes(circuit: Circuit | LoopedCircuit) -> tuple[object, ...]:
    return tuple(circuit.gates) if isinstance(circuit, Circuit) else circuit.operations


def _same_node(left: object, right: object) -> bool:
    if isinstance(left, BoundedLoop) or isinstance(right, BoundedLoop):
        return left == right
    assert isinstance(left, Gate | Measure | Conditional)
    assert isinstance(right, Gate | Measure | Conditional)
    return _node_eq(left, right)


def _same_condition(left: object, right: object) -> bool:
    if isinstance(left, Conditional) and isinstance(right, Conditional):
        return (left.register, left.value, left.bit_index) == (
            right.register,
            right.value,
            right.bit_index,
        )
    if isinstance(left, ConditionalTemplate) and isinstance(right, ConditionalTemplate):
        return (left.register, left.value, left.bit) == (right.register, right.value, right.bit)
    return False


def _same_shell(left: object, right: object, body_position: int | None) -> bool:
    """比较目标 region 所在的顶层节点：条件与循环边界相同，region 之外的循环体节点相同。"""
    if not (isinstance(left, BoundedLoop) and isinstance(right, BoundedLoop)):
        return _same_condition(left, right)
    if dataclasses.replace(left, body=()) != dataclasses.replace(right, body=()):
        return False
    if body_position is None:
        return True
    if len(left.body) != len(right.body):
        return False
    return all(
        _same_condition(left_node, right_node)
        if position == body_position
        else left_node == right_node
        for position, (left_node, right_node) in enumerate(zip(left.body, right.body, strict=True))
    )


def _region_operations(circuit: LoopedCircuit, region: str) -> list[Any]:
    """返回展开后来源为 ``region`` 的操作，按执行顺序排列。"""
    expanded = circuit.expand()
    return [
        operation
        for operation, provenance in zip(expanded.circuit.gates, expanded.provenance, strict=True)
        if provenance.region_id == region
    ]


def _region_instances(
    original: Circuit | LoopedCircuit, transformed: Circuit | LoopedCircuit, region: str
) -> list[_Instance] | None:
    """按结构前提与门数上限取目标 region 的实例；不满足时返回 None。

    门数在展开之前按「迭代数 × 体门数」计算，两侧合计。
    """
    regions = regions_of(original)
    if (
        original.num_qubits != transformed.num_qubits
        or original.cregs != transformed.cregs
        or regions != regions_of(transformed)
        or region not in {candidate.id for candidate in regions}
    ):
        return None
    head, _, leaf = region.partition("/")
    position = int(head.split(":")[1])
    body_position = int(leaf.split(":")[1]) if leaf else None
    left_nodes, right_nodes = _top_nodes(original), _top_nodes(transformed)
    if len(left_nodes) != len(right_nodes) or not all(
        _same_shell(left, right, body_position) if index == position else _same_node(left, right)
        for index, (left, right) in enumerate(zip(left_nodes, right_nodes, strict=True))
    ):
        return None

    left, right = left_nodes[position], right_nodes[position]
    if isinstance(left, Conditional) and isinstance(right, Conditional):
        if len(left.body) + len(right.body) > MAX_LOCAL_GATES:
            return None
        return [(tuple(left.body), tuple(right.body))]
    assert isinstance(original, LoopedCircuit) and isinstance(transformed, LoopedCircuit)
    assert isinstance(left, BoundedLoop) and isinstance(right, BoundedLoop)
    iterations = len(left.values)
    if body_position is None:
        if not all(isinstance(node, GateTemplate) for node in left.body + right.body):
            return None
        if iterations * (len(left.body) + len(right.body)) > MAX_LOCAL_GATES:
            return None
        before = _region_operations(original, region)
        after = _region_operations(transformed, region)
        return [(tuple(before), tuple(after))]
    left_template, right_template = left.body[body_position], right.body[body_position]
    assert isinstance(left_template, ConditionalTemplate)
    assert isinstance(right_template, ConditionalTemplate)
    if iterations == 0:
        return None
    if iterations * (len(left_template.body) + len(right_template.body)) > MAX_LOCAL_GATES:
        return None
    pairs = zip(
        _region_operations(original, region), _region_operations(transformed, region), strict=True
    )
    return [(tuple(before.body), tuple(after.body)) for before, after in pairs]


def _dagger(operator: _Matrix) -> _Matrix:
    size = len(operator)
    return tuple(
        tuple(complex(operator[column][row]).conjugate() for column in range(size))
        for row in range(size)
    )


def _apply(columns: _Columns, operator: _Matrix, positions: list[int]) -> None:
    """把门左乘到每一列上；门矩阵下标以首个比特为高位。"""
    arity = len(positions)
    mask = sum(1 << position for position in positions)
    offsets = [
        sum(((local >> (arity - 1 - k)) & 1) << position for k, position in enumerate(positions))
        for local in range(1 << arity)
    ]
    bases = [base for base in range(len(columns)) if not base & mask]
    for column in columns:
        for base in bases:
            indices = [base | offset for offset in offsets]
            amplitudes = [column[index] for index in indices]
            for row, index in zip(operator, indices, strict=True):
                column[index] = sum(
                    (entry * amplitude for entry, amplitude in zip(row, amplitudes, strict=True)),
                    0j,
                )


def _relative_operator(
    before: list[tuple[_Matrix, list[int]]], after: list[tuple[_Matrix, list[int]]], size: int
) -> _Columns:
    """返回 ``W = U_after·U_before†`` 的列表示：``columns[c][r] = W[r][c]``。"""
    dim = 1 << size
    columns = [[complex(row == column) for row in range(dim)] for column in range(dim)]
    for operator, positions in reversed(before):
        _apply(columns, _dagger(operator), positions)
    for operator, positions in after:
        _apply(columns, operator, positions)
    return columns


def _singular_values(rows: list[list[complex]]) -> list[float] | None:
    """单边 Jacobi 求行向量组的奇异值，降序；轮数用尽仍未收敛时返回 None。

    收敛判据是相对内积 ``|<r_i, r_j>| <= 1e-15·|r_i|·|r_j|``，它保留小奇异值的相对精度。
    ``M·M†`` 的特征值把小奇异值平方，平方后低于舍入误差。
    范数不超过总范数 1e-15 倍的行按零行处理，不再旋转：这样的行只剩舍入残差，
    它与另一行的相对内积不会下降。
    """
    rows = [list(row) for row in rows]
    negligible = _JACOBI_RELATIVE_TOLERANCE**2 * sum(abs(x) ** 2 for row in rows for x in row)
    for _ in range(_JACOBI_MAX_SWEEPS):
        rotated = False
        for i in range(len(rows) - 1):
            for j in range(i + 1, len(rows)):
                left, right = rows[i], rows[j]
                a = sum(abs(x) ** 2 for x in left)
                b = sum(abs(x) ** 2 for x in right)
                c = sum((x.conjugate() * y for x, y in zip(left, right, strict=True)), 0j)
                if min(a, b) <= negligible or abs(c) <= _JACOBI_RELATIVE_TOLERANCE * math.sqrt(
                    a * b
                ):
                    continue
                rotated = True
                phase = c / abs(c)
                zeta = (b - a) / (2 * abs(c))
                tangent = (
                    math.copysign(1.0, zeta) / (abs(zeta) + math.sqrt(1 + zeta * zeta))
                    if zeta
                    else 1.0
                )
                cosine = 1 / math.sqrt(1 + tangent * tangent)
                sine = cosine * tangent
                rows[i] = [
                    cosine * x - sine * phase.conjugate() * y
                    for x, y in zip(left, right, strict=True)
                ]
                rows[j] = [sine * phase * x + cosine * y for x, y in zip(left, right, strict=True)]
        if not rotated:
            return sorted((math.sqrt(sum(abs(x) ** 2 for x in row)) for row in rows), reverse=True)
    return None


def _cut_rows(columns: _Columns, position: int) -> list[list[complex]]:
    """把 W 按（比特 ``position`` | 其余比特）重排成 4 行矩阵。"""
    bit = 1 << position
    rest = [index for index in range(len(columns)) if not index & bit]
    return [
        [columns[column | column_bit][row | row_bit] for column in rest for row in rest]
        for row_bit in (0, bit)
        for column_bit in (0, bit)
    ]


def _instance_verdict(before: tuple[Gate, ...], after: tuple[Gate, ...]) -> EquivLevel | str:
    """判定一个实例；返回等级，或 ``"failed"``、``"unsupported"``。"""
    qubits = sorted({qubit for gate in before + after for qubit in gate.qubits})
    if not qubits:
        return EquivLevel.EXACT
    index_of = {qubit: index for index, qubit in enumerate(qubits)}

    def placed(gates: tuple[Gate, ...]) -> list[tuple[_Matrix, list[int]]]:
        return [(source_operator(gate), [index_of[q] for q in gate.qubits]) for gate in gates]

    columns = _relative_operator(placed(before), placed(after), len(qubits))
    dim = len(columns)

    def close_to(scalar: complex) -> bool:
        return all(
            abs(columns[column][row] - (scalar if row == column else 0)) <= MAX_LOCAL_RESIDUAL
            for column in range(dim)
            for row in range(dim)
        )

    if close_to(1):
        return EquivLevel.EXACT
    if close_to(columns[0][0]):
        return EquivLevel.UP_TO_PHASE
    # 只有 1 个比特时 W 本身是局域算符，没有切分。
    for cut in range(len(qubits) if len(qubits) > 1 else 0):
        values = _singular_values(_cut_rows(columns, cut))
        if values is None:
            return "unsupported"
        if not values[1] / math.sqrt(sum(v * v for v in values)) <= MAX_LOCAL_RESIDUAL:
            return "failed"
    return EquivLevel.UP_TO_LOCAL


def _region_verdict(
    original: Circuit | LoopedCircuit, transformed: Circuit | LoopedCircuit, region: str
) -> tuple[str, EquivLevel | None]:
    """按 region 判定 UP_TO_LOCAL，返回 ``(status, equiv_level)``。"""
    if type(original) is not type(transformed):
        return _UNSUPPORTED
    instances = _region_instances(original, transformed, region)
    if instances is None:
        return _UNSUPPORTED
    for before, after in instances:
        if len({qubit for gate in before + after for qubit in gate.qubits}) > MAX_LOCAL_QUBITS:
            return _UNSUPPORTED
        try:
            for gate in before + after:
                source_operator(gate)
        except ValueError:
            return _UNSUPPORTED
    verdicts = [_instance_verdict(before, after) for before, after in instances]
    if "failed" in verdicts:
        return ("failed", None)
    if "unsupported" in verdicts:
        return _UNSUPPORTED
    levels = [verdict for verdict in verdicts if isinstance(verdict, EquivLevel)]
    return ("passed", max(levels, key=_LEVEL_STRENGTH.index, default=EquivLevel.EXACT))


def check_preservation(
    original: Circuit | LoopedCircuit,
    transformed: Circuit | LoopedCircuit,
    *,
    stage: str = "unspecified_transform",
    requested_level: EquivLevel = EquivLevel.UP_TO_PHASE,
    region: str | None = None,
) -> PreservationSummary:
    """判定 ``transformed`` 是否保持了 ``original`` 的算符语义。

    流水线是严格的优先级顺序：测量湮灭（第 1 步）压过判定域前置条件（第 2 步），
    后者又压过逐位置的 R1-R4 比对（第 3-4 步）。任何落在可判定集合之外的情况一律
    判为 ``unsupported``，绝不给出一个静默错误的 ``passed``，见 I-Q4.6。

    Args:
        original: 变换前的电路。
        transformed: 变换后的电路。
        stage: 本次裁决针对的是哪一个受检变换。
        requested_level: 调用方能接受的等价上限。``EXACT`` 要求全局相位已抵消；
            ``UP_TO_PHASE`` 为默认值，两者皆可接受。``UP_TO_LOCAL`` 只在给出
            ``region`` 时判定，未给出时判为 ``unsupported``。
        region: 要判定的 region 标识，取自 ``regions_of``。给出时只按该 region
            判定 ``UP_TO_LOCAL``：两侧在该 region 之外须逐个节点相同，否则判为
            ``unsupported``。与 ``EXACT``、``UP_TO_PHASE`` 同用时判为 ``unsupported``。

    Returns:
        一个 ``PreservationSummary``。现有流水线在包括 ``failed``/``unsupported``
        在内的每条分支上都填好诊断用的态射字段。``UP_TO_LOCAL`` 与 ``region``
        的分支不填态射字段，两者保持 ``None``。

    Raises:
        UnsupportedEquivLevelError: ``requested_level`` 为 ``ENTANGLEMENT``。
        LoopNotExpandedError: 未给出 ``region``、``requested_level`` 为 ``EXACT`` 或
            ``UP_TO_PHASE``，且任一侧是未展开的 ``LoopedCircuit``。
        ValueError: ``stage`` 不属于已知的 stage 字面量（由本次调用构造的第一个
            裁决在 ``PreservationSummary.__post_init__`` 中抛出）。
    """
    if requested_level is EquivLevel.ENTANGLEMENT:
        raise UnsupportedEquivLevelError(
            f"check_preservation cannot decide requested_level={requested_level.value}"
        )
    if region is not None or requested_level is EquivLevel.UP_TO_LOCAL:
        status, equiv_level = (
            _region_verdict(original, transformed, region)
            if region is not None and requested_level is EquivLevel.UP_TO_LOCAL
            else _UNSUPPORTED
        )
        return PreservationSummary(stage=stage, status=status, equiv_level=equiv_level)
    if not (isinstance(original, Circuit) and isinstance(transformed, Circuit)):
        raise LoopNotExpandedError("Expand the looped circuit before checking preservation")

    original_morphism = _dominant_morphism(original)
    lowered_morphism = _dominant_morphism(transformed)

    # 第 1 步：测量数量是优先级最高的裁决坐标轴。
    original_measures = _top_level_measures(original)
    transformed_measures = _top_level_measures(transformed)
    if len(original_measures) != len(transformed_measures):
        mismatch_at = _first_measure_mismatch(original_measures, transformed_measures)
        return PreservationSummary(
            stage=stage,
            status="failed",
            failed_gate_indices=tuple(index for index, _ in original_measures[mismatch_at:]),
            original_morphism=original_morphism,
            lowered_morphism=lowered_morphism,
        )

    # 第 2 步：判定域的前置条件。
    if original.num_qubits != transformed.num_qubits:
        return PreservationSummary(
            stage=stage,
            status="unsupported",
            original_morphism=original_morphism,
            lowered_morphism=lowered_morphism,
        )
    if original.cregs != transformed.cregs:
        return PreservationSummary(
            stage=stage,
            status="unsupported",
            original_morphism=original_morphism,
            lowered_morphism=lowered_morphism,
        )
    if len(original.gates) != len(transformed.gates):
        return PreservationSummary(
            stage=stage,
            status="unsupported",
            original_morphism=original_morphism,
            lowered_morphism=lowered_morphism,
        )
    node_pairs = list(zip(original.gates, transformed.gates, strict=True))
    first_kind_mismatch = next(
        (
            index
            for index, (left, right) in enumerate(node_pairs)
            if not _same_node_kind(left, right)
        ),
        None,
    )
    if first_kind_mismatch is not None:
        return PreservationSummary(
            stage=stage,
            status="unsupported",
            failed_gate_indices=(first_kind_mismatch,),
            original_morphism=original_morphism,
            lowered_morphism=lowered_morphism,
        )

    # 第 3 步：逐位置的 R1-R4 比对。节点种类已经两两匹配（第 2 步保证了这一点），
    # 因此每条分支只需对其中一侧做 isinstance 检查。
    violations: list[int] = []
    phase_exponent = 0
    for index, (left, right) in enumerate(node_pairs):
        if isinstance(left, Gate):
            assert isinstance(right, Gate)
            exponent = _gate_diff_exponent(left, right)
            if exponent is None:
                violations.append(index)
            else:
                phase_exponent += exponent
        elif isinstance(left, Measure):
            if left != right:
                violations.append(index)
        else:
            assert isinstance(left, Conditional)
            assert isinstance(right, Conditional)
            if (
                left.register != right.register
                or left.value != right.value
                or left.bit_index != right.bit_index
                or len(left.body) != len(right.body)
            ):
                violations.append(index)
                continue
            body_violation = False
            for body_left, body_right in zip(left.body, right.body, strict=True):
                exponent = _gate_diff_exponent(body_left, body_right)
                if exponent is None:
                    body_violation = True
                else:
                    phase_exponent += exponent
            if body_violation:
                violations.append(index)

    # 第 4 步：汇总。收集是穷尽式的（I-Q4.6）：诊断覆盖整个位置集合，而不是只报
    # 第一个出问题的位置。
    if violations:
        return PreservationSummary(
            stage=stage,
            status="unsupported",
            failed_gate_indices=tuple(violations),
            original_morphism=original_morphism,
            lowered_morphism=lowered_morphism,
        )

    equiv_level = EquivLevel.EXACT if phase_exponent % 2 == 0 else EquivLevel.UP_TO_PHASE
    if equiv_level is EquivLevel.UP_TO_PHASE and requested_level is EquivLevel.EXACT:
        return PreservationSummary(
            stage=stage,
            status="unsupported",
            equiv_level=EquivLevel.UP_TO_PHASE,
            original_morphism=original_morphism,
            lowered_morphism=lowered_morphism,
        )

    return PreservationSummary(
        stage=stage,
        status="passed",
        equiv_level=equiv_level,
        original_morphism=original_morphism,
        lowered_morphism=lowered_morphism,
    )
