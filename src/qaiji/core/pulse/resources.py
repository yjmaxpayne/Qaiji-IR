# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""独立端口资源映射、严格编解码与逐 Play 覆盖检查。

映射以 L1 内容身份绑定程序。映射不改变 L1 字段、字节或身份。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, cast

from qaiji.core._codec import canonical_json, sha256_ref
from qaiji.core.native import NativeScheduleIR

from .codec import (
    _array,
    _construct,
    _keys,
    _object,
    _parse,
    native_schedule_ref,
    pulse_program_id,
)
from .errors import _fail
from .model import _REFERENCE, Play, PulseProgramIR, _sequence, _set, _text

PORT_RESOURCES_SCHEMA = "qaiji.port_resources/0.1"


@dataclass(frozen=True, slots=True, kw_only=True)
class PortResourceEntry:
    """端口与非空资源名序列。资源名必须唯一，按升序排列。"""

    port: str
    resources: tuple[str, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _text(self.port, "/port")
        resources = _sequence(self.resources, "/resources")
        for index, resource in enumerate(resources):
            _text(resource, f"/resources/{index}")
        if not resources or resources != tuple(sorted(set(resources))):
            _fail("RESOURCES", "/resources", "Expected nonempty, unique, sorted resource names.")
        _set(self, "resources", resources)


@dataclass(frozen=True, slots=True, kw_only=True)
class PortResourceMap:
    """独立映射记录。条目必须按端口名升序排列，每个端口只能出现一次。"""

    pulse_program_ref: str
    entries: tuple[PortResourceEntry, ...]
    schema: str = PORT_RESOURCES_SCHEMA
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        if type(self.schema) is not str or self.schema != PORT_RESOURCES_SCHEMA:
            _fail("SCHEMA", "/schema", f"Expected schema {PORT_RESOURCES_SCHEMA}.")
        if type(self.pulse_program_ref) is not str or not _REFERENCE.fullmatch(
            self.pulse_program_ref
        ):
            _fail("REFERENCE", "/pulse_program_ref", "Expected a lowercase sha256 reference.")
        entries = _sequence(self.entries, "/entries")
        for index, entry in enumerate(entries):
            if type(entry) is not PortResourceEntry:
                _fail("TYPE", f"/entries/{index}", "Expected PortResourceEntry.")
        ports = tuple(entry.port for entry in entries)
        if ports != tuple(sorted(set(ports))):
            _fail("ORDER", "/entries", "Expected unique ports in ascending order.")
        _set(self, "entries", entries)


def dump_port_resources(mapping: PortResourceMap) -> bytes:
    """编码映射的规范 JSON 字节。

    Args:
        mapping: 独立端口资源映射。

    Returns:
        键排序且无空白的 UTF-8 JSON 字节。

    Raises:
        PulseContractError: 输入不是 PortResourceMap。
    """
    if type(mapping) is not PortResourceMap:
        _fail("TYPE", "", "Expected PortResourceMap.")
    return canonical_json(
        dict(
            schema=mapping.schema,
            pulse_program_ref=mapping.pulse_program_ref,
            entries=[dict(port=e.port, resources=list(e.resources)) for e in mapping.entries],
        )
    )


def load_port_resources(data: bytes) -> PortResourceMap:
    """严格解码映射。拒绝重复键、未知字段与无效记录。

    Args:
        data: UTF-8 JSON 字节。

    Returns:
        不可变的独立映射记录。

    Raises:
        PulseContractError: JSON、字段、版本或映射不合法。路径为 JSON Pointer。
    """
    root = _object(_parse(data), "")
    _keys(root, ("schema", "pulse_program_ref", "entries"), "")
    entries = []
    for index, item in enumerate(_array(root["entries"], "/entries")):
        path = f"/entries/{index}"
        record = _object(item, path)
        _keys(record, ("port", "resources"), path)
        resources = _array(record["resources"], path + "/resources")
        entries.append(
            _construct(PortResourceEntry, dict(port=record["port"], resources=resources), path)
        )
    return cast(
        PortResourceMap,
        _construct(
            PortResourceMap,
            dict(
                schema=root["schema"], pulse_program_ref=root["pulse_program_ref"], entries=entries
            ),
            "",
        ),
    )


def port_resources_id(mapping: PortResourceMap) -> str:
    """计算映射身份：sha256(schema + 零字节 + 规范字节)。

    Args:
        mapping: 独立端口资源映射。

    Returns:
        带 sha256: 前缀的小写摘要。

    Raises:
        PulseContractError: 输入不是 PortResourceMap。
    """
    content = dump_port_resources(mapping)
    return sha256_ref(mapping.schema.encode("utf-8") + b"\0" + content)


def check_port_resources(
    schedule: NativeScheduleIR, pulse: PulseProgramIR, mapping: PortResourceMap
) -> None:
    """检查映射覆盖每条带来源的 Play。

    每个端口的资源必须是对应来源操作资源的子集。
    同一端口上的每条 Play 均单独检查。Acquire、ShiftPhase 与无来源 Play 不参与覆盖检查。
    本函数检查调度引用与来源下标。其余 L1/L2 一致性由 check_pulse_program 检查。

    Args:
        schedule: 来源 L2 调度。
        pulse: 待映射的 L1 程序。
        mapping: 独立端口资源映射。

    Raises:
        PulseContractError: 映射错误的类别为 resources。四个 RESOURCE 码保留目标字段路径。
            调度引用或来源下标错误的类别为 SCHEDULE_MISMATCH。
    """
    if type(schedule) is not NativeScheduleIR:
        _fail("TYPE", "", "Expected NativeScheduleIR.")
    if type(pulse) is not PulseProgramIR:
        _fail("TYPE", "", "Expected PulseProgramIR.")
    if type(mapping) is not PortResourceMap:
        _fail("TYPE", "", "Expected PortResourceMap.")
    if mapping.pulse_program_ref != pulse_program_id(pulse):
        _fail(
            "RESOURCE_REF",
            "/pulse_program_ref",
            "Reference differs from the pulse program.",
            "resources",
        )
    if pulse.source_schedule_ref != native_schedule_ref(schedule):
        _fail(
            "SCHEDULE_REF",
            "/source_schedule_ref",
            "Reference differs from the schedule.",
            "SCHEDULE_MISMATCH",
        )
    ports = {port.id for port in pulse.ports}
    for index, entry in enumerate(mapping.entries):
        if entry.port not in ports:
            _fail("RESOURCE_PORT", f"/entries/{index}/port", "Unknown pulse port.", "resources")
    resources = {entry.port: set(entry.resources) for entry in mapping.entries}
    frame_ports = {frame.id: frame.port for frame in pulse.frames}
    for index, item in enumerate(pulse.instructions):
        if not isinstance(item, Play) or item.source is None:
            continue
        path = f"/instructions/{index}"
        if not 0 <= item.source < len(schedule.operations):
            _fail(
                "SOURCE",
                path + "/source",
                "Expected an operation index of the schedule.",
                "SCHEDULE_MISMATCH",
            )
        port = frame_ports[item.frame]
        if port not in resources:
            _fail(
                "RESOURCE_MISSING", path, f"Play {index} has no port resource entry.", "resources"
            )
        if not resources[port] <= set(schedule.operations[item.source].resources):
            _fail(
                "RESOURCE_COVERAGE",
                path,
                f"Play {index} port resources exceed its source operation resources.",
                "resources",
            )
