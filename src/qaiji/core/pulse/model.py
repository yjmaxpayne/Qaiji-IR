# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1 脉冲层的不可修改记录与程序不变量。

时间为整数 ns，频率为整数 Hz，相位为 rad，幅度为 [-1, 1]。所有记录带绝对时间。
程序在构造时检查全部不变量，解码器经同一构造入口。
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, cast

from .errors import _fail
from .phase import phases_equal

PULSE_SCHEMA = "qaiji.pulse/0.1"
_ROLES = ("drive", "readout", "acquire", "flux", "coupler_flux")
_FLUX_ROLES = ("flux", "coupler_flux")
_ORIGINS = ("gate", "correction")
_SHAPES: dict[str, tuple[str, ...]] = {
    "constant": (),
    "gaussian": ("rel_sigma",),
    "drag": ("rel_sigma", "beta_ns"),
}
_REFERENCE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_INT64 = 1 << 63


def _int(value: Any, path: str, minimum: int, code: str = "INTEGER") -> int:
    if type(value) is not int or not -_INT64 <= value < _INT64:
        _fail("INTEGER", path, "Expected a signed64 integer.")
    if value < minimum:
        _fail(code, path, f"Expected an integer of at least {minimum}.")
    return cast(int, value)


def _real(value: Any, path: str) -> float:
    if type(value) not in (int, float):
        _fail("NUMBER", path, "Expected a real number.")
    try:
        result = float(value)
    except OverflowError:
        _fail("NONFINITE", path, "Number exceeds binary64 range.")
    if not math.isfinite(result):
        _fail("NONFINITE", path, "Expected a finite number.")
    return result


def _text(value: Any, path: str) -> str:
    if type(value) is not str or not value:
        _fail("TEXT", path, "Expected nonempty text.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        _fail("UNICODE", path, "Expected Unicode scalar values.")
    return cast(str, value)


def _choice(value: Any, options: tuple[str, ...], path: str, code: str) -> str:
    if type(value) is not str or value not in options:
        _fail(code, path, "Expected one of: " + ", ".join(options) + ".")
    return cast(str, value)


def _optional(value: Any, check: Callable[[Any, str], Any], path: str) -> None:
    if value is not None:
        check(value, path)


def _sequence(value: Any, path: str) -> tuple[Any, ...]:
    if type(value) not in (list, tuple):
        _fail("TYPE", path, "Expected a list or tuple.")
    return tuple(value)


def _set(obj: Any, name: str, value: Any) -> None:
    object.__setattr__(obj, name, value)


@dataclass(frozen=True, slots=True, kw_only=True)
class Port:
    """物理信号端口。``targets`` 是端口作用的比特，非空且互不相同。"""

    id: str
    role: Literal["drive", "readout", "acquire", "flux", "coupler_flux"]
    targets: tuple[int, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _text(self.id, "/id")
        _choice(self.role, _ROLES, "/role", "ROLE")
        targets = self.targets
        if (
            type(targets) not in (list, tuple)
            or not targets
            or any(type(q) is not int or not 0 <= q < _INT64 for q in targets)
            or len(set(targets)) != len(targets)
        ):
            _fail("TARGETS", "/targets", "Expected nonempty, distinct, nonnegative qubits.")
        _set(self, "targets", tuple(targets))


@dataclass(frozen=True, slots=True, kw_only=True)
class Frame:
    """端口上的载波帧。``phase_rad`` 是程序时间 0 的帧相位。"""

    id: str
    port: str
    frequency_hz: int
    phase_rad: float
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _text(self.id, "/id")
        _text(self.port, "/port")
        _int(self.frequency_hz, "/frequency_hz", -_INT64)
        _set(self, "phase_rad", _real(self.phase_rad, "/phase_rad"))


@dataclass(frozen=True, slots=True, kw_only=True)
class Envelope:
    """连续时间包络。``constant`` 无参数，``gaussian`` 需 ``rel_sigma``，``drag`` 另需 ``beta_ns``。"""

    shape: Literal["constant", "gaussian", "drag"]
    rel_sigma: float | None = None
    beta_ns: float | None = None
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        shape = _choice(self.shape, tuple(_SHAPES), "/shape", "ENVELOPE")
        for name in ("rel_sigma", "beta_ns"):
            value = getattr(self, name)
            if (name in _SHAPES[shape]) != (value is not None):
                _fail("ENVELOPE", "/" + name, f"Field does not match envelope shape {shape}.")
            if value is not None:
                _set(self, name, _real(value, "/" + name))
        if self.rel_sigma is not None and self.rel_sigma <= 0:
            _fail("ENVELOPE", "/rel_sigma", "Expected a positive rel_sigma.")


@dataclass(frozen=True, slots=True, kw_only=True)
class Play:
    """在帧上播放一个包络。``phase_rad`` 相对于帧，载波相位由帧给出。"""

    frame: str
    start_ns: int
    duration_ns: int
    envelope: Envelope
    amplitude: float
    phase_rad: float
    condition_id: str | None = None
    source: int | None = None
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _text(self.frame, "/frame")
        _int(self.start_ns, "/start_ns", 0, "TIME")
        _int(self.duration_ns, "/duration_ns", 1, "DURATION")
        if type(self.envelope) is not Envelope:
            _fail("TYPE", "/envelope", "Expected Envelope.")
        amplitude = _real(self.amplitude, "/amplitude")
        if not -1.0 <= amplitude <= 1.0:
            _fail("AMPLITUDE", "/amplitude", "Expected an amplitude in [-1, 1].")
        _set(self, "amplitude", amplitude)
        _set(self, "phase_rad", _real(self.phase_rad, "/phase_rad"))
        _optional(self.condition_id, _text, "/condition_id")
        _optional(self.source, lambda value, path: _int(value, path, 0), "/source")


@dataclass(frozen=True, slots=True, kw_only=True)
class ShiftPhase:
    """零时长的帧相位增量。``gate`` 来自 L2 的 Z、RZ，``correction`` 来自两比特门。"""

    frame: str
    at_ns: int
    delta_rad: float
    origin: Literal["gate", "correction"]
    condition_id: str | None = None
    source: int | None = None
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _text(self.frame, "/frame")
        _int(self.at_ns, "/at_ns", 0, "TIME")
        _set(self, "delta_rad", _real(self.delta_rad, "/delta_rad"))
        _choice(self.origin, _ORIGINS, "/origin", "ORIGIN")
        _optional(self.condition_id, _text, "/condition_id")
        _optional(self.source, lambda value, path: _int(value, path, 0), "/source")


@dataclass(frozen=True, slots=True, kw_only=True)
class Acquire:
    """在 acquire 端口上采集一个 L2 测量事件。"""

    port: str
    start_ns: int
    duration_ns: int
    event_id: str
    condition_id: str | None = None
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _text(self.port, "/port")
        _int(self.start_ns, "/start_ns", 0, "TIME")
        _int(self.duration_ns, "/duration_ns", 1, "DURATION")
        _text(self.event_id, "/event_id")
        _optional(self.condition_id, _text, "/condition_id")


type Instruction = Play | ShiftPhase | Acquire
_RANK: dict[type, int] = {ShiftPhase: 0, Play: 1, Acquire: 2}


@dataclass(frozen=True, slots=True, kw_only=True)
class PulseProgramIR:
    """L1 脉冲程序。构造时检查全部不变量。

    ``conditions`` 镜像 L2 的条件区间，顺序与 L2 相同，每项为 ``(condition_id, start_ns, end_ns)``。
    ``instructions`` 按 ``(时刻, 帧或端口, 种类, source)`` 严格递增：同刻同帧的
    ``ShiftPhase`` 排在 ``Play`` 前，``source`` 为 None 时排在前。

    Raises:
        PulseContractError: 记录或不变量不合法，类别为 ``INVALID_PROGRAM``。
    """

    source_schedule_ref: str
    ports: tuple[Port, ...]
    frames: tuple[Frame, ...]
    instructions: tuple[Instruction, ...]
    conditions: tuple[tuple[str, int, int], ...]
    end_ns: int
    schema: str = PULSE_SCHEMA
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        if self.schema != PULSE_SCHEMA:
            _fail("SCHEMA", "/schema", f"Expected schema {PULSE_SCHEMA}.")
        ref = self.source_schedule_ref
        if type(ref) is not str or not _REFERENCE.fullmatch(ref):
            _fail("REFERENCE", "/source_schedule_ref", "Expected a lowercase sha256 reference.")
        end = _int(self.end_ns, "/end_ns", 0, "TIME")
        ports = _declarations(self.ports, Port, "/ports")
        frames = _declarations(self.frames, Frame, "/frames")
        roles = {port.id: port.role for port in ports}
        frame_roles: dict[str, str] = {}
        for index, frame in enumerate(frames):
            if frame.port not in roles:
                _fail("PORT_REF", f"/frames/{index}/port", "Undeclared port.")
            if roles[frame.port] in _FLUX_ROLES and frame.frequency_hz != 0:
                _fail("FREQUENCY", f"/frames/{index}/frequency_hz", "Flux frames have frequency 0.")
            frame_roles[frame.id] = roles[frame.port]
        conditions, windows = _conditions(self.conditions, end)
        instructions = _sequence(self.instructions, "/instructions")
        _check_instructions(instructions, roles, frame_roles, windows, end)
        _check_condition_phase(instructions, conditions)
        _set(self, "ports", ports)
        _set(self, "frames", frames)
        _set(self, "conditions", conditions)
        _set(self, "instructions", instructions)


def _declarations[T](value: Any, cls: type[T], path: str) -> tuple[T, ...]:
    items = _sequence(value, path)
    for index, item in enumerate(items):
        if type(item) is not cls:
            _fail("TYPE", f"{path}/{index}", f"Expected {cls.__name__}.")
        if index and item.id <= items[index - 1].id:  # type: ignore[attr-defined]
            _fail("ORDER", f"{path}/{index}", "Ids must be unique and sorted.")
    return items


def _conditions(
    value: Any, end: int
) -> tuple[tuple[tuple[str, int, int], ...], dict[str, tuple[int, int]]]:
    windows: dict[str, tuple[int, int]] = {}
    result: list[tuple[str, int, int]] = []
    for index, item in enumerate(_sequence(value, "/conditions")):
        path = f"/conditions/{index}"
        if type(item) not in (list, tuple) or len(item) != 3:
            _fail("CONDITION", path, "Expected (condition_id, start_ns, end_ns).")
        cid = _text(item[0], path + "/condition_id")
        start = _int(item[1], path + "/start_ns", 0, "TIME")
        stop = _int(item[2], path + "/end_ns", 0, "TIME")
        if not start <= stop <= end:
            _fail("CONDITION", path, "Expected start_ns <= end_ns <= program end_ns.")
        if cid in windows:
            _fail("CONDITION", path, "Condition ids must be unique.")
        windows[cid] = (start, stop)
        result.append((cid, start, stop))
    return tuple(result), windows


def _check_instructions(
    items: tuple[Any, ...],
    roles: Mapping[str, str],
    frame_roles: Mapping[str, str],
    windows: dict[str, tuple[int, int]],
    end: int,
) -> None:
    events: set[str] = set()
    previous: tuple[int, str, int, int] | None = None
    for index, item in enumerate(items):
        path = f"/instructions/{index}"
        kind = type(item)
        if kind not in _RANK:
            _fail("TYPE", path, "Expected Play, ShiftPhase or Acquire.")
        if kind is Acquire:
            target = item.port
            if target not in roles:
                _fail("PORT_REF", path + "/port", "Undeclared port.")
            if roles[target] != "acquire":
                _fail("ACQUIRE_PORT", path + "/port", "Acquire needs an acquire port.")
            if item.event_id in events:
                _fail("EVENT", path + "/event_id", "Acquire event ids must be unique.")
            events.add(item.event_id)
        else:
            target = item.frame
            if target not in frame_roles:
                _fail("FRAME_REF", path + "/frame", "Undeclared frame.")
            if kind is ShiftPhase and frame_roles[target] != "drive":
                _fail("SHIFT_PORT", path + "/frame", "ShiftPhase must act on a drive frame.")
        start = item.at_ns if kind is ShiftPhase else item.start_ns
        stop = start if kind is ShiftPhase else start + item.duration_ns
        condition = item.condition_id
        if condition is not None and condition not in windows:
            _fail("CONDITION_REF", path + "/condition_id", "Undeclared condition.")
        if stop > end:
            _fail("END", path, "Instruction ends after the program end_ns.")
        if (
            condition is not None
            and not windows[condition][0] <= start <= stop <= windows[condition][1]
        ):
            _fail("WINDOW", path, "Conditional instruction lies outside its condition region.")
        source = getattr(item, "source", None)
        key = (start, target, _RANK[kind], -1 if source is None else source)
        if previous is not None and key <= previous:
            _fail(
                "ORDER",
                path,
                "Instructions must be strictly sorted by (time, target, kind, source).",
            )
        previous = key


def _check_condition_phase(
    items: tuple[Any, ...], conditions: tuple[tuple[str, int, int], ...]
) -> None:
    """每个条件区间内，每个帧上条件 ShiftPhase 的和按 2π 取模为 0。"""
    sums: dict[tuple[str, str], list[float]] = {}
    for item in items:
        if type(item) is ShiftPhase and item.condition_id is not None:
            sums.setdefault((item.condition_id, item.frame), []).append(item.delta_rad)
    for index, (cid, _, _) in enumerate(conditions):
        for (condition, frame), deltas in sorted(sums.items()):
            if condition == cid and not phases_equal(math.fsum(deltas), 0.0):
                _fail(
                    "CONDITION_PHASE",
                    f"/conditions/{index}",
                    f"Net frame phase on {frame} is not a multiple of 2*pi.",
                )
