# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Explicit synthetic nanosecond inputs; not a device default configuration."""

from qaiji.core.native.config import OperationSpec, QubitResource, ScheduleConfig
from qaiji.core.native.diagnostics import (
    CheckResult,
    GroupEvidence,
    NativeIssue,
    NativeValidationReport,
)
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

REF = "sha256:" + "a" * 64
FIELDS = {
    SourceLocation: ("gate_index", "body_offset"),
    RegisterDecl: ("name", "size"),
    NativeOperation: (
        "kind",
        "qubits",
        "params",
        "source",
        "ordinal",
        "start_ns",
        "duration_ns",
        "resources",
        "condition_id",
    ),
    SourceGroup: ("source", "rule_id", "op_start", "op_stop", "phase_rad"),
    MeasurementEvent: (
        "event_id",
        "source",
        "operation_index",
        "qubit",
        "register_name",
        "bit_index",
        "end_ns",
        "ready_ns",
    ),
    ConditionRead: ("bit_index", "event_id"),
    ConditionRegion: (
        "condition_id",
        "gate_index",
        "register_name",
        "width",
        "value",
        "reads",
        "op_start",
        "op_stop",
        "start_ns",
        "end_ns",
    ),
    NativeScheduleIR: (
        "schema_version",
        "source_kernel_ref",
        "num_qubits",
        "registers",
        "ruleset_version",
        "operations",
        "groups",
        "events",
        "conditions",
        "end_ns",
    ),
    QubitResource: ("qubit", "resource"),
    OperationSpec: ("kind", "qubits", "duration_ns", "resources", "result_latency_ns"),
    ScheduleConfig: ("qubit_resources", "operation_specs", "cz_couplings"),
    NativeIssue: ("code", "path", "source", "operation_index", "message"),
    CheckResult: ("status", "issues"),
    GroupEvidence: ("source", "rule_id", "rule", "hp", "expected_phase_rad", "max_abs_residual"),
    NativeValidationReport: ("source", "rules", "hp", "schedule", "groups", "all_results_ready_ns"),
}


def values():
    source = SourceLocation(gate_index=0, body_offset=None)
    passed = CheckResult(status="pass", issues=())
    return {
        SourceLocation: dict(gate_index=0, body_offset=None),
        RegisterDecl: dict(name="r", size=1),
        NativeOperation: dict(
            kind="RX90",
            qubits=(0,),
            params=(0.0,),
            source=source,
            ordinal=0,
            start_ns=0,
            duration_ns=20,
            resources=("q0",),
            condition_id=None,
        ),
        SourceGroup: dict(
            source=source, rule_id="cz.v0.RX90", op_start=0, op_stop=1, phase_rad=0.0
        ),
        MeasurementEvent: dict(
            event_id="m0",
            source=source,
            operation_index=0,
            qubit=0,
            register_name="r",
            bit_index=0,
            end_ns=30,
            ready_ns=40,
        ),
        ConditionRead: dict(bit_index=0, event_id="m0"),
        ConditionRegion: dict(
            condition_id="c1",
            gate_index=1,
            register_name="r",
            width=1,
            value=0,
            reads=(ConditionRead(bit_index=0, event_id="m0"),),
            op_start=1,
            op_stop=1,
            start_ns=40,
            end_ns=40,
        ),
        NativeScheduleIR: dict(
            schema_version="qaiji.native_schedule.v0",
            source_kernel_ref=REF,
            num_qubits=1,
            registers=(),
            ruleset_version="qaiji.cz_basis.v0",
            operations=(),
            groups=(),
            events=(),
            conditions=(),
            end_ns=0,
        ),
        QubitResource: dict(qubit=0, resource="q0"),
        OperationSpec: dict(
            kind="RX90", qubits=(0,), duration_ns=20, resources=("q0",), result_latency_ns=0
        ),
        ScheduleConfig: dict(qubit_resources=(), operation_specs=(), cz_couplings=()),
        NativeIssue: dict(
            code="rule_instance",
            path="$.operations[0]",
            source=source,
            operation_index=0,
            message="Unexpected operation.",
        ),
        CheckResult: dict(status="pass", issues=()),
        GroupEvidence: dict(
            source=source,
            rule_id="cz.v0.RX90",
            rule=passed,
            hp=passed,
            expected_phase_rad=0.0,
            max_abs_residual=0.0,
        ),
        NativeValidationReport: dict(
            source=passed,
            rules=passed,
            hp=passed,
            schedule=passed,
            groups=(),
            all_results_ready_ns=0,
        ),
    }


def make(cls, **changes):
    return cls(**(values()[cls] | changes))


def schedule_values():
    measurement = make(NativeOperation, kind="MEASURE", params=(), duration_ns=30)
    body_source = SourceLocation(gate_index=1, body_offset=0)
    body = make(NativeOperation, source=body_source, start_ns=40, condition_id="c1")
    return values()[NativeScheduleIR] | dict(
        registers=(make(RegisterDecl),),
        operations=(measurement, body),
        groups=(
            make(SourceGroup, rule_id="cz.v0.MEASURE"),
            make(SourceGroup, source=body_source, op_start=1, op_stop=2),
        ),
        events=(make(MeasurementEvent),),
        conditions=(make(ConditionRegion, op_stop=2, end_ns=60),),
        end_ns=60,
    )
