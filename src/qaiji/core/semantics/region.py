# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""region：循环体与条件体的结构路径标识，以及引用它们的 L4 注解。"""

import dataclasses
from dataclasses import dataclass
from typing import Literal

from qaiji.core.circuit import Circuit
from qaiji.core.classical import Conditional
from qaiji.core.loop import BoundedLoop, ConditionalTemplate, LoopedCircuit
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
    """按文档顺序列出电路中的 region：循环体排在它的内层条件体之前。

    只遍历节点结构，不展开循环。所以 0 次迭代的循环与空体循环也列出，
    成本与迭代数无关。标识规则与 :meth:`LoopedCircuit.expand` 的来源记录相同。

    Args:
        circuit: 平坦电路或含有界循环的电路。

    Returns:
        region 元组。
    """
    nodes = circuit.gates if isinstance(circuit, Circuit) else circuit.operations
    regions: list[Region] = []
    for position, node in enumerate(nodes):
        if isinstance(node, Conditional):
            regions.append(Region(id=f"if:{position}", kind="conditional_body", parent=None))
        elif isinstance(node, BoundedLoop):
            loop_id = f"loop:{position}"
            regions.append(Region(id=loop_id, kind="loop_body", parent=None))
            regions.extend(
                Region(id=f"{loop_id}/if:{body_position}", kind="conditional_body", parent=loop_id)
                for body_position, template in enumerate(node.body)
                if isinstance(template, ConditionalTemplate)
            )
    return tuple(regions)


def annotate_looped(circuit: LoopedCircuit) -> tuple[SemanticAnnotation, ...]:
    """在展开电路上标注每个操作，并填写它所在的最内层 region 的标识。

    条件头注解（``body_offset`` 为 ``None``）是经典控制，不在条件体内，
    所以取条件体的父 region：顶层为 ``None``，循环内为 ``loop:<位置>``。
    条件体内的注解取条件体的标识。除 ``region_id`` 外，结果与
    ``annotate_circuit(circuit.expand().circuit)`` 相同。

    Args:
        circuit: 含有界循环的电路。

    Returns:
        注解元组；不在任何 region 内的操作，其 ``region_id`` 为 ``None``。
    """
    expanded = circuit.expand()
    return tuple(
        dataclasses.replace(
            annotation,
            region_id=_innermost_region(
                expanded.provenance[annotation.gate_index].region_id, annotation.body_offset
            ),
        )
        for annotation in annotate_circuit(expanded.circuit)
    )


def _innermost_region(node_region: str | None, body_offset: int | None) -> str | None:
    """返回注解所在的最内层 region：条件头取条件体的父 region，其余取节点的 region。"""
    if node_region is None or body_offset is not None:
        return node_region
    parent, _, leaf = node_region.rpartition("/")
    if leaf.startswith("if:"):
        return parent or None
    return node_region
