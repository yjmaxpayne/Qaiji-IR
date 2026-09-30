# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""以独立游标产生式认证实际原生槽，不依赖生成或排程实现。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from qaiji.core.circuit import Gate
from qaiji.core.classical import Measure

from .model import NativeOperation, SourceGroup, SourceLocation


@dataclass(frozen=True, slots=True, kw_only=True)
class _RuleCheck:
    """规则首因；操作索引相对于完整产物，非组内切片。"""

    code: str | None = None
    operation_index: int | None = None
    expected_phase_rad: float | None = None


def _recognize_group(
    node: Gate | Measure,
    source: SourceLocation,
    group: SourceGroup,
    operations: tuple[NativeOperation, ...],
) -> _RuleCheck:
    """检查单组切片；调用方负责源组对应关系及完整产物分组。"""
    name = "MEASURE" if isinstance(node, Measure) else node.gate_type.value
    if group.rule_id != "cz.v0." + name:
        return _RuleCheck(code="rule_id")
    if group.source != source or group.op_stop - group.op_start != len(operations):
        return _RuleCheck(code="rule_instance")
    cursor = _Cursor(operations, source)
    if isinstance(node, Measure):
        cursor.slot("MEASURE", (node.qubit,))
        phase = 0.0
    else:
        cursor.gate(name, node.qubits, tuple(float(x) for x in node.params))
        phase = _phase_expected(node)
    if cursor.failure is not None:
        return _RuleCheck(code="rule_instance", operation_index=group.op_start + cursor.failure)
    if cursor.index != len(operations):
        return _RuleCheck(code="rule_instance", operation_index=group.op_start + cursor.index)
    if group.phase_rad.hex() != phase.hex():
        return _RuleCheck(code="rule_phase", expected_phase_rad=phase)
    return _RuleCheck(expected_phase_rad=phase)


class _Cursor:
    """直接消费实际槽；只保存首个不符位置，不构造期望操作流。"""

    def __init__(self, operations: tuple[NativeOperation, ...], source: SourceLocation) -> None:
        self.operations = operations
        self.source = source
        self.index = 0
        self.failure: int | None = None

    def slot(self, kind: str, qubits: tuple[int, ...], *params: float) -> None:
        """逐槽核对精确字段，包括浮点负零。"""
        i = self.index
        self.index += 1
        if self.failure is not None:
            return
        if i >= len(self.operations):
            self.failure = i
            return
        op = self.operations[i]
        if (
            op.kind != kind
            or op.qubits != qubits
            or op.source != self.source
            or op.ordinal != i
            or tuple(p.hex() for p in op.params) != tuple(p.hex() for p in params)
        ):
            self.failure = i

    def h(self, q: int) -> None:
        """消费目标比特上的三槽 H 产生式。"""
        self.slot("RZ", (q,), math.pi / 2)
        self.slot("RX90", (q,), 0.0)
        self.slot("RZ", (q,), math.pi / 2)

    def cx(self, a: int, b: int) -> None:
        """保留控制、目标的源顺序。"""
        self.h(b)
        self.slot("CZ", (a, b))
        self.h(b)

    def zz(self, a: int, b: int, angle: float) -> None:
        """消费交换族中的 ZZ 产生式。"""
        self.cx(a, b)
        self.slot("RZ", (b,), angle)
        self.cx(a, b)

    def gate(self, name: str, qubits: tuple[int, ...], params: tuple[float, ...]) -> None:
        """手写封闭产生式；不调用展开器或共享模板。"""
        a = qubits[0]
        if name in {"I", "Z", "RZ", "RX90", "CZ"}:
            self.slot(name, qubits, *params)
        elif name in {"X", "Y", "RX180"}:
            axis = {"X": 0.0, "Y": math.pi / 2}.get(name, params[0] if params else 0.0)
            self.slot("RX90", (a,), axis)
            self.slot("RX90", (a,), axis)
        elif name == "H":
            self.h(a)
        elif name in {"S", "T"}:
            self.slot("RZ", (a,), math.pi / (2 if name == "S" else 4))
        elif name in {"RX", "RY", "U3"}:
            if name == "U3":
                self.slot("RZ", (a,), params[2])
            self.slot("RX90", (a,), -math.pi / 2 if name == "RX" else 0.0)
            self.slot("RZ", (a,), params[0])
            self.slot("RX90", (a,), math.pi / 2 if name == "RX" else math.pi)
            if name == "U3":
                self.slot("RZ", (a,), params[1])
        elif name in {"CX", "CNOT"}:
            self.cx(a, qubits[1])
        elif name == "SWAP":
            self.cx(a, qubits[1])
            self.cx(qubits[1], a)
            self.cx(a, qubits[1])
        elif name in {"ISWAP", "SQISWAP"}:
            b = qubits[1]
            angle = -math.pi / (2 if name == "ISWAP" else 4)
            self.h(a)
            self.h(b)
            self.zz(a, b, angle)
            self.h(a)
            self.h(b)
            self.slot("RX90", (a,), math.pi)
            self.slot("RX90", (b,), math.pi)
            self.zz(a, b, angle)
            self.slot("RX90", (a,), 0.0)
            self.slot("RX90", (b,), 0.0)
        else:
            raise ValueError("Unknown source gate kind.")


def _phase_expected(node: Gate) -> float:
    """单独固定相位表达式，不沿产生式累计或取模。"""
    name = node.gate_type.value
    if name == "U3":
        _, phi, lam = (float(x) for x in node.params)
        return -(phi / 2 + lam / 2)
    return {
        "I": 0.0,
        "Z": 0.0,
        "RZ": 0.0,
        "RX90": 0.0,
        "CZ": 0.0,
        "X": -math.pi / 2,
        "Y": -math.pi / 2,
        "H": -math.pi / 2,
        "S": -math.pi / 4,
        "T": -math.pi / 8,
        "RX": 0.0,
        "RY": 0.0,
        "RX180": 0.0,
        "CX": -math.pi,
        "CNOT": -math.pi,
        "SWAP": -3 * math.pi,
        "ISWAP": -6 * math.pi,
        "SQISWAP": -6 * math.pi,
    }[name]
