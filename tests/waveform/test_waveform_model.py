# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L0 记录的构造检查、L0 规则 1、2、3、6、通道引用、声明顺序、段 id 与参数树。"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from types import MappingProxyType
from typing import Any

import pytest

import qaiji
import qaiji.core
import qaiji.core.waveform as waveform_module
from _waveform_fixtures import (
    GHZ,
    REF,
    channel,
    f64le,
    rejects,
    segment,
    transform,
    waveform,
)
from qaiji.core.waveform import (
    WAVEFORM_SCHEMA,
    Channel,
    Segment,
    TransformRecord,
    WaveformContractError,
    WaveformIR,
)
from qaiji.exceptions import QaijiIRError

PUBLIC = {
    "WAVEFORM_SCHEMA",
    "Channel",
    "Segment",
    "TransformRecord",
    "WaveformIR",
    "WaveformDiagnostic",
    "WaveformContractError",
    "sample_count",
    "sample_envelope",
    "sample_play",
    "dump_waveform",
    "load_waveform",
    "waveform_id",
    "sample_digests",
}


def test_public_names_stay_in_the_subpackage() -> None:
    """公开名只在子包导出。包根 qaiji 与 qaiji.core 不导出这些名。"""
    assert set(waveform_module.__all__) == PUBLIC
    for name in PUBLIC:
        assert not hasattr(qaiji, name), name
        assert not hasattr(qaiji.core, name), name
    assert issubclass(WaveformContractError, QaijiIRError)
    assert WAVEFORM_SCHEMA == "qaiji.waveform/0.2"


RECORDS: list[tuple[type, Callable[[], Any]]] = [
    (Channel, channel),
    (Segment, segment),
    (TransformRecord, transform),
    (WaveformIR, waveform),
]


@pytest.mark.parametrize(("cls", "build"), RECORDS, ids=[r[0].__name__ for r in RECORDS])
def test_records_are_frozen_slotted_keyword_only_and_unhashable(
    cls: type, build: Callable[[], Any]
) -> None:
    """记录不可改、无 __dict__、只收关键字参数、不可哈希。"""
    record = build()
    first = dataclasses.fields(record)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(record, first, getattr(record, first))
    assert not hasattr(record, "__dict__")
    assert cls.__hash__ is None
    with pytest.raises(TypeError):
        hash(record)
    values = [getattr(record, f.name) for f in dataclasses.fields(record)]
    with pytest.raises(TypeError):
        cls(*values)


def test_valid_records_keep_their_values() -> None:
    """合法输入原样保留。ports 存为 tuple，schema 默认值即 WAVEFORM_SCHEMA。"""
    built = channel(ports=["d0", "z0"])
    assert built.ports == ("d0", "z0") and type(built.ports) is tuple
    cond = segment(id="s1", branch=(("c1", 1),))
    assert cond.branch == (("c1", 1),) and type(cond.branch) is tuple
    built_waveform = waveform()
    assert built_waveform.schema == WAVEFORM_SCHEMA
    assert built_waveform.source_pulse_ref == REF
    assert built_waveform.segments[0].samples == (("ch0", f64le([0.0, 0.5])),)


CHANNEL_NEGATIVE: list[tuple[str, dict[str, Any], str, str]] = [
    ("empty-id", {"id": ""}, "TEXT", "/id"),
    ("int-id", {"id": 1}, "TEXT", "/id"),
    ("kind", {"kind": "dac_iq"}, "KIND", "/kind"),
    ("empty-ports", {"ports": ()}, "PORTS", "/ports"),
    ("string-ports", {"ports": "d0"}, "PORTS", "/ports"),
    ("set-ports", {"ports": {"d0"}}, "PORTS", "/ports"),
    ("int-port", {"ports": ("d0", 1)}, "PORTS", "/ports"),
    ("empty-port", {"ports": ("d0", "")}, "PORTS", "/ports"),
    ("duplicate-port", {"ports": ("d0", "z0", "d0")}, "PORTS", "/ports"),
    ("surrogate-id", {"id": "\ud800"}, "UNICODE", "/id"),
    ("surrogate-port", {"ports": ("d0", "\ud800")}, "UNICODE", "/ports/1"),
]


@pytest.mark.parametrize(
    ("changes", "code", "path"),
    [case[1:] for case in CHANNEL_NEGATIVE],
    ids=[case[0] for case in CHANNEL_NEGATIVE],
)
def test_channel_negative_space(changes: dict[str, Any], code: str, path: str) -> None:
    """Channel 的每个违规输入由对应字段的检查拒收。"""
    rejects(code, path, lambda: channel(**changes))


_NAN, _INF = math.nan, math.inf
_TWO = (("ch0", f64le([0.0])), ("ch1", f64le([0.0])))

SEGMENT_NEGATIVE: list[tuple[str, dict[str, Any], str, str]] = [
    ("empty-id", {"id": ""}, "TEXT", "/id"),
    ("none-id", {"id": None}, "TEXT", "/id"),
    ("negative-time", {"time_origin_ns": -1}, "TIME", "/time_origin_ns"),
    ("bool-time", {"time_origin_ns": True}, "INTEGER", "/time_origin_ns"),
    ("float-time", {"time_origin_ns": 0.0}, "INTEGER", "/time_origin_ns"),
    ("wide-time", {"time_origin_ns": 1 << 63}, "INTEGER", "/time_origin_ns"),
    ("wide-negative-time", {"time_origin_ns": -(1 << 63) - 1}, "INTEGER", "/time_origin_ns"),
    ("string-condition", {"branch": "c1"}, "BRANCH", "/branch"),
    ("short-condition", {"branch": ("c1",)}, "BRANCH", "/branch"),
    ("long-condition", {"branch": ("c1", True, 0)}, "BRANCH", "/branch"),
    ("empty-condition-id", {"branch": (("", 1),)}, "BRANCH", "/branch"),
    ("int-taken", {"branch": (("c1", True),)}, "BRANCH", "/branch"),
    ("string-samples", {"samples": "ch0"}, "TYPE", "/samples"),
    ("none-samples", {"samples": None}, "TYPE", "/samples"),
    ("short-entry", {"samples": (("ch0",),)}, "SAMPLES", "/samples/0"),
    ("int-channel", {"samples": ((0, f64le([0.0])),)}, "SAMPLES", "/samples/0"),
    ("str-values", {"samples": (("ch0", "AAAA"),)}, "SAMPLES", "/samples/0"),
    ("list-values", {"samples": (("ch0", [0.0]),)}, "SAMPLES", "/samples/0"),
    ("ragged-bytes", {"samples": (("ch0", bytes(12)),)}, "SAMPLES", "/samples/0"),
    ("nan", {"samples": (_TWO[0], ("ch1", f64le([0.0, _NAN])))}, "NONFINITE", "/samples/1"),
    ("inf", {"samples": (("ch0", f64le([_INF])),)}, "NONFINITE", "/samples/0"),
    ("negative-inf", {"samples": (("ch0", f64le([-_INF])),)}, "NONFINITE", "/samples/0"),
    ("reversed", {"samples": (_TWO[1], _TWO[0])}, "ORDER", "/samples/1"),
    ("repeated", {"samples": (_TWO[0], _TWO[0])}, "ORDER", "/samples/1"),
    ("surrogate-condition", {"branch": (("\ud800", 1),)}, "UNICODE", "/branch"),
    ("surrogate-channel", {"samples": (("\ud800", f64le([0.0])),)}, "UNICODE", "/samples/0"),
]


@pytest.mark.parametrize(
    ("changes", "code", "path"),
    [case[1:] for case in SEGMENT_NEGATIVE],
    ids=[case[0] for case in SEGMENT_NEGATIVE],
)
def test_segment_negative_space(changes: dict[str, Any], code: str, path: str) -> None:
    """Segment 的每个违规输入由对应字段的检查拒收。样本须为有限 f64，通道 id 严格升序。"""
    rejects(code, path, lambda: segment(**changes))


def test_transform_params_become_a_frozen_tree() -> None:
    """参数树冻结：dict 存为 MappingProxyType，list 存为 tuple，与调用方的对象脱钩。"""
    params: dict[str, Any] = {"n": -(1 << 63), "x": [1.5, {"on": True, "tag": None}], "s": "é"}
    record = transform(params=params)
    params["x"][1]["on"] = False
    params["n"] = 0
    assert type(record.params) is MappingProxyType
    assert record.params["n"] == -(1 << 63)
    nested = record.params["x"]
    assert type(nested) is tuple and type(nested[1]) is MappingProxyType
    assert nested[1]["on"] is True
    with pytest.raises(TypeError):
        record.params["n"] = 1  # type: ignore[index]
    assert record == transform(
        params={"n": -(1 << 63), "x": [1.5, {"on": True, "tag": None}], "s": "é"}
    )


def _lists(levels: int) -> Any:
    """返回 ``levels`` 层嵌套的空 list。"""
    value: Any = []
    for _ in range(levels - 1):
        value = [value]
    return value


TRANSFORM_NEGATIVE: list[tuple[str, dict[str, Any], str, str]] = [
    ("empty-kind", {"kind": ""}, "TEXT", "/kind"),
    ("int-kind", {"kind": 3}, "TEXT", "/kind"),
    ("list-params", {"params": [1]}, "PARAMS", "/params"),
    ("none-params", {"params": None}, "PARAMS", "/params"),
    ("nan", {"params": {"a": _NAN}}, "PARAMS", "/params/a"),
    ("nested-inf", {"params": {"a": [1, {"b": _INF}]}}, "PARAMS", "/params/a/1/b"),
    ("wide-int", {"params": {"n": 1 << 63}}, "PARAMS", "/params/n"),
    ("bytes", {"params": {"b": b"x"}}, "PARAMS", "/params/b"),
    ("set", {"params": {"s": {1}}}, "PARAMS", "/params/s"),
    ("int-key", {"params": {"x": {1: 2}}}, "PARAMS", "/params/x/1"),
    ("dollar-key", {"params": {"$f64": "3ff0000000000000"}}, "PARAMS", "/params/$f64"),
    ("escaped-key", {"params": {"a/b~": _NAN}}, "PARAMS", "/params/a~1b~0"),
    (
        "nested-dollar-key",
        {"params": {"a": {"$f64": "3ff0000000000000"}}},
        "PARAMS",
        "/params/a/$f64",
    ),
    ("surrogate-value", {"params": {"a": "\ud800"}}, "UNICODE", "/params/a"),
    ("surrogate-key", {"params": {"\ud800": 1}}, "UNICODE", "/params/\ud800"),
    ("too-deep", {"params": {"a": _lists(29)}}, "PARAMS", "/params"),
]


@pytest.mark.parametrize(
    ("changes", "code", "path"),
    [case[1:] for case in TRANSFORM_NEGATIVE],
    ids=[case[0] for case in TRANSFORM_NEGATIVE],
)
def test_transform_negative_space(changes: dict[str, Any], code: str, path: str) -> None:
    """参数树的每个违规值由 PARAMS 拒收，路径为该值的 JSON Pointer。"""
    rejects(code, path, lambda: transform(**changes))


def _pair(*taken: bool) -> tuple[Segment, ...]:
    """返回 1 个无条件段与若干个条件为 c1 的段，id 依次为 s0、s1、…。"""
    branches = [segment(id=f"s{i + 1}", branch=(("c1", int(t)),)) for i, t in enumerate(taken)]
    return (segment(id="s0"), *branches)


def test_valid_waveform_rules_accept() -> None:
    """正控：分支对两种顺序都接受。1.5 GSps 下时刻 2 ns 对齐。两次测量形成完整树。"""
    assert len(waveform(segments=_pair(True, False)).segments) == 3
    assert len(waveform(segments=_pair(False, True)).segments) == 3
    both = (
        *_pair(True, False),
        *(
            segment(id=f"leaf-{a}-{b}", branch=(("c1", a), ("c2", b)))
            for a in (0, 1)
            for b in (0, 1)
        ),
    )
    assert len(waveform(segments=both).segments) == 7
    aligned = (
        segment(id="s0", time_origin_ns=2),
        segment(id="s1", time_origin_ns=4, branch=(("c1", 0),)),
        segment(id="s2", time_origin_ns=4, branch=(("c1", 1),)),
    )
    assert waveform(sample_rate_hz=1_500_000_000, segments=aligned).sample_rate_hz == 1_500_000_000
    two = (channel(), channel(id="ch1", ports=("z0",)))
    assert waveform(channels=two, segments=(segment(samples=_TWO),)).channels == two


WAVEFORM_NEGATIVE: list[tuple[str, dict[str, Any], str, str]] = [
    ("schema", {"schema": "qaiji.waveform/0.1"}, "SCHEMA", "/schema"),
    ("short-ref", {"source_pulse_ref": "sha256:" + "0" * 63}, "REFERENCE", "/source_pulse_ref"),
    ("upper-ref", {"source_pulse_ref": "sha256:" + "A" * 64}, "REFERENCE", "/source_pulse_ref"),
    ("bare-ref", {"source_pulse_ref": "0" * 64}, "REFERENCE", "/source_pulse_ref"),
    ("newline-ref", {"source_pulse_ref": REF + "\n"}, "REFERENCE", "/source_pulse_ref"),
    ("int-ref", {"source_pulse_ref": 1}, "REFERENCE", "/source_pulse_ref"),
    ("zero-rate", {"sample_rate_hz": 0}, "RATE", "/sample_rate_hz"),
    ("negative-rate", {"sample_rate_hz": -GHZ}, "RATE", "/sample_rate_hz"),
    ("bool-rate", {"sample_rate_hz": True}, "RATE", "/sample_rate_hz"),
    ("float-rate", {"sample_rate_hz": 1e9}, "RATE", "/sample_rate_hz"),
    ("wide-rate", {"sample_rate_hz": 1 << 63}, "RATE", "/sample_rate_hz"),
    (
        "channel-type",
        {"channels": ({"id": "ch0"},), "segments": ()},
        "TYPE",
        "/channels/0",
    ),
    (
        "channel-order",
        {"channels": (channel(id="ch1"), channel(id="ch0")), "segments": ()},
        "ORDER",
        "/channels/1",
    ),
    (
        "channel-repeat",
        {"channels": (channel(), channel(ports=("z0",))), "segments": ()},
        "ORDER",
        "/channels/1",
    ),
    ("segment-type", {"segments": (segment(), "s1")}, "TYPE", "/segments/1"),
    (
        "segment-id",
        {"segments": (segment(), segment(time_origin_ns=40))},
        "SEGMENT_ID",
        "/segments/1/id",
    ),
    ("transform-type", {"transforms": ({"kind": "upconvert"},)}, "TYPE", "/transforms/0"),
    (
        "align",
        {
            "sample_rate_hz": 1_500_000_000,
            "segments": (segment(id="s0", time_origin_ns=2), segment(id="s1", time_origin_ns=1)),
        },
        "ALIGN",
        "/segments/1/time_origin_ns",
    ),
    (
        "channel-ref",
        {"segments": (segment(samples=(("ch0", f64le([0.0])), ("zz", f64le([0.0])))),)},
        "CHANNEL_REF",
        "/segments/0/samples/1",
    ),
    ("lone-branch", {"segments": _pair(True)}, "BRANCH", "/segments/1/branch"),
    ("same-taken", {"segments": _pair(True, True)}, "BRANCH", "/segments/2/branch"),
    ("third-branch", {"segments": _pair(True, False, True)}, "BRANCH", "/segments/3/branch"),
]


@pytest.mark.parametrize(
    ("changes", "code", "path"),
    [case[1:] for case in WAVEFORM_NEGATIVE],
    ids=[case[0] for case in WAVEFORM_NEGATIVE],
)
def test_waveform_negative_space(changes: dict[str, Any], code: str, path: str) -> None:
    """WaveformIR 的字段检查与 L0 规则：每个违规输入只给出 1 条诊断，码与路径符合预期。"""
    rejects(code, path, lambda: waveform(**changes))


def test_transform_equality_follows_canonical_bytes() -> None:
    """Python 中相等、规范字节不同的 params，记录不相等。规范字节相同的记录相等。"""
    variants = [transform(params={"a": value}) for value in (True, 1, 1.0)]
    assert variants[0] != variants[1]
    assert variants[1] != variants[2]
    assert variants[0] != variants[2]
    assert transform(params={"a": 0.0}) != transform(params={"a": -0.0})
    assert transform(params={"a": [1.0, {"b": None}]}) == transform(
        params={"a": (1.0, {"b": None})}
    )


def test_lists_are_stored_as_tuples() -> None:
    """list 输入存为 tuple：ports、branch、samples 及其条目、channels。"""
    assert channel(ports=["d0"]).ports == ("d0",)
    assert type(channel(ports=["d0"]).ports) is tuple
    built = segment(branch=[["c1", 1]], samples=[["ch0", f64le([0.0])]])
    assert type(built.branch) is tuple and built.branch == (("c1", 1),)
    assert type(built.samples) is tuple and type(built.samples[0]) is tuple
    assert type(waveform(channels=[channel()]).channels) is tuple
