# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L0 波形测试共用的夹具：合法记录的构造器、f64le 打包与诊断断言。"""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterable
from typing import Any

import pytest

from qaiji.core.waveform import (
    Channel,
    Segment,
    TransformRecord,
    WaveformContractError,
    WaveformDiagnostic,
    WaveformIR,
)

REF = "sha256:" + "0" * 64
GHZ = 1_000_000_000


def f64le(values: Iterable[float]) -> bytes:
    """把浮点值打包为小端 binary64 字节。"""
    items = list(values)
    return struct.pack(f"<{len(items)}d", *items)


def channel(**changes: Any) -> Channel:
    values: dict[str, Any] = dict(id="ch0", kind="dac_real", ports=("d0",))
    return Channel(**(values | changes))


def segment(**changes: Any) -> Segment:
    values: dict[str, Any] = dict(
        id="s0", time_origin_ns=0, branch=(), samples=(("ch0", f64le([0.0, 0.5])),)
    )
    return Segment(**(values | changes))


def transform(**changes: Any) -> TransformRecord:
    values: dict[str, Any] = dict(kind="upconvert", params={"lo_hz": 5_000_000_000, "phase": 0.25})
    return TransformRecord(**(values | changes))


def waveform(**changes: Any) -> WaveformIR:
    """构造 1 GSps、1 个通道、1 个段的波形。``schema`` 取默认值。"""
    values: dict[str, Any] = dict(
        source_pulse_ref=REF,
        sample_rate_hz=GHZ,
        channels=(channel(),),
        segments=(segment(),),
        transforms=(),
    )
    return WaveformIR(**(values | changes))


def rejects(code: str, path: str, call: Callable[..., Any], *args: Any) -> WaveformDiagnostic:
    """断言 ``call`` 只给出 1 条诊断，且类别、诊断码与 JSON Pointer 路径符合预期。"""
    with pytest.raises(WaveformContractError) as caught:
        call(*args)
    (diagnostic,) = caught.value.diagnostics
    expected = ("INVALID_WAVEFORM", code, path)
    assert (diagnostic.category, diagnostic.code, diagnostic.path) == expected, diagnostic
    return diagnostic
