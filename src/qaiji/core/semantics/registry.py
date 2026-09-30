# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""将电路操作分类到语义词汇表中。

合法 ``Circuit`` 能承载的每一种操作在这里都是可判定的；任何落在表格之外的东西都会
抛异常，而不是回退到某个默认分桶：一次静默的默认分类会把未经验证的操作推进下游的
规范化哈希和保持性裁决里。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qaiji.core.circuit import Gate, GateType, _tau_multiple_exponent
from qaiji.core.classical import Conditional, Measure
from qaiji.core.semantics.annotation import SENTINEL_GATE_INDEX, SemanticAnnotation
from qaiji.core.semantics.types import CartanRole, EquivLevel, MorphismType

if TYPE_CHECKING:
    from qaiji.core.circuit import Circuit

__all__ = ["annotate_circuit", "classify_operation"]

RZ_IDENTITY_NOTE = "rz:identity-equivalent"
"""标记一个因转角为整圈而被折叠成恒等的 RZ。"""

_GATE_MORPHISM: dict[GateType, MorphismType] = {
    GateType.I: MorphismType.IDENTITY,
    GateType.X: MorphismType.PERMUTATION,
    GateType.CNOT: MorphismType.PERMUTATION,
    GateType.CX: MorphismType.PERMUTATION,
    GateType.SWAP: MorphismType.PERMUTATION,
    GateType.Z: MorphismType.PHASE,
    GateType.S: MorphismType.PHASE,
    GateType.T: MorphismType.PHASE,
    GateType.CZ: MorphismType.PHASE,
    GateType.RZ: MorphismType.PHASE,
    GateType.H: MorphismType.UNITARY,
    GateType.Y: MorphismType.UNITARY,
    GateType.RX: MorphismType.UNITARY,
    GateType.RY: MorphismType.UNITARY,
    GateType.RX90: MorphismType.UNITARY,
    GateType.RX180: MorphismType.UNITARY,
    GateType.U3: MorphismType.UNITARY,
    GateType.ISWAP: MorphismType.UNITARY,
    GateType.SQISWAP: MorphismType.UNITARY,
}
"""各门类型对应的态射分桶；RZ 会在下文按其转角进一步细化。"""

_GATE_CARTAN: dict[GateType, CartanRole] = {
    GateType.I: CartanRole.NONE,
    GateType.X: CartanRole.K,
    GateType.Y: CartanRole.K,
    GateType.Z: CartanRole.K,
    GateType.H: CartanRole.K,
    GateType.S: CartanRole.K,
    GateType.T: CartanRole.K,
    GateType.RX: CartanRole.K,
    GateType.RY: CartanRole.K,
    GateType.RZ: CartanRole.K,
    GateType.U3: CartanRole.K,
    GateType.RX90: CartanRole.K,
    GateType.RX180: CartanRole.K,
    GateType.CNOT: CartanRole.MIXED,
    GateType.CX: CartanRole.MIXED,
    GateType.SWAP: CartanRole.MIXED,
    GateType.CZ: CartanRole.A,
    GateType.ISWAP: CartanRole.A,
    GateType.SQISWAP: CartanRole.A,
}
"""各门类型对应的参考性 Cartan 角色；绝不作为裁决的输入。"""


def _classify_gate(gate: Gate, gate_index: int, body_offset: int | None) -> SemanticAnnotation:
    """对一个位置已知的门做分类。"""
    morphism = _GATE_MORPHISM[gate.gate_type]
    notes: tuple[str, ...] = ()

    if gate.gate_type is GateType.RZ and _tau_multiple_exponent(gate.params[0]) is not None:
        morphism = MorphismType.IDENTITY
        notes = (RZ_IDENTITY_NOTE,)

    return SemanticAnnotation(
        gate_index=gate_index,
        morphism=morphism,
        equiv_level=EquivLevel.EXACT,
        cartan=_GATE_CARTAN[gate.gate_type],
        body_offset=body_offset,
        notes=notes,
    )


def classify_operation(
    op: Gate | Measure | Conditional, *, gate_index: int = SENTINEL_GATE_INDEX
) -> tuple[SemanticAnnotation, ...]:
    """将一个操作节点分类为一条或多条标注。

    Gate 或 Measure 产出一条标注。Conditional 产出一条节点级的 CLASSICAL_CTRL
    裁决，后面跟着体内每个门各一条标注、各自携带该门自身的态射：分支语义归属于
    节点本身，因此改写体内标注会导致控制被重复计算，同时丢失分支实际执行的内容。

    Args:
        op: 一个 Gate、Measure 或 Conditional 节点。
        gate_index: 该节点在 ``Circuit.gates`` 中的位置。默认值 -1 标记这是一次
            游离探针；用它产出的结果不得拼接成序列（那种场景请用
            ``annotate_circuit``）。

    Returns:
        按位置顺序排列的标注。

    Raises:
        KeyError: 该门类型不在分类表中。
        TypeError: ``op`` 不属于三种操作节点类型之一。
    """
    if isinstance(op, Gate):
        return (_classify_gate(op, gate_index, None),)

    if isinstance(op, Measure):
        return (
            SemanticAnnotation(
                gate_index=gate_index,
                morphism=MorphismType.MEASUREMENT,
                equiv_level=EquivLevel.EXACT,
                cartan=CartanRole.NONE,
            ),
        )

    if isinstance(op, Conditional):
        node = SemanticAnnotation(
            gate_index=gate_index,
            morphism=MorphismType.CLASSICAL_CTRL,
            equiv_level=EquivLevel.EXACT,
            cartan=CartanRole.NONE,
        )
        body = tuple(
            _classify_gate(gate, gate_index, offset) for offset, gate in enumerate(op.body)
        )
        return (node, *body)

    raise TypeError(f"Cannot classify {type(op).__name__}: expected Gate, Measure, or Conditional")


def annotate_circuit(circuit: Circuit) -> tuple[SemanticAnnotation, ...]:
    """对整个电路做分类，并为每条标注分配位置。

    这是编号的权威入口：下标在这里生成，而不是由调用方事后回填，因此没有任何标注
    能带着"游离探针"哨兵值逃逸出去。

    Args:
        circuit: 待标注的电路。

    Returns:
        按顶层顺序排列的标注，每个 Conditional 紧跟其体内标注。

    Raises:
        KeyError: 由无法分类的门类型向上传播。
        TypeError: 由非预期的节点类型向上传播。
    """
    return tuple(
        annotation
        for index, operation in enumerate(circuit.gates)
        for annotation in classify_operation(operation, gate_index=index)
    )
