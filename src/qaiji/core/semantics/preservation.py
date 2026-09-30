# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""R1-R4 保持性裁决流水线：一次变换是否保持算符相等？

分类（registry.py）回答的是"这个操作对测量统计做了什么"；本模块回答的是另一个
问题 —— "变换后电路的算符是否仍与原电路相等（可差一个全局相位）"。二者是共存而非
冲突的关系：RZ(2*pi) 在分类上是 IDENTITY（测量统计分桶），而本模块判定它为
UP_TO_PHASE（代数上差一个 -1 因子），因为这是两条正交的 L4 坐标轴。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from qaiji.core.circuit import _ROTATION_GATES, Gate, GateType, _node_eq, _tau_multiple_exponent
from qaiji.core.classical import Conditional, Measure
from qaiji.core.semantics.registry import annotate_circuit
from qaiji.core.semantics.types import EquivLevel, MorphismType
from qaiji.exceptions import UnsupportedEquivLevelError

if TYPE_CHECKING:
    from qaiji.core.circuit import Circuit

__all__ = ["PreservationSummary", "check_preservation"]

_KNOWN_STAGES = frozenset({"canonicalize", "codec_roundtrip", "unspecified_transform"})
_STATUS_VALUES = frozenset({"passed", "warning", "failed", "unsupported", "planned"})
_UNDECIDABLE_REQUEST_LEVELS = frozenset({EquivLevel.UP_TO_LOCAL, EquivLevel.ENTANGLEMENT})

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


def check_preservation(
    original: Circuit,
    transformed: Circuit,
    *,
    stage: str = "unspecified_transform",
    requested_level: EquivLevel = EquivLevel.UP_TO_PHASE,
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
            ``UP_TO_PHASE`` 为默认值，两者皆可接受。

    Returns:
        一个 ``PreservationSummary``，在包括 ``failed``/``unsupported`` 在内的每条
        分支上都填好了诊断用的态射字段。

    Raises:
        UnsupportedEquivLevelError: ``requested_level`` 为 ``UP_TO_LOCAL`` 或
            ``ENTANGLEMENT`` —— 本流水线无法判定。
        ValueError: ``stage`` 不属于已知的 stage 字面量（由本次调用构造的第一个
            裁决在 ``PreservationSummary.__post_init__`` 中抛出）。
    """
    if requested_level in _UNDECIDABLE_REQUEST_LEVELS:
        raise UnsupportedEquivLevelError(
            f"check_preservation cannot decide requested_level={requested_level.value}"
        )

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
