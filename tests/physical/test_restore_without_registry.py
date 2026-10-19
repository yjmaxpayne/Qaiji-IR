# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查自包含产物的恢复边界。"""

import builtins

import pytest
from _p_analytic_reference import y_density
from _p_fixtures import (
    CONSUMERS,
    Y,
    assert_matrix,
    consumer,
    operator,
    payload,
    request,
    run,
    states,
)
from _p_matrix_ops import fvalues

from qaiji.core.physical.codec import load_request


@pytest.mark.parametrize("name", CONSUMERS)
def test_p_bound_restore(name, monkeypatch):
    req = request(h0=operator(Y, coefficient=0.2))
    artifact = payload(req)
    original_import = builtins.__import__

    def guarded_import(module, *args, **kwargs):
        if any(word in module.lower() for word in ("registry", "calibration", "emuplat")):
            raise AssertionError("external registry access")
        return original_import(module, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    restored = load_request(artifact)
    assert restored == req
    assert fvalues(restored.problem.signal_edges) == [0, 1]
    assert_matrix(states(consumer(name).solve(artifact))[-1], y_density(0.2))


@pytest.mark.parametrize("name", CONSUMERS)
def test_p_rejects_registry_restore(name, monkeypatch):
    from dataclasses import replace

    module = consumer(name)
    req = request(h0=operator(Y, coefficient=0.2))
    expected = y_density(0.2)
    assert_matrix(states(run(name, req))[-1], expected)
    original = module.load_request

    def restore_with_calibration(data):
        restored = original(data)
        h0 = restored.problem.h0
        altered = replace(
            h0, terms=tuple(replace(term, coefficient=term.coefficient * 1.5) for term in h0.terms)
        )
        return replace(restored, problem=replace(restored.problem, h0=altered))

    with monkeypatch.context() as patch:
        patch.setattr(module, "load_request", restore_with_calibration)
        with pytest.raises(AssertionError, match="physical values"):
            assert_matrix(states(run(name, req))[-1], expected)
    assert_matrix(states(run(name, req))[-1], expected)
