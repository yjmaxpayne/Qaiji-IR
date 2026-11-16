# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Readonly native validation results and their exceptions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from qaiji.core.semantics import EquivLevel
from qaiji.core.trace.model import TraceInputError
from qaiji.exceptions import QaijiIRError

from .errors import NativeInputError as NativeInputError
from .model import SourceLocation, _copy, _fail, _number, _objects, _optional, _set, _text, _uint


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeIssue:
    code: str
    path: str
    source: SourceLocation | None
    operation_index: int | None
    message: str
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        for name in ("code", "path", "message"):
            _set(self, name, _text)
        _set(self, "source", _optional(lambda v, p: _copy(v, SourceLocation, p)))
        _set(self, "operation_index", _optional(_uint))


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckResult:
    status: str
    issues: tuple[NativeIssue, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "status", _text)
        _set(self, "issues", _objects(NativeIssue))
        if self.status not in ("pass", "fail", "not_run", "not_applicable"):
            _fail("enum", "$.status", "Unknown check status.")
        if (self.status == "fail") != bool(self.issues):
            _fail("status", "$.issues", "Only failed checks must carry issues.")


@dataclass(frozen=True, slots=True, kw_only=True)
class GroupEvidence:
    source: SourceLocation
    rule_id: str
    rule: CheckResult
    hp: CheckResult
    expected_phase_rad: float | None
    max_abs_residual: float | None
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "source", lambda v, p: _copy(v, SourceLocation, p))
        _set(self, "rule_id", _text)
        for name in ("rule", "hp"):
            _set(self, name, lambda v, p: _copy(v, CheckResult, p))
        for name in ("expected_phase_rad", "max_abs_residual"):
            _set(self, name, _optional(_number))
        if self.max_abs_residual is not None and self.max_abs_residual < 0:
            _fail("range", "$.max_abs_residual", "Residual must be nonnegative.")
        if self.hp.status in ("not_run", "not_applicable"):
            for name in ("expected_phase_rad", "max_abs_residual"):
                if getattr(self, name) is not None:
                    _fail(
                        "status", "$." + name, "An uncomputed HP check has no numerical evidence."
                    )


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeValidationReport:
    source: CheckResult
    rules: CheckResult
    hp: CheckResult
    schedule: CheckResult
    groups: tuple[GroupEvidence, ...]
    all_results_ready_ns: int | None
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        for name in ("source", "rules", "hp", "schedule"):
            _set(self, name, lambda v, p: _copy(v, CheckResult, p))
        _set(self, "groups", _objects(GroupEvidence))
        _set(self, "all_results_ready_ns", _optional(_uint))
        if not self.valid and self.all_results_ready_ns is not None:
            _fail(
                "status",
                "$.all_results_ready_ns",
                "An invalid report cannot claim result readiness.",
            )

    @property
    def valid(self) -> bool:
        accepted = ("pass", "not_applicable")
        return (
            self.source.status == "pass"
            and self.schedule.status == "pass"
            and self.rules.status in accepted
            and self.hp.status in accepted
            and all(
                group.rule.status in accepted and group.hp.status in accepted
                for group in self.groups
            )
        )


class NativeValidationError(QaijiIRError):
    """原生调度未通过独立认证。"""

    def __init__(self, report: NativeValidationReport):
        self.report = _copy(report, NativeValidationReport, "$.report")
        super().__init__("Native schedule validation failed.")

    @property
    def issues(self) -> tuple[NativeIssue, ...]:
        return (
            self.report.source.issues
            + tuple(issue for group in self.report.groups for issue in group.rule.issues)
            + tuple(issue for group in self.report.groups for issue in group.hp.issues)
            + self.report.schedule.issues
        )


def equiv_level_of_native(report: NativeValidationReport) -> EquivLevel | None:
    """返回原生验证报告支持的符号等价级别。

    Args:
        report: 原生降级的验证报告。

    Returns:
        报告无效时返回 None。每个组相位均为 0 或 None 时返回 ``EXACT``，
        否则返回 ``UP_TO_PHASE``。

    Raises:
        TraceInputError: ``report`` 不是 ``NativeValidationReport``。
    """
    if not isinstance(report, NativeValidationReport):
        raise TraceInputError("report must be a NativeValidationReport")
    if not report.valid:
        return None
    phases = (group.expected_phase_rad for group in report.groups)
    if all(phase is None or phase == 0 for phase in phases):
        return EquivLevel.EXACT
    return EquivLevel.UP_TO_PHASE


# --- codec ----------------------------------------------------------------------------
