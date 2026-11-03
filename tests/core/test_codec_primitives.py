# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""编码叶原语的独立参考检查：标准库导入、f64 字节序、规范 JSON 与摘要。"""

from __future__ import annotations

import json
import math
import random
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import qaiji
from qaiji.core._codec import (
    CodecFault,
    canonical_json,
    f64_from_hex,
    f64_to_hex,
    inline_array,
    json_pointer,
    parse_json,
    sha256_ref,
)
from qaiji.exceptions import QaijiIRError


def _finite_samples() -> list[float]:
    """返回 10006 个有限值：边界值加固定种子的随机位型。"""
    values = [0.0, -0.0, 1.0, -1.0, 5e-324, -5e-324, 2.2250738585072014e-308, math.pi]
    values += [sys.float_info.max, -sys.float_info.max]
    rng = random.Random(20261103)
    while len(values) < 10006:
        value = struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0]
        if math.isfinite(value):
            values.append(value)
    return values


def test_f64_hex_matches_struct_and_golden() -> None:
    """f64 用大端十六进制。每个值与 struct 逐值相同，往返按位相同。"""
    assert f64_to_hex(1.0) == "3ff0000000000000"
    assert f64_to_hex(-0.0) == "8000000000000000"
    for value in _finite_samples():
        text = f64_to_hex(value)
        assert text == struct.pack(">d", value).hex()
        back = f64_from_hex(text)
        assert back is not None
        assert struct.pack(">d", back) == struct.pack(">d", value)


@pytest.mark.parametrize(
    "text",
    ["3FF0000000000000", "3ff000000000000", "3ff00000000000000", " 3ff000000000000"],
)
def test_f64_from_hex_rejects_malformed_text(text: object) -> None:
    """格式不符时返回 None：大写、长度 15 或 17、含空格。"""
    assert f64_from_hex(text) is None


@pytest.mark.parametrize("value", [b"3ff0000000000000", 1.0, None])
def test_f64_from_hex_rejects_non_text(value: object) -> None:
    """输入不是 str 时返回 None，不抛异常。"""
    assert f64_from_hex(value) is None


def test_f64_from_hex_keeps_nonfinite_bit_patterns() -> None:
    """原语只解码位型。有限性由调用方的上下文判定。"""
    nan = f64_from_hex("7ff8000000000000")
    assert nan is not None and math.isnan(nan)
    assert f64_from_hex("7ff0000000000000") == math.inf


def test_canonical_json_golden() -> None:
    """键排序、无空格、非 ASCII 原样输出为 UTF-8，拒收 NaN。"""
    assert canonical_json({"b": [1, "é"], "a": None}) == '{"a":null,"b":[1,"é"]}'.encode()
    with pytest.raises(ValueError):
        canonical_json({"x": math.nan})


def test_sha256_ref_and_inline_array_golden() -> None:
    """摘要带 sha256: 前缀。内联数组的 data 为规范 base64。"""
    empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_ref(b"") == "sha256:" + empty
    assert inline_array("f64le", (2,), bytes(16)) == {
        "dtype": "f64le",
        "shape": [2],
        "data": "A" * 22 + "==",
    }


def test_codec_primitives_import_only_standard_library() -> None:
    """在 -I 新进程中导入原语模块。增量只含该模块与标准库模块。"""
    src = str(Path(qaiji.__file__).resolve().parents[1])
    script = "\n".join(
        [
            "import json, sys",
            f"sys.path.insert(0, {src!r})",
            "import qaiji.core",
            "before = set(sys.modules)",
            "import qaiji.core._codec as codec",
            "delta = sorted(set(sys.modules) - before)",
            "loaded = sorted(n for n in before if n.startswith('qaiji.core.'))",
            "print(json.dumps([codec.__file__, loaded, delta]))",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script], capture_output=True, text=True, check=True
    )
    path, loaded, delta = json.loads(result.stdout)
    # 前提：被测源码来自本检出，且 P 层与原生层尚未载入，否则增量看不到它们。
    assert path.startswith(src)
    assert not any(n.startswith(("qaiji.core.physical", "qaiji.core.native")) for n in loaded)
    extra = set(delta) - {"qaiji.core._codec"}
    assert all(name.split(".")[0] in sys.stdlib_module_names for name in extra), extra


def test_json_pointer_escapes_tilde_and_slash() -> None:
    """按 RFC 6901 先转义 ``~`` 再转义 ``/``，整数键写为十进制。"""
    assert json_pointer("/x", "a/b~c") == "/x/a~1b~0c"
    assert json_pointer("", 3) == "/3"


def test_parse_json_accepts_integers_and_depth_limit() -> None:
    """接受 signed64 边界与 32 层嵌套。字符串里的括号不计入深度。"""
    text = "[" * 32 + "]" * 32
    assert parse_json(text.encode()) == json.loads(text)
    assert parse_json(('{"a":"' + "[" * 40 + '"}').encode()) == {"a": "[" * 40}
    assert parse_json(b'{"a":"[[[[","b":[-9223372036854775808,9223372036854775807]}') == {
        "a": "[[[[",
        "b": [-(1 << 63), (1 << 63) - 1],
    }


@pytest.mark.parametrize(
    ("data", "code", "path"),
    [
        ("{}", "JSON_TYPE", ""),
        (bytearray(b"{}"), "JSON_TYPE", ""),
        (b"\xff", "UNICODE", ""),
        (b'{"a":"\\ud800"}', "UNICODE", "/a"),
        (("[" * 33 + "]" * 33).encode(), "DEPTH", ""),
        (('["\\"", ' + "[" * 33 + "]" * 33 + "]").encode(), "DEPTH", ""),
        (b"[Infinity]", "NONFINITE", "/0"),
        (b"[-Infinity]", "NONFINITE", "/0"),
        (b'[{"a":1,"a":2}]', "DUPLICATE", "/0/a"),
        (b"{", "JSON", ""),
        (b'{"a":1,"a":2}', "DUPLICATE", "/a"),
        (b'{"x":{"a/b":1,"a/b":2}}', "DUPLICATE", "/x/a~1b"),
        (b"[1.0]", "NUMBER_ENCODING", "/0"),
        (b"[1e2]", "NUMBER_ENCODING", "/0"),
        (b'{"a":[NaN]}', "NONFINITE", "/a/0"),
        (b"[9223372036854775808]", "INTEGER", "/0"),
        (b"[-9223372036854775809]", "INTEGER", "/0"),
    ],
)
def test_parse_json_rejects_with_code_and_path(data: object, code: str, path: str) -> None:
    """每个拒收只抛中性 CodecFault，码与路径与 L1 解码器原有的诊断相同。"""
    with pytest.raises(CodecFault) as caught:
        parse_json(data)
    assert (caught.value.code, caught.value.path) == (code, path)
    assert isinstance(caught.value.message, str) and caught.value.message
    assert not isinstance(caught.value, QaijiIRError)
