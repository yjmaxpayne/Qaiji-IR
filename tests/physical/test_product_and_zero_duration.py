# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查完整乘积态与零时长输出。"""

from dataclasses import replace

import pytest
from _p_fixtures import (
    CONSUMERS,
    assert_matrix,
    assert_times,
    consumer,
    product_request,
    request,
    run,
    states,
)
from _p_matrix_ops import ConsumerError

from physical_result_factories import farray
from qaiji.core.physical.model import Observation, State


@pytest.mark.parametrize("name", CONSUMERS)
def test_p_product_zero_duration(name, monkeypatch):
    module = consumer(name)
    req = product_request()
    expected = [[complex(i == j == 2) for j in range(6)] for i in range(6)]
    assert_matrix(states(run(name, req))[0], expected)
    incomplete = replace(
        req,
        problem=replace(
            req.problem,
            initial_state=State(
                kind="product",
                frame="lab",
                factors=req.problem.initial_state.factors[:1],
            ),
        ),
    )
    with pytest.raises(ConsumerError, match="INVALID_REQUEST"):
        run(name, incomplete)
    from _p_fixtures import damping_request, operator
    from _p_matrix_ops import cvalues, fvalues

    from physical_result_factories import carray

    zero = damping_request()
    zero = replace(
        zero,
        problem=replace(zero.problem, signal_edges=farray([7])),
        output_times=farray([7]),
        observations=(
            Observation(id="state", kind="full_state", representation="density"),
            Observation(
                id="population",
                kind="expectation",
                operator=operator([[0, 0], [0, 1]], unit="1"),
            ),
            Observation(id="reduced", kind="partial_trace", keep_sites=("a",)),
            Observation(
                id="projected",
                kind="projection",
                input_sites=("a",),
                isometry=carray([1, 0, 0, 1], (2, 2)),
            ),
        ),
    )
    calls = []

    def no_evolution(*args):
        calls.append(args)
        raise AssertionError("zero duration called evolution")

    for target in ("evolve", "signal_value", "generator", "hamiltonian"):
        monkeypatch.setattr(module, target, no_evolution)
    result = run(name, zero)
    assert calls == []
    assert_times(result, [7])
    assert_matrix(states(result)[0], [[0, 0], [0, 1]])
    assert result.output_times == farray([7])
    assert cvalues(result.observations[1].data) == [1 + 0j]
    assert_matrix(states(result, "reduced")[0], [[0, 0], [0, 1]])
    assert cvalues(result.observations[3].block) == [0j, 0j, 0j, 1 + 0j]
    assert fvalues(result.observations[3].leakage) == [0.0]
    from qaiji.core.physical.results import check_result

    report = check_result(zero, result, level="physical")
    assert report.complete, report.diagnostics


@pytest.mark.parametrize("name", CONSUMERS)
@pytest.mark.parametrize(
    "variant",
    ["fill-missing-ground-factor", "drop-zero-duration-output", "call-evolution-at-zero-duration"],
)
def test_p_rejects_default_state_or_empty_output(name, variant, monkeypatch):
    from _p_matrix_ops import zeros

    from physical_result_factories import carray
    from qaiji.core.physical.model import ProductFactor

    module = consumer(name)
    if variant == "fill-missing-ground-factor":
        good = product_request()
        run(name, good)
        req = replace(
            good,
            problem=replace(
                good.problem,
                initial_state=State(
                    kind="product",
                    frame="lab",
                    factors=good.problem.initial_state.factors[:1],
                ),
            ),
        )
        original = module.initial_density

        def verify():
            try:
                module.initial_density(req.problem)
            except ConsumerError as error:
                assert error.category == "INVALID_REQUEST", "missing product factor"
            else:
                raise AssertionError("missing product factor")

        def fill_missing(problem):
            factor = ProductFactor(site="a", kind="ket", data=carray([1, 0], (2,)))
            return original(
                replace(
                    problem,
                    initial_state=State(
                        kind="product",
                        frame="lab",
                        factors=(*problem.initial_state.factors, factor),
                    ),
                )
            )

        target, faulty = "initial_density", fill_missing
    else:
        req = request(edges=(7,), times=(7,), ket=[0, 1])
        calls = []
        original_solve = module.solve

        def spy(*args):
            calls.append(args)
            return [[0, 0], [0, 1]]

        monkeypatch.setattr(module, "evolve", spy)

        def verify():
            calls.clear()
            assert module.output_times(req) == [7], "zero duration output"
            result = run(name, req)
            assert not calls, "zero duration called evolution"
            assert_times(result, [7])
            assert len(states(result)) == 1, "zero duration output"
            assert_matrix(states(result)[0], [[0, 0], [0, 1]])

        if variant == "drop-zero-duration-output":
            target, faulty = "output_times", lambda r: []
        else:

            def call_evolution(data):
                module.evolve(zeros(4), [[0, 0], [0, 1]], 0)
                return original_solve(data)

            target, faulty = "solve", call_evolution
    verify()
    with monkeypatch.context() as patch:
        patch.setattr(module, target, faulty)
        with pytest.raises(
            AssertionError, match=r"missing product factor|output times|zero duration"
        ):
            verify()
    verify()
