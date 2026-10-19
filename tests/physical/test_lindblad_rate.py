# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查跳跃率的耗散语义。"""

import pytest
from _p_analytic_reference import decay_density
from _p_fixtures import CONSUMERS, assert_matrix, damping_request, run, states


@pytest.mark.parametrize("name", CONSUMERS)
def test_p_lindblad_rate(name):
    req = damping_request()
    assert req.problem.environment.jumps[0].rate.value == 0.02
    from _p_fixtures import consumer

    equation = consumer(name).generator(req.problem, 0)
    assert abs(equation[3][3] - (-0.02)) <= 1e-10
    assert_matrix(states(run(name, req))[-1], decay_density(1))


@pytest.mark.parametrize("name", CONSUMERS)
def test_p_rejects_rate_as_amplitude(name, monkeypatch):
    from _p_fixtures import consumer

    module = consumer(name)
    req = damping_request()
    expected = decay_density(1)
    assert_matrix(states(run(name, req))[-1], expected)
    original = module.signal_value

    def rate_as_amplitude(signal, edges, time):
        value = original(signal, edges, time)
        return value * value if signal.unit == "1/ns" else value

    with monkeypatch.context() as patch:
        patch.setattr(module, "signal_value", rate_as_amplitude)
        with pytest.raises(AssertionError, match="physical values"):
            assert_matrix(states(run(name, req))[-1], expected)
    assert_matrix(states(run(name, req))[-1], expected)
