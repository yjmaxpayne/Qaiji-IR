# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L4 语义权威：分类、规范化身份与保持性裁决。

本包在同一个 Circuit 之上承载两类正交的判断。分类（types/annotation/registry）
回答"这个操作对测量统计做了什么"；保持性回答"变换后电路的算符是否与原电路相等
（可差一个全局相位）"—— 二者可以给出不一致的结论且这并不矛盾
（RZ(2*pi) 对前者是 IDENTITY，对后者是 UP_TO_PHASE），因为它们是不同的坐标轴。
规范化身份（summary/hash）与句柄握手建立在这两者之上。本包绝不导入 codec 包、
其解析器依赖或 numpy（I-Q4.1），该约束由
``tests/semantics/test_import_purity.py`` 守护。
"""

from qaiji.core.semantics.annotation import SemanticAnnotation
from qaiji.core.semantics.dataflow import ClassicalEdge, MeasurementHandle, build_dataflow_summary
from qaiji.core.semantics.handle import HandleStatus, JSONValue, SemanticIRHandle, freeze_summary
from qaiji.core.semantics.preservation import PreservationSummary, check_preservation
from qaiji.core.semantics.registry import annotate_circuit, classify_operation
from qaiji.core.semantics.summary import (
    GATE_COVERAGE_TOTAL,
    SUMMARY_SCHEMA_VERSION,
    build_semantic_summary,
    canonical_summary_hash,
)
from qaiji.core.semantics.types import CartanRole, ConditionModel, EquivLevel, MorphismType

__all__ = [
    "GATE_COVERAGE_TOTAL",
    "SUMMARY_SCHEMA_VERSION",
    "CartanRole",
    "ClassicalEdge",
    "ConditionModel",
    "EquivLevel",
    "HandleStatus",
    "JSONValue",
    "MeasurementHandle",
    "MorphismType",
    "PreservationSummary",
    "SemanticAnnotation",
    "SemanticIRHandle",
    "annotate_circuit",
    "build_dataflow_summary",
    "build_semantic_summary",
    "canonical_summary_hash",
    "check_preservation",
    "classify_operation",
    "freeze_summary",
]
