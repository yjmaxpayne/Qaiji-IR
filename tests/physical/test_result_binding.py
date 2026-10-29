# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查结果身份、输出边界与返回值。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from physical_result_factories import carray, farray, result_for, result_request
from qaiji.core.physical.arrays import FrozenJSON
from qaiji.core.physical.model import Observation, ObservationValue
from qaiji.core.physical.results import check_result


@pytest.mark.parametrize("level", ["transport", "structure", "physical"])
def test_p_result_binding(level):
    req = result_request()
    report = check_result(req, result_for(req), level=level)
    assert report.complete, report.diagnostics
    assert not report.diagnostics


@pytest.mark.parametrize(
    "variant",
    [
        "skip-request-id",
        "skip-time",
        "skip-shape",
        "skip-tensor-order",
        "skip-frame",
        "skip-policy-report",
        "skip-observation-set",
    ],
)
def test_p_rejects_result_guard_omission(variant):
    req = result_request()
    if variant == "skip-observation-set":
        req = replace(
            req,
            observations=(
                Observation(id="first", kind="full_state", representation="ket"),
                Observation(id="second", kind="full_state", representation="ket"),
            ),
        )
        count = req.output_times.shape[0]
        values = tuple(
            ObservationValue(
                id=item.id,
                kind="full_state",
                representation="ket",
                data=carray([1, 0] * count, (count, 2)),
            )
            for item in req.observations
        )
        good = result_for(req, values)
    else:
        good = result_for(req)
    assert check_result(req, good, level="structure").complete
    bad = good
    code, path = {
        "skip-request-id": ("REQUEST_ID", "/request_id"),
        "skip-time": ("TIME", "/output_times"),
        "skip-shape": ("SHAPE", "/observations/0/data"),
        "skip-tensor-order": ("TENSOR_ORDER", "/tensor_order"),
        "skip-frame": ("KEYS", "/frame"),
        "skip-policy-report": ("POLICY_REPORT", "/report/policy_differences"),
        "skip-observation-set": ("OBSERVATION_SET", "/observations"),
    }[variant]
    if variant == "skip-request-id":
        bad = replace(good, request_id="sha256:" + "0" * 64)
    elif variant == "skip-time":
        times = [0.0] * good.output_times.shape[0]
        times[-1] = 0.5
        bad = replace(good, output_times=farray(times))
    elif variant == "skip-shape":
        obs = ObservationValue(
            id="state", kind="full_state", representation="ket", data=carray([1], (1, 1))
        )
        bad = replace(good, observations=(obs,))
    elif variant == "skip-tensor-order":
        bad = replace(good, tensor_order=("other",))
    elif variant == "skip-frame":
        bad = replace(good, frame="rotating")
    elif variant == "skip-policy-report":
        from qaiji.core.physical.model import PolicyDifference

        diff = PolicyDifference(
            path="/atol",
            requested=FrozenJSON(value="x"),
            actual=FrozenJSON(value="y"),
            basis="delegated",
        )
        bad = replace(good, report=replace(good.report, policy_differences=(diff,)))
    else:
        bad = replace(good, observations=tuple(reversed(good.observations)))
    report = check_result(req, bad, level="structure")
    assert not report.complete
    assert any(
        (d.category, d.code, d.path) == ("INVALID_RESULT", code, path) for d in report.diagnostics
    ), report.diagnostics


def test_expectation_only_needs_no_full_state():
    req = result_request(
        (Observation(id="mean", kind="expectation", operator=result_request().problem.h0),)
    )
    req = replace(
        req,
        observations=(
            Observation(id="mean", kind="expectation", operator=replace(req.problem.h0, unit="1")),
        ),
    )
    count = req.output_times.shape[0]
    obs = ObservationValue(id="mean", kind="expectation", data=carray([0] * count, (count,)))
    report = check_result(req, result_for(req, (obs,)), level="physical")
    assert report.complete, report.diagnostics


@pytest.mark.parametrize("kind", ["ket", "density", "partial_trace", "projection"])
def test_returned_state_physical_conditions(kind):
    from qaiji.core.physical.model import State

    req = result_request()
    count = req.output_times.shape[0]
    site = req.problem.tensor_order[0]
    if kind == "ket":
        good = result_for(req)
        bad_value = ObservationValue(
            id="state",
            kind="full_state",
            representation="ket",
            data=carray([0, 0] * count, (count, 2)),
        )
    elif kind == "density":
        req = replace(
            req,
            observations=(Observation(id="state", kind="full_state", representation="density"),),
            policy=replace(req.policy, representation="density"),
            problem=replace(
                req.problem,
                initial_state=State(kind="density", frame="lab", data=carray([1, 0, 0, 0], (2, 2))),
            ),
        )
        good_value = ObservationValue(
            id="state",
            kind="full_state",
            representation="density",
            data=carray([1, 0, 0, 0] * count, (count, 2, 2)),
        )
        good = result_for(req, (good_value,))
        bad_value = ObservationValue(
            id="state",
            kind="full_state",
            representation="density",
            data=carray([1.2, 0, 0, -0.2] * count, (count, 2, 2)),
        )
    elif kind == "partial_trace":
        req = replace(
            req, observations=(Observation(id="reduced", kind="partial_trace", keep_sites=(site,)),)
        )
        good_value = ObservationValue(
            id="reduced",
            kind="partial_trace",
            keep_sites=(site,),
            data=carray([1, 0, 0, 0] * count, (count, 2, 2)),
        )
        good = result_for(req, (good_value,))
        bad_value = ObservationValue(
            id="reduced",
            kind="partial_trace",
            keep_sites=(site,),
            data=carray([1.2, 0, 0, -0.2] * count, (count, 2, 2)),
        )
    else:
        req, good = projection_case()
        count = req.output_times.shape[0]
        old = good.observations[0]
        bad_value = ObservationValue(
            id=old.id,
            kind="projection",
            input_sites=old.input_sites,
            block=carray([-0.2] * count, (count, 1, 1)),
            leakage=farray([1.2] * count),
            input_trace=old.input_trace,
            trace_error=old.trace_error,
        )
    assert check_result(req, good, level="physical").complete
    report = check_result(req, replace(good, observations=(bad_value,)), level="physical")
    assert not report.complete
    assert any(
        d.category == "INVALID_RESULT" and d.code in {"NORMALIZATION", "PSD"}
        for d in report.diagnostics
    ), report.diagnostics


def projection_case():
    req = result_request()
    site = req.problem.tensor_order[0]
    req = replace(
        req,
        observations=(
            Observation(
                id="code", kind="projection", input_sites=(site,), isometry=carray([1, 0], (2, 1))
            ),
        ),
    )
    count = req.output_times.shape[0]
    value = ObservationValue(
        id="code",
        kind="projection",
        input_sites=(site,),
        block=carray([0.75] * count, (count, 1, 1)),
        leakage=farray([0.25] * count),
        input_trace=farray([1 - 2**-35] * count),
        trace_error=farray([-(2**-35)] * count),
    )
    return req, result_for(req, (value,))


@pytest.mark.parametrize("field", ["leakage", "trace_error"])
def test_projection_scalar_relations_are_exact(field):
    req, good = projection_case()
    assert check_result(req, good, level="physical").complete
    old = good.observations[0]
    count = req.output_times.shape[0]
    values = dict(
        id=old.id,
        kind="projection",
        input_sites=old.input_sites,
        block=old.block,
        leakage=old.leakage,
        input_trace=old.input_trace,
        trace_error=old.trace_error,
    )
    values[field] = farray([(0.25 if field == "leakage" else -(2**-35)) + 2**-35] * count)
    bad = replace(good, observations=(ObservationValue(**values),))
    report = check_result(req, bad, level="physical")
    assert any(
        d.category == "INVALID_RESULT" and d.path == "/observations/0/" + field
        for d in report.diagnostics
    ), report.diagnostics


def test_invalid_shape_skips_dependent_physics():
    req = result_request()
    good = result_for(req)
    assert check_result(req, good, level="physical").complete
    value = ObservationValue(
        id="state", kind="full_state", representation="ket", data=carray([0], (1, 1))
    )
    report = check_result(req, replace(good, observations=(value,)), level="physical")
    assert any(d.code == "SHAPE" for d in report.diagnostics)
    assert not any(d.code == "NORMALIZATION" for d in report.diagnostics)
    assert "/observations/0/physical" in report.unchecked


def test_invalid_request_structure_keeps_original_classification():
    req = result_request()
    good = result_for(req)
    assert check_result(req, good, level="structure").complete
    bad = replace(req, output_times=farray([-1.0]))
    report = check_result(bad, good, level="structure")
    assert any(
        (d.category, d.code, d.path) == ("INVALID_REQUEST", "OUTPUT_TIME", "/output_times")
        for d in report.diagnostics
    )
    assert "result" in report.unchecked


def test_transport_result_failure_uses_invalid_result():
    req = result_request()
    good = result_for(req)
    assert check_result(req, good, level="transport").complete
    bad = replace(good)
    object.__setattr__(bad, "schema", "qaiji.p.result/unknown")
    report = check_result(req, bad, level="transport")
    assert not report.complete
    assert any(d.category == "INVALID_RESULT" and d.code == "VERSION" for d in report.diagnostics)


def test_unknown_check_level_raises():
    from qaiji.core.physical.diagnostics import PContractError

    req = result_request()
    with pytest.raises(PContractError):
        check_result(req, result_for(req), level="unknown")


def test_result_identity_respects_explicit_wire_budget(monkeypatch):
    from qaiji.core.physical import identity
    from qaiji.core.physical.diagnostics import CheckBudget, PContractError
    from qaiji.core.physical.validation import check_request

    req = result_request()
    result = result_for(req)
    original_id = identity.request_id(req)
    large = replace(
        req,
        provenance=replace(
            req.provenance, prior_transforms=(FrozenJSON(value={"note": "x" * (16 * 1024 * 1024)}),)
        ),
    )
    for public_identity in (identity.request_id, identity.canonical_request_bytes):
        with pytest.raises(PContractError) as caught:
            public_identity(large)
        assert any(
            (d.category, d.code) == ("RESOURCE_LIMIT", "BYTES") for d in caught.value.diagnostics
        )
    budget = CheckBudget(max_wire_bytes=32 * 1024 * 1024)
    assert check_request(large, level="structure", budget=budget).complete
    calls = []
    encode = identity.dump_request

    def record_encode(request, **kwargs):
        calls.append(kwargs.get("budget"))
        return encode(request, **kwargs)

    monkeypatch.setattr(identity, "dump_request", record_encode)
    report = check_result(large, result, level="structure", budget=budget)
    assert report.complete, report.diagnostics
    assert not report.diagnostics
    assert calls == [budget]
    assert result.request_id == original_id
    assert identity.request_id(req) == original_id
    smaller = CheckBudget(max_wire_bytes=1024)
    rejected = check_result(large, result, level="structure", budget=smaller)
    assert not rejected.complete
    assert any((d.category, d.code) == ("RESOURCE_LIMIT", "BYTES") for d in rejected.diagnostics)
    assert "result" in rejected.unchecked


def test_public_identity_and_requirements_take_the_caller_budget():
    # 消费方为大请求放宽检查预算时，必须能用同一预算计算身份与提取需求；
    # 否则请求侧仍被默认 16 MiB 卡住（I-T4b-03）。预算只限资源，不改变身份与需求。
    from qaiji.core.physical import identity
    from qaiji.core.physical.capabilities import extract_requirements
    from qaiji.core.physical.diagnostics import CheckBudget, PContractError

    req = result_request()
    large = replace(
        req,
        provenance=replace(
            req.provenance, prior_transforms=(FrozenJSON(value={"note": "x" * (16 * 1024 * 1024)}),)
        ),
    )
    budget = CheckBudget(max_wire_bytes=32 * 1024 * 1024)
    assert identity.request_id(large, budget=budget) == identity.request_id(req)
    assert extract_requirements(large, budget=budget) == extract_requirements(req)
    # 默认预算拒收大请求。调用方预算的字节与深度两个维度都生效，
    # 所以只转发 max_wire_bytes 的实现会失败。
    rejections = [
        (f, large, CheckBudget(), "BYTES") for f in (identity.request_id, extract_requirements)
    ]
    for smaller, code in (
        (CheckBudget(max_wire_bytes=1024), "BYTES"),
        (CheckBudget(max_depth=1), "DEPTH"),
    ):
        rejections += [(f, req, smaller, code) for f in (identity.request_id, extract_requirements)]
    for function, request, limit, code in rejections:
        with pytest.raises(PContractError) as caught:
            function(request, budget=limit)
        assert ("RESOURCE_LIMIT", code) in {(d.category, d.code) for d in caught.value.diagnostics}


def test_identity_encoding_failure_returns_report(monkeypatch):
    from qaiji.core.physical import identity
    from qaiji.core.physical.diagnostics import Diagnostic, PContractError

    req = result_request()
    result = result_for(req)
    assert check_result(req, result, level="structure").complete
    item = Diagnostic(
        category="RESOURCE_LIMIT",
        code="BYTES",
        path="",
        message="Identity encoding exceeds its wire budget.",
        details=FrozenJSON(value={"resource": "BYTES", "required": 2, "limit": 1}),
    )

    def reject_encoding(request, **kwargs):
        raise PContractError(diagnostics=(item,))

    monkeypatch.setattr(identity, "dump_request", reject_encoding)
    report = check_result(req, result, level="structure")
    assert not report.complete
    assert report.diagnostics == (item,)
    assert "result/identity" in report.unchecked
    assert "result/binding" in report.unchecked
