# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Native value contracts, with independent literal expectations."""

import math
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from _native_fixtures import FIELDS, make, schedule_values, values
from qaiji.core.native.diagnostics import (
    CheckResult,
    GroupEvidence,
    NativeIssue,
    NativeValidationReport,
)
from qaiji.core.native.errors import NativeInputError
from qaiji.core.native.model import (
    ConditionRead,
    ConditionRegion,
    MeasurementEvent,
    NativeOperation,
    NativeScheduleIR,
    RegisterDecl,
    SourceGroup,
    SourceLocation,
)


def test_kw_only_frozen_slots_unhashable():
    with pytest.raises(TypeError):
        SourceLocation(0, None)


def rejects(cls, changes, code, path):
    with pytest.raises(Exception) as caught:
        make(cls, **changes)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == (code, path)


@pytest.mark.parametrize("cls", list(FIELDS))
def test_value_field_contract(cls):
    assert set(f.name for f in fields(cls)) == set(FIELDS[cls])
    assert len(fields(cls)) == len(FIELDS[cls])
    assert cls(**values()[cls]) == make(cls)


@pytest.mark.parametrize("cls", list(FIELDS))
def test_all_value_construction_protocol(cls):
    obj = make(cls)
    with pytest.raises(TypeError):
        cls(*values()[cls].values())
    with pytest.raises(TypeError):
        cls(**(values()[cls] | {"unknown": 1}))
    for field in FIELDS[cls]:
        if field in ("schema_version", "ruleset_version"):
            continue
        kwargs = values()[cls].copy()
        del kwargs[field]
        with pytest.raises(TypeError):
            cls(**kwargs)
    assert not hasattr(obj, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(obj, FIELDS[cls][0], None)
    with pytest.raises(TypeError):
        hash(obj)


class IntSubclass(int):
    pass


class StrSubclass(str):
    pass


class FloatSubclass(float):
    pass


@pytest.mark.parametrize("cls", list(FIELDS))
def test_scalar_and_container_domains(cls):
    for field, value in values()[cls].items():
        if type(value) is int:
            for bad, code in [
                (True, "integer"),
                (IntSubclass(value), "integer"),
                (1.0, "integer"),
                (-1, "range"),
                (10**4096, "range"),
            ]:
                rejects(cls, {field: bad}, code, "$." + field)
        elif type(value) is float:
            for bad, code in [
                (True, "number"),
                (FloatSubclass(value), "number"),
                (float("nan"), "number"),
                (float("inf"), "number"),
                (10**4096, "number"),
            ]:
                rejects(cls, {field: bad}, code, "$." + field)
        elif type(value) is str:
            for bad in [StrSubclass(value), 3, None]:
                rejects(cls, {field: bad}, "type", "$." + field)
        elif type(value) is tuple:
            for bad in [set(), iter(value), ""]:
                rejects(cls, {field: bad}, "container", "$." + field)
            try:
                copied = make(cls, **{field: list(value)})
            except NativeInputError as error:
                assert error is None, "合法 list 容器必须接受并复制: " + str(error)
            assert getattr(copied, field) == value


@pytest.mark.parametrize("cls", list(FIELDS))
def test_deep_copy_and_subclass_projection(cls):
    kwargs = values()[cls]
    for name, val in kwargs.items():
        if isinstance(val, tuple):
            original = list(val)
            obj = make(cls, **{name: original})
            original.append("mutated")
            assert getattr(obj, name) == val
        elif type(val) in FIELDS:
            base = type(val)
            subclass = type("Extended" + base.__name__, (base,), {})
            extended = subclass(**{f: getattr(val, f) for f in FIELDS[base]})
            obj = make(cls, **{name: extended})
            assert type(getattr(obj, name)) is base
            assert getattr(obj, name) is not extended
            object.__setattr__(extended, FIELDS[base][0], "mutated")
            assert getattr(obj, name) == val


@pytest.mark.parametrize(
    "cls,changes,code,path",
    [
        (RegisterDecl, {"name": "bad name"}, "identifier", "$.name"),
        (RegisterDecl, {"size": 0}, "range", "$.size"),
        (NativeOperation, {"kind": "X"}, "enum", "$.kind"),
        (NativeOperation, {"qubits": ()}, "arity", "$.qubits"),
        (NativeOperation, {"params": ()}, "arity", "$.params"),
        (
            NativeOperation,
            {"params": (math.nextafter(math.tau, math.inf),)},
            "range",
            "$.params[0]",
        ),
        (NativeOperation, {"resources": ()}, "resources", "$.resources"),
        (NativeOperation, {"resources": ("q0", "q0")}, "resources", "$.resources"),
        (NativeOperation, {"duration_ns": 0}, "duration", "$.duration_ns"),
        (SourceGroup, {"op_stop": 0}, "span", "$.op_stop"),
        (MeasurementEvent, {"ready_ns": 29}, "event", "$.ready_ns"),
        (
            MeasurementEvent,
            {"source": SourceLocation(gate_index=0, body_offset=0)},
            "event",
            "$.source",
        ),
        (ConditionRegion, {"condition_id": "c2"}, "condition_id", "$.condition_id"),
        (ConditionRegion, {"value": 2}, "condition_value", "$.value"),
        (ConditionRegion, {"reads": ()}, "read_bits", "$.reads"),
        (ConditionRegion, {"end_ns": 39}, "span", "$.end_ns"),
        (NativeScheduleIR, {"num_qubits": 0}, "range", "$.num_qubits"),
        (
            NativeScheduleIR,
            {"source_kernel_ref": "sha256:" + "A" * 64},
            "ref",
            "$.source_kernel_ref",
        ),
        (
            NativeScheduleIR,
            {"source_kernel_ref": "sha256:" + "a" * 63},
            "ref",
            "$.source_kernel_ref",
        ),
        (NativeScheduleIR, {"schema_version": "other"}, "enum", "$.schema_version"),
        (NativeScheduleIR, {"ruleset_version": "other"}, "enum", "$.ruleset_version"),
    ],
)
def test_local_domains(cls, changes, code, path):
    rejects(cls, changes, code, path)


def test_empty_schedule():
    try:
        obj = make(NativeScheduleIR)
    except NativeInputError as error:
        assert error is None, "空 schedule 的 end=0 必须合法: " + str(error)
    assert (obj.operations, obj.groups, obj.end_ns) == ((), (), 0)
    assert make(SourceLocation, gate_index=10**4096 - 1).gate_index == 10**4096 - 1
    assert math.copysign(1, make(NativeOperation, params=(-0.0,)).params[0]) == -1
    assert make(NativeOperation, params=(math.tau,)).params == (math.tau,)


def test_schedule_graph_references():
    try:
        data = schedule_values()
        obj = NativeScheduleIR(**data)
    except NativeInputError as error:
        assert error is None, "测量及条件体的合法图必须接受: " + str(error)
    assert obj.operations[1].condition_id == "c1"
    cases = [
        (
            {"registers": (make(RegisterDecl), make(RegisterDecl))},
            "duplicate_register",
            "$.registers[1].name",
        ),
        ({"groups": ()}, "group_reference", "$.groups"),
        ({"events": ()}, "event_reference", "$.events"),
        ({"conditions": ()}, "condition_reference", "$.operations[1].condition_id"),
        (
            {"operations": (replace(data["operations"][0], qubits=(1,)), data["operations"][1])},
            "qubit_range",
            "$.operations[0].qubits[0]",
        ),
        ({"events": (make(MeasurementEvent, event_id="m1"),)}, "event", "$.events[0].event_id"),
        (
            {"events": (make(MeasurementEvent, register_name="s"),)},
            "register_reference",
            "$.events[0].register_name",
        ),
        (
            {"events": (make(MeasurementEvent, bit_index=1),)},
            "register_reference",
            "$.events[0].bit_index",
        ),
        (
            {
                "conditions": (
                    make(
                        ConditionRegion,
                        op_stop=2,
                        end_ns=60,
                        reads=(ConditionRead(bit_index=0, event_id="m9"),),
                    ),
                )
            },
            "event_reference",
            "$.conditions[0].reads[0].event_id",
        ),
    ]
    for changes, code, path in cases:
        with pytest.raises(Exception) as caught:
            NativeScheduleIR(**(data | changes))
        assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
        assert (caught.value.code, caught.value.path) == (code, path)
    # Time agreement is semantic validation, not a structure constraint.
    assert (
        NativeScheduleIR(**(data | {"events": (make(MeasurementEvent, end_ns=31),)}))
        .events[0]
        .end_ns
        == 31
    )


@pytest.mark.parametrize("status", ["pass", "fail", "not_run", "not_applicable"])
def test_check_status_contract(status):
    issue = make(NativeIssue)
    good = (issue,) if status == "fail" else ()
    assert make(CheckResult, status=status, issues=good).status == status
    rejects(
        CheckResult,
        {"status": status, "issues": () if status == "fail" else (issue,)},
        "status",
        "$.issues",
    )
    rejects(CheckResult, {"status": "unknown"}, "enum", "$.status")


@pytest.mark.parametrize("rule_status", ["pass", "fail", "not_run", "not_applicable"])
@pytest.mark.parametrize("hp_status", ["pass", "fail", "not_run", "not_applicable"])
def test_group_evidence_status_contract(rule_status, hp_status):
    issue = make(NativeIssue)
    rule = make(CheckResult, status=rule_status, issues=(issue,) if rule_status == "fail" else ())
    hp = make(CheckResult, status=hp_status, issues=(issue,) if hp_status == "fail" else ())
    data = dict(rule=rule, hp=hp)
    if hp_status in ("not_run", "not_applicable"):
        obj = make(GroupEvidence, **data, expected_phase_rad=None, max_abs_residual=None)
        assert obj.max_abs_residual is None
        rejects(
            GroupEvidence,
            data | {"expected_phase_rad": 0.0, "max_abs_residual": None},
            "status",
            "$.expected_phase_rad",
        )
        rejects(
            GroupEvidence,
            data | {"expected_phase_rad": None, "max_abs_residual": 0.0},
            "status",
            "$.max_abs_residual",
        )
    else:
        try:
            obj = make(GroupEvidence, **data, expected_phase_rad=-math.pi, max_abs_residual=0.01)
        except NativeInputError as error:
            assert error is None, "非负局部矩阵残差必须接受: " + str(error)
        assert obj.max_abs_residual == 0.01
    rejects(GroupEvidence, {"max_abs_residual": -0.1}, "range", "$.max_abs_residual")


@pytest.mark.parametrize("source_status", ["pass", "fail", "not_run", "not_applicable"])
@pytest.mark.parametrize("rules_status", ["pass", "fail", "not_run", "not_applicable"])
@pytest.mark.parametrize("hp_status", ["pass", "fail", "not_run", "not_applicable"])
@pytest.mark.parametrize("schedule_status", ["pass", "fail", "not_run", "not_applicable"])
def test_report_status_cross_product(source_status, rules_status, hp_status, schedule_status):
    checks = {
        name: make(
            CheckResult, status=status, issues=(make(NativeIssue),) if status == "fail" else ()
        )
        for name, status in [
            ("source", source_status),
            ("rules", rules_status),
            ("hp", hp_status),
            ("schedule", schedule_status),
        ]
    }
    valid = (
        source_status == "pass"
        and schedule_status == "pass"
        and rules_status in ("pass", "not_applicable")
        and hp_status in ("pass", "not_applicable")
    )
    obj = make(NativeValidationReport, **checks, all_results_ready_ns=0 if valid else None)
    assert obj.valid is valid
    if not valid:
        rejects(
            NativeValidationReport,
            checks | {"all_results_ready_ns": 0},
            "status",
            "$.all_results_ready_ns",
        )


def test_report_group_completion_and_issue_order():
    pending = make(CheckResult, status="not_run")
    group = make(
        GroupEvidence, rule=pending, hp=pending, expected_phase_rad=None, max_abs_residual=None
    )
    obj = make(NativeValidationReport, groups=(group,), all_results_ready_ns=None)
    assert obj.valid is False
    rejects(NativeValidationReport, {"groups": (group,)}, "status", "$.all_results_ready_ns")
    from qaiji.core.native.diagnostics import NativeValidationError
    from qaiji.exceptions import QaijiIRError

    issues = [make(NativeIssue, code=code) for code in ("src", "r0", "r1", "h0", "h1", "time")]

    def fail(issue):
        return make(CheckResult, status="fail", issues=(issue,))

    groups = tuple(
        make(
            GroupEvidence,
            source=SourceLocation(gate_index=i, body_offset=None),
            rule=fail(issues[1 + i]),
            hp=fail(issues[3 + i]),
        )
        for i in range(2)
    )
    report = make(
        NativeValidationReport,
        source=fail(issues[0]),
        rules=fail(issues[1]),
        hp=fail(issues[3]),
        schedule=fail(issues[5]),
        groups=groups,
        all_results_ready_ns=None,
    )
    error = NativeValidationError(report)
    assert isinstance(error, QaijiIRError)
    assert error.report == report
    assert error.issues == tuple(issues)


def test_native_exports_available_contract_only():
    import qaiji.core.native as native

    expected = {cls.__name__ for cls in FIELDS} | {
        "NativeInputError",
        "NativeValidationError",
        "NATIVE_SCHEDULE_SCHEMA_VERSION",
        "NATIVE_RULESET_VERSION",
        "ProjectedOperation",
        "NativeProjection",
        "lower_to_native",
        "validate_native_schedule",
        "qubic_mapping",
    }
    assert set(getattr(native, "__all__", ())) == expected
    for name in expected:
        assert getattr(native, name) is not None


@pytest.mark.parametrize(
    "cls,field,good,code",
    [
        (SourceLocation, "body_offset", 0, "integer"),
        (NativeOperation, "condition_id", "c0", "type"),
        (NativeIssue, "source", SourceLocation(gate_index=0, body_offset=None), "type"),
        (NativeIssue, "operation_index", 0, "integer"),
        (GroupEvidence, "expected_phase_rad", 0.0, "number"),
        (GroupEvidence, "max_abs_residual", 0.0, "number"),
        (NativeValidationReport, "all_results_ready_ns", 0, "integer"),
    ],
)
def test_nullable_field_domains(cls, field, good, code):
    assert getattr(make(cls, **{field: None}), field) is None
    assert getattr(make(cls, **{field: good}), field) == good
    rejects(cls, {field: True}, code, "$." + field)


@pytest.mark.parametrize(
    "cls,changes,code,path",
    [
        (
            NativeOperation,
            {
                "kind": "MEASURE",
                "params": (),
                "source": SourceLocation(gate_index=0, body_offset=0),
            },
            "event",
            "$.source",
        ),
        (NativeOperation, {"kind": "CZ", "qubits": (0, 0), "params": ()}, "arity", "$.qubits"),
        (NativeOperation, {"qubits": (False,)}, "integer", "$.qubits[0]"),
        (NativeOperation, {"params": (FloatSubclass(0),)}, "number", "$.params[0]"),
        (NativeOperation, {"resources": ("",)}, "text", "$.resources[0]"),
        (
            ConditionRegion,
            {"reads": (ConditionRead(bit_index=1, event_id="m0"),)},
            "read_bits",
            "$.reads",
        ),
        (ConditionRegion, {"op_start": 2, "op_stop": 1}, "span", "$.op_stop"),
        (NativeIssue, {"operation_index": -1}, "range", "$.operation_index"),
        (SourceLocation, {"body_offset": -1}, "range", "$.body_offset"),
        (NativeOperation, {"condition_id": ""}, "text", "$.condition_id"),
    ],
)
def test_nested_scalar_and_local_boundaries(cls, changes, code, path):
    rejects(cls, changes, code, path)


def rich_instances():
    from qaiji.core.native.config import OperationSpec, QubitResource, ScheduleConfig

    issue = make(NativeIssue)
    failed = make(CheckResult, status="fail", issues=(issue,))
    group = make(GroupEvidence, rule=failed, hp=failed)
    return {
        **{cls: make(cls) for cls in FIELDS},
        NativeScheduleIR: NativeScheduleIR(**schedule_values()),
        ScheduleConfig: make(
            ScheduleConfig,
            qubit_resources=(make(QubitResource), make(QubitResource, qubit=1, resource="q1")),
            operation_specs=(make(OperationSpec),),
            cz_couplings=((0, 1),),
        ),
        CheckResult: failed,
        NativeValidationReport: make(
            NativeValidationReport,
            rules=failed,
            hp=failed,
            groups=(group,),
            all_results_ready_ns=None,
        ),
    }


@pytest.mark.parametrize("cls", list(FIELDS))
def test_nonempty_nested_projection_and_error_paths(cls):
    from dataclasses import dataclass
    from dataclasses import field as datafield

    obj = rich_instances()[cls]
    for field in FIELDS[cls]:
        value = getattr(obj, field)
        if not isinstance(value, tuple) or not value:
            continue
        kwargs = {f: getattr(obj, f) for f in FIELDS[cls]}
        if type(value[0]) in FIELDS:
            base = type(value[0])

            @dataclass(frozen=True, slots=True, kw_only=True)
            class Extended(base):
                extension: list = datafield(default_factory=list)

            original = value[0]
            extended = Extended(
                **{f: getattr(original, f) for f in FIELDS[base]}, extension=["ignored"]
            )
            incoming = [extended, *value[1:]]
            copy = cls(**(kwargs | {field: incoming}))
            incoming.clear()
            extended.extension.append("mutable")
            projected = getattr(copy, field)[0]
            assert type(projected) is base
            assert not hasattr(projected, "extension")
            assert projected == original and projected is not extended
            object.__setattr__(extended, FIELDS[base][0], None)
            assert projected == original
            # Re-projection rechecks tampered input, retaining the full parent path.
            with pytest.raises(Exception) as caught:
                cls(**(kwargs | {field: [extended, *value[1:]]}))
            assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
            assert (caught.value.code, caught.value.path) == (
                "type"
                if type(getattr(original, FIELDS[base][0])) is str
                or type(getattr(original, FIELDS[base][0])) in FIELDS
                else "integer",
                f"$.{field}[0].{FIELDS[base][0]}",
            )
        elif isinstance(value[0], tuple):
            incoming = [list(v) for v in value]
            copy = cls(**(kwargs | {field: incoming}))
            incoming[0][0] = 999
            assert getattr(copy, field) == value
        for bad in [None, object()]:
            with pytest.raises(Exception) as caught:
                cls(**(kwargs | {field: [bad, *value[1:]]}))
            assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
            expected_codes = {
                "qubits": "integer",
                "params": "number",
                "resources": "type",
                "reads": "type",
                "registers": "type",
                "operations": "type",
                "groups": "type",
                "events": "type",
                "conditions": "type",
                "qubit_resources": "type",
                "operation_specs": "type",
                "cz_couplings": "container",
                "issues": "type",
            }
            assert (caught.value.code, caught.value.path) == (
                expected_codes[field],
                f"$.{field}[0]",
            )


def test_schedule_graph_atomic_references():
    data = schedule_values()
    op0, op1 = data["operations"]
    g0, g1 = data["groups"]
    event = data["events"][0]
    region = data["conditions"][0]
    cases = [
        ({"groups": (g0, replace(g1, source=g0.source))}, "duplicate_source", "$.groups[1].source"),
        (
            {"groups": (replace(g0, op_start=1, op_stop=2),)},
            "group_reference",
            "$.groups[0].op_start",
        ),
        ({"groups": (g0, replace(g1, op_stop=3))}, "group_reference", "$.groups[1].op_stop"),
        (
            {"operations": (op0, replace(op1, source=SourceLocation(gate_index=2, body_offset=0)))},
            "group_reference",
            "$.operations[1].source",
        ),
        (
            {"operations": (op0, replace(op1, ordinal=1))},
            "group_reference",
            "$.operations[1].ordinal",
        ),
        ({"events": (event, event)}, "duplicate_event", "$.events[1].event_id"),
        (
            {"events": (replace(event, operation_index=2),)},
            "event_reference",
            "$.events[0].operation_index",
        ),
        (
            {"events": (event, replace(event, event_id="m1"))},
            "event_reference",
            "$.events[1].operation_index",
        ),
        (
            {"events": (replace(event, operation_index=1),)},
            "event_reference",
            "$.events[0].operation_index",
        ),
        ({"events": (replace(event, qubit=1),)}, "event_reference", "$.events[0].qubit"),
        (
            {"events": (replace(event, source=SourceLocation(gate_index=2, body_offset=None)),)},
            "event_reference",
            "$.events[0].source",
        ),
        ({"conditions": (region, region)}, "duplicate_condition", "$.conditions[1].condition_id"),
        (
            {"conditions": (replace(region, register_name="s"),)},
            "register_reference",
            "$.conditions[0].register_name",
        ),
        (
            {"registers": (make(RegisterDecl, size=2),)},
            "register_reference",
            "$.conditions[0].width",
        ),
        (
            {"conditions": (replace(region, op_stop=3),)},
            "condition_reference",
            "$.conditions[0].op_stop",
        ),
        (
            {"operations": (op0, replace(op1, condition_id=None))},
            "condition_reference",
            "$.operations[1].condition_id",
        ),
        (
            {"conditions": (replace(region, op_stop=1),)},
            "condition_reference",
            "$.operations[1].condition_id",
        ),
        (
            {
                "conditions": (replace(region, op_stop=1),),
                "operations": (op0, replace(op1, condition_id=None)),
            },
            "condition_reference",
            "$.operations[1].condition_id",
        ),
        (
            {
                "conditions": (replace(region, condition_id="c2", gate_index=2),),
                "operations": (op0, replace(op1, condition_id="c2")),
            },
            "condition_reference",
            "$.operations[1].source",
        ),
    ]
    top = SourceLocation(gate_index=1, body_offset=None)
    cases.append(
        (
            {
                "operations": (op0, replace(op1, source=top)),
                "groups": (g0, replace(g1, source=top)),
            },
            "condition_reference",
            "$.operations[1].source",
        )
    )
    for change, code, path in cases:
        with pytest.raises(Exception) as caught:
            NativeScheduleIR(**(data | change))
        assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
        assert (caught.value.code, caught.value.path) == (code, path)
    # Empty bodies still have a region; forward reads and event times are semantic.
    empty = data | {
        "operations": (op0,),
        "groups": (g0,),
        "conditions": (replace(region, op_stop=1),),
    }
    assert NativeScheduleIR(**empty).conditions[0].op_start == 1


def test_report_independent_group_completion():
    for side in ("rule", "hp"):
        for status in ("fail", "not_run"):
            check = make(
                CheckResult, status=status, issues=(make(NativeIssue),) if status == "fail" else ()
            )
            changes = {side: check}
            if side == "hp" and status == "not_run":
                changes |= {"expected_phase_rad": None, "max_abs_residual": None}
            group = make(GroupEvidence, **changes)
            report = make(NativeValidationReport, groups=(group,), all_results_ready_ns=None)
            assert report.valid is False


def test_empty_schedule_end_domain():
    rejects(NativeScheduleIR, {"end_ns": 1}, "span", "$.end_ns")


def test_report_invalid_ready():
    pending = make(CheckResult, status="not_run")
    try:
        incomplete = make(NativeValidationReport, source=pending, all_results_ready_ns=None)
    except NativeInputError as error:
        assert error is None, "未完成报告允许没有结果就绪时间: " + str(error)
    assert incomplete.valid is False
    try:
        complete = make(NativeValidationReport)
    except NativeInputError as error:
        assert error is None, "有效报告允许合法结果就绪时间: " + str(error)
    assert complete.valid is True
    rejects(NativeValidationReport, {"source": pending}, "status", "$.all_results_ready_ns")


def test_report_each_validity_requirement():
    failed = make(CheckResult, status="fail", issues=(make(NativeIssue),))
    for name in ("source", "rules", "hp", "schedule"):
        report = make(NativeValidationReport, **{name: failed}, all_results_ready_ns=None)
        assert report.valid is False
    group = make(GroupEvidence, rule=failed)
    assert make(NativeValidationReport, groups=(group,), all_results_ready_ns=None).valid is False


@pytest.mark.parametrize("cls", list(FIELDS))
def test_fixed_base_projection_all_types(cls):
    from dataclasses import dataclass
    from dataclasses import field as datafield

    from qaiji.core.native.model import _copy

    original = rich_instances()[cls]

    @dataclass(frozen=True, slots=True, kw_only=True)
    class Extended(cls):
        extension: list = datafield(default_factory=list)

    extended = Extended(
        **{field: getattr(original, field) for field in FIELDS[cls]}, extension=["ignored"]
    )
    copied = _copy(extended, cls, "$")
    assert type(copied) is cls
    assert copied == original
    assert not hasattr(copied, "extension")
    extended.extension.clear()
    assert copied == original


@pytest.mark.parametrize(
    "kind,qubits,params,duration",
    [
        ("I", (0,), (), 0),
        ("Z", (0,), (), 0),
        ("RZ", (0,), (0.5,), 0),
        ("RX90", (0,), (0.5,), 20),
        ("CZ", (1, 0), (), 40),
        ("MEASURE", (0,), (), 30),
    ],
    ids=["I", "Z", "RZ", "RX90", "CZ", "MEASURE"],
)
def test_each_native_kind_operand_and_parameter_domains(kind, qubits, params, duration):
    data = dict(kind=kind, qubits=qubits, params=params, duration_ns=duration)
    try:
        operation = make(NativeOperation, **data)
    except NativeInputError as error:
        assert error is None, "声明的原生 kind 参数签名必须接受: " + str(error)
    assert (operation.kind, operation.qubits, operation.params, operation.duration_ns) == (
        kind,
        qubits,
        params,
        duration,
    )
    for bad in (qubits[:-1], (*qubits, 2)):
        rejects(NativeOperation, data | {"qubits": bad}, "arity", "$.qubits")
    bad_params = [(*params, 0.0)]
    if params:
        bad_params.append(())
    for bad in bad_params:
        rejects(NativeOperation, data | {"params": bad}, "arity", "$.params")


@pytest.mark.parametrize("kind,duration", [("RZ", 0), ("RX90", 20)], ids=["RZ", "RX90"])
def test_each_angle_kind_symmetric_boundaries(kind, duration):
    data = dict(kind=kind, duration_ns=duration)
    for angle in (-math.tau, math.tau, -0.0, 0.0):
        actual = make(NativeOperation, **data, params=(angle,)).params[0]
        assert actual.hex() == angle.hex()
    for angle in (math.nextafter(-math.tau, -math.inf), math.nextafter(math.tau, math.inf)):
        rejects(NativeOperation, data | {"params": (angle,)}, "range", "$.params[0]")


def test_positive_condition_width():
    rejects(ConditionRegion, {"width": 0}, "range", "$.width")


@pytest.mark.parametrize("cls", list(FIELDS))
def test_each_text_field_empty_domain(cls):
    for field, value in values()[cls].items():
        if type(value) is str:
            rejects(cls, {field: ""}, "text", "$." + field)
