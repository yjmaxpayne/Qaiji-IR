# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Public staged reports retain independent results and stable issue order."""

from dataclasses import replace

import pytest

from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.native import NativeInputError
from qaiji.core.native.api import lower_to_native
from qaiji.core.native.config import OperationSpec, QubitResource, ScheduleConfig
from qaiji.core.native.diagnostics import NativeValidationError
from qaiji.core.native.model import RegisterDecl, SourceLocation
from qaiji.core.native.rules import _expand_source
from qaiji.core.native.scheduler import _schedule_source
from qaiji.core.native.source import _capture_source
from qaiji.core.native.validation import validate_native_schedule


def fixture(kinds=("RZ",), params=(-0.0,)):
    circuit = Circuit(2)
    circuit.gates = [Gate(GateType(kind), (0,), params if kind == "RZ" else ()) for kind in kinds]
    config = ScheduleConfig(
        qubit_resources=(
            QubitResource(qubit=0, resource="q0"),
            QubitResource(qubit=1, resource="q1"),
        ),
        operation_specs=tuple(
            OperationSpec(
                kind=kind,
                qubits=(q,),
                duration_ns=0 if kind in ("I", "RZ", "Z") else 3,
                resources=(f"q{q}",),
                result_latency_ns=5 if kind == "MEASURE" else 0,
            )
            for q in range(2)
            for kind in ("I", "Z", "RZ", "RX90", "MEASURE")
        ),
        cz_couplings=((0, 1),),
    )
    snapshot = _capture_source(circuit)
    return circuit, _schedule_source(snapshot, config, _expand_source(snapshot)), config


def issues(report):
    return tuple(
        (i.code, i.path, i.source, i.operation_index) for i in NativeValidationError(report).issues
    )


def test_independent_rule_hp_schedule_outcomes():
    circuit, good, config = fixture()
    bad = replace(good, operations=(replace(good.operations[0], params=(0.0,)),))
    try:
        report = validate_native_schedule(circuit, bad, config)
    except NativeInputError as error:
        raise AssertionError(
            "Structurally valid candidate must return a semantic report"
        ) from error
    assert (
        report.source.status,
        report.rules.status,
        report.hp.status,
        report.schedule.status,
    ) == ("pass", "fail", "pass", "pass")
    assert issues(report) == (
        ("rule_instance", "$.operations[0]", SourceLocation(gate_index=0, body_offset=None), 0),
    )
    assert not report.valid and report.all_results_ready_ns is None
    assert validate_native_schedule(circuit, good, config).valid


def measurement_fixture(conditional=False):
    circuit, _, config = fixture(())
    register = ClassicalRegister("c", 1)
    circuit.cregs = [register]
    circuit.gates = [Measure(0, ClassicalBit(register, 0))]
    if conditional:
        circuit.gates.append(Conditional(register, 1, (Gate(GateType.Z, (0,)),)))
    snapshot = _capture_source(circuit)
    return circuit, _schedule_source(snapshot, config, _expand_source(snapshot)), config


@pytest.mark.parametrize("shape", ["empty", "measure", "mixed", "negative_zero"])
def test_report_field_and_status_contract(shape):
    if shape in ("measure", "mixed"):
        circuit, good, config = measurement_fixture(shape == "mixed")
    else:
        circuit, good, config = fixture(()) if shape == "empty" else fixture()
    result = lower_to_native(circuit, config)
    assert result == good
    report = validate_native_schedule(circuit, result, config)
    assert report.valid and issues(report) == ()
    assert report.all_results_ready_ns == (8 if shape in ("measure", "mixed") else 0)
    assert (report.source.status, report.schedule.status) == ("pass", "pass")
    assert report.rules.status == ("not_applicable" if shape == "empty" else "pass")
    assert report.hp.status == ("not_applicable" if shape in ("empty", "measure") else "pass")
    if shape in ("measure", "mixed"):
        assert report.groups[0].hp.status == "not_applicable"
        assert report.groups[0].expected_phase_rad is None
        assert report.groups[0].max_abs_residual is None


@pytest.mark.parametrize("fault", ["ref", "width", "registers", "groups", "conditions"])
def test_source_failure_gates_later_stages(fault, monkeypatch):
    circuit, good, config = measurement_fixture(True)
    if fault == "ref":
        bad = replace(good, source_kernel_ref="sha256:" + "0" * 64, num_qubits=3)
        expected = ("source_ref", "$.source_kernel_ref", None, None)
    elif fault == "width":
        bad = replace(
            good, num_qubits=3, registers=(*good.registers, RegisterDecl(name="d", size=1))
        )
        expected = ("source_header", "$.num_qubits", None, None)
    elif fault == "registers":
        bad = replace(good, registers=(*good.registers, RegisterDecl(name="d", size=1)))
        expected = ("source_header", "$.registers", None, None)
    elif fault == "groups":
        loc = SourceLocation(gate_index=8, body_offset=None)
        bad = replace(
            good,
            groups=(replace(good.groups[0], source=loc), *good.groups[1:]),
            operations=(replace(good.operations[0], source=loc), *good.operations[1:]),
            events=(replace(good.events[0], source=loc),),
            conditions=(replace(good.conditions[0], value=0),),
        )
        expected = (
            "source_groups",
            "$.groups[0].source",
            SourceLocation(gate_index=0, body_offset=None),
            0,
        )
    else:
        bad = replace(good, conditions=(replace(good.conditions[0], value=0),))
        expected = (
            "source_conditions",
            "$.conditions[0].value",
            SourceLocation(gate_index=1, body_offset=None),
            1,
        )

    def forbidden(*args):
        raise AssertionError("V1 failure must gate later checks")

    for name in ("_recognize_group", "_check_local_matrix", "_check_timing"):
        monkeypatch.setattr("qaiji.core.native.validation." + name, forbidden)
    report = validate_native_schedule(circuit, bad, config)
    assert issues(report) == (expected,)
    assert (report.rules.status, report.hp.status, report.schedule.status) == ("not_run",) * 3
    assert report.groups == () and report.all_results_ready_ns is None and not report.valid


@pytest.mark.parametrize("fault", ["phase", "id", "matrix", "domain", "missing_event"])
def test_independent_rule_hp_schedule_outcomes_more(fault):
    circuit, good, config = fixture(params=(0.2,))
    loc = SourceLocation(gate_index=0, body_offset=None)
    if fault == "phase":
        bad = replace(good, groups=(replace(good.groups[0], phase_rad=0.1),))
        expected = (("rule_phase", "$.groups[0].phase_rad", loc, None),)
        hp = "pass"
    elif fault == "id":
        bad = replace(good, groups=(replace(good.groups[0], rule_id="bad", phase_rad=0.1),))
        expected = (("rule_id", "$.groups[0].rule_id", loc, None),)
        hp = "pass"
    elif fault in ("matrix", "domain"):
        op = (
            replace(good.operations[0], params=(0.6,))
            if fault == "matrix"
            else replace(good.operations[0], qubits=(1,), resources=("q1",))
        )
        bad = replace(good, operations=(op,))
        expected = (
            ("rule_instance", "$.operations[0]", loc, 0),
            (
                "operator_mismatch" if fault == "matrix" else "operand_domain",
                "$.groups[0]",
                loc,
                None,
            ),
        )
        hp = "fail"
    else:
        circuit, good, config = measurement_fixture()
        bad = replace(
            good,
            operations=(replace(good.operations[0], kind="Z", duration_ns=0),),
            events=(),
            end_ns=0,
        )
        expected = (
            ("rule_instance", "$.operations[0]", loc, 0),
            ("measurement_events", "$.events", loc, 0),
        )
        hp = "not_applicable"
    report = validate_native_schedule(circuit, bad, config)
    assert issues(report) == expected
    assert (report.rules.status, report.hp.status, report.schedule.status) == (
        "fail",
        hp,
        "fail" if fault == "missing_event" else "pass",
    )
    assert report.all_results_ready_ns is None
    if fault == "matrix":
        assert report.groups[0].max_abs_residual > 0.1
        assert report.groups[0].expected_phase_rad == 0.0
    if fault in ("domain", "missing_event"):
        assert report.groups[0].max_abs_residual is None
        assert report.groups[0].expected_phase_rad is None


def test_ordered_multi_group_issues():
    circuit, good, config = fixture(("RZ", "RZ"), (0.2,))
    bad = replace(
        good,
        groups=(
            replace(good.groups[0], rule_id="bad", phase_rad=0.9),
            replace(good.groups[1], phase_rad=0.9),
        ),
        operations=(
            replace(good.operations[0], params=(0.8,)),
            replace(good.operations[1], params=(0.8,)),
        ),
        end_ns=1,
    )
    report = validate_native_schedule(circuit, bad, config)
    a, b = (SourceLocation(gate_index=i, body_offset=None) for i in (0, 1))
    assert issues(report) == (
        ("rule_id", "$.groups[0].rule_id", a, None),
        ("rule_instance", "$.operations[1]", b, 1),
        ("operator_mismatch", "$.groups[0]", a, None),
        ("operator_mismatch", "$.groups[1]", b, None),
        ("end_time", "$.end_ns", None, None),
    )
    assert (report.rules.status, report.hp.status, report.schedule.status) == (
        "fail",
        "fail",
        "fail",
    )
    assert tuple(i for g in report.groups for i in g.rule.issues) == report.rules.issues
    assert tuple(i for g in report.groups for i in g.hp.issues) == report.hp.issues


@pytest.mark.parametrize("fault", ["config", "coupling", "unwritten"])
def test_pre_generation_failure_report(fault):
    circuit, _, config = fixture()
    if fault == "config":
        config = replace(config, operation_specs=())
        expected = (
            "config_missing",
            "$.operations[0]",
            SourceLocation(gate_index=0, body_offset=None),
            0,
        )
    elif fault == "coupling":
        circuit.gates = [Gate(GateType.CZ, (0, 1))]
        config = replace(
            config,
            cz_couplings=(),
            operation_specs=(
                *config.operation_specs,
                OperationSpec(
                    kind="CZ",
                    qubits=(0, 1),
                    duration_ns=7,
                    resources=("q0", "q1"),
                    result_latency_ns=0,
                ),
            ),
        )
        expected = (
            "coupling_missing",
            "$.operations[0].qubits",
            SourceLocation(gate_index=0, body_offset=None),
            0,
        )
    else:
        reg = ClassicalRegister("c", 1)
        circuit.cregs = [reg]
        circuit.gates = [Conditional(reg, 0, ())]
        expected = (
            "condition_binding",
            "$.conditions[0].reads[0].event_id",
            SourceLocation(gate_index=0, body_offset=None),
            None,
        )
    with pytest.raises(NativeValidationError) as caught:
        lower_to_native(circuit, config)
    report = caught.value.report
    assert issues(report) == (expected,)
    assert (
        report.source.status,
        report.rules.status,
        report.hp.status,
        report.schedule.status,
    ) == ("pass", "not_run", "not_run", "fail")
    assert report.groups == () and report.all_results_ready_ns is None


@pytest.mark.parametrize("fault", ["schedule", "config", "source"])
def test_exception_boundaries_and_internal_bug_propagation(fault):
    circuit, good, config = fixture()
    if fault == "schedule":
        object.__setattr__(good.operations[0], "ordinal", True)
        expected = ("integer", "$.operations[0].ordinal")
    elif fault == "config":
        object.__setattr__(config.operation_specs[0], "duration_ns", True)
        expected = ("integer", "$.operation_specs[0].duration_ns")
    else:
        circuit.num_qubits = True
        expected = ("source_qubit", "$.num_qubits")
    with pytest.raises(NativeInputError) as caught:
        validate_native_schedule(circuit, good, config)
    assert (caught.value.code, caught.value.path) == expected


@pytest.mark.parametrize(
    "error", [RuntimeError, AssertionError, MemoryError, KeyboardInterrupt, SystemExit]
)
@pytest.mark.parametrize("entry", ["validate", "lower"])
def test_internal_errors_escape(error, entry, monkeypatch):
    circuit, good, config = fixture()
    marker = error("internal sentinel")

    def fail(*args):
        raise marker

    target = (
        "qaiji.core.native.validation._check_local_matrix"
        if entry == "validate"
        else "qaiji.core.native.api._schedule_source"
    )
    monkeypatch.setattr(target, fail)
    with pytest.raises(error) as caught:
        validate_native_schedule(circuit, good, config) if entry == "validate" else lower_to_native(
            circuit, config
        )
    assert caught.value is marker


@pytest.mark.parametrize("entry", ["validate", "lower", "projection"])
def test_single_snapshot_and_fresh_capture(entry, monkeypatch):
    import qaiji.core.native.api as api
    import qaiji.core.native.projection as projection
    import qaiji.core.native.validation as validation

    module = {"validate": validation, "lower": api, "projection": projection}[entry]
    circuit, good, config = fixture()
    calls = []
    original = module._capture_source

    def capture(value):
        snapshot = original(value)
        calls.append(snapshot)
        circuit.gates[0] = Gate(GateType.RZ, (0,), (0.2,))
        return snapshot

    monkeypatch.setattr(module, "_capture_source", capture)
    if entry == "validate":
        assert validation.validate_native_schedule(circuit, good, config).valid
    elif entry == "lower":
        assert api.lower_to_native(circuit, config) == good
    else:
        assert (
            projection.qubic_mapping(circuit, good, config).operations[0].operation
            == good.operations[0]
        )
    assert len(calls) == 1
    if entry == "validate":
        report = validation.validate_native_schedule(circuit, good, config)
        assert issues(report) == (("source_ref", "$.source_kernel_ref", None, None),)
    elif entry == "lower":
        result = api.lower_to_native(circuit, config)
        assert result.operations[0].params == (0.2,)
        assert result.source_kernel_ref != good.source_kernel_ref
    else:
        with pytest.raises(NativeValidationError) as caught:
            projection.qubic_mapping(circuit, good, config)
        assert issues(caught.value.report) == (("source_ref", "$.source_kernel_ref", None, None),)
    assert len(calls) == 2


@pytest.mark.parametrize("entry", ["validate", "lower", "projection"])
@pytest.mark.parametrize("fault", ["config", "source"])
def test_all_public_entries_recheck_input(entry, fault):
    from qaiji.core.native import qubic_mapping

    circuit, good, config = fixture()
    if fault == "config":
        object.__setattr__(config.operation_specs[0], "duration_ns", True)
        expected = ("integer", "$.operation_specs[0].duration_ns")
    else:
        circuit.num_qubits = True
        expected = ("source_qubit", "$.num_qubits")
    with pytest.raises(NativeInputError) as caught:
        if entry == "lower":
            lower_to_native(circuit, config)
        elif entry == "validate":
            validate_native_schedule(circuit, good, config)
        else:
            qubic_mapping(circuit, good, config)
    assert (caught.value.code, caught.value.path) == expected


def test_lower_authenticates_generated_candidate(monkeypatch):
    circuit, good, config = fixture()
    monkeypatch.setattr(
        "qaiji.core.native.api._schedule_source", lambda *args: replace(good, end_ns=1)
    )
    with pytest.raises(NativeValidationError) as caught:
        lower_to_native(circuit, config)
    assert issues(caught.value.report) == (("end_time", "$.end_ns", None, None),)


@pytest.mark.parametrize("entry", ["lower", "validate", "projection"])
def test_intermediate_overflow_stays_input_error(entry):
    from qaiji.core.native import qubic_mapping
    from qaiji.core.native.model import _LIMIT

    circuit, _, config = fixture(())
    circuit.gates = [Gate(GateType.RX90, (0,), (0.0,)), Gate(GateType.RX90, (0,), (0.0,))]
    snapshot = _capture_source(circuit)
    good = _schedule_source(snapshot, config, _expand_source(snapshot))
    huge_specs = tuple(
        replace(spec, duration_ns=_LIMIT - 1) if spec.kind == "RX90" else spec
        for spec in config.operation_specs
    )
    config = replace(config, operation_specs=huge_specs)
    # Every stored scalar fits; only the independently derived second end overflows.
    bad = replace(
        good,
        operations=tuple(
            replace(op, duration_ns=_LIMIT - 1, start_ns=0 if i == 0 else _LIMIT - 1)
            for i, op in enumerate(good.operations)
        ),
        end_ns=_LIMIT - 1,
    )
    with pytest.raises(NativeInputError) as caught:
        if entry == "lower":
            lower_to_native(circuit, config)
        elif entry == "validate":
            validate_native_schedule(circuit, bad, config)
        else:
            qubic_mapping(circuit, bad, config)
    assert (caught.value.code, caught.value.path) == ("range", "$.operations[1].end_ns")


@pytest.mark.parametrize("fault", ["order", "remove", "add", "condition_width"])
def test_source_header_cannot_be_substituted_by_layout(fault):
    circuit, _, config = fixture(())
    a, b = ClassicalRegister("a", 1), ClassicalRegister("b", 1)
    circuit.cregs = [a, b]
    if fault == "condition_width":
        circuit.gates = [Measure(0, ClassicalBit(a, 0)), Conditional(a, 0, ())]
    snapshot = _capture_source(circuit)
    good = _schedule_source(snapshot, config, _expand_source(snapshot))
    if fault == "order":
        bad = replace(good, registers=tuple(reversed(good.registers)))
    elif fault == "remove":
        bad = replace(good, registers=good.registers[:1])
    elif fault == "add":
        bad = replace(good, registers=(*good.registers, RegisterDecl(name="d", size=1)))
    else:
        from qaiji.core.native.model import ConditionRead

        region = replace(
            good.conditions[0],
            width=2,
            reads=(*good.conditions[0].reads, ConditionRead(bit_index=1, event_id="m0")),
        )
        bad = replace(
            good,
            registers=(RegisterDecl(name="a", size=2), good.registers[1]),
            conditions=(region,),
        )
    report = validate_native_schedule(circuit, bad, config)
    assert issues(report) == (("source_header", "$.registers", None, None),)
    assert (report.rules.status, report.hp.status, report.schedule.status) == ("not_run",) * 3


@pytest.mark.parametrize(
    "statuses,expected",
    [
        ((), "not_applicable"),
        (("not_applicable",), "not_applicable"),
        (("pass", "not_applicable"), "pass"),
        (("pass", "not_run"), "not_run"),
        (("not_run", "fail"), "fail"),
    ],
)
def test_aggregate_status_algebra(statuses, expected):
    # not_run groups do not arise after current V1; test the generic reducer directly.
    from qaiji.core.native.diagnostics import CheckResult
    from qaiji.core.native.validation import _aggregate, _result

    checks = tuple(
        _result("rule_id") if s == "fail" else CheckResult(status=s, issues=()) for s in statuses
    )
    result = _aggregate(checks)
    assert result.status == expected
    assert result.issues == tuple(issue for check in checks for issue in check.issues)


def test_independent_hp_failure_clears_readiness(monkeypatch):
    """Inject a dependency result to exercise HP-only orchestration, not a natural gate case."""
    from qaiji.core.native.matrix import _MatrixCheck

    circuit, good, config = fixture()
    assert validate_native_schedule(circuit, good, config).valid
    failure = _MatrixCheck(
        status="fail", code="operator_mismatch", expected_phase_rad=0.0, max_abs_residual=0.5
    )
    monkeypatch.setattr("qaiji.core.native.validation._check_local_matrix", lambda *args: failure)
    try:
        report = validate_native_schedule(circuit, good, config)
    except NativeInputError as error:
        raise AssertionError(
            "Structurally valid candidate must return a semantic report"
        ) from error
    assert (
        report.source.status,
        report.rules.status,
        report.hp.status,
        report.schedule.status,
    ) == ("pass", "pass", "fail", "pass")
    assert issues(report) == (
        ("operator_mismatch", "$.groups[0]", SourceLocation(gate_index=0, body_offset=None), None),
    )
    assert not report.valid
    assert report.all_results_ready_ns is None
    assert report.groups[0].expected_phase_rad == 0.0
    assert report.groups[0].max_abs_residual == 0.5


@pytest.mark.parametrize("entry", ["lower", "validate", "projection"])
@pytest.mark.parametrize(
    "fault", ["missing", "extra", "unknown", "report", "passed", "checked", "token"]
)
def test_public_signature_negative_space(entry, fault):
    import inspect

    circuit, good, config = fixture()
    from qaiji.core.native import qubic_mapping

    function = {
        "lower": lower_to_native,
        "validate": validate_native_schedule,
        "projection": qubic_mapping,
    }[entry]
    args = (circuit, config) if entry == "lower" else (circuit, good, config)
    names = ("circuit", "config") if entry == "lower" else ("circuit", "schedule", "config")
    assert tuple(inspect.signature(function).parameters) == names
    kwargs = {}
    if fault == "missing":
        args = args[:-1]
    elif fault == "extra":
        args = (*args, True)
    else:
        kwargs = {fault: True}
    with pytest.raises(TypeError):
        function(*args, **kwargs)
