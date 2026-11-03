# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1、L0 与 P 层编解码共用的编码叶原语与 L1、L0 共用的严格 JSON 解析。只依赖标准库。

本模块是这几层编码规则的唯一来源。错误报告留在各层：这里的函数不抛契约错误。严格解析
失败时抛中性的 ``CodecFault``，由各层转为本层的契约错误，码与路径不变。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

_HEX = re.compile(r"[0-9a-f]{16}\Z")
# L1 文档的合法嵌套深度为 4。L0 的数组形状在第 7 层，params 从第 4 层开始。上限留余量，
# 并使深嵌套输入在递归之前被拒收。
_MAX_DEPTH = 32


def canonical_json(value: Any) -> bytes:
    """编码规范 JSON：键排序、无空白、非 ASCII 原样输出，拒收 NaN 与 Inf。

    Args:
        value: 由 dict、list、str、int、bool 与 None 组成的树。

    Returns:
        UTF-8 字节。

    Raises:
        ValueError: 树含非有限浮点数。
    """
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_ref(data: bytes) -> str:
    """返回带 ``sha256:`` 前缀的小写摘要。"""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def f64_to_hex(value: float) -> str:
    """把 binary64 编码为 16 位小写大端十六进制。有限性由调用方检查。"""
    return struct.pack(">d", value).hex()


def f64_from_hex(text: Any) -> float | None:
    """解码 16 位小写大端十六进制。

    Args:
        text: 待解码的值。

    Returns:
        解码得到的 binary64，可能是 NaN 或 Inf。``text`` 不是该格式的 str 时返回 None。
    """
    if type(text) is not str or not _HEX.fullmatch(text):
        return None
    value: float = struct.unpack(">d", bytes.fromhex(text))[0]
    return value


def inline_array(dtype: str, shape: Sequence[int], data: bytes) -> dict[str, Any]:
    """返回内联数组对象 ``{dtype, shape, data}``，``data`` 为规范 base64。"""
    return dict(dtype=dtype, shape=list(shape), data=base64.b64encode(data).decode("ascii"))


class CodecFault(Exception):
    """严格解析的拒绝：诊断码、JSON Pointer 与说明。"""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(f"{code} at {path or '/'}: {message}")
        self.code = code
        self.path = path
        self.message = message


def json_pointer(path: str, key: str | int) -> str:
    """在 JSON Pointer ``path`` 后追加一级，按 RFC 6901 转义 ``~`` 与 ``/``。"""
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def parse_json(data: Any) -> Any:
    """严格解析 UTF-8 JSON 字节。

    拒收非 bytes、非 UTF-8、嵌套超过 32 层、重复键、浮点、非有限常量、超出 signed64 的
    整数与非 Unicode 标量值。

    Args:
        data: 待解析的字节。

    Returns:
        由 dict、list、str、int、bool 与 None 组成的树。

    Raises:
        CodecFault: 输入不合法。码为 ``JSON_TYPE``、``UNICODE``、``DEPTH``、``JSON``、
            ``DUPLICATE``、``NUMBER_ENCODING``、``NONFINITE`` 或 ``INTEGER``。
    """
    if type(data) is not bytes:
        raise CodecFault("JSON_TYPE", "", "Expected bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise CodecFault("UNICODE", "", "Expected UTF-8 bytes.") from None
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
        raise CodecFault("JSON", "", "Invalid JSON document.") from None
    return _materialize(tree, "")


@dataclass
class _Pairs:
    items: list[tuple[str, Any]]


@dataclass
class _Number:
    text: str
    code: str = "INTEGER"


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
                raise CodecFault("DEPTH", "", "JSON nesting exceeds the depth limit.")
        elif char in "]}":
            depth -= 1


def _materialize(value: Any, path: str) -> Any:
    if isinstance(value, _Pairs):
        result: dict[str, Any] = {}
        for key, child in value.items:
            _unicode(key, json_pointer(path, key))
            if key in result:
                raise CodecFault(
                    "DUPLICATE", json_pointer(path, key), "Object keys must be unique."
                )
            result[key] = _materialize(child, json_pointer(path, key))
        return result
    if isinstance(value, list):
        return [_materialize(child, json_pointer(path, i)) for i, child in enumerate(value)]
    if isinstance(value, _Number):
        if value.code != "INTEGER":
            raise CodecFault(value.code, path, "JSON numbers must be signed64 integers.")
        if len(value.text.lstrip("-")) > 19 or not -(1 << 63) <= int(value.text) < (1 << 63):
            raise CodecFault("INTEGER", path, "Expected a signed64 integer.")
        return int(value.text)
    if isinstance(value, str):
        return _unicode(value, path)
    return value


def _unicode(text: str, path: str) -> str:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise CodecFault("UNICODE", path, "Expected Unicode scalar values.") from None
    return text
