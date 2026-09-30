# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""电路语义内容的规范化 JSON 摘要及其内容哈希。

维护规则：凡是改动哈希输入域、14 个稳定键的集合，或 ``types.py`` 中会流入摘要键的
任一字面量（morphism/equiv-level/cartan 字符串、``GATE_COVERAGE_TOTAL``、
``operations`` 的编码形状），都必须递增 ``SUMMARY_SCHEMA_VERSION``。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from qaiji.core.circuit import Gate
from qaiji.core.classical import Conditional, Measure
from qaiji.core.semantics.dataflow import build_dataflow_summary

if TYPE_CHECKING:
    from qaiji.core.circuit import Circuit, GateType
    from qaiji.core.semantics.annotation import SemanticAnnotation

__all__ = [
    "GATE_COVERAGE_TOTAL",
    "SUMMARY_SCHEMA_VERSION",
    "build_semantic_summary",
    "canonical_summary_hash",
]

SUMMARY_SCHEMA_VERSION = "qaiji.semantic_summary.v0"
GATE_COVERAGE_TOTAL = 19


def _encode_gate_triple(gate: Gate) -> list[Any]:
    """编码一个门的结构性身份：类型、量子比特与参数。

    参数以 repr(float) 字符串形式传递 —— 这是 CPython 最短的往返表示 —— 因此哈希
    不受 JSON 数字编码差异的影响。显式的 float() 强制转换很关键：
    Gate.__post_init__ 只把 params 元组化而不强制转 float，于是手工构造的
    Gate(RZ, (0,), (0,)) 与 Gate(RZ, (0,), (0.0,)) 在 dataclass 意义上相等，但
    repr(0) != repr(0.0) —— 不做强转的话，这两个逐位相同的电路会哈希到不同值。
    """
    return [
        gate.gate_type.value,
        list(gate.qubits),
        [repr(float(param)) for param in gate.params],
    ]


def _encode_operation(operation: Gate | Measure | Conditional) -> list[Any]:
    """将一个顶层节点编码进 ``operations`` schema（ARCH §2.2）。"""
    if isinstance(operation, Gate):
        return ["gate", *_encode_gate_triple(operation)]
    if isinstance(operation, Measure):
        return ["measure", operation.qubit, operation.target.register.name, operation.target.index]
    if isinstance(operation, Conditional):
        return [
            "conditional",
            operation.register.name,
            operation.value,
            [_encode_gate_triple(gate) for gate in operation.body],
        ]
    raise TypeError(f"Cannot encode {type(operation).__name__} into operations")


def _gate_coverage(circuit: Circuit) -> dict[str, int]:
    """统计电路中出现过的不同 GateType 数量，含 Conditional 体内的门。"""
    covered: set[GateType] = set()
    for operation in circuit.gates:
        if isinstance(operation, Gate):
            covered.add(operation.gate_type)
        elif isinstance(operation, Conditional):
            covered.update(gate.gate_type for gate in operation.body)
    return {"covered": len(covered), "total_gate_types": GATE_COVERAGE_TOTAL}


def build_semantic_summary(
    *,
    circuit: Circuit,
    annotations: Sequence[SemanticAnnotation],
    status_label: str = "available",
    source_language: str | None = None,
    preservation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构建一个电路的规范化、JSON 安全的语义摘要。

    全部 14 个稳定键都无条件输出，包括空容器和 ``None``：一个时有时无的键会让键的
    漂移只能表现为哈希差异，而不是显式的键名差异，从而变得不可见。

    Args:
        circuit: 判别性键（num_qubits、cregs、operations）与 gate_coverage 的来源。
        annotations: 该电路的语义标注，按 ``annotate_circuit`` 的顺序排列。
        status_label: 取自 ``HandleStatus`` 的值（T3.4；在该枚举落地前是未经校验的
            普通 str）。
        source_language: 可选的溯源标签。生产调用方保持为 None；只有测试会传入
            具体值。
        preservation: 可选的保持性裁决载荷，给定时原样并入。

    Returns:
        一个 JSON 安全的 dict，含 14 个稳定键，外加所有被赋值的可选键。
    """
    dataflow = build_dataflow_summary(circuit)

    summary: dict[str, Any] = {
        "summary_schema_version": SUMMARY_SCHEMA_VERSION,
        "status_label": status_label,
        "num_qubits": circuit.num_qubits,
        "cregs": [[register.name, register.size] for register in circuit.cregs],
        "operations": [_encode_operation(operation) for operation in circuit.gates],
        "annotation_count": len(annotations),
        "gate_coverage": _gate_coverage(circuit),
        "morphism_counts": dict(Counter(annotation.morphism.value for annotation in annotations)),
        "equiv_level_counts": dict(
            Counter(
                annotation.equiv_level.value
                for annotation in annotations
                if annotation.equiv_level is not None
            )
        ),
        "cartan_counts": dict(Counter(annotation.cartan.value for annotation in annotations)),
        "measurement_handles": [
            dataclasses.asdict(handle) for handle in dataflow["measurement_handles"]
        ],
        "classical_edges": [dataclasses.asdict(edge) for edge in dataflow["classical_edges"]],
        "condition_model": dataflow["condition_model"],
        "unitary_segment_count": dataflow["unitary_segment_count"],
    }

    if source_language is not None:
        summary["source_language"] = source_language
    if preservation is not None:
        summary["preservation"] = preservation

    return summary


def _jsonify(value: Any) -> Any:
    """``json.dumps`` 的 ``default=`` 钩子：只处理 Mapping -> dict。

    其余所有类型一律保持 TypeError（R-C01）：除了 ``freeze_summary`` 产出的冻结树
    Mapping 这一种情况，没有任何证据支持为别的类型开特例。
    """
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def canonical_summary_hash(summary: Mapping[str, Any]) -> str:
    """将语义摘要哈希为它的规范化内容身份。

    Args:
        summary: 一份语义摘要，原始的或已冻结的（``freeze_summary`` 的输出）——
            二者经由 ``default=`` 钩子哈希出完全相同的结果。

    Returns:
        规范化 JSON 编码的 ``"sha256:" + 十六进制摘要``。

    Raises:
        ValueError: 摘要中含有 NaN 或 Infinity。
        TypeError: 摘要中含有既非 JSON 原始类型、也非 Mapping 的值。
    """
    encoded = json.dumps(
        summary,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_jsonify,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
