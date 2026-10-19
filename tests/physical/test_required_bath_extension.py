# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查必需 bath 扩展的保真与拒绝阶段。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from qaiji.core.physical import CheckBudget, FrozenJSON, PContractError
from qaiji.core.physical.codec import dump_request, load_request
from qaiji.core.physical.validation import check_request, require_valid


def bath_request():
    return load_request((Path(__file__).parent / "data/bath-fixture.json").read_bytes())


def test_p_required_bath():
    req = bath_request()
    assert load_request(dump_request(req).document) == req
    transport = check_request(req, level="transport")
    structure = check_request(req, level="structure")
    assert transport.complete
    assert structure.complete
    assert structure.unchecked
    report = check_request(req, level="physical", budget=CheckBudget(max_dense_dimension=0))
    assert not report.complete
    assert {d.code for d in report.diagnostics} == {"REQUIRED_EXTENSION"}
    diagnostic = report.diagnostics[0]
    assert diagnostic.category == "UNSUPPORTED_CAPABILITY"
    assert "org.qaiji.fixtures.bath-correlation" in repr(diagnostic.details)
    assert "1.0" in repr(diagnostic.details)
    assert "missing" in repr(diagnostic.details)


@pytest.mark.parametrize(
    "variant",
    [
        "drop-required-extension",
        "certify-unknown-bath",
        "execute-unknown-bath",
        "infer-array-from-ordinary-object",
    ],
)
def test_p_rejects_bath_drop_or_certify(variant):
    req = bath_request()
    assert len(req.problem.extensions) == 1
    if variant == "drop-required-extension":
        document = json.loads(dump_request(req).document)
        assert len(document["problem"]["extensions"]) == 1
        assert load_request(dump_request(req).document).problem.extensions == req.problem.extensions
    elif variant == "infer-array-from-ordinary-object":
        ordinary = {"dtype": "f64le", "shape": [123], "data": "not-an-array"}
        extension = replace(req.problem.extensions[0], payload=FrozenJSON(value=ordinary))
        req = replace(req, problem=replace(req.problem, extensions=[extension]))
        assert check_request(req, level="transport").complete
        assert (
            json.loads(dump_request(req).document)["problem"]["extensions"][0]["payload"]
            == ordinary
        )
    else:
        report = check_request(
            req, level="physical", budget=CheckBudget(max_dense_dimension=0, max_numeric_elements=0)
        )
        assert not report.complete
        assert {d.code for d in report.diagnostics} == {"REQUIRED_EXTENSION"}
        if variant == "execute-unknown-bath":
            with pytest.raises(PContractError) as error:
                require_valid(report)
            assert error.value.diagnostics == report.diagnostics
