# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Reauthenticated neutral operation projections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar

from qaiji.core.circuit import Circuit

from .config import ScheduleConfig
from .diagnostics import NativeValidationError
from .model import (
    ConditionRegion,
    MeasurementEvent,
    NativeOperation,
    NativeScheduleIR,
    _copy,
    _fail,
    _objects,
    _optional,
    _sequence,
    _set,
    _text,
    _uint,
)
from .source import _capture_source
from .validation import _validate_snapshot


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectedOperation:
    operation_index: int
    operation: NativeOperation
    labels: tuple[str, ...]
    event_id: str | None
    result_ready_ns: int | None
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "operation_index", _uint)
        _set(self, "operation", lambda v, p: _copy(v, NativeOperation, p))
        _set(self, "labels", lambda v, p: _sequence(v, p, _text))
        _set(self, "event_id", _optional(_text))
        _set(self, "result_ready_ns", _optional(_uint))


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeProjection:
    source_kernel_ref: str
    operations: tuple[ProjectedOperation, ...]
    conditions: tuple[ConditionRegion, ...]
    events: tuple[MeasurementEvent, ...]
    end_ns: int
    all_results_ready_ns: int
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "source_kernel_ref", _text)
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_kernel_ref) is None:
            _fail("ref", "$.source_kernel_ref", "Invalid source kernel reference.")
        _set(self, "operations", _objects(ProjectedOperation))
        _set(self, "conditions", _objects(ConditionRegion))
        _set(self, "events", _objects(MeasurementEvent))
        _set(self, "end_ns", _uint)
        _set(self, "all_results_ready_ns", _uint)


def _labels(kind: str) -> tuple[str, ...]:
    if kind == "I":
        return ("IDLE",)
    if kind in ("Z", "RZ"):
        return ("VIRTUAL_PHASE",)
    if kind in ("RX90", "CZ"):
        return ("PULSE",)
    if kind == "MEASURE":
        return ("PULSE_READOUT", "REGISTER_RESULT")
    _fail("enum", "$.kind", "Unknown native operation kind.")


def qubic_mapping(
    circuit: Circuit, schedule: NativeScheduleIR, config: ScheduleConfig
) -> NativeProjection:
    """重新捕获并认证电路来源，再构造中性操作记录。"""
    snapshot = _capture_source(circuit)
    candidate = _copy(schedule, NativeScheduleIR, "$")
    configuration = _copy(config, ScheduleConfig, "$")
    report = _validate_snapshot(snapshot, candidate, configuration)
    if not report.valid:
        raise NativeValidationError(report)
    events = {event.operation_index: event for event in candidate.events}
    operations = []
    for index, operation in enumerate(candidate.operations):
        event = events.get(index)
        operations.append(
            ProjectedOperation(
                operation_index=index,
                operation=operation,
                labels=_labels(operation.kind),
                event_id=event.event_id if event is not None else None,
                result_ready_ns=event.ready_ns if event is not None else None,
            )
        )
    assert report.all_results_ready_ns is not None
    return NativeProjection(
        source_kernel_ref=candidate.source_kernel_ref,
        operations=tuple(operations),
        conditions=candidate.conditions,
        events=candidate.events,
        end_ns=candidate.end_ns,
        all_results_ready_ns=report.all_results_ready_ns,
    )
