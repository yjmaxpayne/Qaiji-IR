# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查右连续信号与输出时刻的实际状态。"""

import pytest
from _p_analytic_reference import decay_density, decay_exponent, drive_angle, x_density
from _p_fixtures import (
    CONSUMERS,
    assert_matrix,
    assert_times,
    consumer,
    damping_request,
    drive_request,
    run,
    states,
)
from _p_matrix_ops import fvalues


@pytest.mark.parametrize("name", CONSUMERS)
def test_p_zoh_output_values(name):
    req = drive_request()
    module = consumer(name)
    signal = req.problem.drives[0].signal
    edges = fvalues(req.problem.signal_edges)
    assert module.signal_value(signal, edges, 0) == 0.2
    assert module.signal_value(signal, edges, 1) == 0.4
    assert module.signal_value(signal, edges, 3) == 0.4
    result = run(name, req)
    assert_times(result, [0, 0.5, 1, 3])
    for state, time in zip(states(result), [0, 0.5, 1, 3], strict=True):
        assert_matrix(state, x_density(drive_angle(time)))
    req = damping_request(sampled=True)
    result = run(name, req)
    for state, time in zip(states(result), [0, 0.5, 1, 2, 3], strict=True):
        assert_matrix(state, decay_density(decay_exponent(time)))


@pytest.mark.parametrize("name", CONSUMERS)
@pytest.mark.parametrize(
    "variant",
    [
        "left-boundary",
        "snapped-time-label",
        "left-edge-state-with-original-label",
        "right-edge-state-with-original-label",
        "first-rate-extended",
        "terminal-sample-consumed",
    ],
)
def test_p_rejects_zoh_and_state_snap(name, variant, monkeypatch):
    import bisect

    module = consumer(name)
    req = damping_request(sampled=True) if variant == "first-rate-extended" else drive_request()
    original_signal = module.signal_value
    original_solve = module.solve
    terminal_calls = []

    def tracked(signal, edges, time):
        if time == edges[-1]:
            terminal_calls.append(time)
        return original_signal(signal, edges, time)

    monkeypatch.setattr(module, "signal_value", tracked)

    def verify():
        terminal_calls.clear()
        result = run(name, req)
        assert_times(result, fvalues(req.output_times))
        assert terminal_calls == [], "terminal sample consumption"
        for state, time in zip(states(result), fvalues(req.output_times), strict=True):
            expected = (
                decay_density(decay_exponent(time))
                if variant == "first-rate-extended"
                else x_density(drive_angle(time))
            )
            assert_matrix(state, expected)
        if variant == "left-boundary":
            assert module.signal_value(req.problem.drives[0].signal, [0, 1, 3], 1) == 0.4, (
                "right continuity"
            )

    verify()
    with monkeypatch.context() as patch:
        if variant == "left-boundary":

            def left_value(signal, edges, time):
                if signal.kind == "constant":
                    return original_signal(signal, edges, time)
                index = max(0, min(len(edges) - 2, bisect.bisect_left(edges, time) - 1))
                return fvalues(signal.values)[index]

            patch.setattr(module, "signal_value", left_value)
        elif variant == "first-rate-extended":
            patch.setattr(
                module,
                "signal_value",
                lambda s, e, t: fvalues(s.values)[0] if s.kind == "zoh" else s.value,
            )
        elif variant == "snapped-time-label":
            edges = fvalues(req.problem.signal_edges)
            patch.setattr(
                module,
                "output_times",
                lambda r: [
                    edges[max(0, bisect.bisect_right(edges, t) - 1)]
                    for t in fvalues(r.output_times)
                ],
            )
        elif variant.endswith("state-with-original-label"):
            edges = fvalues(req.problem.signal_edges)
            right = variant.startswith("right")
            patch.setattr(
                module,
                "state_time",
                lambda p, t: (
                    edges[min(len(edges) - 1, bisect.bisect_left(edges, t))]
                    if right
                    else edges[max(0, bisect.bisect_right(edges, t) - 1)]
                ),
            )
        else:

            def consume_terminal(data):
                tracked(req.problem.drives[0].signal, fvalues(req.problem.signal_edges), 3)
                return original_solve(data)

            patch.setattr(module, "solve", consume_terminal)
        with pytest.raises(
            AssertionError,
            match=r"physical values|output times|right continuity|terminal sample consumption",
        ):
            verify()
    verify()
