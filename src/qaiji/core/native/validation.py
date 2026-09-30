# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Independent staged authentication of native schedules."""

from __future__ import annotations

from qaiji.core.circuit import Circuit, Gate
from qaiji.core.classical import Conditional, Measure

from .config import ScheduleConfig
from .diagnostics import CheckResult, GroupEvidence, NativeIssue, NativeValidationReport
from .matrix import _check_local_matrix
from .model import NativeScheduleIR, RegisterDecl, SourceLocation, _copy
from .recognition import _recognize_group
from .source import _capture_source, _SourceSnapshot
from .timing import _check_source_layout, _check_timing


def validate_native_schedule(
    circuit: Circuit, schedule: NativeScheduleIR, config: ScheduleConfig
) -> NativeValidationReport:
    """重建输入值，分别报告来源、规则、算符矩阵与时序的检查结果。"""
    snapshot = _capture_source(circuit)
    candidate = _copy(schedule, NativeScheduleIR, "$")
    configuration = _copy(config, ScheduleConfig, "$")
    return _validate_snapshot(snapshot, candidate, configuration)


def _result(
    code: str | None = None,
    path: str | None = "$",
    source: SourceLocation | None = None,
    operation_index: int | None = None,
) -> CheckResult:
    if code is None:
        return CheckResult(status="pass", issues=())
    issue = NativeIssue(
        code=code,
        path=path or "$",
        source=source,
        operation_index=operation_index,
        message=f"Native validation failed: {code}.",
    )
    return CheckResult(status="fail", issues=(issue,))


def _aggregate(checks: tuple[CheckResult, ...]) -> CheckResult:
    issues = tuple(issue for check in checks for issue in check.issues)
    if issues:
        return CheckResult(status="fail", issues=issues)
    if any(check.status == "not_run" for check in checks):
        return CheckResult(status="not_run", issues=())
    status = "pass" if any(check.status == "pass" for check in checks) else "not_applicable"
    return CheckResult(status=status, issues=())


def _source_check(snapshot: _SourceSnapshot, schedule: NativeScheduleIR) -> CheckResult:
    if snapshot.source_kernel_ref != schedule.source_kernel_ref:
        return _result("source_ref", "$.source_kernel_ref")
    if snapshot.num_qubits != schedule.num_qubits:
        return _result("source_header", "$.num_qubits")
    registers = tuple(RegisterDecl(name=r.name, size=r.size) for r in snapshot.cregs)
    if registers != schedule.registers:
        return _result("source_header", "$.registers")
    layout = _check_source_layout(snapshot, schedule)
    return _result(layout.code, layout.path, layout.source, layout.operation_index)


def _group_evidence(
    snapshot: _SourceSnapshot, schedule: NativeScheduleIR
) -> tuple[GroupEvidence, ...]:
    evidence = []
    for index, group in enumerate(schedule.groups):
        node = snapshot.gates[group.source.gate_index]
        if isinstance(node, Conditional):
            assert group.source.body_offset is not None
            node = node.body[group.source.body_offset]
        assert isinstance(node, (Gate, Measure))
        operations = schedule.operations[group.op_start : group.op_stop]
        rule = _recognize_group(node, group.source, group, operations)
        path = f"$.groups[{index}]"
        if rule.code == "rule_id":
            path += ".rule_id"
        elif rule.code == "rule_phase":
            path += ".phase_rad"
        elif rule.operation_index is not None:
            path = f"$.operations[{rule.operation_index}]"
        hp = _check_local_matrix(node, operations)
        hp_result = (
            _result(hp.code, f"$.groups[{index}]", group.source)
            if hp.code is not None
            else CheckResult(status=hp.status, issues=())
        )
        evidence.append(
            GroupEvidence(
                source=group.source,
                rule_id=group.rule_id,
                rule=_result(rule.code, path, group.source, rule.operation_index),
                hp=hp_result,
                expected_phase_rad=hp.expected_phase_rad,
                max_abs_residual=hp.max_abs_residual,
            )
        )
    return tuple(evidence)


def _validate_snapshot(
    snapshot: _SourceSnapshot, schedule: NativeScheduleIR, config: ScheduleConfig
) -> NativeValidationReport:
    """Consume the same captured source used by generation or projection."""
    source = _source_check(snapshot, schedule)
    if source.status == "fail":
        pending = CheckResult(status="not_run", issues=())
        return NativeValidationReport(
            source=source,
            rules=pending,
            hp=pending,
            schedule=pending,
            groups=(),
            all_results_ready_ns=None,
        )
    groups = _group_evidence(snapshot, schedule)
    rules = _aggregate(tuple(group.rule for group in groups))
    hp = _aggregate(tuple(group.hp for group in groups))
    timing = _check_timing(snapshot, schedule, config)
    schedule_result = _result(timing.code, timing.path, timing.source, timing.operation_index)
    ready = timing.all_results_ready_ns
    if rules.status not in ("pass", "not_applicable") or hp.status not in (
        "pass",
        "not_applicable",
    ):
        ready = None
    return NativeValidationReport(
        source=source,
        rules=rules,
        hp=hp,
        schedule=schedule_result,
        groups=groups,
        all_results_ready_ns=ready,
    )
