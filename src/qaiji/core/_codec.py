# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1、L0 与 P 层编解码共用的编码叶原语。只依赖标准库。

本模块是这几层编码规则的唯一来源。错误报告留在各层：这里的函数不抛契约错误。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
from collections.abc import Sequence
from typing import Any

_HEX = re.compile(r"[0-9a-f]{16}\Z")


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
