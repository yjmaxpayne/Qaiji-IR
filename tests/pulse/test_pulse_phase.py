# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""帧相位比较、帧相位、载波相位与条件区间净帧相位。

参考值在测试内按公式写出，不调用被测函数。VZ 规则：RZ(θ) 使帧相位累加 −θ。
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from _pulse_fixtures import (
    lower_to_l1,
    play,
    ports_frames,
    program,
    rejects,
    schedule,
    shift,
)
from qaiji.core.pulse import (
    PHASE_ATOL,
    Play,
    ShiftPhase,
    carrier_phase,
    check_pulse_program,
    frame_phase,
    phases_equal,
)

TAU = 2 * math.pi


@pytest.mark.parametrize(
    ("a", "b", "equal"),
    [
        (0.0, TAU, True),
        (0.0, -TAU, True),
        (math.pi, -math.pi, True),
        (0.3, 0.3 + 2 * TAU, True),
        (0.0, 1e-10, True),
        (0.0, 2e-10, False),
        (0.0, 0.3, False),
        (1.0, -1.0, False),
    ],
)
def test_phases_equal(a: float, b: float, equal: bool) -> None:
    """按 2π 取模比较，容差 1e-10。"""
    assert PHASE_ATOL == 1e-10
    assert phases_equal(a, b) is equal


def _plays(built):
    return [item for item in built.instructions if isinstance(item, Play)]


@pytest.mark.parametrize("theta", [0.3, -1.1])
def test_frame_phase_matches_virtual_z_rule(theta: float) -> None:
    """RX90、RZ(θ)、RX90。第 2 个 RX90 的帧相位等于 EmuPlat 规则的 −θ。"""
    built = lower_to_l1(schedule(f"rx(pi/2) q[0]; rz({theta!r}) q[0]; rx(pi/2) q[0];"))
    first, second = _plays(built)
    assert frame_phase(built, first) == 0.0
    assert frame_phase(built, second) == -theta


def test_frame_phase_includes_shift_at_play_start() -> None:
    """边界含等号：RZ 的时刻等于下一个 RX90 的起点时计入。"""
    built = lower_to_l1(schedule("sx q[0]; rz(0.7) q[0]; sx q[0];"))
    (vz,) = [item for item in built.instructions if isinstance(item, ShiftPhase)]
    first, second = _plays(built)
    assert vz.at_ns == second.start_ns  # 夹具前提：两者同刻
    assert frame_phase(built, first) == 0.0
    assert frame_phase(built, second) == -0.7


def test_frame_phase_excludes_later_shift() -> None:
    """Play 起点之后的 ShiftPhase 不计入。"""
    built = lower_to_l1(schedule("sx q[0]; rz(0.7) q[0];"))
    (only,) = _plays(built)
    assert frame_phase(built, only) == 0.0


def test_frame_phase_filters_frame() -> None:
    """只计入同一帧的 ShiftPhase。"""
    built = lower_to_l1(schedule("rz(0.4) q[1]; sx q[0]; sx q[1];"))
    first, second = sorted(_plays(built), key=lambda p: p.frame)
    assert (first.frame, second.frame) == ("d0", "d1")
    assert frame_phase(built, first) == 0.0
    assert frame_phase(built, second) == -0.4


def test_frame_phase_adds_initial_and_play_phase() -> None:
    """帧相位 = 帧初相 + Σδ + Play.phase_rad。"""
    _, frames = ports_frames()
    frames = tuple(dataclasses.replace(f, phase_rad=0.2) if f.id == "d0" else f for f in frames)
    target = play(phase_rad=0.5)
    built = program([shift(delta_rad=-0.3), target], frames=frames)
    assert abs(frame_phase(built, target) - math.fsum([0.2, -0.3, 0.5])) <= 1e-15


def test_frame_phase_rejects_foreign_play() -> None:
    """Play 不在程序中时拒收。"""
    built = program([play()])
    rejects("PLAY_REF", "", lambda: frame_phase(built, play(start_ns=40)))


def test_carrier_phase_uses_absolute_time() -> None:
    """载波相位 = 2π·f·t·1e-9 + 帧相位，t 为绝对时刻，不是 Play 起点。"""
    target = play(start_ns=100, phase_rad=0.25)
    built = program([target])
    frequency = 4_900_000_123  # d0 帧，不是 10 MHz 的整数倍
    expected = 2 * math.pi * frequency * 112.5 * 1e-9 + 0.25
    assert abs(carrier_phase(built, target, 112.5) - expected) <= 1e-9


def test_condition_phase_accepts_full_turns() -> None:
    """条件区间净帧相位按 2π 取模：区间内 z; z 的和为 −2π，接受。"""
    full_turn = [
        shift(at_ns=100, delta_rad=-math.pi, condition_id="c1", source=1),
        shift(at_ns=100, delta_rad=-math.pi, condition_id="c1", source=2),
    ]
    program(full_turn, [("c1", 100, 200)])
    program(
        [shift(at_ns=100, delta_rad=0.3, condition_id="c1"), shift(at_ns=150, condition_id="c1")],
        [("c1", 100, 200)],
    )


def test_condition_phase_tolerance() -> None:
    """容差边界：1e-10 与 2π−1e-11 接受，2e-10 拒收。"""
    window = [("c1", 0, 10)]
    for delta in (1e-10, TAU - 1e-11):
        program([shift(delta_rad=delta, condition_id="c1")], window)
    rejects(
        "CONDITION_PHASE",
        "/conditions/0",
        lambda: program([shift(delta_rad=2e-10, condition_id="c1")], window),
    )


def test_condition_phase_is_per_frame() -> None:
    """净帧相位对每个帧分别求和：两帧 +0.3、−0.3 拒收。"""
    items = [
        shift(frame="d0", delta_rad=0.3, condition_id="c1"),
        shift(frame="d1", delta_rad=-0.3, condition_id="c1"),
    ]
    rejects("CONDITION_PHASE", "/conditions/0", lambda: program(items, [("c1", 0, 10)]))


def test_condition_phase_is_per_condition() -> None:
    """净帧相位对每个条件区间分别求和：两个区间 −0.3、+0.3 拒收。"""
    items = [
        shift(at_ns=0, condition_id="c1"),
        shift(at_ns=20, delta_rad=0.3, condition_id="c2"),
    ]
    windows = [("c1", 0, 10), ("c2", 20, 30)]
    rejects("CONDITION_PHASE", "/conditions/0", lambda: program(items, windows))


def test_v0_conditional_rz_is_rejected() -> None:
    """负空间：v0 形式的条件体 rz(0.3) 在区间内保留 RZ，按 2π 取模后不为 0。"""
    rejects(
        "CONDITION_PHASE",
        "/conditions/0",
        lambda: program([shift(at_ns=1200, condition_id="c1", source=1)], [("c1", 1200, 1200)]),
    )


@pytest.mark.parametrize(
    "body", ["z q[1];", "s q[1];", "t q[1];", "sdg q[1];", "rz(0.3) q[1];", "rz(0) q[1];"]
)
def test_lowered_conditional_bodies_pass_l1_9(body: str) -> None:
    """规则集 v1 的条件体降到 L1 后，净帧相位检查与 check_pulse_program 都接受。"""
    native = schedule("", conditional_body=body)
    built = lower_to_l1(native)
    check_pulse_program(built, native)
    shifts = [item for item in built.instructions if isinstance(item, ShiftPhase)]
    assert all(item.condition_id == "c1" for item in shifts)
    if body == "rz(0) q[1];":
        # 条件体 RZ(+0.0) 降为 ShiftPhase(-0.0)，与 L2 一一对应。
        (zero,) = shifts
        assert math.copysign(1.0, zero.delta_rad) == -1.0
