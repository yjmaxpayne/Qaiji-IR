# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""帧相位比较、帧相位与载波相位的纯函数。

L1 不存累计帧相位字段：帧相位由程序计算，只有一个真值来源。所有帧相位比较都调用
``phases_equal``，包括条件区间的净帧相位检查与 ``check_pulse_program``。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .errors import _fail

if TYPE_CHECKING:
    from .model import Frame, Play, PulseProgramIR

PHASE_ATOL = 1e-10


def phases_equal(a: float, b: float) -> bool:
    """按 2π 取模比较两个帧相位。

    判据为 ``abs(math.remainder(a - b, 2π)) <= 1e-10``。帧相位只经 ``e^{iφ}`` 进入波形，
    所以相差 2π 整数倍的两个相位相等。

    Args:
        a: 第 1 个相位，单位 rad。
        b: 第 2 个相位，单位 rad。

    Returns:
        两个相位按 2π 取模后的差不超过 ``PHASE_ATOL`` 时为 True。
    """
    return abs(math.remainder(a - b, math.tau)) <= PHASE_ATOL


def frame_phase(program: PulseProgramIR, play: Play) -> float:
    """计算 ``play`` 的帧相位：帧初相 + Σδ + ``play.phase_rad``。

    Σδ 取同一帧上 ``at_ns <= play.start_ns`` 的全部 ``ShiftPhase``。同一时刻的
    ``ShiftPhase`` 先于 ``Play`` 生效（指令排序规则）。求和用 ``math.fsum``，结果与记录顺序无关。

    Args:
        program: 含 ``play`` 的 L1 程序。
        play: 程序中的一条 ``Play``。

    Returns:
        帧相位，单位 rad，不取模。

    Raises:
        PulseContractError: ``play`` 不是该程序的指令（``PLAY_REF``）。
    """
    from .model import ShiftPhase

    if play not in program.instructions:
        _fail("PLAY_REF", "", "The play is not an instruction of the program.")
    deltas = [
        item.delta_rad
        for item in program.instructions
        if type(item) is ShiftPhase and item.frame == play.frame and item.at_ns <= play.start_ns
    ]
    return math.fsum([_frame(program, play).phase_rad, *deltas, play.phase_rad])


def carrier_phase(program: PulseProgramIR, play: Play, t_ns: float) -> float:
    """计算绝对时刻 ``t_ns`` 的载波相位：``2π·f·t·1e-9 + frame_phase``。

    Args:
        program: 含 ``play`` 的 L1 程序。
        play: 程序中的一条 ``Play``。
        t_ns: 程序时间轴上的绝对时刻，单位 ns，不是相对 ``play`` 起点的时刻。

    Returns:
        载波相位，单位 rad，不取模。

    Raises:
        PulseContractError: ``play`` 不是该程序的指令（``PLAY_REF``）。
    """
    phase = frame_phase(program, play)
    return math.tau * _frame(program, play).frequency_hz * t_ns * 1e-9 + phase


def _frame(program: PulseProgramIR, play: Play) -> Frame:
    return next(frame for frame in program.frames if frame.id == play.frame)
