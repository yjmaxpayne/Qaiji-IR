# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L0 严格编解码、golden 字节、内容身份、跨进程稳定性、样本摘要、导入纯度与解码负空间。"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from _waveform_fixtures import GHZ, channel, f64le, rejects, segment, transform, waveform
from qaiji.core.physical import PContractError, load_problem
from qaiji.core.waveform import (
    WaveformContractError,
    WaveformIR,
    dump_waveform,
    load_waveform,
    sample_digests,
    waveform_id,
)

SRC = str(Path(__file__).parents[2] / "src")
TESTS = str(Path(__file__).parents[1])


def full_waveform(last: float = 0.5) -> WaveformIR:
    """2 个通道、1 个无条件段与 1 对条件段。参数树含 −0.0、嵌套 list 与 dict、非 ASCII 文本。

    ``last`` 是段 ``s0`` 中通道 ``ch0`` 的第 2 个样本。
    """
    return waveform(
        channels=(channel(), channel(id="ch1", ports=("d1", "z1"))),
        segments=(
            segment(samples=(("ch0", f64le([0.0, last])), ("ch1", f64le([1.0, -0.0])))),
            segment(
                id="s1",
                time_origin_ns=40,
                branch=(("c1", 1),),
                samples=(("ch0", f64le([0.25])),),
            ),
            segment(
                id="s2",
                time_origin_ns=40,
                branch=(("c1", 0),),
                samples=(("ch1", f64le([-0.25])),),
            ),
        ),
        transforms=(
            transform(
                params={
                    "lo_hz": 5_000_000_000,
                    "phase": -0.0,
                    "taps": [0.5, [1, "x"]],
                    "meta": {"label": "é", "on": True, "tag": None},
                }
            ),
        ),
    )


def test_round_trip() -> None:
    """解码得到相等的记录。再编码得到同一字节，−0.0 的符号位不丢。"""
    raw = dump_waveform(full_waveform())
    loaded = load_waveform(raw)
    assert loaded == full_waveform()
    assert dump_waveform(loaded) == raw


GOLDEN = (
    '{"channels":[{"id":"ch0","kind":"dac_real","ports":["d0","z0"]}],'
    '"sample_rate_hz":2000000000,"schema":"qaiji.waveform/0.2","segments":['
    '{"branch":[],"id":"s0","samples":[{"array":{"data":"AAAAAAAA8D8AAAAAAAAAgA==",'
    '"dtype":"f64le","shape":[2]},"channel":"ch0"}],"time_origin_ns":0},'
    '{"branch":[{"bit":1,"event_id":"c1"}],"id":"s1","samples":[{"array":'
    '{"data":"AAAAAAAA4D8=","dtype":"f64le","shape":[1]},"channel":"ch0"}],"time_origin_ns":40},'
    '{"branch":[{"bit":0,"event_id":"c1"}],"id":"s2","samples":[{"array":'
    '{"data":"AAAAAAAA0D8=","dtype":"f64le","shape":[1]},"channel":"ch0"}],"time_origin_ns":40}],'
    '"source_pulse_ref":"sha256:0000000000000000000000000000000000000000000000000000000000000000",'
    '"transforms":[{"kind":"upconvert","params":{"lo_hz":5000000000,"on":true,'
    '"phase":{"$f64":"8000000000000000"},"tag":null,'
    '"taps":[{"$f64":"3fe0000000000000"},"x"]}}]}'
)


def test_golden_bytes() -> None:
    """键按字典序、无空白。样本为小端 f64 的规范 base64。参数中的 float 写为 ``$f64`` 十六进制。"""
    built = waveform(
        sample_rate_hz=2 * GHZ,
        channels=(channel(ports=("d0", "z0")),),
        segments=(
            segment(samples=(("ch0", f64le([1.0, -0.0])),)),
            segment(
                id="s1",
                time_origin_ns=40,
                branch=(("c1", 1),),
                samples=(("ch0", f64le([0.5])),),
            ),
            segment(
                id="s2",
                time_origin_ns=40,
                branch=(("c1", 0),),
                samples=(("ch0", f64le([0.25])),),
            ),
        ),
        transforms=(
            transform(
                params={
                    "lo_hz": 5_000_000_000,
                    "on": True,
                    "phase": -0.0,
                    "tag": None,
                    "taps": [0.5, "x"],
                }
            ),
        ),
    )
    assert dump_waveform(built) == GOLDEN.encode("utf-8")


def test_waveform_id() -> None:
    """身份 = sha256(schema + 0 字节 + 规范字节)，带 ``sha256:`` 前缀。改 1 个样本，身份改变。"""
    built = full_waveform()
    content = b"qaiji.waveform/0.2\x00" + dump_waveform(built)
    assert waveform_id(built) == "sha256:" + hashlib.sha256(content).hexdigest()
    assert waveform_id(full_waveform(math.nextafter(0.5, 1.0))) != waveform_id(built)


_SEED_SCRIPT = """
import json, sys
sys.path.insert(0, {src!r})
sys.path.insert(0, {tests!r})
from _waveform_fixtures import channel, waveform
from qaiji.core.waveform import waveform_id
built = waveform(channels=(channel(ports=("d0", "d1", "r0", "r1", "z0")),))
print(json.dumps([waveform_id(built), list({{"d0", "d1", "r0", "r1", "z0"}})]))
"""


def test_identity_is_stable_across_hash_seeds() -> None:
    """8 个 PYTHONHASHSEED 的子进程算出同一身份，与本进程相同。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")}
    ids, orders = set(), set()
    for seed in range(8):
        result = subprocess.run(
            [sys.executable, "-c", _SEED_SCRIPT.format(src=SRC, tests=TESTS)],
            capture_output=True,
            text=True,
            env=env | {"PYTHONHASHSEED": str(seed)},
            check=True,
        )
        identity, order = json.loads(result.stdout)
        ids.add(identity)
        orders.add(tuple(order))
    # 夹具前提：不同种子下 set 的迭代顺序确实不同，否则本用例没有鉴别力。
    assert len(orders) > 1
    assert ids == {waveform_id(waveform(channels=(channel(ports=("d0", "d1", "r0", "r1", "z0")),)))}


def test_sample_digests() -> None:
    """键为 (段 id, 通道 id)。值为小端 f64 字节的 SHA-256 十六进制，不带前缀。"""
    values = {
        ("s0", "ch0"): [0.0, 0.5],
        ("s0", "ch1"): [1.0, -0.0],
        ("s1", "ch0"): [0.25],
        ("s2", "ch1"): [-0.25],
    }
    expected = {
        key: hashlib.sha256(struct.pack(f"<{len(items)}d", *items)).hexdigest()
        for key, items in values.items()
    }
    digests = sample_digests(full_waveform())
    assert digests == expected
    # 只改 s0/ch0 一个样本的最低位：只有这一个摘要改变。
    changed = sample_digests(full_waveform(math.nextafter(0.5, 1.0)))
    assert changed.keys() == digests.keys()
    assert {key for key in digests if changed[key] != digests[key]} == {("s0", "ch0")}


def test_import_purity() -> None:
    """在隔离解释器中导入 L0 包，不载入 numpy 与 P 层。"""
    script = "\n".join(
        [
            "import json, sys",
            f"sys.path.insert(0, {SRC!r})",
            "import qaiji.core.waveform as waveform",
            "names = sorted(n for n in sys.modules if n.split('.')[0] == 'numpy'",
            "               or n.startswith('qaiji.core.physical'))",
            "print(json.dumps([waveform.__file__, names]))",
        ]
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")}
    result = subprocess.run(
        [sys.executable, "-I", "-c", script], capture_output=True, text=True, env=env, check=True
    )
    path, names = json.loads(result.stdout)
    # 前提：被测源码来自本检出（-I 忽略 PYTHONPATH，脚本内显式插入 src）。
    assert path.startswith(SRC)
    assert names == []


def _set(path: tuple[Any, ...], value: Any) -> Callable[[], bytes]:
    """返回一个构造器：把 ``full_waveform`` 文档中 ``path`` 处的值换成 ``value``。"""

    def build() -> bytes:
        document = json.loads(dump_waveform(full_waveform()))
        node = document
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        return json.dumps(document).encode()

    return build


def _drop(key: str) -> Callable[[], bytes]:
    """返回一个构造器：删去 ``full_waveform`` 文档的根键 ``key``。"""

    def build() -> bytes:
        document = json.loads(dump_waveform(full_waveform()))
        del document[key]
        return json.dumps(document).encode()

    return build


def _text(old: str, new: str) -> Callable[[], bytes]:
    """返回一个构造器：在 ``full_waveform`` 的规范字节中把唯一的 ``old`` 换成 ``new``。"""

    def build() -> bytes:
        raw = dump_waveform(full_waveform()).decode()
        assert raw.count(old) == 1
        return raw.replace(old, new).encode()

    return build


ARRAY = ("segments", 0, "samples", 0, "array")
PHASE = ("transforms", 0, "params", "phase")
_GOOD_DATA = base64.b64encode(f64le([0.0, 0.5])).decode()

# 坏 base64 串。被替换的数组形状为 [2]（16 字节）。
BAD_BASE64 = [
    ("alphabet", "!!!!"),
    ("length", "AA"),
    ("pad-bits", "AB=="),
    ("type", 1),
    ("unicode", "μ"),
    ("missing-padding", _GOOD_DATA.rstrip("=")),
    ("trailing-newline", _GOOD_DATA + "\n"),
    ("leading-space", " " + _GOOD_DATA),
    # 末字符的填充位不为 0：宽松解码得到同一 16 字节，但不是规范形式。
    ("noncanonical-tail", _GOOD_DATA[:-3] + "x=="),
]

NEGATIVE = [
    (
        "duplicate-key",
        _text('"id":"s0"', '"id":"s0","id":"s0"'),
        "DUPLICATE",
        "/segments/0/id",
    ),
    (
        "json-float",
        _text('"sample_rate_hz":1000000000', '"sample_rate_hz":1000000000.0'),
        "NUMBER_ENCODING",
        "/sample_rate_hz",
    ),
    ("text-input", lambda: dump_waveform(full_waveform()).decode(), "JSON_TYPE", ""),
    ("missing-key", _drop("transforms"), "KEYS", ""),
    ("channel-extra-key", _set(("channels", 0, "extra"), 1), "KEYS", "/channels/0"),
    ("channels-object", _set(("channels",), {}), "JSON_TYPE", "/channels"),
    ("dtype", _set((*ARRAY, "dtype"), "f32le"), "DTYPE", "/segments/0/samples/0/array/dtype"),
    ("shape-rank", _set((*ARRAY, "shape"), [2, 1]), "SHAPE", "/segments/0/samples/0/array/shape"),
    ("shape-length", _set((*ARRAY, "shape"), [3]), "SHAPE", "/segments/0/samples/0/array/shape"),
    ("shape-negative", _set((*ARRAY, "shape"), [-1]), "SHAPE", "/segments/0/samples/0/array/shape"),
    *(
        (
            f"base64-{name}",
            _set((*ARRAY, "data"), bad),
            "BASE64",
            "/segments/0/samples/0/array/data",
        )
        for name, bad in BAD_BASE64
    ),
    ("f64-short", _set((*PHASE, "$f64"), "8000"), "BINARY64", "/transforms/0/params/phase/$f64"),
    (
        "f64-uppercase",
        _set((*PHASE, "$f64"), "3FE0000000000000"),
        "BINARY64",
        "/transforms/0/params/phase/$f64",
    ),
    (
        "f64-infinite",
        _set((*PHASE, "$f64"), "7ff0000000000000"),
        "NONFINITE",
        "/transforms/0/params/phase/$f64",
    ),
    (
        "f64-extra-key",
        _set(PHASE, {"$f64": "8000000000000000", "x": 1}),
        "PARAMS",
        "/transforms/0/params/phase",
    ),
    ("dollar-key", _set(("transforms", 0, "params", "$x"), 1), "PARAMS", "/transforms/0/params/$x"),
    (
        "nan-sample",
        _set((*ARRAY, "data"), base64.b64encode(f64le([math.nan, 0.5])).decode()),
        "NONFINITE",
        "/segments/0/samples/0",
    ),
    # "ch00" 排在 "ch1" 之前，段内升序仍成立，只剩通道未声明。
    (
        "undeclared-channel",
        _set(("segments", 0, "samples", 0, "channel"), "ch00"),
        "CHANNEL_REF",
        "/segments/0/samples/0",
    ),
    ("schema", _set(("schema",), "qaiji.waveform/9.9"), "SCHEMA", "/schema"),
    ("segment-extra-key", _set(("segments", 0, "extra"), 1), "KEYS", "/segments/0"),
    (
        "condition-extra-key",
        _set(("segments", 1, "branch", 0, "extra"), 1),
        "KEYS",
        "/segments/1/branch/0",
    ),
    (
        "sample-extra-key",
        _set(("segments", 0, "samples", 0, "extra"), 1),
        "KEYS",
        "/segments/0/samples/0",
    ),
    ("array-extra-key", _set((*ARRAY, "extra"), 1), "KEYS", "/segments/0/samples/0/array"),
    ("transform-extra-key", _set(("transforms", 0, "extra"), 1), "KEYS", "/transforms/0"),
    (
        "bool-shape",
        _set(ARRAY, {"dtype": "f64le", "shape": [True], "data": "AAAAAAAAAAA="}),
        "SHAPE",
        "/segments/0/samples/0/array/shape",
    ),
    (
        "nan-hex",
        _set((*PHASE, "$f64"), "7ff8000000000000"),
        "NONFINITE",
        "/transforms/0/params/phase/$f64",
    ),
    (
        "nested-dollar-key",
        _set(("transforms", 0, "params", "deep"), {"inner": {"$x": 1}}),
        "PARAMS",
        "/transforms/0/params/deep/inner/$x",
    ),
]


@pytest.mark.parametrize(
    ("data", "code", "path"),
    [case[1:] for case in NEGATIVE],
    ids=[case[0] for case in NEGATIVE],
)
def test_decode_negative_space(data: Callable[[], Any], code: str, path: str) -> None:
    """每个负例由目标守卫拒收：诊断码与路径都符合预期。构造错误带上记录所在的路径前缀。"""
    rejects(code, path, load_waveform, data())


PROBLEM = json.loads(Path(TESTS, "physical", "data", "schema-fields.json").read_text("utf-8"))[
    "examples"
]["problem"]


def _first_code(error: type[Exception], call: Callable[[bytes], Any], data: bytes) -> str:
    with pytest.raises(error) as caught:
        call(data)
    return caught.value.diagnostics[0].code  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad", [bad for _, bad in BAD_BASE64], ids=[n for n, _ in BAD_BASE64])
def test_base64_parity_with_physical_layer(bad: Any) -> None:
    """同一个坏 base64 串，P 层 ``load_problem`` 与 L0 ``load_waveform`` 都报 ``BASE64``。"""
    problem = copy.deepcopy(PROBLEM)
    problem["signal_edges"]["data"] = bad
    codes = (
        _first_code(PContractError, load_problem, json.dumps(problem).encode()),
        _first_code(WaveformContractError, load_waveform, _set((*ARRAY, "data"), bad)()),
    )
    assert codes == ("BASE64", "BASE64")


def test_params_at_the_depth_limit_round_trip() -> None:
    """params 嵌套 29 层时，编码字节可被解码器接受，往返相等。"""
    nested: Any = []
    for _ in range(26):
        nested = [nested]
    built = waveform(transforms=(transform(params={"a": [nested]}),))
    assert load_waveform(dump_waveform(built)) == built


def test_waveform_sources_do_not_import_pulse_errors() -> None:
    """L0 自带诊断，源码不导入 L1 的 errors 模块。"""
    sources = sorted((Path(SRC) / "qaiji" / "core" / "waveform").glob("*.py"))
    assert len(sources) == 5
    assert not [path.name for path in sources if "pulse.errors" in path.read_text()]
