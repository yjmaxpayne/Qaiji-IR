# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1 包络与 Play 的采样：样本数、包络与独立参考公式的比较、混频。

参考值在测试内按 EmuPlat 的样本序号形式独立写出：x = 0..N−1，sr 以 GSps 计。
不调用被测的 ``sample_envelope`` 构造参考值。
"""

from __future__ import annotations

import dataclasses
import math
from fractions import Fraction
from typing import Any

import pytest

from _pulse_fixtures import DRAG, FLAT, GAUSS, play, ports_frames, program, rebuild, shift
from _waveform_fixtures import GHZ, rejects
from qaiji.core.pulse import Envelope, PulseProgramIR
from qaiji.core.waveform import sample_count, sample_envelope, sample_play

DURATION_NS = 40


def reference_envelope(
    envelope: Envelope, duration_ns: int, rate_hz: int
) -> tuple[list[float], list[float]]:
    """按 EmuPlat 的样本序号形式求 (I, Q)。DRAG 的 Q 带 β·sr，sr 以 GSps 计。"""
    n = duration_ns * rate_hz // GHZ
    sr = rate_hz / GHZ
    centre = (n - 1) / 2
    if envelope.shape == "constant":
        return [1.0] * n, [0.0] * n
    assert envelope.rel_sigma is not None
    width = n / envelope.rel_sigma
    i = [math.exp(-0.5 * ((x - centre) / width) ** 2) for x in range(n)]
    if envelope.shape == "gaussian":
        return i, [0.0] * n
    assert envelope.beta_ns is not None
    beta = envelope.beta_ns
    q = [beta * sr * (-(x - centre) / (width**2)) * i[x] for x in range(n)]
    return i, q


def max_difference(actual: Any, expected: list[float]) -> float:
    assert len(actual) == len(expected)
    return max(abs(a - b) for a, b in zip(actual, expected, strict=True))


def test_sample_count() -> None:
    """N = duration·f_s / 1e9，须为整数。非整数时拒收，不取整。"""
    assert sample_count(40, GHZ) == 40
    assert sample_count(40, 4 * GHZ) == 160
    assert sample_count(2, 1_500_000_000) == 3
    assert sample_count(1_000_000_000, 1) == 1


SAMPLE_COUNT_NEGATIVE: list[tuple[str, tuple[Any, Any], str]] = [
    ("fractional", (1, 1_500_000_000), "SAMPLE_COUNT"),
    ("sub-sample", (1, 1), "SAMPLE_COUNT"),
    ("zero-duration", (0, GHZ), "DURATION"),
    ("bool-duration", (True, GHZ), "DURATION"),
    ("float-duration", (40.0, GHZ), "DURATION"),
    ("zero-rate", (40, 0), "RATE"),
    ("float-rate", (40, 1e9), "RATE"),
    ("bool-rate", (40, True), "RATE"),
    ("negative-duration", (-40, GHZ), "DURATION"),
]


@pytest.mark.parametrize(
    ("args", "code"),
    [case[1:] for case in SAMPLE_COUNT_NEGATIVE],
    ids=[case[0] for case in SAMPLE_COUNT_NEGATIVE],
)
def test_sample_count_negative_space(args: tuple[Any, Any], code: str) -> None:
    """函数参数的诊断路径为文档根 ""。"""
    rejects(code, "", sample_count, *args)


@pytest.mark.parametrize("rate_ghz", [1, 2, 4, 100])
@pytest.mark.parametrize("envelope", [FLAT, GAUSS], ids=["constant", "gaussian"])
def test_envelope_matches_reference(envelope: Envelope, rate_ghz: int) -> None:
    """constant 与 Gaussian 的 (I, Q) 与参考公式的最大差 ≤ 1e-10。求值点为样本中点。"""
    rate = rate_ghz * GHZ
    i, q = sample_envelope(envelope, DURATION_NS, rate)
    ref_i, ref_q = reference_envelope(envelope, DURATION_NS, rate)
    assert type(i) is tuple and type(q) is tuple
    assert len(i) == len(q) == DURATION_NS * rate_ghz
    assert all(type(value) is float for value in (*i, *q))
    assert max_difference(i, ref_i) <= 1e-10
    assert max_difference(q, ref_q) <= 1e-10


@pytest.mark.parametrize("rate_ghz", [1, 4, 8])
def test_drag_matches_reference(rate_ghz: int) -> None:
    """DRAG（rel_sigma=5，β=0.7 ns）的 I、Q 与参考公式的最大差 ≤ 1e-10。β 在各采样率下不缩放。"""
    envelope = Envelope(shape="drag", rel_sigma=5.0, beta_ns=0.7)
    rate = rate_ghz * GHZ
    i, q = sample_envelope(envelope, DURATION_NS, rate)
    ref_i, ref_q = reference_envelope(envelope, DURATION_NS, rate)
    # 前提：Q 明显非零，否则 Q 的符号与 β 的单位都没有鉴别力。
    assert max(abs(value) for value in ref_q) > 0.01
    assert max_difference(i, ref_i) <= 1e-10
    assert max_difference(q, ref_q) <= 1e-10


def test_sample_envelope_negative_space() -> None:
    """包络不是 L1 Envelope 时 TYPE。时长与采样率不给出整数样本数时 SAMPLE_COUNT。"""
    rejects("TYPE", "", sample_envelope, "gaussian", DURATION_NS, GHZ)
    rejects("TYPE", "", sample_envelope, {"shape": "constant"}, DURATION_NS, GHZ)
    rejects("SAMPLE_COUNT", "", sample_envelope, GAUSS, 1, 1_500_000_000)


FREQUENCY_HZ = 5_123_456_789
START_NS = 1000


def mixing_program() -> tuple[PulseProgramIR, Any, float]:
    """返回程序、被测 Play 与在测试内求出的帧相位。

    帧 d0 初相 0.4。计入的 ShiftPhase：t=0 的 −0.3 与 Play 同一时刻的 0.9。不计入的：
    Play 之后的 1.7 与另一帧 d1 上的 2.1。Play 的相位为 0.25。
    """
    _, frames = ports_frames()
    frames = tuple(
        dataclasses.replace(frame, frequency_hz=FREQUENCY_HZ, phase_rad=0.4)
        if frame.id == "d0"
        else frame
        for frame in frames
    )
    target = play(start_ns=START_NS, envelope=DRAG, amplitude=0.6, phase_rad=0.25)
    items = [
        shift(at_ns=0, delta_rad=-0.3),
        shift(at_ns=START_NS, delta_rad=0.9),
        shift(at_ns=1500, delta_rad=1.7),
        shift(frame="d1", at_ns=500, delta_rad=2.1),
        target,
    ]
    built = rebuild(program(frames=frames), items)
    return built, target, math.fsum([0.4, -0.3, 0.9, 0.25])


@pytest.mark.parametrize("rate_hz", [GHZ, 2_500_000_000, 8 * GHZ])
def test_sample_play_mixes_envelope_with_absolute_carrier(rate_hz: int) -> None:
    """s_k = A·(I_k·cos φ_k − Q_k·sin φ_k)，载波时刻为 start_ns + k/f_s，帧相位计入 ShiftPhase。"""
    built, target, frame = mixing_program()
    samples = sample_play(built, target, rate_hz)
    i, q = reference_envelope(DRAG, DURATION_NS, rate_hz)
    offset = (math.tau * FREQUENCY_HZ * START_NS * 1e-9) % math.tau
    expected = []
    for k in range(len(i)):
        phi = math.tau * FREQUENCY_HZ * (k / rate_hz) + offset + frame
        expected.append(0.6 * (i[k] * math.cos(phi) - q[k] * math.sin(phi)))
    assert type(samples) is tuple
    assert all(type(value) is float for value in samples)
    assert max_difference(samples, expected) <= 1e-9


def test_sample_play_rejects_foreign_play() -> None:
    """Play 不是该程序的指令时 PLAY_REF。"""
    built, target, _ = mixing_program()
    foreign = dataclasses.replace(target, start_ns=START_NS + 1)
    assert foreign not in built.instructions
    rejects("PLAY_REF", "", sample_play, built, foreign, GHZ)


def test_sample_play_carrier_phase_does_not_drift_with_time() -> None:
    """起点 1e8 ns 时，载波相位与精确有理数参考的最大差不超过 1e-10。

    浮点直接计算 2π·f·t·1e-9 时，误差随 t 线性增长，1e8 ns 处约为 6e-7 rad。
    """
    _, frames = ports_frames()
    frames = tuple(
        dataclasses.replace(frame, frequency_hz=FREQUENCY_HZ, phase_rad=0.0)
        if frame.id == "d0"
        else frame
        for frame in frames
    )
    start = 10**8
    target = play(start_ns=start, envelope=FLAT, amplitude=1.0, phase_rad=0.0)
    built = rebuild(program(frames=frames), [target], end_ns=start + 1000)
    rate = 2 * GHZ
    samples = sample_play(built, target, rate)
    reference = []
    for k in range(len(samples)):
        turns = Fraction(FREQUENCY_HZ) * (start + Fraction(k * GHZ, rate)) / GHZ
        reference.append(math.cos(math.tau * float(turns % 1)))
    assert len(samples) == 2 * target.duration_ns
    assert max_difference(samples, reference) <= 1e-10
