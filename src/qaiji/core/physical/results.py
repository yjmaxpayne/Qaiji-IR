# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查结果绑定、策略许可与返回值数值条件。"""

from __future__ import annotations

import math
import struct
from dataclasses import replace
from typing import Any

from . import codec
from ._numeric import _hermitian, _NumericContext, _psd, _state, _values
from .arrays import ArrayData, _JSONArray, _JSONObject
from .diagnostics import CheckBudget, CheckReport, Diagnostic, PContractError, _Level
from .identity import _request_id
from .model import Observation, ObservationValue, Request, Result
from .validation import _check, _diagnostic

_DEFAULT_BUDGET = CheckBudget()


def _plain(value: Any) -> Any:
    if type(value) is _JSONObject:
        return {key: _plain(child) for key, child in value.items}
    if type(value) is _JSONArray:
        return [_plain(child) for child in value.items]
    return value


def _bits(value: float | None) -> str | None:
    return None if value is None else struct.pack(">d", value).hex()


def _result_diagnostic(code: str, path: str, **details: Any) -> Diagnostic:
    return _diagnostic(
        code,
        path,
        "The result does not satisfy the request.",
        category="INVALID_RESULT",
        stage="result",
        **details,
    )


class _Binding:
    def __init__(self, request: Request, result: Result):
        self.request = request
        self.result = result
        self.diagnostics: list[Diagnostic] = []
        self.unchecked: list[str] = []
        self.dimension = math.prod(site.dim for site in request.problem.sites)
        self.count = request.output_times.shape[0]
        self.valid_observations: list[tuple[ObservationValue, str]] = []

    def expect(self, condition: bool, code: str, path: str, **details: Any) -> bool:
        if not condition:
            self.diagnostics.append(_result_diagnostic(code, path, **details))
        return condition

    def identity(self, expected_request_id: str) -> None:
        req, result = self.request, self.result
        self.expect(
            result.request_id == expected_request_id,
            "REQUEST_ID",
            "/request_id",
            requested=expected_request_id,
            actual=result.request_id,
        )
        self.expect(
            result.output_times == req.output_times,
            "TIME",
            "/output_times",
            requested=req.output_times.data.hex(),
            actual=result.output_times.data.hex(),
        )
        self.expect(
            result.tensor_order == req.problem.tensor_order,
            "TENSOR_ORDER",
            "/tensor_order",
            requested=list(req.problem.tensor_order),
            actual=list(result.tensor_order),
        )
        self.expect(
            result.frame == req.problem.frame,
            "KEYS",
            "/frame",
            requested=req.problem.frame,
            actual=result.frame,
        )

    def observations(self) -> None:
        req, result = self.request, self.result
        expected = [(item.id, item.kind) for item in req.observations]
        actual = [(item.id, item.kind) for item in result.observations]
        if not self.expect(
            actual == expected,
            "OBSERVATION_SET",
            "/observations",
            requested=[list(x) for x in expected],
            actual=[list(x) for x in actual],
        ):
            self.unchecked.append("/observations/binding-dependent-checks")
            return
        for index, (observation, value) in enumerate(
            zip(req.observations, result.observations, strict=True)
        ):
            path = f"/observations/{index}"
            before = len(self.diagnostics)
            self.observation(observation, value, path)
            if len(self.diagnostics) == before:
                self.valid_observations.append((value, path))
            else:
                self.unchecked.append(path + "/physical")
        representations = {
            value.id: value.representation if value.kind == "full_state" else "density"
            for value in result.observations
            if value.kind != "expectation"
        }
        self.expect(
            _plain(result.report.state_representations.value) == representations,
            "REPRESENTATION",
            "/report/state_representations",
            requested=representations,
            actual=_plain(result.report.state_representations.value),
        )

    def shape(self, array: ArrayData, shape: tuple[int, ...], path: str) -> None:
        self.expect(
            array.shape == shape, "SHAPE", path, requested=list(shape), actual=list(array.shape)
        )

    def observation(self, observation: Observation, value: ObservationValue, path: str) -> None:
        if value.kind == "full_state":
            allowed = (
                ("ket", "density")
                if observation.representation == "either"
                else (observation.representation,)
            )
            self.expect(
                value.representation in allowed,
                "REPRESENTATION",
                path + "/representation",
                requested=list(allowed),
                actual=value.representation,
            )
            assert value.data is not None
            shape = (
                (self.count, self.dimension)
                if value.representation == "ket"
                else (
                    self.count,
                    self.dimension,
                    self.dimension,
                )
            )
            self.shape(value.data, shape, path + "/data")
        elif value.kind == "expectation":
            assert value.data is not None
            self.shape(value.data, (self.count,), path + "/data")
        elif value.kind == "partial_trace":
            self.expect(
                value.keep_sites == observation.keep_sites,
                "TENSOR_ORDER",
                path + "/keep_sites",
                requested=list(observation.keep_sites or ()),
                actual=list(value.keep_sites or ()),
            )
            dims = {site.id: site.dim for site in self.request.problem.sites}
            size = math.prod(dims[site] for site in observation.keep_sites or ())
            assert value.data is not None
            self.shape(value.data, (self.count, size, size), path + "/data")
        else:
            self.expect(
                value.input_sites == observation.input_sites,
                "TENSOR_ORDER",
                path + "/input_sites",
                requested=list(observation.input_sites or ()),
                actual=list(value.input_sites or ()),
            )
            assert observation.isometry is not None and value.block is not None
            size = observation.isometry.shape[1]
            self.shape(value.block, (self.count, size, size), path + "/block")
            for name in ("leakage", "input_trace", "trace_error"):
                array = getattr(value, name)
                assert array is not None
                self.shape(array, (self.count,), path + "/" + name)

    def policy(self) -> None:
        policy = self.request.policy
        actual = _plain(self.result.report.actual_policy.value)
        keys = {"method", "atol", "rtol", "max_step_ns", "representation"}
        if not self.expect(
            type(actual) is dict and set(actual) == keys,
            "POLICY_REPORT",
            "/report/actual_policy",
            required=sorted(keys),
        ):
            self.unchecked.append("/report/actual_policy/dependent-checks")
            return
        differences: list[dict[str, Any]] = []
        method = policy.method
        if method.mode == "fixed":
            self.expect(
                actual["method"] == method.value,
                "POLICY_FIXED",
                "/report/actual_policy/method",
                requested=method.value,
                actual=actual["method"],
            )
        else:
            self.expect(
                type(actual["method"]) is str and actual["method"] in method.allowed,
                "POLICY_BOUND",
                "/report/actual_policy/method",
                allowed=list(method.allowed),
                actual=actual["method"],
            )
            differences.append(
                {
                    "path": "/policy/method",
                    "requested": {
                        "mode": method.mode,
                        "value": method.value,
                        "allowed": list(method.allowed),
                    },
                    "actual": actual["method"],
                    "basis": "delegated",
                }
            )
        for name in ("atol", "rtol", "max_step_ns"):
            requested = _bits(getattr(policy, name))
            self.expect(
                actual[name] == requested,
                "POLICY_FIXED",
                "/report/actual_policy/" + name,
                requested=requested,
                actual=actual[name],
            )
        representation = actual["representation"]
        if policy.representation == "either":
            valid = representation in ("ket", "density")
            valid = valid and all(
                item.representation in ("either", representation)
                for item in self.request.observations
                if item.kind == "full_state"
            )
            from .capabilities import _initial_kind, _representation_missing

            actual_representations = {
                item.id: [representation]
                for item in self.request.observations
                if item.kind == "full_state"
            }
            valid = valid and not _representation_missing(
                self.request.problem.environment.kind,
                _initial_kind(self.request.problem),
                actual_representations,
                {"ket", "density"},
            )
            self.expect(
                valid,
                "POLICY_BOUND",
                "/report/actual_policy/representation",
                requested="either",
                actual=representation,
            )
            differences.append(
                {
                    "path": "/policy/representation",
                    "requested": "either",
                    "actual": representation,
                    "basis": "allowed_representation",
                }
            )
        else:
            self.expect(
                representation == policy.representation,
                "POLICY_FIXED",
                "/report/actual_policy/representation",
                requested=policy.representation,
                actual=representation,
            )
        for index, value in enumerate(self.result.observations):
            if value.kind == "full_state":
                self.expect(
                    value.representation == representation,
                    "REPRESENTATION",
                    f"/observations/{index}/representation",
                    requested=representation,
                    actual=value.representation,
                )
        differences.sort(key=lambda item: item["path"])
        reported = [
            {
                "path": item.path,
                "requested": _plain(item.requested.value),
                "actual": _plain(item.actual.value),
                "basis": item.basis,
            }
            for item in self.result.report.policy_differences
        ]
        self.expect(
            reported == differences,
            "POLICY_REPORT",
            "/report/policy_differences",
            requested=differences,
            actual=reported,
        )

    def transforms(self) -> None:
        # 授权只引用既有规则。它不能增加物理变换许可。
        rules = {
            "sparse_storage": ("exact_representation", {"rule": "sparse_storage"}),
            "integration_substep": ("numerical_substep", {"policy": "/policy"}),
        }
        for index, transform in enumerate(self.result.report.transforms):
            path = f"/report/transforms/{index}"
            rule = rules.get(transform.name)
            self.expect(
                rule is not None
                and (transform.kind, _plain(transform.authorization.value)) == rule,
                "TRANSFORM_FORBIDDEN",
                path,
                name=transform.name,
                kind=transform.kind,
                authorization=_plain(transform.authorization.value),
            )


def _real_values(array: ArrayData) -> list[float]:
    return [value for (value,) in struct.iter_unpack("<d", array.data)]


def _projection(value: ObservationValue, ctx: _NumericContext, path: str) -> None:
    assert value.block is not None and value.leakage is not None
    assert value.input_trace is not None and value.trace_error is not None
    count, size, _ = value.block.shape
    retained = math.prod(value.block.shape) + 3 * count
    ctx.dimension(size, path + "/block")
    ctx.slots(retained + 7 * size * size + 32, path)
    blocks = _values(value.block)
    leakage = _real_values(value.leakage)
    input_trace = _real_values(value.input_trace)
    trace_error = _real_values(value.trace_error)
    for index in range(count):
        block = blocks[index * size * size : (index + 1) * size * size]
        _hermitian(block, size, ctx, path + "/block")
        _psd(block, size, ctx, path + "/block", retained=retained)
        trace = 0j
        for diagonal in range(size):
            trace += block[diagonal * size + diagonal]
            ctx.finite(trace, path + "/block")
        expected_leakage = 1.0 - trace.real
        expected_error = input_trace[index] - 1.0
        ctx.finite(expected_leakage, path + "/leakage")
        ctx.finite(expected_error, path + "/trace_error")
        if leakage[index] != expected_leakage:
            ctx.fail(
                "NORMALIZATION",
                path + "/leakage",
                index=index,
                expected=expected_leakage,
                actual=leakage[index],
            )
        if trace_error[index] != expected_error:
            ctx.fail(
                "NORMALIZATION",
                path + "/trace_error",
                index=index,
                expected=expected_error,
                actual=trace_error[index],
            )
        if abs(trace.imag) > 1e-10:
            ctx.fail("HERMITIAN", path + "/block", trace_imag=trace.imag)


def _physical_observation(value: ObservationValue, ctx: _NumericContext, path: str) -> None:
    if value.kind == "projection":
        _projection(value, ctx, path)
        return
    assert value.data is not None
    count = value.data.shape[0]
    retained = math.prod(value.data.shape)
    if value.kind == "expectation":
        ctx.slots(retained + 16, path + "/data")
        for index, number in enumerate(_values(value.data)):
            if abs(number.imag) > 1e-10:
                ctx.fail("HERMITIAN", path + "/data", index=index, imaginary=number.imag)
        return
    size = value.data.shape[1]
    ctx.dimension(size, path + "/data")
    kind = value.representation if value.kind == "full_state" else "density"
    width = size if kind == "ket" else size * size
    ctx.slots(retained + (width + 16 if kind == "ket" else 7 * size * size + 32), path + "/data")
    values = _values(value.data)
    for index in range(count):
        _state(
            values[index * width : (index + 1) * width],
            kind or "density",
            size,
            ctx,
            path + "/data",
            retained=retained,
        )


def check_result(
    request: Request, result: Result, *, level: _Level, budget: CheckBudget = _DEFAULT_BUDGET
) -> CheckReport:
    """检查结果是否符合原请求。

    Args:
        request: 原始请求。
        result: 待检查的结果。
        level: 请求的检查级别。
        budget: 请求与结果共用的资源上限。

    Returns:
        检查报告。请求拒绝保留原始类别。
        结果自身的违例使用 INVALID_RESULT。
        资源超限使用 RESOURCE_LIMIT。

    Raises:
        PContractError: level 不是已知检查级别。
    """
    context = _NumericContext(budget)
    request_report = _check(request, level, budget, Request, context=context)
    if request_report.diagnostics or not request_report.complete:
        return replace(request_report, unchecked=(*request_report.unchecked, "result"))
    checked = tuple("request/" + item for item in request_report.checked)
    unchecked = list(request_report.unchecked)
    try:
        codec.dump_result(result, budget=budget)
    except PContractError as error:
        transport_diagnostics = tuple(
            replace(item, category="INVALID_RESULT") if item.category != "RESOURCE_LIMIT" else item
            for item in error.diagnostics
        )
        return CheckReport(
            level=level,
            complete=False,
            diagnostics=transport_diagnostics,
            checked=checked,
            unchecked=(*unchecked, "result/transport", "result"),
        )
    checked += ("result/transport",)
    if level == "transport":
        return CheckReport(
            level=level, complete=True, diagnostics=(), checked=checked, unchecked=tuple(unchecked)
        )
    try:
        expected_request_id = _request_id(request, budget=budget)
    except PContractError as error:
        return CheckReport(
            level=level,
            complete=False,
            diagnostics=error.diagnostics,
            checked=checked,
            unchecked=(*unchecked, "result/identity", "result/binding", "result"),
        )
    binding = _Binding(request, result)
    binding.identity(expected_request_id)
    binding.observations()
    binding.policy()
    binding.transforms()
    diagnostics = binding.diagnostics
    unchecked.extend(binding.unchecked)
    if result.report.diagnostics:
        # 后端失败证据保留类别。检查器不把声明当成成功。
        diagnostics.extend(result.report.diagnostics)
    if not diagnostics:
        checked += ("result/structure",)
    else:
        unchecked.append("result/structure")
    if level == "physical":
        for value, path in binding.valid_observations:
            try:
                _physical_observation(value, context, path)
            except PContractError as error:
                diagnostics.extend(
                    replace(item, category="INVALID_RESULT")
                    if item.category != "RESOURCE_LIMIT"
                    else item
                    for item in error.diagnostics
                )
                unchecked.append(path + "/physical")
        if diagnostics:
            unchecked.append("result/physical")
        else:
            checked += ("result/physical",)
    return CheckReport(
        level=level,
        complete=not diagnostics,
        diagnostics=tuple(diagnostics),
        checked=checked,
        unchecked=tuple(dict.fromkeys(unchecked)),
    )
