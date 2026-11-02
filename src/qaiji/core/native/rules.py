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
_ZERO_HEX = frozenset({(0.0).hex(), (-0.0).hex()})
_HALF_PI = math.pi / 2
# 按位为 ±π/2 的转角使用单个 RX90。字典值为该 RX90 的轴相位。
_SHORT_AXIS = {
    (GateType.RX, _HALF_PI.hex()): 0.0,
    (GateType.RX, (-_HALF_PI).hex()): math.pi,
    (GateType.RY, _HALF_PI.hex()): _HALF_PI,
    (GateType.RY, (-_HALF_PI).hex()): -_HALF_PI,
}


def _is_zero(value: float) -> bool:
    """按位判定 ±0.0。非零次正规数不算零。"""
    return value.hex() in _ZERO_HEX


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
        conditional = source.body_offset is not None
        if conditional:
            specs = _frame_free(specs, node.qubits)
        phase = _phase(node.gate_type, params, conditional)
    return _UnscheduledGroup(
        source=source,
        rule_id="cz.v1." + name,
        phase_rad=phase,
        operations=tuple(
            _NativeSlot(kind=kind, qubits=qubits, params=params, ordinal=ordinal)
            for ordinal, (kind, qubits, params) in enumerate(specs)
        ),
    )


def _gate_slots(
    kind: GateType, qubits: tuple[int, ...], params: tuple[float, ...] = ()
) -> tuple[_SlotSpec, ...]:
    """递归展开批准模板。

    RX、RY、U3 的转角按位为 ±0.0 或 ±π/2 时使用短模板。U3 省略角度按位为 ±0.0 的 RZ 槽。
    其余门族不省略零槽。所有门族都不合并相邻 RZ，因为合并后的角度可能超出 2π 界。
    """
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
            theta = params[0]
            if _is_zero(theta):
                return (("RZ", (a,), (theta,)),)
            short = _SHORT_AXIS.get((kind, theta.hex()))
            if short is not None:
                return (("RX90", (a,), (short,)),)
            first, last = (-math.pi / 2, math.pi / 2) if kind == GateType.RX else (0.0, math.pi)
            return (
                ("RX90", (a,), (first,)),
                ("RZ", (a,), params),
                ("RX90", (a,), (last,)),
            )
        case GateType.U3:
            theta, phi, lam = params
            core = () if _is_zero(theta) else _gate_slots(GateType.RY, (a,), (theta,))
            kept = tuple(
                slot
                for slot in (("RZ", (a,), (lam,)), *core, ("RZ", (a,), (phi,)))
                if slot[0] != "RZ" or not _is_zero(slot[2][0])
            )
            # 组不能为空。三个槽都省略时保留 RZ(λ)，λ 的零符号不变。
            return kept or (("RZ", (a,), (lam,)),)
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


def _frame_free(specs: tuple[_SlotSpec, ...], qubits: tuple[int, ...]) -> tuple[_SlotSpec, ...]:
    """把条件体模板改写为不含 Z 与非零 RZ 的槽序列。

    每个比特的帧 F 在首个 RZ 或 Z 槽处从 0.0 起，按时间序累加。之后的 RX90(p) 改为
    RX90(remainder(p − F, 2π))。F 不按位为 ±0.0 的比特，按源门比特顺序追加
    RX90(π)、RX90(π)、RX90(w)、RX90(w)，w = remainder(F/2, 2π)。在 n(+φ) 约定下，
    尾部乘积为 RZ(F)，所以改写不改变组的乘积。结果为空时输出 RZ(+0.0)。
    浮点运算顺序固定，识别器按同一顺序独立重算。
    """
    frames: dict[int, float] = {}
    out: list[_SlotSpec] = []
    for kind, slot_qubits, slot_params in specs:
        q = slot_qubits[0]
        if kind in ("RZ", "Z"):
            frames[q] = frames.get(q, 0.0) + (slot_params[0] if kind == "RZ" else math.pi)
        elif kind == "RX90" and q in frames:
            out.append(
                ("RX90", slot_qubits, (math.remainder(slot_params[0] - frames[q], math.tau),))
            )
        else:
            out.append((kind, slot_qubits, slot_params))
    for q in qubits:
        if q in frames and not _is_zero(frames[q]):
            w = math.remainder(0.5 * frames[q], math.tau)
            out += [("RX90", (q,), (math.pi,))] * 2 + [("RX90", (q,), (w,))] * 2
    # 不取无条件模板的槽：净帧按位为 0 时，被吸收的 RZ 角可以非零。
    return tuple(out) or (("RZ", (qubits[0],), (0.0,)),)


def _phase(kind: GateType, params: tuple[float, ...], conditional: bool) -> float:
    """直接使用固定求值式，避免递归相位累加改变末位或负零。

    条件体中 Z 改写为 RZ(π) = e^{−iπ/2}·Z，所以它的相位为 −π/2。其余门族与无条件相同。
    """
    if conditional and kind == GateType.Z:
        return -math.pi / 2
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
