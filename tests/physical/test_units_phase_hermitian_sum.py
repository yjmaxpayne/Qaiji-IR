# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查相位、量纲和 Hermitian 总和。"""

import math

import pytest
from _p_analytic_reference import x_density, y_density, z_plus_density
from _p_fixtures import (
    CONSUMERS,
    LOWER,
    X,
    Y,
    Z,
    assert_matrix,
    consumer,
    operator,
    request,
    run,
    states,
)
from _p_matrix_ops import cvalues

from qaiji.core.physical.model import Observation, OperatorSum


@pytest.mark.parametrize("name", CONSUMERS)
def test_p_units_phase_sum(name):
    req = request(h0=operator(Y, coefficient=0.2))
    assert_matrix(states(run(name, req))[-1], y_density(0.2))
    phase = request(
        h0=operator(Z, coefficient=0.1),
        ket=[2**-0.5, 2**-0.5],
        observations=(
            Observation(id="state", kind="full_state", representation="density"),
            Observation(id="Y", kind="expectation", operator=operator(Y, unit="1")),
        ),
    )
    result = run(name, phase)
    assert_matrix(states(result)[-1], z_plus_density(0.1))
    assert abs(cvalues(result.observations[1].data)[-1] - math.sin(0.2)) <= 1e-10
    upper = [[0, 0], [1, 0]]
    summed = OperatorSum(unit="rad/ns", terms=operator(LOWER).terms + operator(upper).terms)
    assert_matrix(consumer(name).assemble(req.problem, summed), X)
    assert_matrix(states(run(name, request(h0=summed)))[-1], x_density(1))


@pytest.mark.parametrize("name", CONSUMERS)
@pytest.mark.parametrize("variant", ["extra-2pi", "reverse-Y", "wrong-Hamiltonian-sign"])
def test_p_rejects_phase_unit_sign(name, variant, monkeypatch):
    from _p_matrix_ops import scale

    module = consumer(name)
    req = request(h0=operator(Y, coefficient=0.2))
    expected = y_density(0.2)
    assert_matrix(states(run(name, req))[-1], expected)
    target = {
        "extra-2pi": "hamiltonian",
        "reverse-Y": "assemble",
        "wrong-Hamiltonian-sign": "generator",
    }[variant]
    original = getattr(module, target)
    if variant == "reverse-Y":

        def faulty(*args):
            return [[x.conjugate() for x in row] for row in original(*args)]
    else:

        def faulty(*args):
            return scale(original(*args), 2 * math.pi if variant == "extra-2pi" else -1)

    with monkeypatch.context() as patch:
        patch.setattr(module, target, faulty)
        with pytest.raises(AssertionError, match="physical values"):
            assert_matrix(states(run(name, req))[-1], expected)
    assert_matrix(states(run(name, req))[-1], expected)
