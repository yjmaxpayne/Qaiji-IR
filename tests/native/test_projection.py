# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Neutral projections authenticate all inputs and preserve every base field."""

import inspect
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from qaiji.core.circuit import Gate, GateType
from qaiji.core.native import NativeInputError, NativeValidationError
from qaiji.core.native.config import OperationSpec
from qaiji.core.native.model import NativeOperation
from qaiji.core.native.projection import (
    NativeProjection,
    ProjectedOperation,
    _labels,
    qubic_mapping,
)
from qaiji.core.native.rules import _expand_source
from qaiji.core.native.scheduler import _schedule_source
from qaiji.core.native.source import _capture_source

from .test_diagnostics import fixture, issues, measurement_fixture


def test_exact_kind_labels_and_full_fields():
    circuit, _, config = fixture(())
    circuit.gates = [
        Gate(GateType.I, (0,)),
        Gate(GateType.Z, (0,)),
        Gate(GateType.RZ, (0,), (-0.0,)),
        Gate(GateType.RX90, (0,), (0.3,)),
        Gate(GateType.CZ, (1, 0)),
    ]
    config = replace(
        config,
        operation_specs=(
            *config.operation_specs,
            OperationSpec(
                kind="CZ",
                qubits=(1, 0),
                duration_ns=7,
                resources=("q1", "q0", "coupler"),
                result_latency_ns=0,
            ),
        ),
    )
    snap = _capture_source(circuit)
    good = _schedule_source(snap, config, _expand_source(snap))
    projection = qubic_mapping(circuit, good, config)
    assert isinstance(projection, NativeProjection)
    assert tuple(op.labels for op in projection.operations) == (
        ("IDLE",),
        ("VIRTUAL_PHASE",),
        ("VIRTUAL_PHASE",),
        ("PULSE",),
        ("PULSE",),
    )
    assert projection.source_kernel_ref == good.source_kernel_ref
    assert projection.end_ns == projection.all_results_ready_ns == 10
    assert projection.conditions == projection.events == ()
    for i, projected in enumerate(projection.operations):
        assert projected.operation_index == i
        assert projected.operation == good.operations[i]
        assert projected.operation is not good.operations[i]
        assert projected.event_id is projected.result_ready_ns is None
    assert projection.operations[2].operation.params[0].hex() == "-0x0.0p+0"
    assert projection.operations[4].operation.qubits == (1, 0)
    assert projection.operations[4].operation.resources == ("q1", "q0", "coupler")


def test_measure_has_one_record_two_labels():
    circuit, good, config = measurement_fixture(True)
    projection = qubic_mapping(circuit, good, config)
    assert isinstance(projection, NativeProjection)
    assert len(projection.operations) == 2
    assert projection.operations[0].labels == ("PULSE_READOUT", "REGISTER_RESULT")
    assert (projection.operations[0].event_id, projection.operations[0].result_ready_ns) == (
        "m0",
        8,
    )
    assert projection.operations[0].operation == good.operations[0]
    assert projection.operations[1].operation.condition_id == "c1"
    assert projection.conditions == good.conditions
    assert projection.events == good.events
    assert (projection.end_ns, projection.all_results_ready_ns) == (8, 8)


@pytest.mark.parametrize("fault", ["source", "schedule", "config"])
def test_reauthenticate_source_schedule_config(fault):
    circuit, good, config = measurement_fixture() if fault == "config" else fixture()
    assert isinstance(qubic_mapping(circuit, good, config), NativeProjection)
    if fault == "source":
        circuit.gates[0] = Gate(GateType.RZ, (0,), (0.2,))
        expected = ("source_ref", "$.source_kernel_ref", None, None)
    elif fault == "schedule":
        good = replace(good, end_ns=1)
        expected = ("end_time", "$.end_ns", None, None)
    else:
        config = replace(
            config,
            operation_specs=tuple(
                replace(spec, duration_ns=4) if spec.kind == "MEASURE" else spec
                for spec in config.operation_specs
            ),
        )
        expected = (
            "duration_mismatch",
            "$.operations[0].duration_ns",
            good.operations[0].source,
            0,
        )
    with pytest.raises(NativeValidationError) as caught:
        qubic_mapping(circuit, good, config)
    assert issues(caught.value.report) == (expected,)


@pytest.mark.parametrize("extra", ["report", "passed", "checked", "token"])
def test_no_external_report_or_token(extra):
    circuit, good, config = fixture()
    assert tuple(inspect.signature(qubic_mapping).parameters) == ("circuit", "schedule", "config")
    with pytest.raises(TypeError):
        qubic_mapping(circuit, good, config, **{extra: True})


@pytest.mark.parametrize("layer", ["internal", "public"])
def test_unknown_kind_has_no_default(layer):
    if layer == "internal":
        with pytest.raises(NativeInputError) as caught:
            _labels("FUTURE")
        assert (caught.value.code, caught.value.path) == ("enum", "$.kind")
    else:
        circuit, good, config = fixture()
        object.__setattr__(good.operations[0], "kind", "FUTURE")
        with pytest.raises(NativeInputError) as caught:
            qubic_mapping(circuit, good, config)
        assert (caught.value.code, caught.value.path) == ("enum", "$.operations[0].kind")


def projected_value():
    _, good, _ = fixture()
    return ProjectedOperation(
        operation_index=0,
        operation=good.operations[0],
        labels=("VIRTUAL_PHASE",),
        event_id=None,
        result_ready_ns=None,
    )


def projection_value():
    return NativeProjection(
        source_kernel_ref="sha256:" + "0" * 64,
        operations=(projected_value(),),
        conditions=(),
        events=(),
        end_ns=0,
        all_results_ready_ns=0,
    )


@pytest.mark.parametrize(
    "factory,names",
    [
        (
            projected_value,
            ("operation_index", "operation", "labels", "event_id", "result_ready_ns"),
        ),
        (
            projection_value,
            (
                "source_kernel_ref",
                "operations",
                "conditions",
                "events",
                "end_ns",
                "all_results_ready_ns",
            ),
        ),
    ],
)
def test_projection_value_contract(factory, names):
    value = factory()
    assert tuple(field.name for field in fields(value)) == names
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(value, names[0], None)
    with pytest.raises(TypeError):
        hash(value)
    with pytest.raises(TypeError):
        type(value)(*(getattr(value, name) for name in names))


@pytest.mark.parametrize(
    "factory,field,bad,code,path",
    [
        (projected_value, "operation_index", True, "integer", "$.operation_index"),
        (projected_value, "operation", None, "type", "$.operation"),
        (projected_value, "labels", [True], "type", "$.labels[0]"),
        (projected_value, "event_id", 1, "type", "$.event_id"),
        (projected_value, "result_ready_ns", -1, "range", "$.result_ready_ns"),
        (projection_value, "source_kernel_ref", 1, "type", "$.source_kernel_ref"),
        (projection_value, "operations", [None], "type", "$.operations[0]"),
        (projection_value, "conditions", [None], "type", "$.conditions[0]"),
        (projection_value, "events", [None], "type", "$.events[0]"),
        (projection_value, "end_ns", True, "integer", "$.end_ns"),
        (projection_value, "all_results_ready_ns", None, "integer", "$.all_results_ready_ns"),
    ],
)
def test_projection_value_field_validation(factory, field, bad, code, path):
    with pytest.raises(NativeInputError) as caught:
        replace(factory(), **{field: bad})
    assert (caught.value.code, caught.value.path) == (code, path)


def test_projection_copies_subclasses_and_lists():
    class ExtendedOperation(NativeOperation):
        pass

    class ExtendedProjected(ProjectedOperation):
        pass

    original = projected_value()
    extended = ExtendedOperation(
        **{f.name: getattr(original.operation, f.name) for f in fields(NativeOperation)}
    )
    labels = ["VIRTUAL_PHASE"]
    item = ExtendedProjected(
        operation_index=0, operation=extended, labels=labels, event_id="m0", result_ready_ns=0
    )
    operations = [item]
    projection = NativeProjection(
        source_kernel_ref="sha256:" + "0" * 64,
        operations=operations,
        conditions=[],
        events=[],
        end_ns=0,
        all_results_ready_ns=0,
    )
    labels.clear()
    operations.clear()
    assert type(projection.operations) is tuple and len(projection.operations) == 1
    assert type(projection.operations[0]) is ProjectedOperation
    assert type(projection.operations[0].operation) is NativeOperation
    assert projection.operations[0].labels == ("VIRTUAL_PHASE",)
    assert (projection.operations[0].event_id, projection.operations[0].result_ready_ns) == (
        "m0",
        0,
    )


@pytest.mark.parametrize("field", ["operation_index", "result_ready_ns", "event_id", "labels"])
def test_projection_rejects_scalar_subclasses(field):
    class MyInt(int):
        pass

    class MyStr(str):
        pass

    value = MyInt(0) if field in ("operation_index", "result_ready_ns") else MyStr("m0")
    if field == "labels":
        value = [MyStr("PULSE")]
    with pytest.raises(NativeInputError) as caught:
        replace(projected_value(), **{field: value})
    assert caught.value.path == "$." + field + ("[0]" if field == "labels" else "")


@pytest.mark.parametrize(
    "ref",
    [
        "x",
        "sha256:" + "0" * 63,
        "sha256:" + "A" * 64,
        "sha256:" + "g" * 64,
        "sha256:" + "0" * 64 + "\n",
    ],
)
def test_projection_reference_format(ref):
    with pytest.raises(NativeInputError) as caught:
        replace(projection_value(), source_kernel_ref=ref)
    assert (caught.value.code, caught.value.path) == ("ref", "$.source_kernel_ref")


@pytest.mark.parametrize("field", ["event_id", "result_ready_ns"])
def test_projection_nullable_field_boundaries(field):
    assert getattr(replace(projected_value(), **{field: None}), field) is None
    with pytest.raises(NativeInputError) as caught:
        replace(projected_value(), **{field: True})
    assert caught.value.path == "$." + field


@pytest.mark.parametrize("field", ["source_kernel_ref", "end_ns", "all_results_ready_ns"])
def test_projection_header_scalar_subclasses(field):
    class MyInt(int):
        pass

    class MyStr(str):
        pass

    bad = MyStr("sha256:" + "0" * 64) if field == "source_kernel_ref" else MyInt(0)
    with pytest.raises(NativeInputError) as caught:
        replace(projection_value(), **{field: bad})
    assert caught.value.path == "$." + field


def test_projection_nested_values_are_detached():
    from qaiji.core.native.model import ConditionRegion, MeasurementEvent

    class ExtendedCondition(ConditionRegion):
        pass

    class ExtendedEvent(MeasurementEvent):
        pass

    _, good, _ = measurement_fixture(True)
    condition = ExtendedCondition(
        **{f.name: getattr(good.conditions[0], f.name) for f in fields(ConditionRegion)}
    )
    event = ExtendedEvent(
        **{f.name: getattr(good.events[0], f.name) for f in fields(MeasurementEvent)}
    )
    conditions, events = [condition], [event]
    projection = replace(projection_value(), conditions=conditions, events=events)
    conditions.clear()
    events.clear()
    object.__setattr__(condition, "value", 0)
    object.__setattr__(event, "ready_ns", 99)
    assert type(projection.conditions[0]) is ConditionRegion
    assert type(projection.events[0]) is MeasurementEvent
    assert projection.conditions == good.conditions
    assert projection.events == good.events


def test_empty_projection():
    circuit, good, config = fixture(())
    projection = qubic_mapping(circuit, good, config)
    assert projection == NativeProjection(
        source_kernel_ref=good.source_kernel_ref,
        operations=(),
        conditions=(),
        events=(),
        end_ns=0,
        all_results_ready_ns=0,
    )


@pytest.mark.parametrize(
    "error", [RuntimeError, AssertionError, MemoryError, KeyboardInterrupt, SystemExit]
)
def test_projection_internal_errors_escape(error, monkeypatch):
    circuit, good, config = fixture()
    marker = error("internal sentinel")

    def fail(*args):
        raise marker

    monkeypatch.setattr("qaiji.core.native.validation._check_local_matrix", fail)
    with pytest.raises(error) as caught:
        qubic_mapping(circuit, good, config)
    assert caught.value is marker


@pytest.mark.parametrize(
    "factory,field",
    [
        (projected_value, "operation_index"),
        (projected_value, "result_ready_ns"),
        (projection_value, "end_ns"),
        (projection_value, "all_results_ready_ns"),
    ],
)
@pytest.mark.parametrize("boundary", ["negative", "zero", "max", "overflow"])
def test_projection_integer_boundaries(factory, field, boundary):
    value = {"negative": -1, "zero": 0, "max": 10**4096 - 1, "overflow": 10**4096}[boundary]
    if boundary in ("zero", "max"):
        assert getattr(replace(factory(), **{field: value}), field) == value
    else:
        with pytest.raises(NativeInputError) as caught:
            replace(factory(), **{field: value})
        assert (caught.value.code, caught.value.path) == ("range", "$." + field)


@pytest.mark.parametrize("container", ["set", "generator", "string", "empty_text"])
def test_projection_labels_container_and_text(container):
    labels = {
        "set": {"PULSE"},
        "generator": (label for label in ("PULSE",)),
        "string": "PULSE",
        "empty_text": [""],
    }[container]
    with pytest.raises(NativeInputError) as caught:
        replace(projected_value(), labels=labels)
    expected = ("text", "$.labels[0]") if container == "empty_text" else ("container", "$.labels")
    assert (caught.value.code, caught.value.path) == expected


def test_projection_end_and_readiness_are_distinct():
    """Measurement execution ends before its classical result becomes ready."""
    from qaiji.core.native.model import MeasurementEvent, SourceLocation

    circuit, good, config = measurement_fixture(False)
    projection = qubic_mapping(circuit, good, config)
    source = SourceLocation(gate_index=0, body_offset=None)
    expected_operation = NativeOperation(
        kind="MEASURE",
        qubits=(0,),
        params=(),
        source=source,
        ordinal=0,
        start_ns=0,
        duration_ns=3,
        resources=("q0",),
        condition_id=None,
    )
    assert projection == NativeProjection(
        source_kernel_ref=good.source_kernel_ref,
        operations=(
            ProjectedOperation(
                operation_index=0,
                operation=expected_operation,
                labels=("PULSE_READOUT", "REGISTER_RESULT"),
                event_id="m0",
                result_ready_ns=8,
            ),
        ),
        conditions=(),
        events=(
            MeasurementEvent(
                event_id="m0",
                source=source,
                operation_index=0,
                qubit=0,
                register_name="c",
                bit_index=0,
                end_ns=3,
                ready_ns=8,
            ),
        ),
        end_ns=3,
        all_results_ready_ns=8,
    )
