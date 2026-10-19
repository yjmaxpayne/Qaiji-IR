# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""分别对照独立解析参考。"""

import pytest
from _p_analytic_reference import decay_density, y_density
from _p_fixtures import CONSUMERS, Y, assert_matrix, damping_request, operator, request, states

from qaiji.core.physical.results import check_result


def oracle_case(case):
    import math

    from _p_analytic_reference import decay_exponent, drive_angle, x_density, z_plus_density
    from _p_fixtures import (
        LOWER,
        Z,
        asymmetric_request,
        drive_request,
        product_request,
        projection_request,
    )

    from qaiji.core.physical.model import Observation, OperatorSum, Site

    if case == "rotation":
        return request(h0=operator(Y, coefficient=0.2)), [y_density(0), y_density(0.2)]
    if case == "phase":
        req = request(
            h0=operator(Z, coefficient=0.1),
            ket=[2**-0.5, 2**-0.5],
            observations=(
                Observation(id="state", kind="full_state", representation="density"),
                Observation(id="Y", kind="expectation", operator=operator(Y, unit="1")),
            ),
        )
        return req, [z_plus_density(0), z_plus_density(0.1)]
    if case == "decay":
        return damping_request(), [decay_density(0), decay_density(1)]
    if case == "zoh-drive":
        return drive_request(), [x_density(drive_angle(t)) for t in (0, 0.5, 1, 3)]
    if case == "zoh-rate":
        return damping_request(sampled=True), [
            decay_density(decay_exponent(t)) for t in (0, 0.5, 1, 2, 3)
        ]
    if case == "asymmetric":
        expected = []
        for theta in (0, 1):
            c, v = math.cos(theta), math.sin(theta)
            rho = [[0j] * 6 for _ in range(6)]
            rho[2][2], rho[5][5] = c * c, v * v
            rho[2][5], rho[5][2] = 1j * c * v, -1j * c * v
            expected.append(rho)
        return asymmetric_request(), expected
    if case == "bell":
        req = request(
            sites=(Site(id="a", dim=2, basis=("0", "1")), Site(id="b", dim=2, basis=("0", "1"))),
            edges=(0,),
            ket=[2**-0.5, 0, 0, 2**-0.5],
            observations=(Observation(id="reduced", kind="partial_trace", keep_sites=("b",)),),
        )
        return req, [[[0.5, 0], [0, 0.5]]]
    if case in ("basic-projection", "complex-projection", "trace-projection"):
        kind = case.split("-")[0]
        expected = (
            [[0.5, 0], [0, 0.25]]
            if kind == "basic"
            else [[1]]
            if kind == "complex"
            else [[1 + 2**-35, 0], [0, 0]]
        )
        return projection_request(kind), [expected]
    if case == "zero":
        return request(edges=(7,), ket=[0, 1]), [[[0, 0], [0, 1]]]
    if case == "hermitian-sum":
        summed = OperatorSum(
            unit="rad/ns", terms=operator(LOWER).terms + operator([[0, 0], [1, 0]]).terms
        )
        return request(h0=summed), [x_density(0), x_density(1)]
    assert case == "product"
    rho = [[complex(i == j == 2) for j in range(6)] for i in range(6)]
    return product_request(), [rho, rho]


@pytest.mark.parametrize(
    "case",
    [
        "asymmetric",
        "rotation",
        "phase",
        "decay",
        "zoh-drive",
        "zoh-rate",
        "bell",
        "basic-projection",
        "complex-projection",
        "trace-projection",
        "zero",
        "hermitian-sum",
        "product",
    ],
)
def test_p_independent_consumers(case):
    import math

    from _p_fixtures import assert_times, consumer, payload
    from _p_matrix_ops import cvalues, fvalues

    req, expected = oracle_case(case)
    artifact = payload(req)
    results = [consumer(name).solve(artifact) for name in CONSUMERS]
    for result in results:
        assert_times(result, fvalues(req.output_times))
        value = result.observations[0]
        if value.kind == "projection":
            n = value.block.shape[-1]
            values = cvalues(value.block)
            assert_matrix([values[i * n : (i + 1) * n] for i in range(n)], expected[0])
            leakage, input_trace, trace_error = (
                ([-(2**-35)], [1 + 2**-35], [2**-35])
                if case == "trace-projection"
                else ([0.25 if case == "basic-projection" else 0], [1], [0])
            )
            for array, reference in (
                (value.leakage, leakage),
                (value.input_trace, input_trace),
                (value.trace_error, trace_error),
            ):
                if case == "trace-projection":
                    assert fvalues(array) == reference
                else:
                    assert all(
                        abs(a - b) <= 1e-10 for a, b in zip(fvalues(array), reference, strict=True)
                    )
        else:
            for actual, reference in zip(states(result, value.id), expected, strict=True):
                assert_matrix(actual, reference)
        if case == "phase":
            assert all(
                abs(a - b) <= 1e-10
                for a, b in zip(
                    cvalues(result.observations[1].data), [0, math.sin(0.2)], strict=True
                )
            )
        report = check_result(req, result, level="physical")
        assert report.complete, report.diagnostics
        assert not report.diagnostics
    for left, right in zip(results[0].observations, results[1].observations, strict=True):
        for field in ("data", "block", "leakage", "input_trace", "trace_error"):
            a, b = getattr(left, field), getattr(right, field)
            if a is not None:
                assert a.shape == b.shape
                values = cvalues if a.dtype == "c128le" else fvalues
                assert all(abs(x - y) <= 1e-10 for x, y in zip(values(a), values(b), strict=True))


def test_p_rejects_consumer_target_site(monkeypatch):

    from _p_fixtures import asymmetric_request, consumer

    req = asymmetric_request()
    a, b = consumer("a"), consumer("b")
    expected = [[complex(row == (col + 3) % 6) for col in range(6)] for row in range(6)]
    original = a.assemble
    assert_matrix(original(req.problem, req.problem.h0), expected)
    assert_matrix(b.assemble(req.problem, req.problem.h0), expected)

    def wrong_target(problem, op):
        from physical_result_factories import carray
        from qaiji.core.physical.model import LocalFactor, OperatorSum, OperatorTerm

        matrix = [[0, 1, 0], [1, 0, 0], [0, 0, 1]]
        altered = OperatorSum(
            unit=op.unit,
            terms=(
                OperatorTerm(
                    coefficient=1,
                    factors=(
                        LocalFactor(
                            site="b", matrix=carray([x for row in matrix for x in row], (3, 3))
                        ),
                    ),
                ),
            ),
        )
        return original(problem, altered)

    with monkeypatch.context() as patch:
        patch.setattr(a, "assemble", wrong_target)
        with pytest.raises(AssertionError, match="physical values"):
            assert_matrix(a.assemble(req.problem, req.problem.h0), expected)
        assert_matrix(b.assemble(req.problem, req.problem.h0), expected)
    assert_matrix(a.assemble(req.problem, req.problem.h0), expected)


@pytest.mark.parametrize("name", CONSUMERS)
def test_p_unknown_bath_refused_before_execution(name, monkeypatch):
    from pathlib import Path

    from _p_fixtures import consumer
    from _p_matrix_ops import ConsumerError

    from qaiji.core.physical.codec import load_request
    from qaiji.core.physical.validation import check_request

    data = (Path(__file__).parent / "data/bath-fixture.json").read_bytes()
    req = load_request(data)
    assert req.problem.extensions
    assert check_request(req, level="structure").complete
    module = consumer(name)
    calls = []

    def forbidden(*args):
        calls.append(args)
        raise AssertionError("unknown bath reached execution")

    for target in ("assemble", "initial_density", "generator", "evolve", "signal_value"):
        monkeypatch.setattr(module, target, forbidden)
    with pytest.raises(ConsumerError) as failure:
        module.solve(data)
    assert calls == []
    assert failure.value.category == "UNSUPPORTED_CAPABILITY"
    assert failure.value.code == "REQUIRED_EXTENSION"
    ext = req.problem.extensions[0]
    assert failure.value.details == {"namespace": ext.namespace, "version": ext.version}


def test_p_consumers_have_separate_equations():
    import ast
    import inspect

    import _p_analytic_reference as reference
    from _p_fixtures import consumer

    for name in CONSUMERS:
        module = consumer(name)
        source = inspect.getsource(module)
        tree = ast.parse(source)
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any("_numeric" in value or "_p_consumer" in value for value in imports)
        assert module.generator.__module__ == module.__name__
        assert module.assemble.__module__ == module.__name__
        assert "_p_fixtures" not in imports
    source = inspect.getsource(reference)
    assert "_p_consumer" not in source
    assert "_p_matrix_ops" not in source
