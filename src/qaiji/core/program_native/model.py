# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Immutable invocation bindings and output references."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from qaiji.core.native import NativeScheduleIR, NativeValidationReport, ScheduleConfig
from qaiji.core.native.model import _copy, _identifier, _objects, _optional, _set, _text, _uint
from qaiji.exceptions import QaijiIRError


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeBinding:
    schedule: NativeScheduleIR
    config: ScheduleConfig
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "schedule", lambda v, p: _copy(v, NativeScheduleIR, p))
        _set(self, "config", lambda v, p: _copy(v, ScheduleConfig, p))


@dataclass(frozen=True, slots=True, kw_only=True)
class InvocationEventRef:
    invocation_index: int
    event_id: str
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "invocation_index", _uint)
        _set(self, "event_id", _text)


@dataclass(frozen=True, slots=True, kw_only=True)
class FinalBitBinding:
    bit_index: int
    event: InvocationEventRef
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "bit_index", _uint)
        _set(self, "event", lambda v, p: _copy(v, InvocationEventRef, p))


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputMeasurementBinding:
    invocation_index: int
    register_name: str
    history: tuple[InvocationEventRef, ...]
    final_bits: tuple[FinalBitBinding, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "invocation_index", _uint)
        _set(self, "register_name", _identifier)
        _set(self, "history", _objects(InvocationEventRef))
        _set(self, "final_bits", _objects(FinalBitBinding))


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgramNativeMap:
    outputs: tuple[OutputMeasurementBinding, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "outputs", _objects(OutputMeasurementBinding))


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgramNativeIssue:
    invocation_index: int
    code: str
    native_report: NativeValidationReport | None
    input_code: str | None
    input_path: str | None
    message: str
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "invocation_index", _uint)
        for name in ("code", "message"):
            _set(self, name, _text)
        _set(self, "native_report", _optional(lambda v, p: _copy(v, NativeValidationReport, p)))
        for name in ("input_code", "input_path"):
            _set(self, name, _optional(_text))


class ProgramNativeValidationError(QaijiIRError):
    """程序调用的原生调度绑定或认证失败。"""

    def __init__(self, issues: Sequence[ProgramNativeIssue]) -> None:
        self.issues = tuple(
            _copy(issue, ProgramNativeIssue, f"$.issues[{index}]")
            for index, issue in enumerate(issues)
        )
        super().__init__("Program native validation failed.")
