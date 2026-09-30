# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Immutable native schedule declarations."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any, ClassVar, NoReturn, cast

from .errors import NativeInputError

NATIVE_SCHEDULE_SCHEMA_VERSION = "qaiji.native_schedule.v0"
NATIVE_RULESET_VERSION = "qaiji.cz_basis.v0"


_LIMIT = 10**4096
_KINDS = ("I", "Z", "RZ", "RX90", "CZ", "MEASURE")


def _fail(code: str, path: str, message: str) -> NoReturn:
    raise NativeInputError(code, path, message)


def _uint(value: Any, path: str, positive: bool = False) -> int:
    if type(value) is not int:
        _fail("integer", path, "Expected a built-in integer.")
    if value < int(positive) or value >= _LIMIT:
        _fail("range", path, "Integer outside the supported range.")
    return cast(int, value)


def _number(value: Any, path: str) -> float:
    if type(value) not in (int, float):
        _fail("number", path, "Expected a finite built-in number.")
    try:
        result = float(value)
    except OverflowError:
        _fail("number", path, "Number cannot be represented as binary64.")
    if not math.isfinite(result):
        _fail("number", path, "Expected a finite number.")
    return result


def _text(value: Any, path: str) -> str:
    if type(value) is not str:
        _fail("type", path, "Expected a built-in string.")
    if not value:
        _fail("text", path, "Expected nonempty text.")
    return cast(str, value)


def _identifier(value: Any, path: str) -> str:
    result = _text(value, path)
    if not result.isidentifier():
        _fail("identifier", path, "Expected a register identifier.")
    return result


def _sequence(value: Any, path: str, convert: Callable[[Any, str], Any]) -> tuple[Any, ...]:
    if type(value) not in (list, tuple):
        _fail("container", path, "Expected a list or tuple.")
    return tuple(convert(item, f"{path}[{i}]") for i, item in enumerate(value))


def _copy[T](value: Any, cls: type[T], path: str) -> T:
    if not isinstance(value, cls):
        _fail("type", path, f"Expected {cls.__name__}.")
    try:
        return cls(**{field.name: getattr(value, field.name) for field in fields(cls)})  # type: ignore[arg-type]
    except NativeInputError as error:
        raise NativeInputError(error.code, path + error.path[1:], str(error)) from error


def _set(obj: Any, name: str, convert: Callable[[Any, str], Any]) -> None:
    object.__setattr__(obj, name, convert(getattr(obj, name), "$." + name))


def _optional(convert: Callable[[Any, str], Any]) -> Callable[[Any, str], Any]:
    return lambda value, path: None if value is None else convert(value, path)


def _objects[T](cls: type[T]) -> Callable[[Any, str], tuple[T, ...]]:
    return lambda value, path: _sequence(value, path, lambda item, at: _copy(item, cls, at))


def _kind(value: Any, path: str) -> str:
    result = _text(value, path)
    if result not in _KINDS:
        _fail("enum", path, "Unknown native operation kind.")
    return result


def _qubits(value: Any, path: str) -> tuple[int, ...]:
    return _sequence(value, path, _uint)


def _resources(value: Any, path: str) -> tuple[str, ...]:
    result = _sequence(value, path, _text)
    if not result or len(set(result)) != len(result):
        _fail("resources", path, "Resources must be nonempty and distinct.")
    return result


def _operands(kind: str, qubits: tuple[int, ...]) -> None:
    if len(qubits) != (2 if kind == "CZ" else 1):
        _fail("arity", "$.qubits", "Incorrect number of qubits.")
    if len(set(qubits)) != len(qubits):
        _fail("arity", "$.qubits", "Qubits must be distinct.")


def _duration(kind: str, duration: int) -> None:
    if (kind in ("I", "Z", "RZ")) != (duration == 0):
        _fail("duration", "$.duration_ns", "Duration does not match operation kind.")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceLocation:
    gate_index: int
    body_offset: int | None
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "gate_index", _uint)
        _set(self, "body_offset", _optional(_uint))


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisterDecl:
    name: str
    size: int
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "name", _identifier)
        _set(self, "size", lambda v, p: _uint(v, p, True))


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeOperation:
    kind: str
    qubits: tuple[int, ...]
    params: tuple[float, ...]
    source: SourceLocation
    ordinal: int
    start_ns: int
    duration_ns: int
    resources: tuple[str, ...]
    condition_id: str | None
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "kind", _kind)
        _set(self, "qubits", _qubits)
        _set(self, "params", lambda v, p: _sequence(v, p, _number))
        _set(self, "source", lambda v, p: _copy(v, SourceLocation, p))
        for name in ("ordinal", "start_ns", "duration_ns"):
            _set(self, name, _uint)
        _set(self, "resources", _resources)
        _set(self, "condition_id", _optional(_text))
        _operands(self.kind, self.qubits)
        if len(self.params) != int(self.kind in ("RZ", "RX90")):
            _fail("arity", "$.params", "Incorrect number of parameters.")
        for i, angle in enumerate(self.params):
            if abs(angle) > math.tau:
                _fail("range", f"$.params[{i}]", "Angle outside the supported range.")
        _duration(self.kind, self.duration_ns)
        if self.kind == "MEASURE" and self.source.body_offset is not None:
            _fail("event", "$.source", "Conditional bodies cannot measure.")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceGroup:
    source: SourceLocation
    rule_id: str
    op_start: int
    op_stop: int
    phase_rad: float
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "source", lambda v, p: _copy(v, SourceLocation, p))
        _set(self, "rule_id", _text)
        _set(self, "op_start", _uint)
        _set(self, "op_stop", _uint)
        _set(self, "phase_rad", _number)
        if self.op_stop <= self.op_start:
            _fail("span", "$.op_stop", "Groups must contain operations.")


@dataclass(frozen=True, slots=True, kw_only=True)
class MeasurementEvent:
    event_id: str
    source: SourceLocation
    operation_index: int
    qubit: int
    register_name: str
    bit_index: int
    end_ns: int
    ready_ns: int
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "event_id", _text)
        _set(self, "source", lambda v, p: _copy(v, SourceLocation, p))
        _set(self, "register_name", _identifier)
        for name in ("operation_index", "qubit", "bit_index", "end_ns", "ready_ns"):
            _set(self, name, _uint)
        if self.source.body_offset is not None:
            _fail("event", "$.source", "Conditional bodies cannot measure.")
        if self.ready_ns < self.end_ns:
            _fail("event", "$.ready_ns", "A result cannot be ready before measurement ends.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ConditionRead:
    bit_index: int
    event_id: str
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "bit_index", _uint)
        _set(self, "event_id", _text)


@dataclass(frozen=True, slots=True, kw_only=True)
class ConditionRegion:
    condition_id: str
    gate_index: int
    register_name: str
    width: int
    value: int
    reads: tuple[ConditionRead, ...]
    op_start: int
    op_stop: int
    start_ns: int
    end_ns: int
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "condition_id", _text)
        _set(self, "register_name", _identifier)
        for name in ("gate_index", "value", "op_start", "op_stop", "start_ns", "end_ns"):
            _set(self, name, _uint)
        _set(self, "width", lambda v, p: _uint(v, p, True))
        _set(self, "reads", _objects(ConditionRead))
        if self.condition_id != f"c{self.gate_index}":
            _fail("condition_id", "$.condition_id", "Condition ID must match its source index.")
        if self.value.bit_length() > self.width:
            _fail("condition_value", "$.value", "Condition value exceeds register width.")
        if len(self.reads) != self.width or any(
            read.bit_index != i for i, read in enumerate(self.reads)
        ):
            _fail("read_bits", "$.reads", "Reads must contain each bit in register order.")
        if self.op_stop < self.op_start:
            _fail("span", "$.op_stop", "Reversed operation span.")
        if self.end_ns < self.start_ns:
            _fail("span", "$.end_ns", "Reversed time span.")


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeScheduleIR:
    source_kernel_ref: str
    num_qubits: int
    registers: tuple[RegisterDecl, ...]
    operations: tuple[NativeOperation, ...]
    groups: tuple[SourceGroup, ...]
    events: tuple[MeasurementEvent, ...]
    conditions: tuple[ConditionRegion, ...]
    end_ns: int
    schema_version: str = NATIVE_SCHEDULE_SCHEMA_VERSION
    ruleset_version: str = NATIVE_RULESET_VERSION
    __hash__: ClassVar[Any] = None

    def to_json(self) -> str:
        """Serialize a revalidated projection of the declared schedule fields."""
        from .jsonio import to_json

        return to_json(self)

    @staticmethod
    def from_json(text: str) -> NativeScheduleIR:
        """Restore a complete schedule from strict JSON text."""
        from .jsonio import from_json

        return from_json(text)

    def __post_init__(self) -> None:
        for name in ("schema_version", "ruleset_version", "source_kernel_ref"):
            _set(self, name, _text)
        if self.schema_version != NATIVE_SCHEDULE_SCHEMA_VERSION:
            _fail("enum", "$.schema_version", "Unknown schedule schema version.")
        if self.ruleset_version != NATIVE_RULESET_VERSION:
            _fail("enum", "$.ruleset_version", "Unknown native ruleset version.")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_kernel_ref) is None:
            _fail("ref", "$.source_kernel_ref", "Invalid source kernel reference.")
        _set(self, "num_qubits", lambda v, p: _uint(v, p, True))
        _set(self, "end_ns", _uint)
        for name, cls in (
            ("registers", RegisterDecl),
            ("operations", NativeOperation),
            ("groups", SourceGroup),
            ("events", MeasurementEvent),
            ("conditions", ConditionRegion),
        ):
            _set(self, name, _objects(cls))
        _schedule_graph(self)


def _schedule_graph(schedule: NativeScheduleIR) -> None:
    registers: dict[str, int] = {}
    for i, register in enumerate(schedule.registers):
        if register.name in registers:
            _fail("duplicate_register", f"$.registers[{i}].name", "Duplicate register.")
        registers[register.name] = register.size
    for i, op in enumerate(schedule.operations):
        for j, qubit in enumerate(op.qubits):
            if qubit >= schedule.num_qubits:
                _fail(
                    "qubit_range", f"$.operations[{i}].qubits[{j}]", "Qubit outside the schedule."
                )
    _group_graph(schedule)
    _event_graph(schedule, registers)
    _condition_graph(schedule, registers)
    if not schedule.operations and schedule.end_ns != 0:
        _fail("span", "$.end_ns", "An empty schedule must end at zero.")


def _group_graph(schedule: NativeScheduleIR) -> None:
    cursor = 0
    sources: set[tuple[int, int | None]] = set()
    for i, group in enumerate(schedule.groups):
        path = f"$.groups[{i}]"
        key = (group.source.gate_index, group.source.body_offset)
        if key in sources:
            _fail("duplicate_source", path + ".source", "Duplicate group source.")
        sources.add(key)
        if group.op_start != cursor:
            _fail("group_reference", path + ".op_start", "Group spans must be contiguous.")
        if group.op_stop > len(schedule.operations):
            _fail("group_reference", path + ".op_stop", "Group span exceeds operations.")
        for ordinal, index in enumerate(range(group.op_start, group.op_stop)):
            operation = schedule.operations[index]
            if operation.source != group.source:
                _fail(
                    "group_reference",
                    f"$.operations[{index}].source",
                    "Operation source differs from its group.",
                )
            if operation.ordinal != ordinal:
                _fail(
                    "group_reference", f"$.operations[{index}].ordinal", "Incorrect group ordinal."
                )
        cursor = group.op_stop
    if cursor != len(schedule.operations):
        _fail("group_reference", "$.groups", "Groups must cover all operations.")


def _event_graph(schedule: NativeScheduleIR, registers: dict[str, int]) -> None:
    ids: set[str] = set()
    measured: set[int] = set()
    for i, event in enumerate(schedule.events):
        path = f"$.events[{i}]"
        if event.event_id in ids:
            _fail("duplicate_event", path + ".event_id", "Duplicate event ID.")
        ids.add(event.event_id)
        if event.event_id != f"m{i}":
            _fail("event", path + ".event_id", "Event IDs must follow list order.")
        if event.operation_index >= len(schedule.operations) or event.operation_index in measured:
            _fail(
                "event_reference",
                path + ".operation_index",
                "Invalid or repeated measurement reference.",
            )
        operation = schedule.operations[event.operation_index]
        if operation.kind != "MEASURE":
            _fail(
                "event_reference", path + ".operation_index", "Event must refer to a measurement."
            )
        if event.qubit != operation.qubits[0]:
            _fail("event_reference", path + ".qubit", "Event qubit differs from measurement.")
        if event.source != operation.source:
            _fail("event_reference", path + ".source", "Event source differs from measurement.")
        measured.add(event.operation_index)
        if event.register_name not in registers:
            _fail("register_reference", path + ".register_name", "Unknown register.")
        if event.bit_index >= registers[event.register_name]:
            _fail("register_reference", path + ".bit_index", "Bit outside register.")
    if measured != {i for i, op in enumerate(schedule.operations) if op.kind == "MEASURE"}:
        _fail("event_reference", "$.events", "Every measurement requires one event.")


def _condition_graph(schedule: NativeScheduleIR, registers: dict[str, int]) -> None:
    regions: dict[str, ConditionRegion] = {}
    events = {event.event_id for event in schedule.events}
    for i, region in enumerate(schedule.conditions):
        path = f"$.conditions[{i}]"
        if region.condition_id in regions:
            _fail("duplicate_condition", path + ".condition_id", "Duplicate condition ID.")
        regions[region.condition_id] = region
        if region.register_name not in registers:
            _fail("register_reference", path + ".register_name", "Unknown register.")
        if region.width != registers[region.register_name]:
            _fail("register_reference", path + ".width", "Condition width differs from register.")
        if region.op_stop > len(schedule.operations):
            _fail("condition_reference", path + ".op_stop", "Condition span exceeds operations.")
        for j, read in enumerate(region.reads):
            if read.event_id not in events:
                _fail(
                    "event_reference", f"{path}.reads[{j}].event_id", "Unknown measurement event."
                )
        for index in range(region.op_start, region.op_stop):
            op = schedule.operations[index]
            if op.condition_id != region.condition_id:
                _fail(
                    "condition_reference",
                    f"$.operations[{index}].condition_id",
                    "Condition span and operation ID differ.",
                )
    for i, op in enumerate(schedule.operations):
        path = f"$.operations[{i}]"
        if op.condition_id is None:
            if op.source.body_offset is not None:
                _fail(
                    "condition_reference",
                    path + ".condition_id",
                    "Body operation requires a condition.",
                )
            continue
        matched = regions.get(op.condition_id)
        if matched is None:
            _fail("condition_reference", path + ".condition_id", "Unknown condition.")
        if not matched.op_start <= i < matched.op_stop:
            _fail(
                "condition_reference",
                path + ".condition_id",
                "Operation outside its condition span.",
            )
        if op.source.gate_index != matched.gate_index or op.source.body_offset is None:
            _fail(
                "condition_reference",
                path + ".source",
                "Operation source differs from condition body.",
            )
