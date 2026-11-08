# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L0 采样波形层的不可修改记录与 L0 规则。

样本是实值实验室系输出，每个通道存为 f64le 字节。时间为整数 ns，采样率为整数 Hz。
记录在构造时检查全部规则，解码器经同一构造入口。
"""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Literal, cast

from qaiji.core._codec import canonical_json, f64_to_hex, json_pointer

from .errors import _fail

WAVEFORM_SCHEMA = "qaiji.waveform/0.2"
NS_PER_SECOND = 10**9

_REFERENCE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_INT64 = 1 << 63
# The decoder accepts 32 levels. The root, the transforms array and a transform use 3 of them.
_PARAMS_DEPTH = 29


def _int(value: Any, path: str, minimum: int, code: str = "INTEGER") -> int:
    if type(value) is not int or not -_INT64 <= value < _INT64:
        _fail("INTEGER", path, "Expected a signed64 integer.")
    if value < minimum:
        _fail(code, path, f"Expected an integer of at least {minimum}.")
    return cast(int, value)


def _unicode(value: str, path: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        _fail("UNICODE", path, "Expected Unicode scalar values.")
    return value


def _text(value: Any, path: str) -> str:
    if type(value) is not str or not value:
        _fail("TEXT", path, "Expected nonempty text.")
    return _unicode(value, path)


def _pair(value: Any) -> bool:
    return type(value) in (list, tuple) and len(value) == 2


def _records[T](value: Any, cls: type[T], path: str) -> tuple[T, ...]:
    if type(value) not in (list, tuple):
        _fail("TYPE", path, "Expected a list or tuple.")
    for index, item in enumerate(value):
        if type(item) is not cls:
            _fail("TYPE", f"{path}/{index}", f"Expected {cls.__name__}.")
    return tuple(value)


def _set(obj: Any, name: str, value: Any) -> None:
    object.__setattr__(obj, name, value)


def _freeze(value: Any, path: str) -> Any:
    if value is None or type(value) is bool:
        return value
    if type(value) is str:
        return _unicode(value, path)
    if type(value) is int:
        if not -_INT64 <= value < _INT64:
            _fail("PARAMS", path, "Expected a signed64 integer.")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail("PARAMS", path, "Expected a finite number.")
        return value
    if type(value) in (list, tuple):
        return tuple(_freeze(child, json_pointer(path, i)) for i, child in enumerate(value))
    if type(value) in (dict, MappingProxyType):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if type(key) is not str or key.startswith("$"):
                _fail("PARAMS", json_pointer(path, str(key)), "Keys are text without a leading $.")
            _unicode(key, json_pointer(path, key))
            result[key] = _freeze(child, json_pointer(path, key))
        return MappingProxyType(result)
    _fail("PARAMS", path, "Expected a JSON value.")


def _encoded(value: Any) -> Any:
    """把冻结树转为可编码的 JSON 树：浮点写为 ``{"$f64": hex}``。"""
    if type(value) is float:
        return {"$f64": f64_to_hex(value)}
    if type(value) is tuple:
        return [_encoded(child) for child in value]
    if type(value) is MappingProxyType:
        return {key: _encoded(child) for key, child in value.items()}
    return value


def _depth(value: Any) -> int:
    if type(value) is dict:
        return 1 + max(map(_depth, value.values()), default=0)
    if type(value) is list:
        return 1 + max(map(_depth, value), default=0)
    return 0


@dataclass(frozen=True, slots=True, kw_only=True)
class Channel:
    """DAC 实值输出通道。一个通道复用多个端口时，``ports`` 列出全部端口。"""

    id: str
    kind: Literal["dac_real"]
    ports: tuple[str, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _text(self.id, "/id")
        if type(self.kind) is not str or self.kind != "dac_real":
            _fail("KIND", "/kind", "Expected dac_real.")
        ports = self.ports
        if (
            type(ports) not in (list, tuple)
            or not ports
            or any(type(port) is not str or not port for port in ports)
            or len(set(ports)) != len(ports)
        ):
            _fail("PORTS", "/ports", "Expected nonempty, distinct port ids.")
        for index, port in enumerate(ports):
            _unicode(port, f"/ports/{index}")
        _set(self, "ports", tuple(ports))


@dataclass(frozen=True, slots=True, kw_only=True)
class Segment:
    """一段采样。第 k 个样本对应时刻 ``time_origin_ns + k · 1e9 / sample_rate_hz``。

    ``branch`` 按事件顺序保存全部先前测量的 ``(event_id, bit)``。根段使用空元组。
    ``samples`` 按通道 id 升序，每个通道的值为 f64le 字节。
    """

    id: str
    time_origin_ns: int
    branch: tuple[tuple[str, int], ...]
    samples: tuple[tuple[str, bytes], ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _text(self.id, "/id")
        _int(self.time_origin_ns, "/time_origin_ns", 0, "TIME")
        if type(self.branch) not in (list, tuple):
            _fail("BRANCH", "/branch", "Branch history must be a sequence.")
        events: set[str] = set()
        history: list[tuple[str, int]] = []
        for pair in self.branch:
            if not _pair(pair) or type(pair[0]) is not str or not pair[0]:
                _fail("BRANCH", "/branch", "Each branch entry must contain an event id and a bit.")
            event, bit = pair
            _unicode(event, "/branch")
            if type(bit) is not int or bit not in (0, 1):
                _fail("BRANCH", "/branch", "A measurement bit must be integer 0 or 1.")
            if event in events:
                _fail("BRANCH_EVENTS", "/branch", "A branch history must not repeat an event.")
            events.add(event)
            history.append((event, bit))
        _set(self, "branch", tuple(history))
        if type(self.samples) not in (list, tuple):
            _fail("TYPE", "/samples", "Expected a list or tuple.")
        previous: str | None = None
        for index, item in enumerate(self.samples):
            path = f"/samples/{index}"
            if not _pair(item) or type(item[0]) is not str or type(item[1]) is not bytes:
                _fail("SAMPLES", path, "Expected (channel_id, f64le bytes).")
            channel, data = item
            if not channel or len(data) % 8:
                _fail("SAMPLES", path, "Expected a channel id and whole binary64 values.")
            _unicode(channel, path)
            if not all(math.isfinite(value) for (value,) in struct.iter_unpack("<d", data)):
                _fail("NONFINITE", path, "Expected finite binary64 samples.")
            if previous is not None and channel <= previous:
                _fail("ORDER", path, "Channel ids must be unique and sorted.")
            previous = channel
        _set(self, "samples", tuple((channel, data) for channel, data in self.samples))


@dataclass(frozen=True, slots=True, kw_only=True)
class TransformRecord:
    """L1→L0 变换链中的一步，如包络恢复、上采样或上变频。

    ``params`` 是冻结 JSON 树：对象为只读映射，数组为 tuple，浮点有限。键不以 ``$`` 开头。
    编码后的嵌套不超过 29 层。相等按 ``params`` 的规范字节比较，所以 ``True``、``1`` 与
    ``1.0`` 互不相等，``0.0`` 与 ``-0.0`` 也不相等。
    """

    kind: str
    params: Mapping[str, Any] = field(compare=False)
    _params_json: bytes = field(init=False, repr=False)
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _text(self.kind, "/kind")
        if type(self.params) not in (dict, MappingProxyType):
            _fail("PARAMS", "/params", "Expected a JSON object.")
        params = _freeze(self.params, "/params")
        tree = _encoded(params)
        if _depth(tree) > _PARAMS_DEPTH:
            _fail("PARAMS", "/params", f"Nesting exceeds {_PARAMS_DEPTH} levels.")
        _set(self, "params", params)
        _set(self, "_params_json", canonical_json(tree))


@dataclass(frozen=True, slots=True, kw_only=True)
class WaveformIR:
    """L0 程序：全部通道共用一个整数采样率。

    ``segments`` 保留完整分支树。每层测量分出整数位 0 与 1。
    ``channels`` 按 id 升序。
    """

    source_pulse_ref: str
    sample_rate_hz: int
    channels: tuple[Channel, ...]
    segments: tuple[Segment, ...]
    transforms: tuple[TransformRecord, ...]
    schema: str = WAVEFORM_SCHEMA
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        if self.schema != WAVEFORM_SCHEMA:
            _fail("SCHEMA", "/schema", f"Expected schema {WAVEFORM_SCHEMA}.")
        ref = self.source_pulse_ref
        if type(ref) is not str or not _REFERENCE.fullmatch(ref):
            _fail("REFERENCE", "/source_pulse_ref", "Expected a lowercase sha256 reference.")
        rate = self.sample_rate_hz
        if type(rate) is not int or not 1 <= rate < _INT64:
            _fail("RATE", "/sample_rate_hz", "Expected a positive signed64 integer.")
        channels = _records(self.channels, Channel, "/channels")
        for index in range(1, len(channels)):
            if channels[index].id <= channels[index - 1].id:
                _fail("ORDER", f"/channels/{index}", "Ids must be unique and sorted.")
        segments = _records(self.segments, Segment, "/segments")
        _check_segments(segments, {channel.id for channel in channels}, rate)
        _set(self, "channels", channels)
        _set(self, "segments", segments)
        _set(self, "transforms", _records(self.transforms, TransformRecord, "/transforms"))


def _check_segments(segments: tuple[Segment, ...], declared: set[str], rate: int) -> None:
    ids: set[str] = set()
    branches: dict[tuple[tuple[str, int], ...], int] = {}
    events_by_depth: dict[int, tuple[str, ...]] = {}
    for index, segment in enumerate(segments):
        path = f"/segments/{index}"
        if segment.id in ids:
            _fail("SEGMENT_ID", path + "/id", "Segment ids must be unique.")
        ids.add(segment.id)
        if segment.time_origin_ns * rate % NS_PER_SECOND:
            _fail("ALIGN", path + "/time_origin_ns", "The origin is not on the sample grid.")
        for position, (channel, _) in enumerate(segment.samples):
            if channel not in declared:
                _fail("CHANNEL_REF", f"{path}/samples/{position}", "Undeclared channel.")
        events = tuple(event for event, _ in segment.branch)
        depth = len(events)
        if events_by_depth.setdefault(depth, events) != events:
            _fail(
                "BRANCH_EVENTS",
                path + "/branch",
                "Branches at the same depth must use the same event sequence.",
            )
        if segment.branch in branches:
            _fail("BRANCH", path + "/branch", "Branch histories must be unique.")
        branches[segment.branch] = index
    maximum = max(map(len, branches), default=0)
    for branch, index in branches.items():
        path = f"/segments/{index}/branch"
        if branch:
            if branch[:-1] not in branches:
                _fail("BRANCH", path, "A branch is missing its parent prefix.")
            event, bit = branch[-1]
            if (*branch[:-1], (event, 1 - bit)) not in branches:
                _fail("BRANCH", path, "A branch is missing its sibling.")
    child_counts: dict[tuple[tuple[str, int], ...], int] = {}
    for branch in branches:
        if branch:
            child_counts[branch[:-1]] = child_counts.get(branch[:-1], 0) + 1
    for branch, index in branches.items():
        if len(branch) < maximum and child_counts.get(branch, 0) != 2:
            _fail(
                "BRANCH",
                f"/segments/{index}/branch",
                "A non-leaf segment must retain both children.",
            )
