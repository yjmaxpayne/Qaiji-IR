# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""构造自包含的物理验收产物。"""

from __future__ import annotations

import importlib
import math
from dataclasses import replace

from _p_matrix_ops import cvalues, flatten, fvalues, outer

from physical_result_factories import carray, farray, result_request
from qaiji.core.physical.codec import dump_request
from qaiji.core.physical.model import (
    Drive,
    Environment,
    Jump,
    LocalFactor,
    Observation,
    OperatorSum,
    OperatorTerm,
    ProductFactor,
    Signal,
    Site,
    State,
)

X = [[0j, 1 + 0j], [1 + 0j, 0j]]
Y = [[0j, -1j], [1j, 0j]]
Z = [[1 + 0j, 0j], [0j, -1 + 0j]]
LOWER = [[0j, 1 + 0j], [0j, 0j]]
CONSUMERS = ("a", "b")


def consumer(name):
    return importlib.import_module(f"_p_consumer_{name}")


def operator(matrix, site="a", coefficient=1, unit="rad/ns"):
    return OperatorSum(
        unit=unit,
        terms=(
            OperatorTerm(
                coefficient=coefficient,
                factors=(
                    LocalFactor(
                        site=site, matrix=carray(flatten(matrix), (len(matrix), len(matrix[0])))
                    ),
                ),
            ),
        ),
    )


def request(
    *,
    sites=None,
    edges=(0.0, 1.0),
    times=None,
    ket=None,
    density=None,
    h0=None,
    drives=(),
    jumps=(),
    observations=None,
    tensor_order=None,
):
    base = result_request()
    sites = tuple(sites or (Site(id="a", dim=2, basis=("0", "1")),))
    order = tuple(tensor_order or (s.id for s in sites))
    dim = math.prod(s.dim for s in sites)
    if density is not None:
        initial = State(kind="density", frame="lab", data=carray(flatten(density), (dim, dim)))
    else:
        ket = ket if ket is not None else [1] + [0] * (dim - 1)
        initial = State(kind="ket", frame="lab", data=carray(ket, (dim,)))
    problem = replace(
        base.problem,
        sites=sites,
        tensor_order=order,
        h0=h0 or OperatorSum(unit="rad/ns", terms=()),
        drives=tuple(drives),
        environment=Environment(kind="markovian" if jumps else "closed", jumps=tuple(jumps)),
        initial_state=initial,
        signal_edges=farray(edges),
        extensions=(),
    )
    return replace(
        base,
        problem=problem,
        output_times=farray(edges if times is None else times),
        observations=tuple(observations)
        if observations is not None
        else (Observation(id="state", kind="full_state", representation="density"),),
        policy=replace(base.policy, representation="density", max_step_ns=None),
    )


def drive_request():
    return request(
        edges=(0, 1, 3),
        times=(0, 0.5, 1, 3),
        drives=(
            Drive(
                id="drive",
                operator=operator(X, unit="1"),
                signal=Signal(kind="zoh", unit="rad/ns", values=farray([0.2, 0.4])),
            ),
        ),
    )


def damping_request(*, sampled=False):
    edges = (0, 1, 3) if sampled else (0, 50)
    rate = (
        Signal(kind="zoh", unit="1/ns", values=farray([0.1, 0.3]))
        if sampled
        else Signal(
            kind="constant",
            unit="1/ns",
            value=0.02,
        )
    )
    return request(
        edges=edges,
        times=(0, 0.5, 1, 2, 3) if sampled else (0, 50),
        ket=[0, 1],
        jumps=(Jump(id="decay", operator=operator(LOWER, unit="1"), rate=rate),),
    )


def asymmetric_request():
    return request(
        sites=(Site(id="a", dim=2, basis=("0", "1")), Site(id="b", dim=3, basis=("0", "1", "2"))),
        ket=[0, 0, 1, 0, 0, 0],
        h0=operator(X, site="a"),
    )


def product_request():
    req = asymmetric_request()
    factors = (
        ProductFactor(site="b", kind="ket", data=carray([0, 0, 1], (3,))),
        ProductFactor(site="a", kind="ket", data=carray([1, 0], (2,))),
    )
    return replace(
        req,
        problem=replace(
            req.problem,
            initial_state=State(
                kind="product",
                frame="lab",
                factors=factors,
            ),
            h0=OperatorSum(unit="rad/ns", terms=()),
        ),
    )


def payload(req):
    return dump_request(req).document


def run(name, req):
    return consumer(name).solve(payload(req))


def states(result, observation_id="state"):
    value = next(x for x in result.observations if x.id == observation_id)
    values = cvalues(value.data)
    if value.representation == "ket":
        size = value.data.shape[1]
        return [outer(values[i : i + size]) for i in range(0, len(values), size)]
    size = value.data.shape[-1]
    width = size * size
    return [
        [values[i + j * size : i + (j + 1) * size] for j in range(size)]
        for i in range(0, len(values), width)
    ]


def assert_matrix(actual, expected, *, label="physical values", atol=1e-10):
    assert len(actual) == len(expected), label
    assert all(len(a) == len(b) for a, b in zip(actual, expected, strict=True)), label
    error = max(
        (
            abs(x - y)
            for a, b in zip(actual, expected, strict=True)
            for x, y in zip(a, b, strict=True)
        ),
        default=0,
    )
    assert error <= atol, f"{label}: error={error}"


def assert_times(result, expected):
    assert fvalues(result.output_times) == list(expected), "output times"


def projection_request(kind):
    if kind == "complex":
        v = [2**-0.5, 1j * 2**-0.5, 0]
        rho = [[v[i] * v[j].conjugate() for j in range(3)] for i in range(3)]
        iso = carray(v, (3, 1))
        dim = 3
    elif kind == "trace":
        rho = [[1 + 2**-35, 0], [0, 0]]
        iso = carray([1, 0, 0, 1], (2, 2))
        dim = 2
    else:
        rho = [[0.5, 0, 0], [0, 0.25, 0], [0, 0, 0.25]]
        iso = carray([1, 0, 0, 1, 0, 0], (3, 2))
        dim = 3
    return request(
        sites=(Site(id="a", dim=dim, basis=tuple(str(i) for i in range(dim))),),
        edges=(0,),
        density=rho,
        observations=(
            Observation(
                id="projection",
                kind="projection",
                input_sites=("a",),
                isometry=iso,
            ),
        ),
    )


def ordered_reduction_request():
    return request(
        sites=(Site(id="a", dim=2, basis=("0", "1")), Site(id="b", dim=3, basis=("0", "1", "2"))),
        edges=(0,),
        ket=[0, 0, 1, 0, 0, 0],
        observations=(Observation(id="reordered", kind="partial_trace", keep_sites=("b", "a")),),
    )
