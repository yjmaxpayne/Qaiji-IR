# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""P 层模型：构造签名、分支互斥、深层不可变与显式空值。"""

from __future__ import annotations

import dataclasses
import inspect
import os
import struct
import subprocess
import sys
import typing
from collections.abc import Mapping
from dataclasses import MISSING, FrozenInstanceError

import pytest

import qaiji.core.physical as physical
from qaiji.core.physical import (
    ArrayData,
    BasisMapping,
    Capabilities,
    CheckBudget,
    CheckReport,
    Diagnostic,
    Drive,
    EncodedArtifact,
    Environment,
    ExecutionPolicy,
    ExecutionReport,
    FrozenJSON,
    Jump,
    LocalFactor,
    MethodChoice,
    Observation,
    ObservationValue,
    OperatorSum,
    OperatorTerm,
    PContractError,
    PolicyDifference,
    Problem,
    ProductFactor,
    Provenance,
    Request,
    RequiredExtension,
    Requirements,
    Result,
    Signal,
    Site,
    SnapshotRef,
    State,
    TransformRecord,
)
from qaiji.core.physical.arrays import _JSONArray, _JSONObject

EXPECTED_FIELDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "ArrayData": (("dtype", "shape", "data"),),
    "FrozenJSON": (("value",),),
    "Site": (("id", "dim", "basis"),),
    "LocalFactor": (("site", "matrix"),),
    "OperatorTerm": (("coefficient", "factors"),),
    "OperatorSum": (("unit", "terms"),),
    "Signal": (("kind", "unit", "value"), ("kind", "unit", "values")),
    "Drive": (("id", "operator", "signal"),),
    "Jump": (("id", "operator", "rate"),),
    "Environment": (("kind", "jumps"),),
    "ProductFactor": (("site", "kind", "data"),),
    "State": (("kind", "frame", "data"), ("kind", "frame", "factors")),
    "RequiredExtension": (
        ("namespace", "version", "content_type", "required", "affects_physics", "payload"),
    ),
    "SnapshotRef": (("id", "version", "digest"),),
    "BasisMapping": (("logical_bit", "site", "zero_label", "one_label"),),
    "Provenance": (
        (
            "kind",
            "program_ref",
            "binder_version",
            "device_snapshot",
            "calibration_snapshot",
            "basis_mapping",
            "prior_transforms",
        ),
    ),
    "Observation": (
        ("id", "kind", "representation"),
        ("id", "kind", "operator"),
        ("id", "kind", "keep_sites"),
        ("id", "kind", "input_sites", "isometry"),
    ),
    "ObservationValue": (
        ("id", "kind", "representation", "data"),
        ("id", "kind", "data"),
        ("id", "kind", "keep_sites", "data"),
        ("id", "kind", "input_sites", "block", "leakage", "input_trace", "trace_error"),
    ),
    "MethodChoice": (("mode", "value", "allowed"), ("mode", "value", "allowed")),
    "ExecutionPolicy": (("method", "atol", "rtol", "max_step_ns", "representation"),),
    "PolicyDifference": (("path", "requested", "actual", "basis"),),
    "TransformRecord": (("name", "kind", "authorization"),),
    "ExecutionReport": (
        (
            "backend_id",
            "backend_version",
            "actual_policy",
            "policy_differences",
            "transforms",
            "state_representations",
            "validation_level",
            "diagnostics",
        ),
    ),
    "Problem": (
        (
            "sites",
            "tensor_order",
            "h0",
            "drives",
            "environment",
            "initial_state",
            "signal_edges",
            "time_unit",
            "frame",
            "approximations",
            "extensions",
            "schema",
        ),
    ),
    "Request": (("problem", "output_times", "observations", "policy", "provenance", "schema"),),
    "Result": (
        (
            "request_id",
            "output_times",
            "tensor_order",
            "frame",
            "observations",
            "report",
            "schema",
        ),
    ),
    "Requirements": (
        (
            "profiles",
            "dimension",
            "precision",
            "required_extensions",
            "output_kinds",
            "methods",
            "schema",
        ),
    ),
    "Capabilities": (
        (
            "consumer_id",
            "consumer_version",
            "profiles",
            "max_dimension",
            "precision",
            "required_extensions",
            "output_kinds",
            "methods",
            "schema",
        ),
    ),
    "CheckBudget": (
        (
            "max_wire_bytes",
            "max_depth",
            "max_attachment_bytes",
            "max_dense_dimension",
            "max_numeric_elements",
            "max_rational_ops",
            "max_rational_bits",
        ),
    ),
    "Diagnostic": (("category", "code", "path", "message", "details"),),
    "CheckReport": (("level", "complete", "diagnostics", "checked", "unchecked"),),
    "EncodedArtifact": (("document", "attachments"),),
    "PContractError": (("diagnostics",),),
}

OVERLOADED = frozenset({"Signal", "State", "Observation", "ObservationValue"})

SCHEMA_DEFAULTS = {
    "Problem": "qaiji.p.problem/1.0",
    "Request": "qaiji.p.request/1.0",
    "Result": "qaiji.p.result/1.0",
    "Requirements": "qaiji.p.requirements/1.0",
    "Capabilities": "qaiji.p.capabilities/1.0",
}

BUDGET_DEFAULTS = {
    "max_wire_bytes": 16777216,
    "max_depth": 32,
    "max_attachment_bytes": 16777216,
    "max_dense_dimension": 64,
    "max_numeric_elements": 1048576,
    "max_rational_ops": 1000000,
    "max_rational_bits": 16384,
}

EXPECTED_EXPORTS = tuple(sorted(EXPECTED_FIELDS))


def _f64_array(values: tuple[float, ...]) -> ArrayData:
    return ArrayData(
        dtype="f64le",
        shape=(len(values),),
        data=struct.pack(f"<{len(values)}d", *values),
    )


def _c128_array(values: tuple[complex, ...], shape: tuple[int, ...]) -> ArrayData:
    payload = bytearray()
    for value in values:
        payload += struct.pack("<dd", value.real, value.imag)
    return ArrayData(dtype="c128le", shape=shape, data=payload)


def _site() -> Site:
    return Site(id="q0", dim=2, basis=("0", "1"))


def _ket() -> ArrayData:
    return _c128_array((1 + 0j, 0 + 0j), (2,))


def _density() -> ArrayData:
    return _c128_array((1 + 0j, 0 + 0j, 0 + 0j, 0 + 0j), (2, 2))


def _operator(unit: str) -> OperatorSum:
    matrix = _c128_array((1 + 0j, 0 + 0j, 0 + 0j, -1 + 0j), (2, 2))
    factor = LocalFactor(site="q0", matrix=matrix)
    term = OperatorTerm(coefficient=1 + 0j, factors=(factor,))
    return OperatorSum(unit=unit, terms=(term,))


def _extension(payload: dict[str, object] | None = None) -> RequiredExtension:
    return RequiredExtension(
        namespace="org.qaiji.tests.models",
        version="1.0",
        content_type="application/vnd.qaiji.p.opaque+json",
        required=True,
        affects_physics=True,
        payload=FrozenJSON(value=payload if payload is not None else {"a": [1, 2]}),
    )


def _manual_provenance() -> Provenance:
    return Provenance(
        kind="manual",
        program_ref=None,
        binder_version=None,
        device_snapshot=None,
        calibration_snapshot=None,
        basis_mapping=(BasisMapping(logical_bit=0, site="q0", zero_label="0", one_label="1"),),
        prior_transforms=(FrozenJSON(value={"transform": "none"}),),
    )


def _diagnostic(path: str = "", code: str = "KEYS") -> Diagnostic:
    return Diagnostic(
        category="INVALID_REQUEST",
        code=code,
        path=path,
        message="synthetic diagnostic",
        details=FrozenJSON(value={"code": code}),
    )


def _problem() -> Problem:
    state = State(kind="ket", frame="lab", data=_ket())
    return Problem(
        sites=(_site(),),
        tensor_order=("q0",),
        h0=_operator("rad/ns"),
        drives=(
            Drive(
                id="d0",
                operator=_operator("1"),
                signal=Signal(kind="constant", unit="rad/ns", value=1.0),
            ),
        ),
        environment=Environment(
            kind="markovian",
            jumps=(
                Jump(
                    id="j0",
                    operator=_operator("1"),
                    rate=Signal(kind="constant", unit="1/ns", value=0.1),
                ),
            ),
        ),
        initial_state=state,
        signal_edges=_f64_array((0.0, 1.0)),
        time_unit="ns",
        frame="lab",
        approximations=(),
        extensions=(_extension(),),
    )


def _request() -> Request:
    return Request(
        problem=_problem(),
        output_times=_f64_array((0.0, 1.0)),
        observations=(
            Observation(id="full", kind="full_state", representation="ket"),
            Observation(id="expect", kind="expectation", operator=_operator("1")),
            Observation(id="trace", kind="partial_trace", keep_sites=("q0",)),
            Observation(
                id="project",
                kind="projection",
                input_sites=("q0",),
                isometry=_c128_array((1 + 0j, 0 + 0j), (2, 1)),
            ),
        ),
        policy=ExecutionPolicy(
            method=MethodChoice(mode="fixed", value="exact", allowed=()),
            atol=1e-10,
            rtol=0.0,
            max_step_ns=None,
            representation="ket",
        ),
        provenance=_manual_provenance(),
    )


def _report() -> ExecutionReport:
    return ExecutionReport(
        backend_id="qaiji.tests",
        backend_version="1.0",
        actual_policy=FrozenJSON(value={"method": "exact"}),
        policy_differences=(
            PolicyDifference(
                path="/policy/representation",
                requested=FrozenJSON(value={"representation": "either"}),
                actual=FrozenJSON(value={"representation": "ket"}),
                basis="allowed_representation",
            ),
        ),
        transforms=(
            TransformRecord(
                name="sparse_storage",
                kind="exact_representation",
                authorization=FrozenJSON(value={"rule": "representation"}),
            ),
        ),
        state_representations=FrozenJSON(value={"full": "ket"}),
        validation_level="physical",
        diagnostics=(_diagnostic(),),
    )


def _result() -> Result:
    return Result(
        request_id="sha256:" + "0" * 64,
        output_times=_f64_array((0.0, 1.0)),
        tensor_order=("q0",),
        frame="lab",
        observations=(
            ObservationValue(
                id="full",
                kind="full_state",
                representation="ket",
                data=_c128_array((1 + 0j, 0 + 0j, 1 + 0j, 0 + 0j), (2, 2)),
            ),
        ),
        report=_report(),
    )


def test_p_constructor_signatures_match() -> None:
    for name, branches in EXPECTED_FIELDS.items():
        cls = getattr(physical, name)
        if name in OVERLOADED:
            overloads = typing.get_overloads(cls.__init__)
            assert len(overloads) == len(branches), name
            for function, expected in zip(overloads, branches, strict=True):
                parameters = list(inspect.signature(function).parameters.values())[1:]
                assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters), name
                assert tuple(p.name for p in parameters) == expected, name
                assert all(p.default is inspect.Parameter.empty for p in parameters), name
            continue

        parameters = list(inspect.signature(cls).parameters.values())
        assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters), name
        assert tuple(p.name for p in parameters) == branches[0], name

        if dataclasses.is_dataclass(cls):
            expected_defaults: dict[str, object] = {}
            if name in SCHEMA_DEFAULTS:
                expected_defaults["schema"] = SCHEMA_DEFAULTS[name]
            if name == "CheckBudget":
                expected_defaults.update(BUDGET_DEFAULTS)
            for field in dataclasses.fields(cls):
                if field.name in expected_defaults:
                    assert field.default == expected_defaults[field.name], name
                else:
                    assert field.default is MISSING, name
            assert all(not field.name.startswith("_") for field in dataclasses.fields(cls)), name
        else:
            assert tuple(p.name for p in parameters) == ("diagnostics",), name
            assert parameters[0].default is inspect.Parameter.empty, name

    with pytest.raises(TypeError):
        Site("q0", 2, ("0", "1"))  # type: ignore[misc]

    assert [name for name in physical.__all__ if isinstance(getattr(physical, name), type)] == list(
        EXPECTED_EXPORTS
    )
    assert all(isinstance(getattr(physical, name), type) for name in EXPECTED_EXPORTS)

    ordered = (
        _diagnostic("/sites/10", "SHAPE"),
        _diagnostic("/sites/2", "SHAPE"),
        _diagnostic("/sites", "SHAPE"),
        _diagnostic("/sites/2", "NUMBER"),
    )
    error = PContractError(diagnostics=ordered)
    assert [item.path for item in error.diagnostics] == [
        "/sites",
        "/sites/2",
        "/sites/2",
        "/sites/10",
    ]
    assert [item.code for item in error.diagnostics] == ["SHAPE", "NUMBER", "SHAPE", "SHAPE"]
    report = CheckReport(
        level="structure",
        complete=True,
        diagnostics=ordered,
        checked=("schema",),
        unchecked=(),
    )
    assert [item.path for item in report.diagnostics] == [
        "/sites",
        "/sites/2",
        "/sites/2",
        "/sites/10",
    ]


def test_p_kind_branches_are_exclusive() -> None:
    constant = Signal(kind="constant", unit="rad/ns", value=1.0)
    zoh = Signal(kind="zoh", unit="rad/ns", values=_f64_array((0.0, 1.0)))
    assert constant.value == 1.0 and constant.values is None
    assert zoh.value is None and zoh.values is not None

    ket_state = State(kind="ket", frame="lab", data=_ket())
    product_state = State(
        kind="product",
        frame="lab",
        factors=(ProductFactor(site="q0", kind="ket", data=_ket()),),
    )
    assert ket_state.data is not None and ket_state.factors is None
    assert product_state.data is None and product_state.factors is not None

    full = Observation(id="full", kind="full_state", representation="ket")
    expectation = Observation(id="expect", kind="expectation", operator=_operator("1"))
    trace = Observation(id="trace", kind="partial_trace", keep_sites=("q0",))
    projection = Observation(
        id="project",
        kind="projection",
        input_sites=("q0",),
        isometry=_c128_array((1 + 0j, 0 + 0j), (2, 1)),
    )
    assert full.representation == "ket" and full.operator is None
    assert expectation.operator is not None and expectation.representation is None
    assert trace.keep_sites == ("q0",) and trace.input_sites is None
    assert projection.input_sites == ("q0",) and projection.isometry is not None

    full_value = ObservationValue(
        id="full",
        kind="full_state",
        representation="ket",
        data=_c128_array((1 + 0j, 0 + 0j), (1, 2)),
    )
    expectation_value = ObservationValue(
        id="expect", kind="expectation", data=_c128_array((1 + 0j,), (1,))
    )
    trace_value = ObservationValue(
        id="trace",
        kind="partial_trace",
        keep_sites=("q0",),
        data=_c128_array((1 + 0j, 0 + 0j, 0 + 0j, 0 + 0j), (1, 2, 2)),
    )
    block = _c128_array((1 + 0j,) * 8, (2, 2, 2))
    projection_value = ObservationValue(
        id="project",
        kind="projection",
        input_sites=("q0",),
        block=block,
        leakage=_f64_array((0.0, 0.0)),
        input_trace=_f64_array((1.0, 1.0)),
        trace_error=_f64_array((0.0, 0.0)),
    )
    assert full_value.data is not None and full_value.block is None
    assert expectation_value.data is not None and expectation_value.keep_sites is None
    assert trace_value.keep_sites == ("q0",) and trace_value.input_sites is None
    assert projection_value.block is not None and projection_value.data is None

    with pytest.raises(PContractError) as both_signal_fields:
        Signal(kind="constant", unit="rad/ns", value=1.0, values=_f64_array((0.0,)))
    assert both_signal_fields.value.diagnostics[0].code == "KEYS"

    with pytest.raises(PContractError) as wrong_signal_field:
        Signal(kind="zoh", unit="rad/ns", value=1.0)
    assert wrong_signal_field.value.diagnostics[0].code == "KEYS"

    with pytest.raises(PContractError) as both_state_fields:
        State(kind="ket", frame="lab", data=_ket(), factors=())
    assert both_state_fields.value.diagnostics[0].code == "KEYS"

    with pytest.raises(PContractError) as wrong_state_field:
        State(kind="product", frame="lab", data=_ket())
    assert wrong_state_field.value.diagnostics[0].code == "KEYS"

    with pytest.raises(PContractError) as wrong_observation_field:
        Observation(id="full", kind="full_state", operator=_operator("1"))
    assert wrong_observation_field.value.diagnostics[0].code == "KEYS"

    with pytest.raises(PContractError) as wrong_value_field:
        ObservationValue(
            id="expect", kind="expectation", representation="ket", data=_f64_array((1.0,))
        )
    assert wrong_value_field.value.diagnostics[0].code == "KEYS"

    with pytest.raises(PContractError):
        Signal(kind="unknown", unit="rad/ns", value=1.0)  # type: ignore[arg-type]

    with pytest.raises(PContractError) as closed_with_jumps:
        Environment(
            kind="closed",
            jumps=(
                Jump(
                    id="j0",
                    operator=_operator("1"),
                    rate=Signal(kind="constant", unit="1/ns", value=0.1),
                ),
            ),
        )
    assert closed_with_jumps.value.diagnostics[0].code == "KEYS"

    with pytest.raises(PContractError):
        MethodChoice(mode="fixed", value="exact", allowed=("exact",))
    with pytest.raises(PContractError):
        MethodChoice(mode="delegate", value="exact", allowed=("exact",))
    with pytest.raises(PContractError):
        MethodChoice(mode="delegate", value=None, allowed=())
    with pytest.raises(PContractError):
        MethodChoice(mode="fixed", value="", allowed=())


def test_p_records_are_deeply_immutable() -> None:
    basis = ["0", "1"]
    site = Site(id="q0", dim=2, basis=basis)
    drives = [
        Drive(
            id="d0",
            operator=_operator("1"),
            signal=Signal(kind="constant", unit="rad/ns", value=1.0),
        )
    ]
    payload = {"nested": [1, 2], "flag": True}
    extensions = [_extension(payload)]
    provenance = _manual_provenance()
    problem = Problem(
        sites=[site],
        tensor_order=["q0"],
        h0=_operator("rad/ns"),
        drives=drives,
        environment=Environment(kind="closed", jumps=[]),
        initial_state=State(kind="ket", frame="lab", data=_ket()),
        signal_edges=_f64_array((0.0, 1.0)),
        time_unit="ns",
        frame="lab",
        approximations=[],
        extensions=extensions,
    )
    request = Request(
        problem=problem,
        output_times=_f64_array((0.0,)),
        observations=[Observation(id="full", kind="full_state", representation="ket")],
        policy=ExecutionPolicy(
            method=MethodChoice(mode="delegate", value=None, allowed=("exact",)),
            atol=1e-10,
            rtol=0.0,
            max_step_ns=None,
            representation="either",
        ),
        provenance=provenance,
    )
    result = _result()
    requirements = Requirements(
        profiles=(FrozenJSON(value={"environment": "closed"}),),
        dimension=2,
        precision=FrozenJSON(
            value={"dtype": "f64le", "atol": "0000000000000000", "rtol": "0000000000000000"}
        ),
        required_extensions=(("org.qaiji.tests.models", "1.0"),),
        output_kinds=("full_state",),
        methods=("exact",),
    )
    capabilities = Capabilities(
        consumer_id="qaiji.tests",
        consumer_version="1.0",
        profiles=(FrozenJSON(value={"environment": "closed"}),),
        max_dimension=64,
        precision=FrozenJSON(
            value={
                "dtype": "f64le",
                "min_atol": "0000000000000000",
                "min_rtol": "0000000000000000",
            }
        ),
        required_extensions=(("org.qaiji.tests.models", "1.0"),),
        output_kinds=("full_state",),
        methods=("exact",),
    )
    budget = CheckBudget()
    report = CheckReport(
        level="physical",
        complete=True,
        diagnostics=(_diagnostic(),),
        checked=("schema", "dimension"),
        unchecked=(),
    )
    artifact = EncodedArtifact(
        document=bytearray(b"{}"),
        attachments=[("/bath", bytearray(b"\x00"))],
    )
    error = PContractError(diagnostics=[_diagnostic()])

    basis[0] = "x"
    drives.clear()
    payload["nested"].append(3)
    extensions.clear()
    assert site.basis == ("0", "1")
    assert problem.drives == (request.problem.drives[0],)
    assert request.problem.extensions[0].payload.value == _JSONObject(
        (("flag", True), ("nested", _JSONArray((1, 2))))
    )
    assert artifact.document == b"{}"
    assert artifact.attachments == (("/bath", b"\x00"),)

    with pytest.raises(FrozenInstanceError):
        site.id = "q1"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        problem.frame = "rotating"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        artifact.document = b""  # type: ignore[misc]

    roots = (
        problem,
        request,
        result,
        requirements,
        capabilities,
        budget,
        report,
        artifact,
        error,
    )
    for root in roots:
        if isinstance(root, PContractError):
            _walk(root.diagnostics, set())
        else:
            _walk(root, set())


def _walk(value: object, seen: set[int]) -> None:
    assert not isinstance(value, (dict, list, set, bytearray, memoryview))
    if isinstance(value, tuple):
        for item in value:
            _walk(item, seen)
        return
    if isinstance(value, (str, bytes, int, float, complex, bool)) or value is None:
        return
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        for field in dataclasses.fields(value):
            _walk(getattr(value, field.name), seen)
        return
    raise AssertionError(f"unexpected mutable value: {type(value)!r}")


def test_p_frozen_json_keeps_container_kinds() -> None:
    empty_object = FrozenJSON(value={})
    empty_array = FrozenJSON(value=[])
    assert empty_object != empty_array
    assert isinstance(empty_object.value, _JSONObject)
    assert isinstance(empty_array.value, _JSONArray)
    assert empty_object.value.items == ()
    assert empty_array.value.items == ()

    ordered = FrozenJSON(value={"b": 1, "a": {"d": [], "c": {}}})
    reordered = FrozenJSON(value={"a": {"c": {}, "d": []}, "b": 1})
    assert ordered == reordered
    assert isinstance(ordered.value, _JSONObject)
    assert [key for key, _ in ordered.value.items] == ["a", "b"]

    source = {"items": [1, {"deep": [True, None]}]}
    frozen = FrozenJSON(value=source)
    source["items"].append(2)
    source["items"][1]["deep"].append(False)
    assert frozen.value == _JSONObject(
        (
            (
                "items",
                _JSONArray((1, _JSONObject((("deep", _JSONArray((True, None))),)))),
            ),
        )
    )

    assert FrozenJSON(value=True).value is True
    assert FrozenJSON(value=3).value == 3
    assert FrozenJSON(value="").value == ""

    with pytest.raises(PContractError) as float_value:
        FrozenJSON(value=1.0)
    assert float_value.value.diagnostics[0].code == "JSON_TYPE"

    with pytest.raises(PContractError) as nested_float:
        FrozenJSON(value={"a": [1.5]})
    assert nested_float.value.diagnostics[0].code == "JSON_TYPE"

    with pytest.raises(PContractError) as non_text_key:
        FrozenJSON(value={1: "a"})  # type: ignore[dict-item]
    assert non_text_key.value.diagnostics[0].code == "KEY_TYPE"

    with pytest.raises(PContractError) as bytes_value:
        FrozenJSON(value=b"\x00")  # type: ignore[arg-type]
    assert bytes_value.value.diagnostics[0].code == "JSON_TYPE"

    with pytest.raises(PContractError) as surrogate:
        FrozenJSON(value="\ud800")
    assert surrogate.value.diagnostics[0].code == "UNICODE"

    duplicate = _DuplicateMapping((("a", 1), ("a", 2)))
    with pytest.raises(PContractError) as duplicate_key:
        FrozenJSON(value=duplicate)
    assert duplicate_key.value.diagnostics[0].code == "DUPLICATE"


class _DuplicateMapping(Mapping[str, object]):
    def __init__(self, items: tuple[tuple[str, object], ...]) -> None:
        self._items = items

    def __getitem__(self, key: str) -> object:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> typing.Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def items(self) -> typing.Iterator[tuple[str, object]]:  # type: ignore[override]
        return iter(self._items)


def test_p_nullable_fields_are_explicit() -> None:
    nullable = {
        SnapshotRef: ("version", "digest"),
        Provenance: (
            "program_ref",
            "binder_version",
            "device_snapshot",
            "calibration_snapshot",
        ),
        ExecutionPolicy: ("max_step_ns",),
    }
    for cls, names in nullable.items():
        parameters = inspect.signature(cls).parameters
        for name in names:
            assert parameters[name].default is inspect.Parameter.empty, (cls.__name__, name)

    with pytest.raises(TypeError):
        SnapshotRef(id="snap")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        Provenance(  # type: ignore[call-arg]
            kind="manual",
            basis_mapping=(),
            prior_transforms=(),
        )
    with pytest.raises(TypeError):
        ExecutionPolicy(  # type: ignore[call-arg]
            method=MethodChoice(mode="fixed", value="exact", allowed=()),
            atol=1e-10,
            rtol=0.0,
            representation="ket",
        )

    snapshot = SnapshotRef(id="snap", version=None, digest="sha256:" + "0" * 64)
    assert snapshot.version is None
    policy = ExecutionPolicy(
        method=MethodChoice(mode="fixed", value="exact", allowed=()),
        atol=1e-10,
        rtol=0.0,
        max_step_ns=None,
        representation="ket",
    )
    assert policy.max_step_ns is None

    with pytest.raises(PContractError):
        SnapshotRef(id="snap", version=None, digest=None)

    with pytest.raises(PContractError):
        Provenance(
            kind="device_bound",
            program_ref=None,
            binder_version=None,
            device_snapshot=None,
            calibration_snapshot=snapshot,
            basis_mapping=(),
            prior_transforms=(),
        )


def test_p_root_package_does_not_import_physical() -> None:
    script = "import sys, qaiji, qaiji.core; print('qaiji.core.physical' in sys.modules)"
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.stdout.strip() == "False"
