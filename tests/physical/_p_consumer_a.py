# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""按张量顺序装配测试方程与观测。"""

from __future__ import annotations

import bisect
import itertools
import math
import struct

from _p_matrix_ops import (
    ConsumerError,
    add,
    cvalues,
    dagger,
    expm,
    eye,
    flatten,
    fvalues,
    kron,
    matmul,
    matrix,
    outer,
    scale,
    trace,
    zeros,
)

from qaiji.core.physical import (
    ArrayData,
    ExecutionReport,
    FrozenJSON,
    ObservationValue,
    PolicyDifference,
    Result,
)
from qaiji.core.physical.codec import load_request
from qaiji.core.physical.identity import request_id


def assemble(problem, operator):
    """按 tensor_order 对每项逐次取张量积。"""
    dimensions = {site.id: site.dim for site in problem.sites}
    result = zeros(math.prod(dimensions.values()))
    for term in operator.terms:
        factors = {factor.site: matrix(factor.matrix) for factor in term.factors}
        term_matrix = [[1 + 0j]]
        for site in problem.tensor_order:
            local = factors.get(site)
            term_matrix = kron(term_matrix, eye(dimensions[site]) if local is None else local)
        result = add(result, scale(term_matrix, term.coefficient))
    return result


def initial_density(problem):
    """按张量顺序构造初始密度矩阵。"""
    state = problem.initial_state
    if state.kind == "density":
        return matrix(state.data)
    if state.kind == "ket":
        return outer(cvalues(state.data))
    factors = {factor.site: factor for factor in state.factors}
    if set(factors) != set(problem.tensor_order):
        raise ConsumerError("INVALID_REQUEST", "PRODUCT_COVERAGE")
    result = [[1 + 0j]]
    for site in problem.tensor_order:
        factor = factors[site]
        local = matrix(factor.data) if factor.kind == "density" else outer(cvalues(factor.data))
        result = kron(result, local)
    return result


def signal_value(signal, edges, time):
    """内部边界取右区间。末端取左极限。"""
    if len(edges) < 2 or edges[0] == edges[-1]:
        raise ConsumerError("INVALID_REQUEST", "ZERO_DURATION_COEFFICIENT")
    if signal.kind == "constant":
        return signal.value
    index = min(len(edges) - 2, bisect.bisect_right(edges, time) - 1)
    if index < 0 or time > edges[-1]:
        raise ConsumerError("INVALID_REQUEST", "TIME_RANGE")
    return fvalues(signal.values)[index]


def hamiltonian(problem, time):
    """使用已声明的 rad/ns 数值构造 Hamiltonian。"""
    result = assemble(problem, problem.h0)
    edges = fvalues(problem.signal_edges)
    for drive in problem.drives:
        result = add(
            result,
            scale(assemble(problem, drive.operator), signal_value(drive.signal, edges, time)),
        )
    return result


def generator(problem, time):
    """为按行展开的密度矩阵构造 Lindblad 方程。"""
    h = hamiltonian(problem, time)
    identity = eye(len(h))
    transpose = [list(row) for row in zip(*h, strict=True)]
    result = scale(add(kron(h, identity), scale(kron(identity, transpose), -1)), -1j)
    edges = fvalues(problem.signal_edges)
    for jump in problem.environment.jumps:
        operator = assemble(problem, jump.operator)
        norm = matmul(dagger(operator), operator)
        conjugate = [[value.conjugate() for value in row] for row in operator]
        norm_transpose = [list(row) for row in zip(*norm, strict=True)]
        dissipator = add(
            kron(operator, conjugate),
            scale(add(kron(norm, identity), kron(identity, norm_transpose)), -0.5),
        )
        result = add(result, scale(dissipator, signal_value(jump.rate, edges, time)))
    return result


def evolve(generator, rho, duration):
    """对单个常系数区间计算矩阵指数。"""
    propagator = expm(scale(generator, duration))
    column = matmul(propagator, [[value] for value in flatten(rho)])
    dimension = len(rho)
    return [
        [column[row * dimension + col][0] for col in range(dimension)] for row in range(dimension)
    ]


def partial_trace(problem, rho, keep_sites):
    """按 keep_sites 声明的顺序计算部分迹。"""
    dimensions = {site.id: site.dim for site in problem.sites}
    discarded = tuple(site for site in problem.tensor_order if site not in keep_sites)
    kept_coordinates = list(itertools.product(*(range(dimensions[site]) for site in keep_sites)))
    discarded_coordinates = list(
        itertools.product(*(range(dimensions[site]) for site in discarded))
    )

    def index(kept, rest):
        coordinates = dict(zip(keep_sites, kept, strict=True))
        coordinates.update(zip(discarded, rest, strict=True))
        value = 0
        for site in problem.tensor_order:
            value = value * dimensions[site] + coordinates[site]
        return value

    result = zeros(len(kept_coordinates))
    for row, left in enumerate(kept_coordinates):
        for col, right in enumerate(kept_coordinates):
            result[row][col] = sum(
                rho[index(left, rest)][index(right, rest)] for rest in discarded_coordinates
            )
    return result


def project(rho, isometry):
    """保留投影块的原始迹与原始泄漏。"""
    embedding = matrix(isometry)
    block = matmul(matmul(dagger(embedding), rho), embedding)
    input_trace = trace(rho).real
    return block, 1.0 - trace(block).real, input_trace, input_trace - 1.0


def _carray(values, shape):
    return ArrayData.from_values(dtype="c128le", shape=shape, values=values)


def _farray(values):
    return ArrayData.from_values(dtype="f64le", shape=(len(values),), values=values)


def _observations(request, states):
    result = []
    problem = request.problem
    count = len(states)
    for observation in request.observations:
        common = {"id": observation.id, "kind": observation.kind}
        if observation.kind == "full_state":
            if observation.representation not in ("density", "either"):
                raise ConsumerError("UNSUPPORTED_CAPABILITY", "REPRESENTATION")
            dimension = len(states[0])
            result.append(
                ObservationValue(
                    **common,
                    representation="density",
                    data=_carray(
                        [value for state in states for value in flatten(state)],
                        (count, dimension, dimension),
                    ),
                )
            )
        elif observation.kind == "expectation":
            operator = assemble(problem, observation.operator)
            result.append(
                ObservationValue(
                    **common,
                    data=_carray([trace(matmul(operator, state)) for state in states], (count,)),
                )
            )
        elif observation.kind == "partial_trace":
            reduced = [partial_trace(problem, state, observation.keep_sites) for state in states]
            dimension = len(reduced[0])
            result.append(
                ObservationValue(
                    **common,
                    keep_sites=observation.keep_sites,
                    data=_carray(
                        [value for state in reduced for value in flatten(state)],
                        (count, dimension, dimension),
                    ),
                )
            )
        else:
            projections = [
                project(
                    partial_trace(problem, state, observation.input_sites), observation.isometry
                )
                for state in states
            ]
            dimension = observation.isometry.shape[1]
            result.append(
                ObservationValue(
                    **common,
                    input_sites=observation.input_sites,
                    block=_carray(
                        [value for block, *_ in projections for value in flatten(block)],
                        (count, dimension, dimension),
                    ),
                    leakage=_farray([value[1] for value in projections]),
                    input_trace=_farray([value[2] for value in projections]),
                    trace_error=_farray([value[3] for value in projections]),
                )
            )
    return tuple(result)


def _report(request):
    policy = request.policy
    differences = []
    if policy.method.mode == "delegate":
        if "reference-exact" not in policy.method.allowed:
            raise ConsumerError("UNSUPPORTED_CAPABILITY", "METHOD")
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
    elif policy.method.value != "reference-exact":
        raise ConsumerError("UNSUPPORTED_CAPABILITY", "METHOD")
    if policy.representation == "either":
        differences.append(
            PolicyDifference(
                path="/policy/representation",
                requested=FrozenJSON(value="either"),
                actual=FrozenJSON(value="density"),
                basis="allowed_representation",
            )
        )
    elif policy.representation != "density":
        raise ConsumerError("UNSUPPORTED_CAPABILITY", "REPRESENTATION")
    actual = {
        "method": "reference-exact",
        "representation": "density",
        "atol": struct.pack(">d", policy.atol).hex(),
        "rtol": struct.pack(">d", policy.rtol).hex(),
        "max_step_ns": None
        if policy.max_step_ns is None
        else struct.pack(">d", policy.max_step_ns).hex(),
    }
    return ExecutionReport(
        backend_id="test-consumer-a",
        backend_version="1",
        actual_policy=FrozenJSON(value=actual),
        policy_differences=tuple(differences),
        transforms=(),
        state_representations=FrozenJSON(
            value={
                item.id: "density" for item in request.observations if item.kind != "expectation"
            }
        ),
        validation_level="transport",
        diagnostics=(),
    )


def output_times(request):
    """返回请求中的实际输出时刻。"""
    return fvalues(request.output_times)


def state_time(problem, time):
    """保留输出时刻对应的演化时刻。"""
    return time


def solve(payload):
    """从交换字节恢复请求并返回独立计算的结果。"""
    request = load_request(payload)
    problem = request.problem
    if problem.extensions:
        extension = problem.extensions[0]
        raise ConsumerError(
            "UNSUPPORTED_CAPABILITY",
            "REQUIRED_EXTENSION",
            {"namespace": extension.namespace, "version": extension.version},
        )
    if problem.frame != "lab" or problem.approximations:
        raise ConsumerError("UNSUPPORTED_CAPABILITY", "FRAME_OR_APPROXIMATION")
    report = _report(request)
    edges = fvalues(problem.signal_edges)
    rho = initial_density(problem)
    current = edges[0]
    times = output_times(request)
    states = []
    for output_time in times:
        target = state_time(problem, output_time)
        while current < target:
            next_edge = next(edge for edge in edges if edge > current)
            endpoint = min(next_edge, target)
            if request.policy.max_step_ns is not None:
                endpoint = min(endpoint, current + request.policy.max_step_ns)
            rho = evolve(generator(problem, current), rho, endpoint - current)
            current = endpoint
        states.append(rho)
    return Result(
        request_id=request_id(request),
        output_times=_farray(times),
        tensor_order=problem.tensor_order,
        frame=problem.frame,
        observations=_observations(request, states),
        report=report,
    )
