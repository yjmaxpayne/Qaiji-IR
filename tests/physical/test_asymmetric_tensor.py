# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查非对称张量顺序。"""

import pytest
from _p_fixtures import CONSUMERS, X, assert_matrix, asymmetric_request, consumer, operator


@pytest.mark.parametrize("name", CONSUMERS)
@pytest.mark.parametrize("site_order", ["ab", "ba"])
def test_p_asymmetric_tensor(name, site_order):
    req = asymmetric_request()
    assert [s.dim for s in req.problem.sites] == [2, 3]
    from dataclasses import replace

    if site_order == "ba":
        req = replace(req, problem=replace(req.problem, sites=tuple(reversed(req.problem.sites))))
    actual = consumer(name).assemble(req.problem, operator(X))
    assert [actual[row][2] for row in range(6)] == [0, 0, 0, 0, 0, 1]
    expected = [[complex(row == (col + 3) % 6) for col in range(6)] for row in range(6)]
    assert_matrix(actual, expected)


@pytest.mark.parametrize("name", CONSUMERS)
def test_p_rejects_tensor_factor_swap(name, monkeypatch):
    from dataclasses import replace

    module = consumer(name)
    req = asymmetric_request()
    expected = [[complex(row == (col + 3) % 6) for col in range(6)] for row in range(6)]
    original = module.assemble
    assert_matrix(original(req.problem, operator(X)), expected)
    with monkeypatch.context() as patch:
        patch.setattr(
            module,
            "assemble",
            lambda p, op: original(
                replace(p, tensor_order=tuple(reversed(p.tensor_order))),
                op,
            ),
        )
        with pytest.raises(AssertionError, match="physical values"):
            assert_matrix(module.assemble(req.problem, operator(X)), expected)
    assert_matrix(module.assemble(req.problem, operator(X)), expected)
