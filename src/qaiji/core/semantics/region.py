# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""region：循环体与条件体的结构路径标识，以及引用它们的 L4 注解。"""

import dataclasses
from dataclasses import dataclass
from typing import Literal

from qaiji.core.circuit import Circuit
from qaiji.core.loop import LoopedCircuit
from qaiji.core.semantics.annotation import SemanticAnnotation
from qaiji.core.semantics.registry import annotate_circuit

__all__ = ["Region", "annotate_looped", "regions_of"]


@dataclass(frozen=True, slots=True)
class Region:
    """一个循环体或条件体。只描述结构位置，不携带量子控制信息。

    标识是结构路径：顶层条件体 ``if:<位置>``，循环体 ``loop:<位置>``，
    循环内条件体 ``loop:<位置>/if:<循环体内位置>``。位置按节点计数，声明不计入。

    Example:
        >>> Region(id="loop:0/if:3", kind="conditional_body", parent="loop:0").parent
        'loop:0'
    """

    id: str
    kind: Literal["loop_body", "conditional_body"]
    parent: str | None


def regions_of(circuit: Circuit | LoopedCircuit) -> tuple[Region, ...]:
    """按文档顺序列出电路中的 region，父 region 排在子 region 之前。

    标识取自展开结果的来源记录，所以只列出展开后有操作的 region：
    0 次迭代的循环没有 region。循环体只含条件体时，循环体仍作为父 region 列出。

    Args:
        circuit: 平坦电路或含有界循环的电路。

    Returns:
        去重后的 region 元组。
    """
    if isinstance(circuit, Circuit):
        circuit = LoopedCircuit(circuit.num_qubits, tuple(circuit.cregs), tuple(circuit.gates))
    regions: dict[str, Region] = {}
    for provenance in circuit.expand().provenance:
        if provenance.region_id is None or provenance.region_id in regions:
            continue
        parent, _, leaf = provenance.region_id.rpartition("/")
        if parent and parent not in regions:
            regions[parent] = Region(id=parent, kind="loop_body", parent=None)
        kind: Literal["loop_body", "conditional_body"] = (
            "conditional_body" if leaf.startswith("if:") else "loop_body"
        )
        regions[provenance.region_id] = Region(
            id=provenance.region_id, kind=kind, parent=parent or None
        )
    return tuple(regions.values())


def annotate_looped(circuit: LoopedCircuit) -> tuple[SemanticAnnotation, ...]:
    """在展开电路上标注每个操作，并填写它所在 region 的标识。

    除 ``region_id`` 外，结果与 ``annotate_circuit(circuit.expand().circuit)`` 相同。

    Args:
        circuit: 含有界循环的电路。

    Returns:
        注解元组；不在任何 region 内的操作，其 ``region_id`` 为 ``None``。
    """
    expanded = circuit.expand()
    return tuple(
        dataclasses.replace(
            annotation, region_id=expanded.provenance[annotation.gate_index].region_id
        )
        for annotation in annotate_circuit(expanded.circuit)
    )
