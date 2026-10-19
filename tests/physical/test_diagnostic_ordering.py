# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查诊断分类、阶段顺序与路径转义。"""

from __future__ import annotations

from dataclasses import replace
from itertools import permutations

import pytest

from physical_result_factories import result_for, result_request
from qaiji.core.physical.arrays import FrozenJSON
from qaiji.core.physical.diagnostics import CheckBudget, CheckReport, Diagnostic, PContractError
from qaiji.core.physical.model import State
from qaiji.core.physical.results import check_result
from qaiji.core.physical.validation import require_valid


def diagnostic(category="INVALID_REQUEST", code="SHAPE", path="", details=None):
    return Diagnostic(
        category=category,
        code=code,
        path=path,
        message="Validation failed.",
        details=FrozenJSON(value={} if details is None else details),
    )


def consumer_failure(error):
    """把消费者异常映射为求解器失败。"""
    raise PContractError(
        diagnostics=(
            diagnostic(
                "SOLVER_FAILURE", "BACKEND_FAILURE", "/backend", {"backend": "test-consumer"}
            ),
        )
    ) from error


def test_p_diagnostic_ordering():
    items = (
        diagnostic("INVALID_RESULT", "TIME", "/a"),
        diagnostic(code="NORMALIZATION", path="/a"),
        diagnostic(
            "RESOURCE_LIMIT",
            "RATIONAL_OPS",
            "/a",
            {"resource": "RATIONAL_OPS", "required": 2, "limit": 1},
        ),
        diagnostic("UNSUPPORTED_CAPABILITY", "PROFILE", "/a", {"missing": ["frame"]}),
        diagnostic(code="SITE", path="/z"),
        diagnostic(code="JSON_TYPE", path="/z"),
    )
    expected = tuple(reversed(items))
    for order in permutations(items):
        error = PContractError(diagnostics=order)
        assert error.diagnostics == expected
    indices = (
        diagnostic(path="/items/10"),
        diagnostic(path="/items/2"),
        diagnostic(path="/items"),
        diagnostic(path="/items/key"),
    )
    assert [d.path for d in PContractError(diagnostics=indices).diagnostics] == [
        "/items",
        "/items/key",
        "/items/2",
        "/items/10",
    ]


@pytest.mark.parametrize(
    "variant",
    [
        "empty-success-invalid-request",
        "empty-success-unsupported",
        "empty-success-resource",
        "empty-success-solver",
        "empty-success-invalid-result",
        "lexical-index-sort",
        "unescaped-json-pointer",
    ],
)
def test_p_rejects_failure_classification(variant):
    req = result_request()
    good = result_for(req)
    assert check_result(req, good, level="physical").complete
    if variant == "empty-success-solver":
        cause = RuntimeError("Backend stopped.")
        with pytest.raises(PContractError) as caught:
            consumer_failure(cause)
        assert caught.value.__cause__ is cause
        item = caught.value.diagnostics[0]
        assert (item.category, item.code, item.path) == (
            "SOLVER_FAILURE",
            "BACKEND_FAILURE",
            "/backend",
        )
        assert item.details == FrozenJSON(value={"backend": "test-consumer"})
        return
    if variant == "lexical-index-sort":
        items = (diagnostic(path="/a/10"), diagnostic(path="/a/2"))
        assert [d.path for d in PContractError(diagnostics=items).diagnostics] == ["/a/2", "/a/10"]
        return
    if variant == "unescaped-json-pointer":
        with pytest.raises(PContractError) as caught:
            FrozenJSON(value={"a/b~0c": {"bad": 1.5}})
        assert caught.value.diagnostics[0].path == "/a~1b~00c/bad"
        assert caught.value.diagnostics[0].code == "JSON_TYPE"
        return
    kwargs = {}
    if variant == "empty-success-invalid-request":
        req = replace(req)
        object.__setattr__(req, "schema", "qaiji.p.request/unknown")
        expected = ("INVALID_REQUEST", "VERSION")
    elif variant == "empty-success-unsupported":
        req = replace(
            req,
            problem=replace(
                req.problem,
                frame="rotating",
                initial_state=State(
                    kind="ket", frame="rotating", data=req.problem.initial_state.data
                ),
            ),
        )
        expected = ("UNSUPPORTED_CAPABILITY", "PROFILE")
    elif variant == "empty-success-resource":
        kwargs["budget"] = CheckBudget(max_dense_dimension=1)
        expected = ("RESOURCE_LIMIT", "DENSE_DIMENSION")
    else:
        good = replace(good, request_id="wrong")
        expected = ("INVALID_RESULT", "REQUEST_ID")
    report = check_result(req, good, level="physical", **kwargs)
    assert not report.complete
    item = report.diagnostics[0]
    assert (item.category, item.code) == expected
    assert type(item.path) is str
    if variant != "empty-success-invalid-request":
        assert item.details != FrozenJSON(value={})
    with pytest.raises(PContractError) as caught:
        require_valid(report)
    assert caught.value.diagnostics == report.diagnostics


def test_unicode_digits_are_object_keys():
    items = (diagnostic(path="/items/²"), diagnostic(path="/items/2"))
    assert [d.path for d in PContractError(diagnostics=items).diagnostics] == [
        "/items/²",
        "/items/2",
    ]


def test_explicit_stage_distinguishes_same_code():
    items = (
        diagnostic(code="SHAPE", path="/a", details={"stage": "structure"}),
        diagnostic(code="SHAPE", path="/z", details={"stage": "transport"}),
    )
    assert PContractError(diagnostics=items).diagnostics == tuple(reversed(items))


def test_backend_level_does_not_certify_result():
    req = result_request()
    good = result_for(req)
    bad = replace(
        good, request_id="wrong", report=replace(good.report, validation_level="physical")
    )
    report = check_result(req, bad, level="physical")
    assert not report.complete
    assert any(d.code == "REQUEST_ID" for d in report.diagnostics)


def test_incomplete_report_cannot_pass_require_valid():
    report = CheckReport(
        level="physical", complete=False, diagnostics=(), checked=(), unchecked=("physical",)
    )
    with pytest.raises(PContractError):
        require_valid(report)


def test_state_representation_ids_are_object_keys():
    items = tuple(
        diagnostic(
            category="INVALID_RESULT",
            code="REPRESENTATION",
            path="/report/state_representations/" + key,
        )
        for key in ("2", "10")
    )
    assert [item.path for item in PContractError(diagnostics=items).diagnostics] == [
        "/report/state_representations/10",
        "/report/state_representations/2",
    ]


@pytest.mark.parametrize(
    "kinds,expected",
    [
        (["key", "key"], ["/opaque/10", "/opaque/2"]),
        (["key", "index"], ["/opaque/2", "/opaque/10"]),
    ],
)
def test_opaque_pointer_sorting_uses_declared_container_types(kinds, expected):
    # 相同路径文本需要容器类型才能区分对象键和数组下标。
    items = tuple(
        diagnostic(path="/opaque/" + token, details={"path_kinds": kinds}) for token in ("2", "10")
    )
    assert [item.path for item in PContractError(diagnostics=items).diagnostics] == expected


@pytest.mark.parametrize("hint", [None, [], ["key"], ["key", "other"], ["index", "index"]])
def test_invalid_pointer_context_preserves_default_index_sorting(hint):
    items = tuple(
        diagnostic(path="/opaque/" + token, details={"path_kinds": hint}) for token in ("10", "2")
    )
    assert [item.path for item in PContractError(diagnostics=items).diagnostics] == [
        "/opaque/2",
        "/opaque/10",
    ]


def test_pointer_context_cannot_retype_known_representation_keys():
    items = tuple(
        diagnostic(
            path="/report/state_representations/" + token,
            details={"path_kinds": ["key", "key", "index"]},
        )
        for token in ("2", "10")
    )
    assert [item.path for item in PContractError(diagnostics=items).diagnostics] == [
        "/report/state_representations/10",
        "/report/state_representations/2",
    ]


@pytest.mark.parametrize(
    "parent",
    [
        "/observations",
        "/report/policy_differences",
        "/report/transforms",
        "/report/diagnostics",
        "/sites",
        "/sites/0/basis",
        "/problem/tensor_order",
        "/problem/drives",
        "/problem/environment/jumps",
        "/problem/initial_state/factors",
        "/problem/approximations",
        "/problem/extensions",
        "/policy/method/allowed",
        "/provenance/basis_mapping",
        "/provenance/prior_transforms",
        "/profiles",
        "/required_extensions",
        "/required_extensions/0",
        "/output_kinds",
        "/methods",
        "/problem/h0/terms",
        "/problem/h0/terms/0/factors",
        "/problem/h0/terms/0/coefficient",
        "/observations/0/keep_sites",
        "/observations/0/input_sites",
        "/observations/0/data/shape",
        "/shape",
        "/$p_array/shape",
        "/problem/extensions/0/payload/$p_array/shape",
    ],
)
def test_known_schema_arrays_ignore_object_key_hints(parent):
    items = tuple(
        diagnostic(
            path=parent + "/" + key, details={"path_kinds": ["key"] * (parent.count("/") + 1)}
        )
        for key in ("10", "2")
    )
    assert [item.path for item in PContractError(diagnostics=items).diagnostics] == [
        parent + "/2",
        parent + "/10",
    ]


@pytest.mark.parametrize(
    "parent",
    [
        "",
        "/problem",
        "/sites/0",
        "/problem/drives/0",
        "/problem/drives/0/signal",
        "/problem/environment",
        "/problem/environment/jumps/0",
        "/problem/initial_state",
        "/problem/initial_state/factors/0",
        "/problem/h0",
        "/problem/h0/terms/0",
        "/problem/h0/terms/0/factors/0",
        "/observations/0",
        "/policy",
        "/policy/method",
        "/provenance",
        "/provenance/device_snapshot",
        "/provenance/basis_mapping/0",
        "/problem/extensions/0",
        "/report",
        "/report/policy_differences/0",
        "/report/transforms/0",
        "/report/transforms/0/authorization",
        "/report/diagnostics/0",
        "/report/state_representations",
        "/report/actual_policy",
        "/precision",
        "/profiles/0",
        "/observations/0/data",
    ],
)
def test_known_schema_objects_ignore_numeric_index_hints(parent):
    items = []
    for key in ("2", "10"):
        path = parent + "/" + key
        kinds = [
            "index" if token.isascii() and token.isdecimal() else "key"
            for token in path[1:].split("/")
        ]
        items.append(diagnostic(path=path, details={"path_kinds": kinds}))
    assert [item.path for item in PContractError(diagnostics=items).diagnostics] == [
        parent + "/10",
        parent + "/2",
    ]


@pytest.mark.parametrize(
    "parent",
    [
        "/opaque/observations",
        "/problem/extensions/0/payload/observations",
        "/provenance/prior_transforms/0/observations",
        "/report/policy_differences/0/requested/observations",
        "/report/policy_differences/0/actual/observations",
        "/report/diagnostics/0/details/observations",
        "/profiles/0/state_representations",
    ],
)
def test_opaque_paths_do_not_inherit_schema_field_names(parent):
    items = tuple(
        diagnostic(
            path=parent + "/" + key, details={"path_kinds": ["key"] * (parent.count("/") + 1)}
        )
        for key in ("2", "10")
    )
    assert [item.path for item in PContractError(diagnostics=items).diagnostics] == [
        parent + "/10",
        parent + "/2",
    ]


@pytest.mark.parametrize("kind", ["key", "index"])
def test_long_numeric_pointer_tokens_do_not_require_integer_conversion(kind):
    long_key = "1" * 5000
    items = (
        diagnostic(path="/opaque/" + long_key, details={"path_kinds": ["key", kind]}),
        diagnostic(path="/opaque/2", details={"path_kinds": ["key", kind]}),
    )
    expected = (
        ["/opaque/" + long_key, "/opaque/2"]
        if kind == "key"
        else [
            "/opaque/2",
            "/opaque/" + long_key,
        ]
    )
    assert [item.path for item in PContractError(diagnostics=items).diagnostics] == expected


def test_long_numeric_pointer_tokens_use_length_then_digits():
    smaller, larger = "1" * 5000, "2" * 5000
    items = tuple(diagnostic(path="/opaque/" + token) for token in (larger, smaller, "9" * 4999))
    assert [item.path for item in PContractError(diagnostics=items).diagnostics] == [
        "/opaque/" + "9" * 4999,
        "/opaque/" + smaller,
        "/opaque/" + larger,
    ]
