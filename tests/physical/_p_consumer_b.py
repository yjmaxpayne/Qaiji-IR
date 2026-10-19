# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""按局域坐标装配独立的测试消费者。"""

from __future__ import annotations

import bisect
import math
import struct

from _p_matrix_ops import (
    ConsumerError,
    cvalues,
    expm,
    flatten,
    fvalues,
    matmul,
    matrix,
    scale,
    zeros,
)

from qaiji.core.physical.arrays import ArrayData, FrozenJSON
from qaiji.core.physical.codec import load_request
from qaiji.core.physical.identity import request_id
from qaiji.core.physical.model import ExecutionReport, ObservationValue, PolicyDifference, Result
from qaiji.core.physical.validation import check_request


def _dimensions(problem):
    sites = {site.id: site.dim for site in problem.sites}
    return [sites[site] for site in problem.tensor_order]


def _coordinate(index, dimensions):
    result = [0] * len(dimensions)
    for position in range(len(dimensions) - 1, -1, -1):
        index, result[position] = divmod(index, dimensions[position])
    return result


def _index(coordinate, dimensions):
    value = 0
    for digit, size in zip(coordinate, dimensions, strict=True):
        value = value * size + digit
    return value


def assemble(problem, operator):
    """用全局行列坐标装配算子和。"""
    dimensions = _dimensions(problem)
    size = math.prod(dimensions)
    coordinates = [_coordinate(index, dimensions) for index in range(size)]
    result = zeros(size)
    for term in operator.terms:
        local = {factor.site: matrix(factor.matrix) for factor in term.factors}
        for row, row_coordinate in enumerate(coordinates):
            for col, col_coordinate in enumerate(coordinates):
                value = term.coefficient
                for position, site in enumerate(problem.tensor_order):
                    left, right = row_coordinate[position], col_coordinate[position]
                    value *= local[site][left][right] if site in local else complex(left == right)
                result[row][col] += value
    return result


def initial_density(problem):
    """按坐标恢复全局密度矩阵。"""
    state = problem.initial_state
    dimensions = _dimensions(problem)
    size = math.prod(dimensions)
    if state.kind == "density":
        return matrix(state.data)
    if state.kind == "ket":
        values = cvalues(state.data)
        return [[left * right.conjugate() for right in values] for left in values]
    factors = {factor.site: factor for factor in state.factors}
    if set(factors) != set(problem.tensor_order):
        raise ConsumerError("INVALID_REQUEST", "PRODUCT_COVERAGE")
    local = {}
    for site, factor in factors.items():
        values = cvalues(factor.data)
        local[site] = (
            [[left * right.conjugate() for right in values] for left in values]
            if factor.kind == "ket"
            else matrix(factor.data)
        )
    coordinates = [_coordinate(index, dimensions) for index in range(size)]
    result = zeros(size)
    for row, left in enumerate(coordinates):
        for col, right in enumerate(coordinates):
            value = 1 + 0j
            for position, site in enumerate(problem.tensor_order):
                value *= local[site][left[position]][right[position]]
            result[row][col] = value
    return result


def signal_value(signal, edges, time):
    """内部边界取右值，末端取左极限。"""
    if len(edges) < 2:
        raise ConsumerError("INVALID_REQUEST", "ZERO_DURATION_COEFFICIENT")
    if signal.kind == "constant":
        return signal.value
    interval = min(bisect.bisect_right(edges, time) - 1, len(edges) - 2)
    return fvalues(signal.values)[interval]


def hamiltonian(problem, time):
    """独立累加静态项与驱动项。"""
    result = assemble(problem, problem.h0)
    edges = fvalues(problem.signal_edges)
    for drive in problem.drives:
        amplitude = signal_value(drive.signal, edges, time)
        drive_matrix = assemble(problem, drive.operator)
        for row in range(len(result)):
            for col in range(len(result)):
                result[row][col] += amplitude * drive_matrix[row][col]
    return result


def generator(problem, time):
    """直接按四指标构造密度矩阵生成元。"""
    h = hamiltonian(problem, time)
    size = len(h)
    result = zeros(size * size)
    for i in range(size):
        for j in range(size):
            for k in range(size):
                for ell in range(size):
                    result[i * size + j][k * size + ell] = -1j * (
                        h[i][k] * (j == ell) - (i == k) * h[ell][j]
                    )
    edges = fvalues(problem.signal_edges)
    for jump in problem.environment.jumps:
        rate = signal_value(jump.rate, edges, time)
        local = assemble(problem, jump.operator)
        gram = [
            [sum(local[m][i].conjugate() * local[m][k] for m in range(size)) for k in range(size)]
            for i in range(size)
        ]
        for i in range(size):
            for j in range(size):
                for k in range(size):
                    for ell in range(size):
                        result[i * size + j][k * size + ell] += rate * (
                            local[i][k] * local[j][ell].conjugate()
                            - 0.5 * gram[i][k] * (j == ell)
                            - 0.5 * (i == k) * gram[ell][j]
                        )
    return result


def evolve(equation, rho, duration):
    """用常系数生成元演化指定时长。"""
    values = matmul(expm(scale(equation, duration)), [[value] for value in flatten(rho)])
    size = len(rho)
    return [[values[i * size + j][0] for j in range(size)] for i in range(size)]


def partial_trace(problem, rho, keep_sites):
    """按声明顺序编码保留位点的坐标。"""
    dimensions = _dimensions(problem)
    positions = [problem.tensor_order.index(site) for site in keep_sites]
    discarded = [p for p in range(len(dimensions)) if p not in positions]
    kept_dimensions = [dimensions[p] for p in positions]
    result = zeros(math.prod(kept_dimensions))
    coordinates = [_coordinate(index, dimensions) for index in range(len(rho))]
    for row, left in enumerate(coordinates):
        kept_row = _index([left[p] for p in positions], kept_dimensions)
        for col, right in enumerate(coordinates):
            if all(left[p] == right[p] for p in discarded):
                kept_col = _index([right[p] for p in positions], kept_dimensions)
                result[kept_row][kept_col] += rho[row][col]
    return result


def project(rho, isometry):
    """计算复数投影块与未经截断的泄漏。"""
    v = matrix(isometry)
    count = len(v[0])
    block = zeros(count)
    for row in range(count):
        for col in range(count):
            block[row][col] = sum(
                v[i][row].conjugate() * rho[i][j] * v[j][col]
                for i in range(len(rho))
                for j in range(len(rho))
            )
    input_trace = sum(rho[i][i].real for i in range(len(rho)))
    block_trace = sum(block[i][i].real for i in range(count))
    return block, 1.0 - block_trace, input_trace, input_trace - 1.0


def _complex_array(values, shape):
    return ArrayData.from_values(dtype="c128le", shape=shape, values=values)


def _real_array(values):
    return ArrayData.from_values(dtype="f64le", shape=(len(values),), values=values)


def _observations(request, states):
    values = []
    for observation in request.observations:
        if observation.kind == "full_state":
            size = len(states[0])
            values.append(
                ObservationValue(
                    id=observation.id,
                    kind="full_state",
                    representation="density",
                    data=_complex_array(
                        [x for rho in states for x in flatten(rho)], (len(states), size, size)
                    ),
                )
            )
        elif observation.kind == "expectation":
            operator = assemble(request.problem, observation.operator)
            expectation = [
                sum(rho[i][j] * operator[j][i] for i in range(len(rho)) for j in range(len(rho)))
                for rho in states
            ]
            values.append(
                ObservationValue(
                    id=observation.id,
                    kind="expectation",
                    data=_complex_array(expectation, (len(states),)),
                )
            )
        elif observation.kind == "partial_trace":
            reduced = [
                partial_trace(request.problem, rho, observation.keep_sites) for rho in states
            ]
            size = len(reduced[0])
            values.append(
                ObservationValue(
                    id=observation.id,
                    kind="partial_trace",
                    keep_sites=observation.keep_sites,
                    data=_complex_array(
                        [x for rho in reduced for x in flatten(rho)], (len(states), size, size)
                    ),
                )
            )
        else:
            projected = [
                project(
                    partial_trace(request.problem, rho, observation.input_sites),
                    observation.isometry,
                )
                for rho in states
            ]
            size = len(projected[0][0])
            values.append(
                ObservationValue(
                    id=observation.id,
                    kind="projection",
                    input_sites=observation.input_sites,
                    block=_complex_array(
                        [x for item in projected for x in flatten(item[0])],
                        (len(states), size, size),
                    ),
                    leakage=_real_array([item[1] for item in projected]),
                    input_trace=_real_array([item[2] for item in projected]),
                    trace_error=_real_array([item[3] for item in projected]),
                )
            )
    return tuple(values)


def _report(request, observations):
    policy = request.policy
    differences = []
    if policy.method.mode == "delegate":
        differences.append(
            PolicyDifference(
                path="/policy/method",
                requested=FrozenJSON(
                    value={
                        "mode": "delegate",
                        "value": None,
                        "allowed": list(policy.method.allowed),
                    }
                ),
                actual=FrozenJSON(value="reference-exact"),
                basis="delegated",
            )
        )
    if policy.representation == "either":
        differences.append(
            PolicyDifference(
                path="/policy/representation",
                requested=FrozenJSON(value="either"),
                actual=FrozenJSON(value="density"),
                basis="allowed_representation",
            )
        )
    actual = {
        "method": "reference-exact",
        "atol": struct.pack(">d", policy.atol).hex(),
        "rtol": struct.pack(">d", policy.rtol).hex(),
        "max_step_ns": (
            None if policy.max_step_ns is None else struct.pack(">d", policy.max_step_ns).hex()
        ),
        "representation": "density",
    }
    return ExecutionReport(
        backend_id="coordinate-reference",
        backend_version="1",
        actual_policy=FrozenJSON(value=actual),
        policy_differences=tuple(differences),
        transforms=(),
        state_representations=FrozenJSON(
            value={item.id: "density" for item in observations if item.kind != "expectation"}
        ),
        validation_level="structure",
        diagnostics=(),
    )


def output_times(request):
    """读取请求中的输出标签。"""
    return fvalues(request.output_times)


def state_time(problem, time):
    """保留状态的实际输出时刻。"""
    return time


def solve(payload: bytes) -> Result:
    """从请求字节恢复问题并返回真实时刻的状态。"""
    request = load_request(payload)
    problem = request.problem
    if problem.extensions:
        extension = problem.extensions[0]
        raise ConsumerError(
            "UNSUPPORTED_CAPABILITY",
            "REQUIRED_EXTENSION",
            {
                "namespace": extension.namespace,
                "version": extension.version,
            },
        )
    report = check_request(request, level="structure")
    if not report.complete or report.diagnostics:
        raise ConsumerError("INVALID_REQUEST", "STRUCTURE", {"diagnostics": report.diagnostics})
    method = request.policy.method
    if (method.mode == "fixed" and method.value != "reference-exact") or (
        method.mode == "delegate" and "reference-exact" not in method.allowed
    ):
        raise ConsumerError("UNSUPPORTED_CAPABILITY", "METHOD")
    if request.policy.representation == "ket" or any(
        observation.kind == "full_state" and observation.representation == "ket"
        for observation in request.observations
    ):
        raise ConsumerError("UNSUPPORTED_CAPABILITY", "REPRESENTATION")
    if problem.frame != "lab" or problem.approximations:
        raise ConsumerError("UNSUPPORTED_CAPABILITY", "FRAME_OR_APPROXIMATION")
    edges = fvalues(problem.signal_edges)
    current = edges[0]
    rho = initial_density(problem)
    states = []
    times = output_times(request)
    if not times:
        raise ConsumerError("INVALID_RESULT", "OUTPUT_TIMES")
    for label in times:
        target = state_time(problem, label)
        while current < target:
            interval = bisect.bisect_right(edges, current) - 1
            boundary = min(target, edges[interval + 1])
            duration = boundary - current
            equation = generator(problem, current)
            max_step = request.policy.max_step_ns
            count = 1 if max_step is None else max(1, math.ceil(duration / max_step))
            for _ in range(count):
                rho = evolve(equation, rho, duration / count)
            current = boundary
        states.append([row[:] for row in rho])
    observations = _observations(request, states)
    return Result(
        request_id=request_id(request),
        output_times=_real_array(times),
        tensor_order=problem.tensor_order,
        frame=problem.frame,
        observations=observations,
        report=_report(request, observations),
    )
