# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查策略差异、表示解析与变换授权。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from physical_result_factories import bits, policy_values, result_for, result_request
from qaiji.core.physical.arrays import FrozenJSON
from qaiji.core.physical.model import MethodChoice, Observation, PolicyDifference, TransformRecord
from qaiji.core.physical.results import check_result


def difference(path, requested, actual, basis):
    return PolicyDifference(
        path=path,
        requested=FrozenJSON(value=requested),
        actual=FrozenJSON(value=actual),
        basis=basis,
    )


def delegated_request():
    req = result_request()
    method = MethodChoice(mode="delegate", value=None, allowed=("reference-exact", "rk4"))
    return replace(req, policy=replace(req.policy, method=method))


def delegated_difference(req, actual="reference-exact"):
    return difference(
        "/policy/method",
        {"mode": "delegate", "value": None, "allowed": list(req.policy.method.allowed)},
        actual,
        "delegated",
    )


@pytest.mark.parametrize("case", ["fixed", "delegated", "either", "sparse", "substep"])
def test_p_policy_permissions(case):
    req = result_request()
    kwargs = {}
    if case == "delegated":
        req = delegated_request()
        kwargs["differences"] = (delegated_difference(req),)
    elif case == "either":
        req = replace(req, policy=replace(req.policy, representation="either"))
        kwargs["actual"] = policy_values(req, representation="ket")
        kwargs["differences"] = (
            difference("/policy/representation", "either", "ket", "allowed_representation"),
        )
    elif case == "sparse":
        kwargs["transforms"] = (
            TransformRecord(
                name="sparse_storage",
                kind="exact_representation",
                authorization=FrozenJSON(value={"rule": "sparse_storage"}),
            ),
        )
    elif case == "substep":
        kwargs["transforms"] = (
            TransformRecord(
                name="integration_substep",
                kind="numerical_substep",
                authorization=FrozenJSON(value={"policy": "/policy"}),
            ),
        )
    report = check_result(req, result_for(req, **kwargs), level="physical")
    assert report.complete, report.diagnostics


@pytest.mark.parametrize(
    "variant",
    [
        "compress-idle",
        "truncate-readout",
        "quantize-edge",
        "change-zoh-by-resampling",
        "apply-rwa",
        "change-fixed-bound",
        "omit-difference",
        "invent-difference",
        "out-of-allowed-method",
        "illegal-either-resolution",
    ],
)
def test_p_rejects_report_as_permission(variant):
    req = result_request()
    kwargs = {}
    if variant in ("omit-difference", "out-of-allowed-method"):
        req = delegated_request()
        kwargs["differences"] = (delegated_difference(req),)
    elif variant == "illegal-either-resolution":
        req = replace(req, observations=(), policy=replace(req.policy, representation="either"))
        kwargs.update(
            observations=(),
            actual=policy_values(req, representation="ket"),
            differences=(
                difference("/policy/representation", "either", "ket", "allowed_representation"),
            ),
        )
    good = result_for(req, **kwargs)
    assert check_result(req, good, level="physical").complete
    report = good.report
    if variant in (
        "compress-idle",
        "truncate-readout",
        "quantize-edge",
        "change-zoh-by-resampling",
        "apply-rwa",
    ):
        transform = TransformRecord(
            name=variant.replace("-", "_"),
            kind="exact_representation",
            authorization=FrozenJSON(value={"reported": True}),
        )
        report = replace(report, transforms=(transform,))
        code, path = "TRANSFORM_FORBIDDEN", "/report/transforms/0"
    elif variant == "change-fixed-bound":
        actual = policy_values(req)
        actual["atol"] = bits(req.policy.atol * 2)
        report = replace(report, actual_policy=FrozenJSON(value=actual))
        code, path = "POLICY_FIXED", "/report/actual_policy/atol"
    elif variant == "omit-difference":
        report = replace(report, policy_differences=())
        code, path = "POLICY_REPORT", "/report/policy_differences"
    elif variant == "invent-difference":
        report = replace(
            report, policy_differences=(difference("/policy/atol", "x", "y", "delegated"),)
        )
        code, path = "POLICY_REPORT", "/report/policy_differences"
    elif variant == "out-of-allowed-method":
        actual = policy_values(req, method="forbidden")
        report = replace(
            report,
            actual_policy=FrozenJSON(value=actual),
            policy_differences=(delegated_difference(req, "forbidden"),),
        )
        code, path = "POLICY_BOUND", "/report/actual_policy/method"
    else:
        actual = policy_values(req, representation="either")
        report = replace(
            report,
            actual_policy=FrozenJSON(value=actual),
            policy_differences=(
                difference("/policy/representation", "either", "either", "allowed_representation"),
            ),
        )
        code, path = "POLICY_BOUND", "/report/actual_policy/representation"
    checked = check_result(req, replace(good, report=report), level="physical")
    assert not checked.complete
    assert any(
        (d.category, d.code, d.path) == ("INVALID_RESULT", code, path) for d in checked.diagnostics
    ), checked.diagnostics


@pytest.mark.parametrize(
    "name,kind,authorization",
    [
        ("sparse_storage", "exact_representation", {}),
        ("sparse_storage", "numerical_substep", {"rule": "sparse_storage"}),
        ("integration_substep", "numerical_substep", {"policy": "/provenance/prior_transforms"}),
        ("integration_substep", "exact_representation", {"policy": "/policy"}),
    ],
)
def test_known_transform_requires_its_authorization(name, kind, authorization):
    req = result_request()
    assert check_result(req, result_for(req), level="structure").complete
    transform = TransformRecord(name=name, kind=kind, authorization=FrozenJSON(value=authorization))
    report = check_result(req, result_for(req, transforms=(transform,)), level="structure")
    assert any(d.code == "TRANSFORM_FORBIDDEN" for d in report.diagnostics)


@pytest.mark.parametrize("field", ["atol", "rtol", "max_step_ns"])
def test_only_method_can_be_delegated(field):
    req = result_request()
    good = result_for(req)
    assert check_result(req, good, level="structure").complete
    actual = policy_values(req)
    actual[field] = {"mode": "delegate", "allowed": [bits(1e-7)]}
    report = check_result(
        req,
        replace(good, report=replace(good.report, actual_policy=FrozenJSON(value=actual))),
        level="structure",
    )
    assert any(
        d.code == "POLICY_FIXED" and d.path.endswith("/" + field) for d in report.diagnostics
    )


def test_either_resolution_must_satisfy_every_full_state():
    req = result_request((Observation(id="state", kind="full_state", representation="ket"),))
    req = replace(req, policy=replace(req.policy, representation="either"))
    good = result_for(
        req,
        actual=policy_values(req, representation="ket"),
        differences=(
            difference("/policy/representation", "either", "ket", "allowed_representation"),
        ),
    )
    assert check_result(req, good, level="physical").complete
    actual = policy_values(req, representation="density")
    bad = replace(
        good,
        report=replace(
            good.report,
            actual_policy=FrozenJSON(value=actual),
            policy_differences=(
                difference("/policy/representation", "either", "density", "allowed_representation"),
            ),
        ),
    )
    report = check_result(req, bad, level="physical")
    assert any(d.code == "POLICY_BOUND" for d in report.diagnostics)


@pytest.mark.parametrize("condition", ["density_initial", "markovian"])
def test_either_resolution_obeys_physical_representation_limits(condition):
    from physical_result_factories import carray
    from qaiji.core.physical.model import ObservationValue, State

    req = result_request((Observation(id="state", kind="full_state", representation="either"),))
    req = replace(req, policy=replace(req.policy, representation="either"))
    if condition == "density_initial":
        req = replace(
            req,
            problem=replace(
                req.problem,
                initial_state=State(kind="density", frame="lab", data=carray([1, 0, 0, 0], (2, 2))),
            ),
        )
    else:
        from qaiji.core.physical.model import Environment

        req = replace(
            req, problem=replace(req.problem, environment=Environment(kind="markovian", jumps=()))
        )
    count = req.output_times.shape[0]
    density = ObservationValue(
        id="state",
        kind="full_state",
        representation="density",
        data=carray([1, 0, 0, 0] * count, (count, 2, 2)),
    )
    good = result_for(
        req,
        (density,),
        actual=policy_values(req, representation="density"),
        differences=(
            difference("/policy/representation", "either", "density", "allowed_representation"),
        ),
    )
    assert check_result(req, good, level="physical").complete
    ket = ObservationValue(
        id="state", kind="full_state", representation="ket", data=carray([1, 0] * count, (count, 2))
    )
    bad = result_for(
        req,
        (ket,),
        actual=policy_values(req, representation="ket"),
        differences=(
            difference("/policy/representation", "either", "ket", "allowed_representation"),
        ),
    )
    report = check_result(req, bad, level="physical")
    assert not report.complete
    assert any(
        d.category == "INVALID_RESULT"
        and d.code == "POLICY_BOUND"
        and d.path == "/report/actual_policy/representation"
        for d in report.diagnostics
    )
