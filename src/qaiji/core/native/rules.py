# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""从同一源快照生成封闭规则的未排程槽与来源分组。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from qaiji.core.circuit import Gate, GateType
from qaiji.core.classical import Conditional, Measure

from .model import SourceLocation
from .source import _SourceSnapshot

_SlotSpec = tuple[str, tuple[int, ...], tuple[float, ...]]


@dataclass(frozen=True, slots=True, kw_only=True)
class _NativeSlot:
    """组内原生槽；来源由所属分组持有，不含时间或资源。"""

    kind: str
    qubits: tuple[int, ...]
    params: tuple[float, ...]
    ordinal: int


@dataclass(frozen=True, slots=True, kw_only=True)
class _UnscheduledGroup:
    """单个源门或测量的规则实例，条件体每个门各自成组。"""

    source: SourceLocation
    rule_id: str
    phase_rad: float
    operations: tuple[_NativeSlot, ...]


def _expand_source(snapshot: _SourceSnapshot) -> tuple[_UnscheduledGroup, ...]:
    """按快照源序展开；空条件仍由后续排程消费同一快照处理。"""
    groups: list[_UnscheduledGroup] = []
    for gate_index, node in enumerate(snapshot.gates):
        if isinstance(node, Conditional):
            for body_offset, gate in enumerate(node.body):
                source = SourceLocation(gate_index=gate_index, body_offset=body_offset)
                groups.append(_group(gate, source))
        else:
            source = SourceLocation(gate_index=gate_index, body_offset=None)
            groups.append(_group(node, source))
    return tuple(groups)


def _group(node: Gate | Measure, source: SourceLocation) -> _UnscheduledGroup:
    if isinstance(node, Measure):
        name = "MEASURE"
        specs: tuple[_SlotSpec, ...] = (("MEASURE", (node.qubit,), ()),)
        phase = 0.0
    else:
        name = node.gate_type.value
        params = tuple(float(value) for value in node.params)
        specs = _gate_slots(node.gate_type, node.qubits, params)
        phase = _phase(node.gate_type, params)
    return _UnscheduledGroup(
        source=source,
        rule_id="cz.v0." + name,
        phase_rad=phase,
        operations=tuple(
            _NativeSlot(kind=kind, qubits=qubits, params=params, ordinal=ordinal)
            for ordinal, (kind, qubits, params) in enumerate(specs)
        ),
    )


def _gate_slots(
    kind: GateType, qubits: tuple[int, ...], params: tuple[float, ...] = ()
) -> tuple[_SlotSpec, ...]:
    """递归展开批准模板，不消除零槽，也不合并相邻原生槽。"""
    a = qubits[0]
    match kind:
        case GateType.I | GateType.Z | GateType.RZ | GateType.RX90 | GateType.CZ:
            return ((kind.value, qubits, params),)
        case GateType.X | GateType.Y | GateType.RX180:
            axis = (
                params[0] if kind == GateType.RX180 else math.pi / 2 if kind == GateType.Y else 0.0
            )
            return (("RX90", (a,), (axis,)), ("RX90", (a,), (axis,)))
        case GateType.H:
            return (
                ("RZ", (a,), (math.pi / 2,)),
                ("RX90", (a,), (0.0,)),
                ("RZ", (a,), (math.pi / 2,)),
            )
        case GateType.S | GateType.T:
            angle = math.pi / 4 if kind == GateType.T else math.pi / 2
            return (("RZ", (a,), (angle,)),)
        case GateType.RX | GateType.RY:
            first, last = (-math.pi / 2, math.pi / 2) if kind == GateType.RX else (0.0, math.pi)
            return (
                ("RX90", (a,), (first,)),
                ("RZ", (a,), params),
                ("RX90", (a,), (last,)),
            )
        case GateType.U3:
            theta, phi, lam = params
            return (
                ("RZ", (a,), (lam,)),
                *_gate_slots(GateType.RY, (a,), (theta,)),
                ("RZ", (a,), (phi,)),
            )
        case GateType.CNOT | GateType.CX:
            target_h = _gate_slots(GateType.H, (qubits[1],))
            return (*target_h, ("CZ", qubits, ()), *target_h)
        case GateType.SWAP:
            forward = _gate_slots(GateType.CX, qubits)
            reverse = _gate_slots(GateType.CX, (qubits[1], a))
            return forward + reverse + forward
        case GateType.ISWAP | GateType.SQISWAP:
            angle = -math.pi / 2 if kind == GateType.ISWAP else -math.pi / 4
            b = qubits[1]
            cx = _gate_slots(GateType.CX, qubits)
            rzz = (*cx, ("RZ", (b,), (angle,)), *cx)
            basis = _gate_slots(GateType.H, (a,)) + _gate_slots(GateType.H, (b,))
            rxx = basis + rzz + basis
            ryy = (
                ("RX90", (a,), (math.pi,)),
                ("RX90", (b,), (math.pi,)),
                *rzz,
                ("RX90", (a,), (0.0,)),
                ("RX90", (b,), (0.0,)),
            )
            return rxx + ryy
    raise ValueError("Unknown source gate kind.")


def _phase(kind: GateType, params: tuple[float, ...]) -> float:
    """直接使用固定求值式，避免递归相位累加改变末位或负零。"""
    if kind == GateType.U3:
        _, phi, lam = params
        return -(phi / 2 + lam / 2)
    return {
        GateType.I: 0.0,
        GateType.X: -math.pi / 2,
        GateType.Y: -math.pi / 2,
        GateType.Z: 0.0,
        GateType.H: -math.pi / 2,
        GateType.S: -math.pi / 4,
        GateType.T: -math.pi / 8,
        GateType.RX: 0.0,
        GateType.RY: 0.0,
        GateType.RZ: 0.0,
        GateType.RX90: 0.0,
        GateType.RX180: 0.0,
        GateType.CNOT: -math.pi,
        GateType.CX: -math.pi,
        GateType.CZ: 0.0,
        GateType.SWAP: -3 * math.pi,
        GateType.ISWAP: -6 * math.pi,
        GateType.SQISWAP: -6 * math.pi,
    }[kind]
