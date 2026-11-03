# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1 包络的参考采样与混频。

包络按连续时间定义求值，与采样率无关：第 k 个样本取中点 ``t_k = (k + ½) / f_s``。
混频的载波取样本时刻 ``start_ns + k / f_s``，输出 ``s = A·(I·cos φ − Q·sin φ)``。
"""

from __future__ import annotations

import math
from typing import Any, cast

from qaiji.core.pulse import Envelope, Play, PulseProgramIR, frame_phase

from .errors import _fail
from .model import NS_PER_SECOND


def _positive(value: Any, path: str, code: str) -> int:
    if type(value) is not int or value < 1:
        _fail(code, path, "Expected a positive integer.")
    return cast(int, value)


def sample_count(duration_ns: int, sample_rate_hz: int) -> int:
    """计算样本数 N = ``duration_ns · sample_rate_hz / 1e9``。

    Args:
        duration_ns: 时长，单位 ns，正整数。
        sample_rate_hz: 采样率，单位 Hz，正整数。

    Returns:
        样本数 N。

    Raises:
        WaveformContractError: 参数不是正整数（``DURATION``、``RATE``），或 N 不是整数
            （``SAMPLE_COUNT``）。
    """
    duration = _positive(duration_ns, "", "DURATION")
    rate = _positive(sample_rate_hz, "", "RATE")
    count, remainder = divmod(duration * rate, NS_PER_SECOND)
    if remainder:
        _fail("SAMPLE_COUNT", "", "duration_ns · sample_rate_hz is not a multiple of 1e9.")
    return count


def sample_envelope(
    envelope: Envelope, duration_ns: int, sample_rate_hz: int
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """按中点规则对单位幅度包络采样。

    设 T 为时长，σ = T / ``rel_sigma``。gaussian 为 ``exp(−½((t − T/2)/σ)²)``。
    drag 的 I 与 gaussian 相同，Q 为 ``−β·(t − T/2)/σ²·I``，β 为 ``beta_ns``。

    Args:
        envelope: L1 包络。
        duration_ns: 时长，单位 ns。
        sample_rate_hz: 采样率，单位 Hz。

    Returns:
        ``(I, Q)``，各含 N 个值。

    Raises:
        WaveformContractError: ``envelope`` 不是 ``Envelope``（``TYPE``），或样本数不合法。
    """
    if type(envelope) is not Envelope:
        _fail("TYPE", "", "Expected Envelope.")
    count = sample_count(duration_ns, sample_rate_hz)
    if envelope.shape == "constant":
        return (1.0,) * count, (0.0,) * count
    centre = duration_ns / 2
    sigma = duration_ns / cast(float, envelope.rel_sigma)
    times = [(k + 0.5) * NS_PER_SECOND / sample_rate_hz for k in range(count)]
    in_phase = tuple(math.exp(-0.5 * ((t - centre) / sigma) ** 2) for t in times)
    if envelope.shape == "gaussian":
        return in_phase, (0.0,) * count
    beta = cast(float, envelope.beta_ns)
    quadrature = tuple(
        -beta * (t - centre) / sigma**2 * value for t, value in zip(times, in_phase, strict=True)
    )
    return in_phase, quadrature


def sample_play(program: PulseProgramIR, play: Play, sample_rate_hz: int) -> tuple[float, ...]:
    """把一条 ``Play`` 混频为实值实验室系样本。

    第 k 个样本的载波相位为 ``2π·f·t_k·1e-9 + frame_phase``，``t_k = start_ns + k·1e9 / f_s``（单位 ns）。
    ``f·t_k·1e-9`` 先用整数按整周约简，再乘 2π。

    Args:
        program: 含 ``play`` 的 L1 程序。
        play: 程序中的一条 ``Play``。
        sample_rate_hz: 采样率，单位 Hz。

    Returns:
        N 个实值样本。

    Raises:
        WaveformContractError: ``program`` 不是 ``PulseProgramIR``（``TYPE``），``play`` 不是该
            程序的指令（``PLAY_REF``），或样本数不合法。
    """
    if type(program) is not PulseProgramIR:
        _fail("TYPE", "", "Expected PulseProgramIR.")
    if type(play) is not Play or play not in program.instructions:
        _fail("PLAY_REF", "", "The play is not an instruction of the program.")
    in_phase, quadrature = sample_envelope(play.envelope, play.duration_ns, sample_rate_hz)
    frequency = next(frame.frequency_hz for frame in program.frames if frame.id == play.frame)
    phase = frame_phase(program, play)
    # Reduce f·t to a fraction of one turn in integers, so the error does not grow with t.
    start_turns = (frequency * play.start_ns) % NS_PER_SECOND / NS_PER_SECOND
    samples = []
    for k, (i_value, q_value) in enumerate(zip(in_phase, quadrature, strict=True)):
        turns = start_turns + (frequency * k) % sample_rate_hz / sample_rate_hz
        carrier = math.tau * turns + phase
        samples.append(play.amplitude * (i_value * math.cos(carrier) - q_value * math.sin(carrier)))
    return tuple(samples)
