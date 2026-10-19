# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查部分迹与复数投影。"""

import math

import pytest
from _p_fixtures import (
    CONSUMERS,
    assert_matrix,
    ordered_reduction_request,
    projection_request,
    request,
    run,
    states,
)
from _p_matrix_ops import fvalues, matrix

from qaiji.core.physical.model import Observation, Site


@pytest.mark.parametrize("name", CONSUMERS)
def test_p_partial_trace_projection(name):
    bell = request(
        sites=(Site(id="a", dim=2, basis=("0", "1")), Site(id="b", dim=2, basis=("0", "1"))),
        edges=(0,),
        ket=[2**-0.5, 0, 0, 2**-0.5],
        observations=(Observation(id="reduced", kind="partial_trace", keep_sites=("b",)),),
    )
    assert_matrix(states(run(name, bell), "reduced")[0], [[0.5, 0], [0, 0.5]])
    for kind in ("basic", "complex", "trace"):
        result = run(name, projection_request(kind))
        value = result.observations[0]
        block = value.block
        n = block.shape[-1]
        expected = (
            [[0.5, 0], [0, 0.25]]
            if kind == "basic"
            else [[1]]
            if kind == "complex"
            else [[1 + 2**-35, 0], [0, 0]]
        )
        from _p_matrix_ops import cvalues

        vals = cvalues(block)
        assert_matrix([vals[i * n : (i + 1) * n] for i in range(n)], expected)
        if kind == "trace":
            assert fvalues(value.leakage) == [-(2**-35)]
            assert fvalues(value.trace_error) == [2**-35]
        else:
            assert math.isclose(
                fvalues(value.leakage)[0], 0.25 if kind == "basic" else 0, abs_tol=1e-10
            )


@pytest.mark.parametrize("name", CONSUMERS)
def test_p_partial_trace_declared_order(name):
    req = ordered_reduction_request()
    expected = [[complex(i == j == 4) for j in range(6)] for i in range(6)]
    value = run(name, req).observations[0]
    assert value.keep_sites == ("b", "a")
    assert_matrix(states(run(name, req), "reordered")[0], expected)


@pytest.mark.parametrize("name", CONSUMERS)
@pytest.mark.parametrize(
    "variant",
    [
        "normalize-block",
        "transpose-without-conjugate",
        "subtract-input-trace",
        "clip-negative-leakage",
        "wrong-partial-trace-order",
    ],
)
def test_p_rejects_projection_formula(name, variant, monkeypatch):
    from _p_fixtures import consumer
    from _p_matrix_ops import dagger, matmul, scale, trace

    module = consumer(name)
    kind = (
        "complex"
        if variant == "transpose-without-conjugate"
        else "trace"
        if variant in ("subtract-input-trace", "clip-negative-leakage")
        else "basic"
    )
    req = (
        ordered_reduction_request()
        if variant == "wrong-partial-trace-order"
        else projection_request(kind)
    )

    def verify():
        if variant == "wrong-partial-trace-order":
            expected = [[complex(i == j == 4) for j in range(6)] for i in range(6)]
            assert_matrix(states(run(name, req), "reordered")[0], expected)
        else:
            value = run(name, req).observations[0]
            from _p_matrix_ops import cvalues

            n = value.block.shape[-1]
            vals = cvalues(value.block)
            expected = (
                [[0.5, 0], [0, 0.25]]
                if kind == "basic"
                else [[1]]
                if kind == "complex"
                else [[1 + 2**-35, 0], [0, 0]]
            )
            assert_matrix([vals[i * n : (i + 1) * n] for i in range(n)], expected)
            if kind == "trace":
                assert fvalues(value.leakage) == [-(2**-35)], "raw leakage"
                assert fvalues(value.trace_error) == [2**-35], "trace error"

    verify()
    with monkeypatch.context() as patch:
        if variant == "wrong-partial-trace-order":
            original = module.partial_trace
            patch.setattr(
                module,
                "partial_trace",
                lambda p, rho, keep: original(p, rho, tuple(reversed(keep))),
            )
        else:

            def faulty(rho, isometry):
                v = matrix(isometry) if hasattr(isometry, "dtype") else isometry
                left = (
                    list(map(list, zip(*v, strict=True)))
                    if variant == "transpose-without-conjugate"
                    else dagger(v)
                )
                block = matmul(matmul(left, rho), v)
                input_trace = trace(rho).real
                if variant == "normalize-block":
                    block = scale(block, 1 / trace(block).real)
                leakage = (input_trace if variant == "subtract-input-trace" else 1) - trace(
                    block
                ).real
                if variant == "clip-negative-leakage":
                    leakage = max(0, leakage)
                return block, leakage, input_trace, input_trace - 1

            patch.setattr(module, "project", faulty)
        with pytest.raises(AssertionError, match=r"physical values|raw leakage|trace error"):
            verify()
    verify()
