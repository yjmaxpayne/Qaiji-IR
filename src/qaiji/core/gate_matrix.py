# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""源门的直接矩阵定义，供原生检验与语义判定共用；只依赖标准库与电路模型。"""

from __future__ import annotations

import cmath
import math

from qaiji.core.circuit import Gate

_Matrix = tuple[tuple[complex, ...], ...]


def _identity(size: int) -> _Matrix:
    return tuple(tuple(complex(i == j) for j in range(size)) for i in range(size))


def _rz(angle: float) -> _Matrix:
    return ((cmath.exp(-0.5j * angle), 0j), (0j, cmath.exp(0.5j * angle)))


def _axis_rotation(angle: float, axis: float) -> _Matrix:
    c, s = math.cos(angle / 2), math.sin(angle / 2)
    return (
        (complex(c), -1j * s * cmath.exp(-1j * axis)),
        (-1j * s * cmath.exp(1j * axis), complex(c)),
    )


def source_operator(node: Gate) -> _Matrix:
    """按源门直接矩阵定义求值，不展开为原生门。

    双比特矩阵的行列下标以 ``qubits[0]`` 为高位。

    Args:
        node: 源门。

    Returns:
        二阶或四阶矩阵。

    Raises:
        ValueError: 门类型没有矩阵定义。
    """
    name = node.gate_type.value
    params = tuple(float(p) for p in node.params)
    if name == "I":
        return _identity(2)
    if name == "X":
        return ((0, 1), (1, 0))
    if name == "Y":
        return ((0, -1j), (1j, 0))
    if name == "Z":
        return ((1, 0), (0, -1))
    if name == "H":
        s = 1 / math.sqrt(2)
        return ((s, s), (s, -s))
    if name in {"S", "T"}:
        return ((1, 0), (0, cmath.exp(1j * math.pi / (2 if name == "S" else 4))))
    if name == "RZ":
        return _rz(params[0])
    if name in {"RX", "RY"}:
        c, s = math.cos(params[0] / 2), math.sin(params[0] / 2)
        return ((c, -1j * s), (-1j * s, c)) if name == "RX" else ((c, -s), (s, c))
    if name in {"RX90", "RX180"}:
        return _axis_rotation(math.pi / 2 if name == "RX90" else math.pi, params[0])
    if name == "U3":
        theta, phi, lam = params
        c, s = math.cos(theta / 2), math.sin(theta / 2)
        return (
            (c, -cmath.exp(1j * lam) * s),
            (cmath.exp(1j * phi) * s, cmath.exp(1j * (phi + lam)) * c),
        )
    if name in {"CX", "CNOT"}:
        return ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1), (0, 0, 1, 0))
    if name == "CZ":
        return ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, -1))
    if name == "SWAP":
        return ((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1))
    if name in {"ISWAP", "SQISWAP"}:
        c, s = (0.0, 1.0) if name == "ISWAP" else (1 / math.sqrt(2), 1 / math.sqrt(2))
        return ((1, 0, 0, 0), (0, c, 1j * s, 0), (0, 1j * s, c, 0), (0, 0, 0, 1))
    raise ValueError("Unknown source gate kind.")
