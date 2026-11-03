# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L0 程序的严格编解码、内容身份与逐通道样本摘要。

规范字节用 P 层风格：键排序、无空白、数组内联为 ``{dtype, shape, data}``。
``params`` 树中的浮点写为 ``{"$f64": <16 位大端十六进制>}``。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
from typing import Any, cast

from qaiji.core._codec import (
    CodecFault,
    canonical_json,
    f64_from_hex,
    inline_array,
    parse_json,
    sha256_ref,
)
from qaiji.core._codec import json_pointer as _at

from .errors import WaveformContractError, _fail
from .model import Channel, Segment, TransformRecord, WaveformIR, _encoded

_ROOT = ("channels", "sample_rate_hz", "schema", "segments", "source_pulse_ref", "transforms")
_CHANNEL = ("id", "kind", "ports")
_SEGMENT = ("condition", "id", "samples", "time_origin_ns")
_CONDITION = ("id", "taken")
_SAMPLE = ("array", "channel")
_ARRAY = ("data", "dtype", "shape")
_TRANSFORM = ("kind", "params")
_F64 = "$f64"


def dump_waveform(waveform: WaveformIR) -> bytes:
    """编码 L0 程序的规范字节。

    Args:
        waveform: 待编码的程序。

    Returns:
        规范 JSON 的 UTF-8 字节。

    Raises:
        WaveformContractError: ``waveform`` 不是 ``WaveformIR``（``TYPE``）。
    """
    if type(waveform) is not WaveformIR:
        _fail("TYPE", "", "Expected WaveformIR.")
    tree = dict(
        schema=waveform.schema,
        source_pulse_ref=waveform.source_pulse_ref,
        sample_rate_hz=waveform.sample_rate_hz,
        channels=[dict(id=c.id, kind=c.kind, ports=list(c.ports)) for c in waveform.channels],
        segments=[_encode_segment(segment) for segment in waveform.segments],
        transforms=[dict(kind=t.kind, params=_encoded(t.params)) for t in waveform.transforms],
    )
    return canonical_json(tree)


def waveform_id(waveform: WaveformIR) -> str:
    """计算 L0 程序的内容身份：``sha256(schema + b"\\0" + 规范字节)``。

    Args:
        waveform: 待计算身份的程序。

    Returns:
        带 ``sha256:`` 前缀的小写摘要。

    Raises:
        WaveformContractError: ``waveform`` 不是 ``WaveformIR``（``TYPE``）。
    """
    content = dump_waveform(waveform)
    return sha256_ref(waveform.schema.encode("utf-8") + b"\0" + content)


def sample_digests(waveform: WaveformIR) -> dict[tuple[str, str], str]:
    """计算每个段、每个通道的 f64le 样本字节的 SHA-256。

    值的格式与 EmuPlat ``L0DriveSet.values_sha256()`` 相同：小写十六进制，无前缀。

    Args:
        waveform: L0 程序。

    Returns:
        键为 ``(segment_id, channel_id)`` 的摘要表。

    Raises:
        WaveformContractError: ``waveform`` 不是 ``WaveformIR``（``TYPE``）。
    """
    if type(waveform) is not WaveformIR:
        _fail("TYPE", "", "Expected WaveformIR.")
    return {
        (segment.id, channel): hashlib.sha256(data).hexdigest()
        for segment in waveform.segments
        for channel, data in segment.samples
    }


def load_waveform(data: bytes) -> WaveformIR:
    """严格解码 L0 程序，并经构造入口检查全部 L0 规则。

    Args:
        data: 规范或非规范的 UTF-8 JSON 字节。

    Returns:
        解码得到的程序。

    Raises:
        WaveformContractError: JSON、键集、数组、``$f64`` 编码或 L0 规则不合法。
    """
    try:
        tree = parse_json(data)
    except CodecFault as fault:
        _fail(fault.code, fault.path, fault.message)
    root = _object(tree, "")
    _keys(root, _ROOT, "")
    values = dict(
        schema=root["schema"],
        source_pulse_ref=root["source_pulse_ref"],
        sample_rate_hz=root["sample_rate_hz"],
        channels=_items(root["channels"], "/channels", _channel),
        segments=_items(root["segments"], "/segments", _segment),
        transforms=_items(root["transforms"], "/transforms", _transform),
    )
    return cast(WaveformIR, _construct(WaveformIR, values, ""))


def _encode_segment(segment: Segment) -> dict[str, Any]:
    condition = segment.condition
    return dict(
        id=segment.id,
        time_origin_ns=segment.time_origin_ns,
        condition=None if condition is None else dict(zip(_CONDITION, condition, strict=True)),
        samples=[
            dict(channel=channel, array=inline_array("f64le", (len(data) // 8,), data))
            for channel, data in segment.samples
        ],
    )


def _object(value: Any, path: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail("JSON_TYPE", path, "Expected an object.")
    return cast(dict[str, Any], value)


def _keys(value: dict[str, Any], expected: tuple[str, ...], path: str) -> None:
    if set(value) != set(expected):
        _fail("KEYS", path, "Fields do not match the declared record.")


def _items(value: Any, path: str, decode: Any) -> list[Any]:
    if type(value) is not list:
        _fail("JSON_TYPE", path, "Expected an array.")
    return [decode(item, _at(path, index)) for index, item in enumerate(value)]


def _channel(value: Any, path: str) -> Channel:
    obj = _object(value, path)
    _keys(obj, _CHANNEL, path)
    ports = obj["ports"]
    if type(ports) is not list:
        _fail("JSON_TYPE", _at(path, "ports"), "Expected an array.")
    values = dict(id=obj["id"], kind=obj["kind"], ports=ports)
    return cast(Channel, _construct(Channel, values, path))


def _segment(value: Any, path: str) -> Segment:
    obj = _object(value, path)
    _keys(obj, _SEGMENT, path)
    condition = obj["condition"]
    if condition is not None:
        condition_obj = _object(condition, _at(path, "condition"))
        _keys(condition_obj, _CONDITION, _at(path, "condition"))
        condition = (condition_obj["id"], condition_obj["taken"])
    samples = _items(obj["samples"], _at(path, "samples"), _sample)
    values = dict(
        id=obj["id"], time_origin_ns=obj["time_origin_ns"], condition=condition, samples=samples
    )
    return cast(Segment, _construct(Segment, values, path))


def _sample(value: Any, path: str) -> tuple[Any, bytes]:
    obj = _object(value, path)
    _keys(obj, _SAMPLE, path)
    return obj["channel"], _f64le(obj["array"], _at(path, "array"))


def _f64le(value: Any, path: str) -> bytes:
    obj = _object(value, path)
    _keys(obj, _ARRAY, path)
    if obj["dtype"] != "f64le":
        _fail("DTYPE", _at(path, "dtype"), "Expected dtype f64le.")
    shape = obj["shape"]
    if type(shape) is not list or len(shape) != 1 or type(shape[0]) is not int or shape[0] < 0:
        _fail("SHAPE", _at(path, "shape"), "Expected a one-dimensional shape.")
    encoded = obj["data"]
    if type(encoded) is not str:
        _fail("BASE64", _at(path, "data"), "Expected a padded base64 string.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        _fail("BASE64", _at(path, "data"), "Invalid base64 data.")
    if base64.b64encode(data).decode("ascii") != encoded:
        _fail("BASE64", _at(path, "data"), "Expected canonical padded base64 data.")
    if len(data) != 8 * shape[0]:
        _fail("SHAPE", _at(path, "shape"), "The shape does not match the data length.")
    return data


def _transform(value: Any, path: str) -> TransformRecord:
    obj = _object(value, path)
    _keys(obj, _TRANSFORM, path)
    values = dict(kind=obj["kind"], params=_decode_tree(obj["params"], _at(path, "params")))
    return cast(TransformRecord, _construct(TransformRecord, values, path))


def _decode_tree(value: Any, path: str) -> Any:
    if type(value) is list:
        return [_decode_tree(child, _at(path, index)) for index, child in enumerate(value)]
    if type(value) is not dict:
        return value
    if _F64 not in value:
        return {key: _decode_tree(child, _at(path, key)) for key, child in value.items()}
    if set(value) != {_F64}:
        _fail("PARAMS", path, "A $f64 object has exactly one key.")
    number = f64_from_hex(value[_F64])
    if number is None:
        _fail("BINARY64", _at(path, _F64), "Expected 16 lowercase hexadecimal digits.")
    if not math.isfinite(number):
        _fail("NONFINITE", _at(path, _F64), "Expected finite binary64.")
    return number


def _construct(cls: type, values: dict[str, Any], path: str) -> Any:
    try:
        return cls(**values)
    except WaveformContractError as error:
        diagnostic = error.diagnostics[0]
        _fail(diagnostic.code, path + diagnostic.path, diagnostic.message)
