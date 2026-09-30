# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Convenient authenticated native lowering."""

from qaiji.core.circuit import Circuit

from .config import ScheduleConfig
from .diagnostics import CheckResult, NativeValidationError, NativeValidationReport
from .model import NativeScheduleIR, _copy
from .rules import _expand_source
from .scheduler import _schedule_source, _SchedulingError
from .source import _capture_source
from .validation import _result, _validate_snapshot


def lower_to_native(circuit: Circuit, config: ScheduleConfig) -> NativeScheduleIR:
    """从同一份电路快照生成原生调度，并独立认证其内容。"""
    snapshot = _capture_source(circuit)
    configuration = _copy(config, ScheduleConfig, "$")
    groups = _expand_source(snapshot)
    try:
        schedule = _schedule_source(snapshot, configuration, groups)
    except _SchedulingError as error:
        pending = CheckResult(status="not_run", issues=())
        report = NativeValidationReport(
            source=_result(),
            rules=pending,
            hp=pending,
            schedule=_result(error.code, error.path, error.source, error.operation_index),
            groups=(),
            all_results_ready_ns=None,
        )
        raise NativeValidationError(report) from error
    report = _validate_snapshot(snapshot, schedule, configuration)
    if not report.valid:
        raise NativeValidationError(report)
    return schedule
