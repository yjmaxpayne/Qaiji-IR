# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""电路中一等公民的测量节点与条件节点之间的数据流边。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from qaiji.core.classical import Conditional, Measure
from qaiji.core.semantics.types import ConditionModel

if TYPE_CHECKING:
    from qaiji.core.circuit import Circuit

__all__ = ["ClassicalEdge", "MeasurementHandle", "build_dataflow_summary"]


@dataclass(frozen=True, slots=True)
class MeasurementHandle:
    """指向某次测量的经典目的地的句柄。"""

    measurement_id: str
    qubit_index: int
    creg_name: str
    creg_index: int
    source: str = "measure_node"


@dataclass(frozen=True, slots=True)
class ClassicalEdge:
    """从一次测量指向一个条件节点的声明式数据流边。"""

    source_handle: str
    target: str
    edge_kind: str = "measurement_to_condition"


def build_dataflow_summary(circuit: Circuit) -> dict[str, Any]:
    """直接读取电路中一等公民的测量节点与条件节点。

    只要测量句柄与条件节点共享同一个寄存器名，二者之间就连一条边；寄存器级条件
    读取整个寄存器，因此写入该寄存器的每一个句柄都会被连上。这些边表达的是声明式
    数据流，而非因果证明：即便某个 Conditional 在门序中排在与之匹配的 Measure
    之前，边依然会连上 —— 顺序与因果属于 L2 调度层的议题，不由语义层判定。

    Args:
        circuit: 待读取的电路。

    Returns:
        一个 dict，含 ``measurement_handles``，即 ``MeasurementHandle`` 元组；以及
        ``classical_edges``，即 ``ClassicalEdge`` 元组 —— 都是带类型的值对象，尚未
        JSON 编码；那一步投影是 summary.py 的职责，正如 ``operations`` 的编码也
        归它所有。另含 ``condition_model``，取值为 ``ConditionModel.REGISTER_ALU.value``
        或 ``None``，始终存在；以及 ``unitary_segment_count``，即顶层 measure 数量
        加一。
    """
    handles: list[MeasurementHandle] = []
    for operation in circuit.gates:
        if isinstance(operation, Measure):
            handles.append(
                MeasurementHandle(
                    measurement_id=f"m{len(handles)}",
                    qubit_index=operation.qubit,
                    creg_name=operation.target.register.name,
                    creg_index=operation.target.index,
                )
            )

    edges: list[ClassicalEdge] = []
    has_conditional = False
    for index, operation in enumerate(circuit.gates):
        if isinstance(operation, Conditional):
            has_conditional = True
            target = f"cond{index}"
            edges.extend(
                ClassicalEdge(source_handle=handle.measurement_id, target=target)
                for handle in handles
                if handle.creg_name == operation.register.name
            )

    return {
        "measurement_handles": tuple(handles),
        "classical_edges": tuple(edges),
        "condition_model": ConditionModel.REGISTER_ALU.value if has_conditional else None,
        "unitary_segment_count": len(handles) + 1,
    }
