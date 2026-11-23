# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""直接定义理想算符并检验实际局部乘积，仅分配二阶或四阶矩阵。"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass

from qaiji.core.circuit import Gate
from qaiji.core.classical import Measure
from qaiji.core.gate_matrix import _axis_rotation, _identity, _Matrix, _rz, source_operator

from .model import NativeOperation


@dataclass(frozen=True, slots=True, kw_only=True)
class _MatrixCheck:
    """局部 HP 结果；测量没有相位或残差。"""

    status: str
    code: str | None = None
    max_abs_residual: float | None = None
    expected_phase_rad: float | None = None


def _check_local_matrix(
    node: Gate | Measure, operations: tuple[NativeOperation, ...], conditional: bool
) -> _MatrixCheck:
    """独立消费实际槽，不接收规则认证结果或产物声称的相位。

    `conditional` 表示源门在条件体中。它只改变条件体 Z 的期望全局相位。
    """
    if isinstance(node, Measure):
        return _MatrixCheck(status="not_applicable")
    domain = node.qubits
    if any(op.kind == "MEASURE" or any(q not in domain for q in op.qubits) for op in operations):
        return _MatrixCheck(status="fail", code="operand_domain")
    expected = source_operator(node)
    actual = _identity(len(expected))
    for op in operations:
        local = _native_operator(op)
        if len(domain) == 2 and len(op.qubits) == 1:
            local = _embed(local, domain.index(op.qubits[0]))
        actual = _multiply(local, actual)
    delta = _expected_delta(node, conditional)
    factor = cmath.exp(1j * delta)
    residuals = tuple(
        (abs(actual[i][j] - factor * value), 1e-10 + 1e-8 * abs(value))
        for i, row in enumerate(expected)
        for j, value in enumerate(row)
    )
    passed = all(error <= tolerance for error, tolerance in residuals)
    return _MatrixCheck(
        status="pass" if passed else "fail",
        code=None if passed else "operator_mismatch",
        max_abs_residual=max(error for error, _ in residuals),
        expected_phase_rad=delta,
    )


def _multiply(left: _Matrix, right: _Matrix) -> _Matrix:
    size = len(left)
    return tuple(
        tuple(sum(left[i][k] * right[k][j] for k in range(size)) for j in range(size))
        for i in range(size)
    )


def _embed(operator: _Matrix, position: int) -> _Matrix:
    """局部首位是源 qubits[0]，与物理索引大小无关。"""
    return tuple(
        tuple(
            operator[(i >> (1 - position)) & 1][(j >> (1 - position)) & 1]
            if ((i >> position) & 1) == ((j >> position) & 1)
            else 0j
            for j in range(4)
        )
        for i in range(4)
    )


def _native_operator(op: NativeOperation) -> _Matrix:
    """原生算符直接定义，源门不通过原生路线求值。"""
    if op.kind == "I":
        return _identity(2)
    if op.kind == "Z":
        return ((1 + 0j, 0j), (0j, -1 + 0j))
    if op.kind == "RZ":
        return _rz(op.params[0])
    if op.kind == "RX90":
        return _axis_rotation(math.pi / 2, op.params[0])
    if op.kind == "CZ":
        return ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, -1))
    raise ValueError("Unknown unitary native operation.")


def _expected_delta(node: Gate, conditional: bool) -> float:
    """矩阵侧独立相位，不读取产物声明或识别器。

    条件体中的 Z 由 RX90 实现，乘积为 RZ(π) = e^{−iπ/2}·Z。RX90 的乘积都在 SU(2) 中，
    Z 不在，所以该行的相位为 −π/2。
    """
    name = node.gate_type.value
    if conditional and name == "Z":
        return -math.pi / 2
    if name == "U3":
        phi, lam = float(node.params[1]), float(node.params[2])
        return -(phi / 2 + lam / 2)
    if name in {"X", "Y", "H"}:
        return -math.pi / 2
    if name == "S":
        return -math.pi / 4
    if name == "T":
        return -math.pi / 8
    if name in {"CX", "CNOT"}:
        return -math.pi
    if name == "SWAP":
        return -3 * math.pi
    if name in {"ISWAP", "SQISWAP"}:
        return -6 * math.pi
    return 0.0
