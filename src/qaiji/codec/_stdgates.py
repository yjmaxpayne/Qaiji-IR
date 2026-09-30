# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""把标准门名展开为已有且可序列化的电路门。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import pi
from types import MappingProxyType

from qaiji.core.circuit import Gate, GateType


@dataclass(frozen=True)
class _Expansion:
    """描述标准门的形状及其按程序顺序执行的展开函数。

    Example:
        ``_EXPANSIONS["sx"].build((0,), ())`` 返回一门 RX(π/2)。
    """

    name: str
    arity: int
    n_params: int
    build: Callable[[tuple[int, ...], tuple[float, ...]], tuple[Gate, ...]]


def _u3(qubit: int, theta: float, phi: float, lam: float) -> Gate:
    return Gate(GateType.U3, (qubit,), (theta, phi, lam))


def _ccx(qubits: tuple[int, ...], params: tuple[float, ...]) -> tuple[Gate, ...]:
    a, b, c = qubits
    return (
        Gate(GateType.H, (c,)),
        Gate(GateType.CX, (b, c)),
        _u3(c, 0.0, 0.0, -pi / 4),
        Gate(GateType.CX, (a, c)),
        Gate(GateType.T, (c,)),
        Gate(GateType.CX, (b, c)),
        _u3(c, 0.0, 0.0, -pi / 4),
        Gate(GateType.CX, (a, c)),
        Gate(GateType.T, (b,)),
        Gate(GateType.T, (c,)),
        Gate(GateType.H, (c,)),
        Gate(GateType.CX, (a, b)),
        Gate(GateType.T, (a,)),
        _u3(b, 0.0, 0.0, -pi / 4),
        Gate(GateType.CX, (a, b)),
    )


def _cswap(qubits: tuple[int, ...], params: tuple[float, ...]) -> tuple[Gate, ...]:
    _, b, c = qubits
    cx = Gate(GateType.CX, (c, b))
    return (cx, *_ccx(qubits, params), cx)


def _cy(qubits: tuple[int, ...], params: tuple[float, ...]) -> tuple[Gate, ...]:
    _, target = qubits
    return (
        _u3(target, 0.0, 0.0, -pi / 2),
        Gate(GateType.CX, qubits),
        Gate(GateType.S, (target,)),
    )


def _ch(qubits: tuple[int, ...], params: tuple[float, ...]) -> tuple[Gate, ...]:
    _, target = qubits
    return (
        Gate(GateType.RY, (target,), (pi / 4,)),
        Gate(GateType.CX, qubits),
        Gate(GateType.RY, (target,), (-pi / 4,)),
    )


def _crx(qubits: tuple[int, ...], params: tuple[float, ...]) -> tuple[Gate, ...]:
    _, target = qubits
    (theta,) = params
    return (
        Gate(GateType.H, (target,)),
        Gate(GateType.RZ, (target,), (theta / 2,)),
        Gate(GateType.CX, qubits),
        Gate(GateType.RZ, (target,), (-theta / 2,)),
        Gate(GateType.CX, qubits),
        Gate(GateType.H, (target,)),
    )


def _cry(qubits: tuple[int, ...], params: tuple[float, ...]) -> tuple[Gate, ...]:
    _, target = qubits
    (theta,) = params
    return (
        Gate(GateType.RY, (target,), (theta / 2,)),
        Gate(GateType.CX, qubits),
        Gate(GateType.RY, (target,), (-theta / 2,)),
        Gate(GateType.CX, qubits),
    )


def _crz(qubits: tuple[int, ...], params: tuple[float, ...]) -> tuple[Gate, ...]:
    _, target = qubits
    (theta,) = params
    return (
        Gate(GateType.RZ, (target,), (theta / 2,)),
        Gate(GateType.CX, qubits),
        Gate(GateType.RZ, (target,), (-theta / 2,)),
        Gate(GateType.CX, qubits),
    )


def _cp(qubits: tuple[int, ...], params: tuple[float, ...]) -> tuple[Gate, ...]:
    control, target = qubits
    (lam,) = params
    return (
        _u3(control, 0.0, 0.0, lam / 2),
        Gate(GateType.CX, qubits),
        _u3(target, 0.0, 0.0, -lam / 2),
        Gate(GateType.CX, qubits),
        _u3(target, 0.0, 0.0, lam / 2),
    )


def _cu(qubits: tuple[int, ...], params: tuple[float, ...]) -> tuple[Gate, ...]:
    control, target = qubits
    theta, phi, lam, gamma = params
    return (
        _u3(control, 0.0, 0.0, gamma + (lam + phi) / 2),
        _u3(target, 0.0, 0.0, (lam - phi) / 2),
        Gate(GateType.CX, qubits),
        _u3(target, -theta / 2, 0.0, -(phi + lam) / 2),
        Gate(GateType.CX, qubits),
        _u3(target, theta / 2, phi, 0.0),
    )


def _cu3(qubits: tuple[int, ...], params: tuple[float, ...]) -> tuple[Gate, ...]:
    """采用官方 qelib1 的受控 U，不添加 Qiskit 读法的控制位相位。"""
    _, target = qubits
    theta, phi, lam = params
    return (
        _u3(target, 0.0, 0.0, (lam - phi) / 2),
        Gate(GateType.CX, qubits),
        _u3(target, -theta / 2, 0.0, -(phi + lam) / 2),
        Gate(GateType.CX, qubits),
        _u3(target, theta / 2, phi, 0.0),
    )


_EXPANSIONS: Mapping[str, _Expansion] = MappingProxyType(
    {
        "p": _Expansion("p", 1, 1, lambda qs, ps: (_u3(qs[0], 0.0, 0.0, ps[0]),)),
        "u1": _Expansion("u1", 1, 1, lambda qs, ps: (_u3(qs[0], 0.0, 0.0, ps[0]),)),
        "u2": _Expansion("u2", 1, 2, lambda qs, ps: (_u3(qs[0], pi / 2, ps[0], ps[1]),)),
        "u": _Expansion("u", 1, 3, lambda qs, ps: (_u3(qs[0], *ps),)),
        "sdg": _Expansion("sdg", 1, 0, lambda qs, ps: (_u3(qs[0], 0.0, 0.0, -pi / 2),)),
        "tdg": _Expansion("tdg", 1, 0, lambda qs, ps: (_u3(qs[0], 0.0, 0.0, -pi / 4),)),
        "sx": _Expansion("sx", 1, 0, lambda qs, ps: (Gate(GateType.RX, qs, (pi / 2,)),)),
        "sxdg": _Expansion("sxdg", 1, 0, lambda qs, ps: (Gate(GateType.RX, qs, (-pi / 2,)),)),
        "cy": _Expansion("cy", 2, 0, _cy),
        "ch": _Expansion("ch", 2, 0, _ch),
        "crx": _Expansion("crx", 2, 1, _crx),
        "cry": _Expansion("cry", 2, 1, _cry),
        "crz": _Expansion("crz", 2, 1, _crz),
        "cp": _Expansion("cp", 2, 1, _cp),
        "cu1": _Expansion("cu1", 2, 1, _cp),
        "cu": _Expansion("cu", 2, 4, _cu),
        "cu3": _Expansion("cu3", 2, 3, _cu3),
        "ccx": _Expansion("ccx", 3, 0, _ccx),
        "cswap": _Expansion("cswap", 3, 0, _cswap),
    }
)
