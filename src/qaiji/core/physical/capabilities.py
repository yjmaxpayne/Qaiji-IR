# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""P 层完整能力组合。"""

from __future__ import annotations

import math
import re
import struct
from typing import Any, cast

from . import codec
from .arrays import FrozenJSON, _JSONArray, _JSONObject
from .diagnostics import CheckReport, Diagnostic, PContractError, _fail
from .model import Capabilities, Problem, Request, Requirements
from .validation import _diagnostic, check_request, require_valid

_PROFILE_FIELDS = {
    "approximations",
    "environment",
    "frame",
    "interpolation",
    "determinism",
    "initial_kind",
    "method",
    "output_kinds",
    "state_representations",
}
_OUTPUTS = {"full_state", "expectation", "partial_trace", "projection"}
_APPROXIMATIONS = {"rwa"}
_HEX = re.compile(r"[0-9a-f]{16}\Z")


def _plain(value: Any) -> Any:
    if isinstance(value, FrozenJSON):
        return _plain(value.value)
    if isinstance(value, _JSONObject):
        return {key: _plain(child) for key, child in value.items}
    if isinstance(value, _JSONArray):
        return [_plain(child) for child in value.items]
    return value


def _hex(value: float) -> str:
    return struct.pack(">d", value).hex()


def _number(value: Any, path: str) -> float:
    if type(value) is not str or not _HEX.fullmatch(value):
        _fail("NUMBER_ENCODING", path, "Expected a binary64 hexadecimal string.")
    number = struct.unpack(">d", bytes.fromhex(value))[0]
    if not math.isfinite(number) or number < 0:
        _fail("NUMBER", path, "Expected a finite nonnegative value.")
    return cast(float, number)


def _strings(value: Any, allowed: set[str] | None, path: str) -> list[str]:
    if type(value) is not list or any(type(v) is not str or not v for v in value):
        _fail("KEYS", path, "Expected a string list.")
    if len(set(value)) != len(value) or (allowed is not None and not set(value) <= allowed):
        _fail("KEYS", path, "Unexpected or duplicate profile values.")
    return value


def _profiles(record: Requirements | Capabilities) -> list[dict[str, Any]]:
    capability = isinstance(record, Capabilities)
    profiles = [_plain(profile) for profile in record.profiles]
    if not profiles:
        _fail("KEYS", "/profiles", "Expected at least one complete profile.")
    for index, profile in enumerate(profiles):
        path = f"/profiles/{index}"
        if type(profile) is not dict or set(profile) != _PROFILE_FIELDS:
            _fail("KEYS", path, "Expected every complete profile field.")
        choices = {
            "environment": {"closed", "markovian"},
            "frame": {"lab", "rotating"},
            "interpolation": {"zoh"},
            "determinism": {"deterministic"},
            "initial_kind": {"ket", "density"},
        }
        for name, allowed in choices.items():
            if type(profile[name]) is not str or profile[name] not in allowed:
                _fail("KEYS", path + "/" + name, "Unknown profile value.")
        if type(profile["method"]) is not str or not profile["method"]:
            _fail("KEYS", path + "/method", "Expected a nonempty method ID.")
        _strings(profile["output_kinds"], _OUTPUTS, path + "/output_kinds")
        _strings(profile["approximations"], _APPROXIMATIONS, path + "/approximations")
        representations = profile["state_representations"]
        if capability:
            _strings(representations, {"ket", "density"}, path + "/state_representations")
        else:
            if type(representations) is not dict:
                _fail(
                    "PROFILE",
                    path + "/state_representations",
                    "Expected observation representation choices.",
                )
            for observation, values in representations.items():
                if not observation:
                    _fail(
                        "PROFILE",
                        path + "/state_representations",
                        "Expected a nonempty observation ID.",
                    )
                _strings(values, {"ket", "density"}, path + "/state_representations")
        if not capability and ("full_state" in profile["output_kinds"]) != bool(representations):
            _fail(
                "KEYS",
                path + "/state_representations",
                "Full-state output needs observation representation choices.",
            )
        if bool(representations) and "full_state" not in profile["output_kinds"]:
            _fail(
                "PROFILE",
                path + "/state_representations",
                "State representations need full-state output.",
            )
    if set(record.methods) != {p["method"] for p in profiles}:
        _fail("KEYS", "/methods", "Method summary must equal the profile union.")
    if set(record.output_kinds) != {kind for p in profiles for kind in p["output_kinds"]}:
        _fail("KEYS", "/output_kinds", "Output summary must equal the profile union.")
    return profiles


def _precision(record: Requirements | Capabilities) -> dict[str, Any]:
    precision = _plain(record.precision)
    names = ("min_atol", "min_rtol") if isinstance(record, Capabilities) else ("atol", "rtol")
    if type(precision) is not dict or set(precision) != {"dtype", *names}:
        _fail("KEYS", "/precision", "Unexpected precision fields.")
    if precision["dtype"] != "binary64":
        _fail("KEYS", "/precision/dtype", "Expected binary64 precision.")
    for name in names:
        precision[name] = _number(precision[name], "/precision/" + name)
    if isinstance(record, Requirements) and precision["atol"] == 0:
        _fail("KEYS", "/precision/atol", "Absolute tolerance must be positive.")
    return precision


def _initial_kind(problem: Problem) -> str:
    initial = problem.initial_state
    initial_kind = initial.kind
    if initial_kind == "product":
        initial_kind = (
            "density" if any(f.kind == "density" for f in initial.factors or ()) else "ket"
        )
    return initial_kind


def _request_representations(request: Request) -> dict[str, list[str]]:
    representations: dict[str, list[str]] = {}
    for observation in request.observations:
        if observation.kind == "full_state":
            requested = (
                {"ket", "density"}
                if observation.representation == "either"
                else {cast(str, observation.representation)}
            )
            policy = (
                {"ket", "density"}
                if request.policy.representation == "either"
                else {request.policy.representation}
            )
            representations[observation.id] = sorted(requested & policy)
    return representations


def _representation_missing(
    environment: str, initial_kind: str, representations: dict[str, list[str]], supported: set[str]
) -> list[str]:
    missing: list[str] = []
    permitted = set(supported)
    if environment == "markovian" or initial_kind == "density":
        permitted &= {"density"}
    common = set(permitted)
    for choices in representations.values():
        common.intersection_update(choices)
    for observation, choices in representations.items():
        if not permitted.intersection(choices) or not common:
            missing.append(
                "state_representations/" + observation.replace("~", "~0").replace("/", "~1")
            )
    return missing


def extract_requirements(request: Request) -> Requirements:
    """从请求提取完整候选能力组合。

    Args:
        request: 结构合法的请求。

    Returns:
        保留各观测表示选择的候选需求。

    Raises:
        PContractError: 请求未通过结构检查。
    """
    require_valid(check_request(request, level="structure"))
    problem = request.problem
    initial_kind = _initial_kind(problem)
    methods = (
        (request.policy.method.value,)
        if request.policy.method.mode == "fixed"
        else request.policy.method.allowed
    )
    representations = _request_representations(request)
    outputs = sorted({observation.kind for observation in request.observations})
    profiles = [
        FrozenJSON(
            value=cast(
                Any,
                dict(
                    approximations=tuple(sorted(problem.approximations)),
                    environment=problem.environment.kind,
                    frame=problem.frame,
                    interpolation="zoh",
                    determinism="deterministic",
                    initial_kind=initial_kind,
                    method=method,
                    output_kinds=tuple(outputs),
                    state_representations=representations,
                ),
            )
        )
        for method in methods
    ]
    return Requirements(
        profiles=tuple(profiles),
        dimension=math.prod(site.dim for site in problem.sites),
        precision=FrozenJSON(
            value=cast(
                Any,
                dict(
                    dtype="binary64", atol=_hex(request.policy.atol), rtol=_hex(request.policy.rtol)
                ),
            )
        ),
        required_extensions=tuple((e.namespace, e.version) for e in problem.extensions),
        output_kinds=tuple(outputs),
        methods=cast(tuple[str, ...], methods),
    )


def _profile_missing(required: dict[str, Any], supported: dict[str, Any]) -> list[str]:
    missing = []
    for field in ("environment", "frame", "interpolation", "determinism", "initial_kind", "method"):
        if required[field] != supported[field]:
            missing.append(field)
    if not set(required["output_kinds"]) <= set(supported["output_kinds"]):
        missing.append("output_kinds")
    # 消费者声明的是允许的近似集合；请求要求的近似都在其中才匹配。
    if not set(required["approximations"]) <= set(supported["approximations"]):
        missing.append("approximations")
    missing.extend(
        _representation_missing(
            required["environment"],
            required["initial_kind"],
            required["state_representations"],
            set(supported["state_representations"]),
        )
    )
    return missing


def match_capabilities(requirements: Requirements, capabilities: Capabilities) -> CheckReport:
    """逐个匹配完整能力组合。

    Args:
        requirements: 待满足的候选需求。
        capabilities: 消费者声明的能力。

    Returns:
        匹配报告。诊断列出全部缺失能力。
    """
    try:
        codec.dump_requirements(requirements)
        codec.dump_capabilities(capabilities)
        required_profiles = _profiles(requirements)
        supported_profiles = _profiles(capabilities)
        precision = _precision(requirements)
        supported_precision = _precision(capabilities)
    except PContractError as error:
        return CheckReport(
            level="structure",
            complete=False,
            diagnostics=error.diagnostics,
            checked=(),
            unchecked=("capability",),
        )
    missing: list[str] = []
    if requirements.dimension > capabilities.max_dimension:
        missing.append("dimension")
    for field in ("atol", "rtol"):
        if precision[field] < supported_precision["min_" + field]:
            missing.append("precision/" + field)
    for namespace, version in requirements.required_extensions:
        if (namespace, version) not in capabilities.required_extensions:
            missing.append("required_extensions/" + namespace + "/" + version)
    candidates = []
    for i, required in enumerate(required_profiles):
        for j, supported in enumerate(supported_profiles):
            candidates.append((i, j, _profile_missing(required, supported)))
    if not any(not candidate[2] for candidate in candidates):
        for i, j, fields in candidates:
            missing.extend(f"profiles/{i}/capabilities/{j}/{field}" for field in fields)
    diagnostics: tuple[Diagnostic, ...] = ()
    if missing:
        diagnostics = (
            _diagnostic(
                "PROFILE",
                "",
                "No complete capability combination satisfies the request.",
                category="UNSUPPORTED_CAPABILITY",
                missing=sorted(set(missing)),
            ),
        )
    return CheckReport(
        level="structure",
        complete=not missing,
        diagnostics=diagnostics,
        checked=("capability",) if not missing else (),
        unchecked=("capability",) if missing else (),
    )
