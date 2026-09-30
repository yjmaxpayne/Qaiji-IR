# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Invocation authentication contract."""

from dataclasses import FrozenInstanceError, fields, replace

import pytest

import qaiji.core.program_native as public
import qaiji.core.program_native.bridge as bridge_module
from qaiji.core.circuit import Circuit
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Measure
from qaiji.core.native import (
    NativeInputError,
    OperationSpec,
    QubitResource,
    ScheduleConfig,
    SourceLocation,
    lower_to_native,
)
from qaiji.core.program import (
    ExperimentMetadata,
    ProgramIR,
    ProgramValidationError,
    QuantumInvocation,
    ResultOutput,
    compute_kernel_ref,
)
from qaiji.core.program_native import (
    FinalBitBinding,
    InvocationEventRef,
    NativeBinding,
    OutputMeasurementBinding,
    ProgramNativeIssue,
    ProgramNativeMap,
    ProgramNativeValidationError,
    bridge_program_native,
)


def fixture(count=2, duration=3):
    circuit = Circuit(1)
    register = ClassicalRegister("c", 1)
    circuit.cregs = [register]
    circuit.gates = [Measure(0, ClassicalBit(register, 0))]
    config = ScheduleConfig(
        qubit_resources=(QubitResource(qubit=0, resource="q"),),
        operation_specs=(
            OperationSpec(
                kind="MEASURE",
                qubits=(0,),
                duration_ns=duration,
                resources=("q",),
                result_latency_ns=5,
            ),
        ),
        cz_couplings=(),
    )
    ref = compute_kernel_ref(circuit)
    program = ProgramIR(
        quantum_invocations=tuple(QuantumInvocation(ref) for _ in range(count)),
        experiment_metadata=ExperimentMetadata(7, "opaque", "opaque"),
        result_outputs=(ResultOutput(0, "c"),),
    )
    binding = NativeBinding(schedule=lower_to_native(circuit, config), config=config)
    return program, {ref: circuit}, {i: binding for i in range(count)}


def inner(report):
    return tuple(
        (i.code, i.path, i.source, i.operation_index)
        for check in (report.source, report.rules, report.hp, report.schedule)
        for i in check.issues
    )


def test_same_ref_distinct_invocations_and_configs():
    program, kernels, bindings = fixture()
    config = replace(
        bindings[0].config,
        operation_specs=(replace(bindings[0].config.operation_specs[0], duration_ns=9),),
    )
    bindings[1] = NativeBinding(
        schedule=lower_to_native(next(iter(kernels.values())), config), config=config
    )
    bridge_program_native(program, kernels, bindings)
    bindings[1] = replace(bindings[1], config=bindings[0].config)
    with pytest.raises(ProgramNativeValidationError) as caught:
        bridge_program_native(program, kernels, bindings)
    assert tuple(
        (i.invocation_index, i.code, i.input_code, i.input_path) for i in caught.value.issues
    ) == ((1, "native_invalid", None, None),)
    assert inner(caught.value.issues[0].native_report) == (
        (
            "duration_mismatch",
            "$.operations[0].duration_ns",
            SourceLocation(gate_index=0, body_offset=None),
            0,
        ),
    )


def test_old_validation_runs_first_and_propagates():
    program, _, _ = fixture()
    with pytest.raises(ProgramValidationError) as old:
        from qaiji.core.program import validate_program

        validate_program(program, {})
    error = None
    try:
        bridge_program_native(program, {}, None)
    except Exception as caught:
        error = caught
    assert type(error) is ProgramValidationError
    assert error.problems == old.value.problems


def test_old_type_error_propagates():
    from qaiji.core.program import validate_program

    program, kernels, _ = fixture()
    next(iter(kernels.values())).gates = [object()]
    with pytest.raises(TypeError) as old:
        validate_program(program, kernels)
    error = None
    try:
        bridge_program_native(program, kernels, None)
    except Exception as caught:
        error = caught
    assert type(error) is TypeError
    assert error.args == old.value.args


def test_all_invocations_including_no_output_revalidated():
    program, kernels, bindings = fixture()
    bridge_program_native(program, kernels, bindings)
    bindings[1] = replace(bindings[1], schedule=replace(bindings[1].schedule, end_ns=13))
    with pytest.raises(ProgramNativeValidationError) as caught:
        bridge_program_native(program, kernels, bindings)
    assert [(i.invocation_index, i.code, inner(i.native_report)) for i in caught.value.issues] == [
        (1, "native_invalid", (("end_time", "$.end_ns", None, None),))
    ]


def test_missing_binding_and_wrong_source():
    program, kernels, bindings = fixture()
    bindings.pop(0)
    bindings[1] = replace(
        bindings[1], schedule=replace(bindings[1].schedule, source_kernel_ref="sha256:" + "f" * 64)
    )
    with pytest.raises(ProgramNativeValidationError) as caught:
        bridge_program_native(program, kernels, bindings)
    assert [
        (i.invocation_index, i.code, i.input_code, i.input_path) for i in caught.value.issues
    ] == [(0, "binding_missing", None, None), (1, "native_invalid", None, None)]
    assert caught.value.issues[0].native_report is None
    assert inner(caught.value.issues[1].native_report) == (
        ("source_ref", "$.source_kernel_ref", None, None),
    )


def test_ordered_aggregate_without_partial_result():
    program, kernels, bindings = fixture(4)
    bindings.pop(0)
    bindings[1] = object()
    bindings[2] = replace(bindings[2], schedule=replace(bindings[2].schedule, end_ns=13))
    with pytest.raises(ProgramNativeValidationError) as caught:
        bridge_program_native(program, kernels, bindings)
    assert [
        (i.invocation_index, i.code, i.input_code, i.input_path) for i in caught.value.issues
    ] == [
        (0, "binding_missing", None, None),
        (1, "native_input", "type", "$"),
        (2, "native_invalid", None, None),
    ]
    assert caught.value.issues[1].native_report is None
    assert inner(caught.value.issues[2].native_report) == (("end_time", "$.end_ns", None, None),)


@pytest.mark.parametrize("key", [True, False, "1", 1.0])
def test_binding_keys_and_unreferenced_values(key):
    program, kernels, bindings = fixture(1)
    bindings[99] = object()
    bridge_program_native(program, kernels, bindings)
    bad = {key: bindings[0]}
    with pytest.raises(NativeInputError) as caught:
        bridge_program_native(program, kernels, bad)
    assert (caught.value.code, caught.value.path) == ("integer", "$.bindings")


def test_top_level_mapping_shape():
    program, kernels, _ = fixture(1)
    error = None
    try:
        bridge_program_native(program, kernels, [])
    except Exception as caught:
        error = caught
    assert type(error) is NativeInputError
    assert (error.code, error.path) == ("container", "$.bindings")


@pytest.mark.parametrize("both", [False, True])
def test_source_changed_after_old_validation(monkeypatch, both):
    program, kernels, bindings = fixture(1)
    original = bridge_module.validate_program

    def change(p, k):
        original(p, k)
        from qaiji.core.circuit import Gate, GateType

        circuit = next(iter(k.values()))
        circuit.gates.insert(0, Gate(GateType.Z, (0,)))
        if both:
            config = replace(
                bindings[0].config,
                operation_specs=(
                    *bindings[0].config.operation_specs,
                    OperationSpec(
                        kind="Z", qubits=(0,), duration_ns=0, resources=("q",), result_latency_ns=0
                    ),
                ),
            )
            bindings[0] = NativeBinding(schedule=lower_to_native(circuit, config), config=config)

    monkeypatch.setattr(bridge_module, "validate_program", change)
    with pytest.raises(ProgramNativeValidationError) as caught:
        bridge_program_native(program, kernels, bindings)
    (issue,) = caught.value.issues
    assert (issue.invocation_index, issue.code) == (0, "native_invalid")
    assert inner(issue.native_report) == (("source_ref", "$.source_kernel_ref", None, None),)
    assert tuple(
        getattr(issue.native_report, k).status for k in ("source", "rules", "hp", "schedule")
    ) == ("fail", "not_run", "not_run", "not_run")


@pytest.mark.parametrize("fault", ["schedule", "config", "source"])
def test_entry_rechecks_mutated_fields(monkeypatch, fault):
    program, kernels, bindings = fixture(1)
    if fault == "schedule":
        object.__setattr__(bindings[0].schedule, "end_ns", True)
        expected = ("integer", "$.schedule.end_ns")
    elif fault == "config":
        object.__setattr__(bindings[0].config, "cz_couplings", None)
        expected = ("container", "$.config.cz_couplings")
    else:
        original = bridge_module.validate_program

        def change(p, k):
            original(p, k)
            next(iter(k.values())).num_qubits = True

        monkeypatch.setattr(bridge_module, "validate_program", change)
        expected = ("source_qubit", "$.num_qubits")
    with pytest.raises(ProgramNativeValidationError) as caught:
        bridge_program_native(program, kernels, bindings)
    (issue,) = caught.value.issues
    assert (
        issue.invocation_index,
        issue.code,
        issue.native_report,
        issue.input_code,
        issue.input_path,
    ) == (0, "native_input", None, *expected)


def model_values():
    _, _, bindings = fixture(1)
    event = InvocationEventRef(invocation_index=2, event_id="m7")
    bit = FinalBitBinding(bit_index=1, event=event)
    output = OutputMeasurementBinding(
        invocation_index=2, register_name="c", history=[event], final_bits=[bit]
    )
    issue = ProgramNativeIssue(
        invocation_index=2,
        code="native_input",
        native_report=None,
        input_code="integer",
        input_path="$.x",
        message="bad input",
    )
    return [bindings[0], event, bit, output, ProgramNativeMap(outputs=[output]), issue]


@pytest.mark.parametrize("index", range(6))
def test_value_fields_copy_and_readonly(index):
    value = model_values()[index]
    assert type(value).__hash__ is None
    assert not hasattr(value, "__dict__")
    with pytest.raises(TypeError):
        hash(value)
    with pytest.raises(FrozenInstanceError):
        setattr(value, fields(value)[0].name, None)
    with pytest.raises(TypeError):
        type(value)(*(getattr(value, f.name) for f in fields(value)))

    class Extension(type(value)):
        pass

    extended = Extension(**{f.name: getattr(value, f.name) for f in fields(value)})
    from qaiji.core.native.model import _copy

    copied = _copy(extended, type(value), "$")
    assert type(copied) is type(value) and copied == value
    if index == 0:
        assert copied.schedule is not value.schedule and copied.config is not value.config
    if index == 2:
        assert copied.event is not value.event
    if index == 3:
        assert type(value.history) is type(value.final_bits) is tuple
        assert copied.history[0] is not value.history[0]
        assert copied.final_bits[0] is not value.final_bits[0]
    if index == 4:
        assert type(value.outputs) is tuple and copied.outputs[0] is not value.outputs[0]


class IntSubclass(int):
    pass


class StrSubclass(str):
    pass


@pytest.mark.parametrize(
    "cls,field,bad,code",
    [
        (NativeBinding, "schedule", None, "type"),
        (NativeBinding, "config", None, "type"),
        (InvocationEventRef, "invocation_index", True, "integer"),
        (InvocationEventRef, "invocation_index", IntSubclass(1), "integer"),
        (InvocationEventRef, "invocation_index", -1, "range"),
        (InvocationEventRef, "event_id", StrSubclass("m1"), "type"),
        (InvocationEventRef, "event_id", "", "text"),
        (FinalBitBinding, "bit_index", True, "integer"),
        (FinalBitBinding, "bit_index", -1, "range"),
        (FinalBitBinding, "event", None, "type"),
        (OutputMeasurementBinding, "invocation_index", True, "integer"),
        (OutputMeasurementBinding, "register_name", "bad name", "identifier"),
        (OutputMeasurementBinding, "register_name", StrSubclass("c"), "type"),
        (OutputMeasurementBinding, "history", {}, "container"),
        (OutputMeasurementBinding, "history", [None], "type"),
        (OutputMeasurementBinding, "final_bits", None, "container"),
        (OutputMeasurementBinding, "final_bits", [None], "type"),
        (ProgramNativeMap, "outputs", None, "container"),
        (ProgramNativeMap, "outputs", [None], "type"),
        (ProgramNativeIssue, "invocation_index", True, "integer"),
        (ProgramNativeIssue, "code", "", "text"),
        (ProgramNativeIssue, "code", StrSubclass("native_input"), "type"),
        (ProgramNativeIssue, "native_report", object(), "type"),
        (ProgramNativeIssue, "input_code", "", "text"),
        (ProgramNativeIssue, "input_path", True, "type"),
        (ProgramNativeIssue, "message", "", "text"),
    ],
)
def test_value_field_shape(cls, field, bad, code):
    value = next(v for v in model_values() if type(v) is cls)
    path = "$." + field + ("[0]" if type(bad) is list else "")
    with pytest.raises(NativeInputError) as caught:
        replace(value, **{field: bad})
    assert (caught.value.code, caught.value.path) == (code, path)


def test_public_exports_and_signatures():
    import inspect

    assert set(public.__all__) == {
        "NativeBinding",
        "InvocationEventRef",
        "FinalBitBinding",
        "OutputMeasurementBinding",
        "ProgramNativeMap",
        "ProgramNativeIssue",
        "ProgramNativeValidationError",
        "bridge_program_native",
    }
    assert tuple(inspect.signature(bridge_program_native).parameters) == (
        "program",
        "kernels",
        "bindings",
    )
    program, kernels, bindings = fixture(1)
    for keyword in ("report", "passed", "checked", "token"):
        with pytest.raises(TypeError):
            bridge_program_native(program, kernels, bindings, **{keyword: True})


def test_exception_copies_issue_objects():
    issue = model_values()[-1]

    class ExtendedIssue(ProgramNativeIssue):
        pass

    extended = ExtendedIssue(**{field.name: getattr(issue, field.name) for field in fields(issue)})
    inputs = [extended]
    error = ProgramNativeValidationError(inputs)
    inputs.clear()
    assert len(error.issues) == 1
    assert type(error.issues[0]) is ProgramNativeIssue
    assert error.issues[0] is not extended
    assert error.issues == (issue,)
    assert (
        error.issues[0].invocation_index,
        error.issues[0].code,
        error.issues[0].native_report,
        error.issues[0].input_code,
        error.issues[0].input_path,
        error.issues[0].message,
    ) == (2, "native_input", None, "integer", "$.x", "bad input")


def test_kernel_container_shape_after_legacy_validation():
    program, kernels, bindings = fixture(1)

    class Lookup:
        def __contains__(self, key):
            return key in kernels

        def __getitem__(self, key):
            return kernels[key]

    with pytest.raises(NativeInputError) as caught:
        bridge_program_native(program, Lookup(), bindings)
    assert (caught.value.code, caught.value.path) == ("container", "$.kernels")


@pytest.mark.parametrize("error_type", [RuntimeError, MemoryError, KeyboardInterrupt, SystemExit])
def test_internal_failures_are_not_wrapped(monkeypatch, error_type):
    program, kernels, bindings = fixture(1)
    failure = error_type("injected failure")

    def broken(*args):
        raise failure

    monkeypatch.setattr(bridge_module, "_validate_snapshot", broken)
    error = None
    try:
        bridge_program_native(program, kernels, bindings)
    except BaseException as caught:
        error = caught
    assert error is failure


def test_issue_report_and_nullable_fields_copy():
    from qaiji.core.native import validate_native_schedule

    program, kernels, bindings = fixture(1)
    report = validate_native_schedule(
        next(iter(kernels.values())), bindings[0].schedule, bindings[0].config
    )
    issue = ProgramNativeIssue(
        invocation_index=0,
        code="native_invalid",
        native_report=report,
        input_code=None,
        input_path=None,
        message="report",
    )
    assert issue.native_report == report and issue.native_report is not report
    assert issue.input_code is None and issue.input_path is None
    assert (issue.invocation_index, issue.code, issue.message) == (0, "native_invalid", "report")
    # Carrier shape does not constitute a trusted authentication token.
    with pytest.raises(TypeError):
        bridge_program_native(program, kernels, bindings, report=report)


@pytest.mark.parametrize("value", [-1, 10**4096])
@pytest.mark.parametrize(
    "index,field",
    [(1, "invocation_index"), (2, "bit_index"), (3, "invocation_index"), (5, "invocation_index")],
)
def test_integer_ranges_on_each_carrier(index, field, value):
    with pytest.raises(NativeInputError) as caught:
        replace(model_values()[index], **{field: value})
    assert (caught.value.code, caught.value.path) == ("range", "$." + field)


def test_list_inputs_detached_and_base_fields_preserved():
    event = InvocationEventRef(invocation_index=4, event_id="m8")
    final = FinalBitBinding(bit_index=3, event=event)
    history = [event]
    bits = [final]
    output = OutputMeasurementBinding(
        invocation_index=4, register_name="other", history=history, final_bits=bits
    )
    outputs = [output]
    mapped = ProgramNativeMap(outputs=outputs)
    history.clear()
    bits.clear()
    outputs.clear()
    assert mapped.outputs == (output,)
    actual = mapped.outputs[0]
    assert (actual.invocation_index, actual.register_name) == (4, "other")
    assert [(e.invocation_index, e.event_id) for e in actual.history] == [(4, "m8")]
    assert [
        (b.bit_index, b.event.invocation_index, b.event.event_id) for b in actual.final_bits
    ] == [(3, 4, "m8")]
    assert actual.history[0] is not event and actual.final_bits[0] is not final


@pytest.mark.parametrize(
    "index,field,sequence",
    [
        (0, "schedule", False),
        (0, "config", False),
        (2, "event", False),
        (3, "history", True),
        (3, "final_bits", True),
        (4, "outputs", True),
        (5, "native_report", False),
    ],
)
def test_nested_constructor_normalizes_subclasses(index, field, sequence):
    value = model_values()[index]
    if field == "native_report":
        from qaiji.core.native import validate_native_schedule

        _, kernels, bindings = fixture(1)
        nested = validate_native_schedule(
            next(iter(kernels.values())), bindings[0].schedule, bindings[0].config
        )
    else:
        nested = getattr(value, field)
        if sequence:
            nested = nested[0]

    class Extension(type(nested)):
        pass

    extended = Extension(**{f.name: getattr(nested, f.name) for f in fields(nested)})
    converted = replace(value, **{field: [extended] if sequence else extended})
    actual = getattr(converted, field)
    if sequence:
        actual = actual[0]
    assert type(actual) is type(nested)
    assert actual == nested and actual is not extended
