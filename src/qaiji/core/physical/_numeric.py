# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""提供受请求级预算约束的物理数值检查。"""

from __future__ import annotations

import math
import struct
import sys
from fractions import Fraction
from typing import Any, NoReturn, cast

from .arrays import ArrayData, FrozenJSON
from .diagnostics import CheckBudget, Diagnostic, PContractError
from .model import OperatorSum, Problem, Request

_NORMALIZATION_TOLERANCE = 1e-10
_PSD_TOLERANCE = 1e-10


class _NumericContext:
    """在一次检查中累计 Schur 更新次数。"""

    def __init__(self, budget: CheckBudget):
        self.budget = budget
        self.operations = 0

    def fail(self, code: str, path: str, **details: Any) -> NoReturn:
        resource = code in {
            "DENSE_DIMENSION",
            "NUMERIC_ELEMENTS",
            "RATIONAL_OPS",
            "RATIONAL_BITS",
            "NUMERIC_RANGE",
        }
        raise PContractError(
            diagnostics=(
                Diagnostic(
                    category="RESOURCE_LIMIT" if resource else "INVALID_REQUEST",
                    code=code,
                    path=path,
                    message="Physical validation failed.",
                    details=FrozenJSON(
                        value=cast(
                            Any,
                            {
                                key: value.hex() if isinstance(value, float) else value
                                for key, value in details.items()
                            },
                        )
                    ),
                ),
            )
        )

    def limit(self, resource: str, required: int, limit: int, path: str) -> None:
        if required > limit:
            self.fail(resource, path, resource=resource, required=required, limit=limit)

    def dimension(self, dimension: int, path: str) -> None:
        self.limit("DENSE_DIMENSION", dimension, self.budget.max_dense_dimension, path)

    def slots(self, required: int, path: str) -> None:
        self.limit("NUMERIC_ELEMENTS", required, self.budget.max_numeric_elements, path)

    def update(self, path: str) -> None:
        self.limit("RATIONAL_OPS", self.operations + 1, self.budget.max_rational_ops, path)
        self.operations += 1

    def integer(self, value: int, path: str) -> int:
        self.limit("RATIONAL_BITS", abs(value).bit_length(), self.budget.max_rational_bits, path)
        return value

    def integer_product(self, left: int, right: int, path: str) -> int:
        self.integer(left, path)
        self.integer(right, path)
        if not left or not right:
            return 0
        # 单位因子不增加位长。其他乘法使用瞬时位长上界。
        required = abs(left).bit_length() + abs(right).bit_length()
        if abs(left) == 1 or abs(right) == 1:
            required -= 1
        self.limit("RATIONAL_BITS", required, self.budget.max_rational_bits, path)
        return self.integer(left * right, path)

    def rational(self, numerator: int, denominator: int, path: str) -> Fraction:
        self.integer(numerator, path)
        self.integer(denominator, path)
        return Fraction(numerator, denominator)

    def exact(self, value: float, path: str) -> Fraction:
        return self.rational(*value.as_integer_ratio(), path)

    def add(self, left: Fraction, right: Fraction, path: str) -> Fraction:
        common = math.gcd(left.denominator, right.denominator)
        a = right.denominator // common
        b = left.denominator // common
        numerator = self.integer(
            self.integer_product(left.numerator, a, path)
            + self.integer_product(right.numerator, b, path),
            path,
        )
        # 分子中的公因子须在分母乘法前消去。
        cancel = math.gcd(numerator, common)
        denominator = self.integer_product(b, right.denominator // cancel, path)
        return self.rational(numerator // cancel, denominator, path)

    def multiply(self, left: Fraction, right: Fraction, path: str) -> Fraction:
        a = math.gcd(left.numerator, right.denominator)
        b = math.gcd(right.numerator, left.denominator)
        return self.rational(
            self.integer_product(left.numerator // a, right.numerator // b, path),
            self.integer_product(left.denominator // b, right.denominator // a, path),
            path,
        )

    def finite(self, value: complex | float, path: str) -> complex | float:
        number = complex(value)
        if not (math.isfinite(number.real) and math.isfinite(number.imag)):
            self.fail(
                "NUMERIC_RANGE",
                path,
                resource="binary64",
                required="nonfinite",
                limit=sys.float_info.max,
            )
        return value


def _values(array: ArrayData) -> list[complex]:
    return [complex(real, imag) for real, imag in struct.iter_unpack("<dd", array.data)]


def _coordinates(index: int, dimensions: list[int]) -> list[int]:
    result = [0] * len(dimensions)
    for i in range(len(dimensions) - 1, -1, -1):
        index, result[i] = divmod(index, dimensions[i])
    return result


def _close(left: complex, right: complex, ctx: _NumericContext, path: str) -> bool:
    try:
        delta = abs(left - right)
        scale = max(abs(left), abs(right))
    except OverflowError:
        ctx.fail(
            "NUMERIC_RANGE",
            path,
            resource="binary64",
            required="overflow",
            limit=sys.float_info.max,
        )
    ctx.finite(delta, path)
    ctx.finite(scale, path)
    return delta <= 1e-12 + 1e-10 * scale


def _hermitian(matrix: list[complex], size: int, ctx: _NumericContext, path: str) -> None:
    for i in range(size):
        for j in range(i + 1):
            if not _close(matrix[i * size + j], matrix[j * size + i].conjugate(), ctx, path):
                ctx.fail("HERMITIAN", path, row=i, column=j)


def _assemble_operator(
    operator: OperatorSum, problem: Problem, ctx: _NumericContext, path: str
) -> list[complex]:
    dims = {site.id: site.dim for site in problem.sites}
    dimensions = [dims[site] for site in problem.tensor_order]
    size = math.prod(dimensions)
    local_slots = max(
        (sum(dims[f.site] ** 2 for f in term.factors) for term in operator.terms), default=0
    )
    ctx.slots(size * size + local_slots + 2 * len(dimensions) + 16, path)
    result = [0j] * (size * size)
    for term in operator.terms:
        factors = {f.site: _values(f.matrix) for f in term.factors}
        for i in range(size):
            rows = _coordinates(i, dimensions)
            for j in range(size):
                columns = _coordinates(j, dimensions)
                value = term.coefficient
                for k, site in enumerate(problem.tensor_order):
                    factor = (
                        factors[site][rows[k] * dims[site] + columns[k]]
                        if site in factors
                        else complex(rows[k] == columns[k])
                    )
                    value *= factor
                    ctx.finite(value, path)
                result[i * size + j] += value
                ctx.finite(result[i * size + j], path)
        del factors
    return result


def _psd(
    matrix: list[complex], size: int, ctx: _NumericContext, path: str, *, retained: int = 0
) -> None:
    # 预估原矩阵、Hermitian 分量、实嵌入和有理数临时槽位。
    ctx.slots(retained + 7 * size * size + 32, path)
    width = 2 * size
    embedded = [[Fraction(0)] * width for _ in range(width)]
    half = Fraction(1, 2)
    tau = ctx.exact(_PSD_TOLERANCE, path)
    for i in range(size):
        for j in range(size):
            a, b = matrix[i * size + j], matrix[j * size + i]
            real = ctx.multiply(
                ctx.add(ctx.exact(a.real, path), ctx.exact(b.real, path), path), half, path
            )
            imag = ctx.multiply(
                ctx.add(ctx.exact(a.imag, path), -ctx.exact(b.imag, path), path), half, path
            )
            if i == j:
                real = ctx.add(real, tau, path)
            embedded[i][j] = embedded[i + size][j + size] = real
            embedded[i][j + size] = -imag
            embedded[i + size][j] = imag
    for k in range(width):
        pivot = embedded[k][k]
        if pivot < 0:
            ctx.fail("PSD", path, pivot=k, sign="negative")
        if pivot == 0:
            if any(embedded[i][k] != 0 for i in range(k + 1, width)):
                ctx.fail("PSD", path, pivot=k, sign="zero", nonzero_column=True)
            continue
        inverse = ctx.rational(pivot.denominator, pivot.numerator, path)
        for i in range(k + 1, width):
            for j in range(i, width):
                ctx.update(path)
                delta = ctx.multiply(
                    ctx.multiply(embedded[i][k], embedded[j][k], path), inverse, path
                )
                value = ctx.add(embedded[j][i], -delta, path)
                embedded[j][i] = embedded[i][j] = value


def _state(
    values: list[complex],
    kind: str,
    size: int,
    ctx: _NumericContext,
    path: str,
    *,
    retained: int = 0,
) -> None:
    ctx.slots(retained + len(values) + 16, path)
    if kind == "ket":
        total = 0.0
        for value in values:
            term = value.real * value.real + value.imag * value.imag
            ctx.finite(term, path)
            total += term
            ctx.finite(total, path)
        if not abs(total - 1) <= _NORMALIZATION_TOLERANCE:
            ctx.fail("NORMALIZATION", path, norm_squared=total)
        return
    trace = 0j
    for i in range(size):
        trace += values[i * size + i]
        ctx.finite(trace, path)
    if not (
        abs(trace.real - 1) <= _NORMALIZATION_TOLERANCE
        and abs(trace.imag) <= _NORMALIZATION_TOLERANCE
    ):
        ctx.fail("NORMALIZATION", path, trace_real=trace.real, trace_imag=trace.imag)
    _hermitian(values, size, ctx, path)
    _psd(values, size, ctx, path, retained=retained)


def _initial_state(problem: Problem, ctx: _NumericContext, prefix: str) -> None:
    path = prefix + "/initial_state"
    state = problem.initial_state
    dims = {site.id: site.dim for site in problem.sites}
    size = math.prod(dims.values())
    if state.kind != "product":
        assert state.data is not None
        ctx.slots(math.prod(state.data.shape) + 16, path + "/data")
        _state(_values(state.data), state.kind, size, ctx, path + "/data")
        return
    assert state.factors is not None
    for i, factor in enumerate(state.factors):
        local_path = f"{path}/factors/{i}/data"
        ctx.slots(math.prod(factor.data.shape) + 16, local_path)
        _state(_values(factor.data), factor.kind, dims[factor.site], ctx, local_path)
    density = any(f.kind == "density" for f in state.factors)
    local_slots = sum(math.prod(f.data.shape) for f in state.factors)
    global_slots = size * size if density else size
    ctx.slots(local_slots + global_slots + 2 * len(dims) + 32, path)
    factors = {f.site: (f.kind, _values(f.data)) for f in state.factors}
    dimensions = [dims[site] for site in problem.tensor_order]
    values = []
    for i in range(size):
        rows = _coordinates(i, dimensions)
        for j in range(size if density else 1):
            columns = _coordinates(j, dimensions)
            value = 1 + 0j
            for k, site in enumerate(problem.tensor_order):
                kind, local = factors[site]
                if kind == "density":
                    factor_value = local[rows[k] * dims[site] + columns[k]]
                elif density:
                    factor_value = local[rows[k]] * local[columns[k]].conjugate()
                else:
                    factor_value = local[rows[k]]
                ctx.finite(factor_value, path)
                value *= factor_value
                ctx.finite(value, path)
            values.append(value)
    _state(
        values,
        "density" if density else "ket",
        size,
        ctx,
        path,
        retained=local_slots + 2 * len(dims),
    )


def _isometry(array: ArrayData, ctx: _NumericContext, path: str) -> None:
    rows, columns = array.shape
    ctx.slots(rows * columns + 16, path)
    values = _values(array)
    for i in range(columns):
        for j in range(columns):
            entry = 0j
            for k in range(rows):
                term = values[k * columns + i].conjugate() * values[k * columns + j]
                ctx.finite(term, path)
                entry += term
                ctx.finite(entry, path)
            if not _close(entry, complex(i == j), ctx, path):
                ctx.fail("ISOMETRY", path, row=i, column=j)


def _check_physical(value: Problem | Request, ctx: _NumericContext) -> None:
    request = value if isinstance(value, Request) else None
    problem = request.problem if request is not None else cast(Problem, value)
    prefix = "/problem" if request is not None else ""
    size = math.prod(site.dim for site in problem.sites)
    ctx.dimension(size, prefix + "/sites")
    operators = [(problem.h0, prefix + "/h0", True)]
    operators.extend(
        (drive.operator, f"{prefix}/drives/{i}/operator", True)
        for i, drive in enumerate(problem.drives)
    )
    operators.extend(
        (jump.operator, f"{prefix}/environment/jumps/{i}/operator", False)
        for i, jump in enumerate(problem.environment.jumps)
    )
    for operator, path, hermitian in operators:
        matrix = _assemble_operator(operator, problem, ctx, path)
        if hermitian:
            _hermitian(matrix, size, ctx, path)
        del matrix
    _initial_state(problem, ctx, prefix)
    if request is not None:
        for i, observation in enumerate(request.observations):
            path = f"/observations/{i}"
            if observation.kind == "expectation":
                assert observation.operator is not None
                matrix = _assemble_operator(observation.operator, problem, ctx, path + "/operator")
                _hermitian(matrix, size, ctx, path + "/operator")
                del matrix
            elif observation.kind == "projection":
                assert observation.isometry is not None
                _isometry(observation.isometry, ctx, path + "/isometry")
