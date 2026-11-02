# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1 程序的严格编解码、内容身份与 L2 调度引用。

编码沿用 P 层规则：输入为 UTF-8 字节，f64 为 16 位小写大端十六进制，JSON 数只能是
signed64 整数，键集精确，拒收重复键。编码叶原语来自 ``qaiji.core._codec``。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, cast

from qaiji.core._codec import canonical_json, f64_from_hex, f64_to_hex, sha256_ref
from qaiji.core.native import NativeScheduleIR

from .errors import PulseContractError, _fail
from .model import _SHAPES, Acquire, Envelope, Frame, Play, Port, PulseProgramIR, ShiftPhase

_ROOT = (
    "schema",
    "source_schedule_ref",
    "ports",
    "frames",
    "instructions",
    "conditions",
    "end_ns",
)
_CONDITION = ("condition_id", "start_ns", "end_ns")
# L1 文档的合法嵌套深度为 4。上限留余量，并使深嵌套输入在递归之前被拒收。
_MAX_DEPTH = 32
# 字段表。值为 "f64" 的字段编码为十六进制。"envelope" 为包络对象。其余字段原样编码。
_FIELDS: dict[type, dict[str, str]] = {
    Port: dict(id="raw", role="raw", targets="raw"),
    Frame: dict(id="raw", port="raw", frequency_hz="raw", phase_rad="f64"),
    Play: dict(
        frame="raw",
        start_ns="raw",
        duration_ns="raw",
        envelope="envelope",
        amplitude="f64",
        phase_rad="f64",
        condition_id="raw",
        source="raw",
    ),
    ShiftPhase: dict(
        frame="raw", at_ns="raw", delta_rad="f64", origin="raw", condition_id="raw", source="raw"
    ),
    Acquire: dict(
        port="raw", start_ns="raw", duration_ns="raw", event_id="raw", condition_id="raw"
    ),
}
_KINDS: dict[str, type] = {"play": Play, "shift_phase": ShiftPhase, "acquire": Acquire}
_KIND_NAMES = {cls: name for name, cls in _KINDS.items()}


def dump_pulse_program(program: PulseProgramIR) -> bytes:
    """编码 L1 程序的规范字节。

    Args:
        program: 待编码的程序。

    Returns:
        规范 JSON 的 UTF-8 字节：键排序、无空白、f64 为十六进制。

    Raises:
        PulseContractError: ``program`` 不是 ``PulseProgramIR``（``TYPE``）。
    """
    if type(program) is not PulseProgramIR:
        _fail("TYPE", "", "Expected PulseProgramIR.")
    tree = dict(
        schema=program.schema,
        source_schedule_ref=program.source_schedule_ref,
        end_ns=program.end_ns,
        ports=[_encode(port) for port in program.ports],
        frames=[_encode(frame) for frame in program.frames],
        conditions=[dict(zip(_CONDITION, item, strict=True)) for item in program.conditions],
        instructions=[
            {"kind": _KIND_NAMES[type(item)], **_encode(item)} for item in program.instructions
        ],
    )
    return canonical_json(tree)


def pulse_program_id(program: PulseProgramIR) -> str:
    """计算 L1 程序的内容身份：``sha256(schema + b"\\0" + 规范字节)``。

    Args:
        program: 待计算身份的程序。

    Returns:
        带 ``sha256:`` 前缀的小写摘要。

    Raises:
        PulseContractError: ``program`` 不是 ``PulseProgramIR``（``TYPE``）。
    """
    content = dump_pulse_program(program)
    return sha256_ref(program.schema.encode("utf-8") + b"\0" + content)


def native_schedule_ref(schedule: NativeScheduleIR) -> str:
    """计算 L2 调度的引用：``sha256(schema_version + b"\\0" + to_json() 字节)``。

    L1 程序的 ``source_schedule_ref`` 取该值。``check_pulse_program`` 检查二者相等。

    Args:
        schedule: L2 原生调度。

    Returns:
        带 ``sha256:`` 前缀的小写摘要。

    Raises:
        PulseContractError: ``schedule`` 不是 ``NativeScheduleIR``（``TYPE``）。
    """
    if type(schedule) is not NativeScheduleIR:
        _fail("TYPE", "", "Expected NativeScheduleIR.")
    content = schedule.to_json().encode("utf-8")
    return sha256_ref(schedule.schema_version.encode("utf-8") + b"\0" + content)


def load_pulse_program(data: bytes) -> PulseProgramIR:
    """严格解码 L1 程序，并经构造入口检查全部不变量。

    Args:
        data: 规范或非规范的 UTF-8 JSON 字节。

    Returns:
        解码得到的程序。

    Raises:
        PulseContractError: 字节、键集、数值编码、记录或不变量不合法。诊断路径为 JSON Pointer。
    """
    root = _object(_parse(data), "")
    _keys(root, _ROOT, "")
    conditions = []
    for index, item in enumerate(_array(root["conditions"], "/conditions")):
        path = _at("/conditions", index)
        obj = _object(item, path)
        _keys(obj, _CONDITION, path)
        conditions.append(tuple(obj[name] for name in _CONDITION))
    instructions = [
        _instruction(item, _at("/instructions", index))
        for index, item in enumerate(_array(root["instructions"], "/instructions"))
    ]
    values = dict(
        schema=root["schema"],
        source_schedule_ref=root["source_schedule_ref"],
        ports=[
            _record(item, Port, _at("/ports", i))
            for i, item in enumerate(_array(root["ports"], "/ports"))
        ],
        frames=[
            _record(item, Frame, _at("/frames", i))
            for i, item in enumerate(_array(root["frames"], "/frames"))
        ],
        instructions=instructions,
        conditions=conditions,
        end_ns=root["end_ns"],
    )
    return cast(PulseProgramIR, _construct(PulseProgramIR, values, ""))


def _encode(record: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, kind in _FIELDS[type(record)].items():
        value = getattr(record, name)
        if kind == "f64":
            result[name] = f64_to_hex(value)
        elif kind == "envelope":
            result[name] = {"shape": value.shape} | {
                field: f64_to_hex(getattr(value, field)) for field in _SHAPES[value.shape]
            }
        else:
            result[name] = list(value) if type(value) is tuple else value
    return result


def _at(path: str, key: str | int) -> str:
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


@dataclass
class _Pairs:
    items: list[tuple[str, Any]]


@dataclass
class _Number:
    text: str
    code: str = "INTEGER"


def _parse(data: Any) -> Any:
    if type(data) is not bytes:
        _fail("JSON_TYPE", "", "Expected bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        _fail("UNICODE", "", "Expected UTF-8 bytes.")
    _depth(text)
    try:
        tree = json.loads(
            text,
            object_pairs_hook=_Pairs,
            parse_int=_Number,
            parse_float=lambda s: _Number(s, "NUMBER_ENCODING"),
            parse_constant=lambda s: _Number(s, "NONFINITE"),
        )
    except (ValueError, RecursionError):
        _fail("JSON", "", "Invalid JSON document.")
    return _materialize(tree, "")


def _depth(text: str) -> None:
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > _MAX_DEPTH:
                _fail("DEPTH", "", "JSON nesting exceeds the depth limit.")
        elif char in "]}":
            depth -= 1


def _materialize(value: Any, path: str) -> Any:
    if isinstance(value, _Pairs):
        result: dict[str, Any] = {}
        for key, child in value.items:
            _unicode(key, _at(path, key))
            if key in result:
                _fail("DUPLICATE", _at(path, key), "Object keys must be unique.")
            result[key] = _materialize(child, _at(path, key))
        return result
    if isinstance(value, list):
        return [_materialize(child, _at(path, i)) for i, child in enumerate(value)]
    if isinstance(value, _Number):
        if value.code != "INTEGER":
            _fail(value.code, path, "JSON numbers must be signed64 integers.")
        if len(value.text.lstrip("-")) > 19 or not -(1 << 63) <= int(value.text) < (1 << 63):
            _fail("INTEGER", path, "Expected a signed64 integer.")
        return int(value.text)
    if isinstance(value, str):
        return _unicode(value, path)
    return value


def _unicode(text: str, path: str) -> str:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        _fail("UNICODE", path, "Expected Unicode scalar values.")
    return text


def _object(value: Any, path: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail("JSON_TYPE", path, "Expected an object.")
    return cast(dict[str, Any], value)


def _array(value: Any, path: str) -> list[Any]:
    if type(value) is not list:
        _fail("JSON_TYPE", path, "Expected an array.")
    return cast(list[Any], value)


def _keys(value: dict[str, Any], expected: tuple[str, ...], path: str) -> None:
    if set(value) != set(expected):
        _fail("KEYS", path, "Fields do not match the declared record.")


def _f64(value: Any, path: str) -> float:
    number = f64_from_hex(value)
    if number is None:
        _fail("BINARY64", path, "Expected 16 lowercase hexadecimal digits.")
    if not math.isfinite(number):
        _fail("NONFINITE", path, "Expected finite binary64.")
    return number


def _envelope(value: Any, path: str) -> Envelope:
    obj = _object(value, path)
    shape = obj.get("shape")
    if type(shape) is not str or shape not in _SHAPES:
        _fail("ENVELOPE", _at(path, "shape"), "Unknown envelope shape.")
    _keys(obj, ("shape", *_SHAPES[shape]), path)
    values = {"shape": shape} | {name: _f64(obj[name], _at(path, name)) for name in _SHAPES[shape]}
    return cast(Envelope, _construct(Envelope, values, path))


def _record(value: Any, cls: type, path: str) -> Any:
    obj = _object(value, path)
    fields = _FIELDS[cls]
    _keys(obj, tuple(fields), path)
    values: dict[str, Any] = {}
    for name, kind in fields.items():
        if kind == "f64":
            values[name] = _f64(obj[name], _at(path, name))
        elif kind == "envelope":
            values[name] = _envelope(obj[name], _at(path, name))
        else:
            values[name] = obj[name]
    return _construct(cls, values, path)


def _instruction(value: Any, path: str) -> Any:
    obj = _object(value, path)
    kind = obj.get("kind")
    if type(kind) is not str or kind not in _KINDS:
        _fail("KIND", _at(path, "kind"), "Unknown instruction kind.")
    record = {name: item for name, item in obj.items() if name != "kind"}
    return _record(record, _KINDS[kind], path)


def _construct(cls: type, values: dict[str, Any], path: str) -> Any:
    try:
        return cls(**values)
    except PulseContractError as error:
        diagnostic = error.diagnostics[0]
        _fail(diagnostic.code, path + diagnostic.path, diagnostic.message, diagnostic.category)
