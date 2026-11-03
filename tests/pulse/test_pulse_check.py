# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1 与 L2 的一致性检查：引用、时间、条件、记录来源与覆盖、测量事件。"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from _pulse_fixtures import HEAD, config, lower_to_l1, rebuild, rejects, schedule
from qaiji.codec import from_qasm3
from qaiji.core.native import NativeScheduleIR, lower_to_native
from qaiji.core.pulse import (
    Acquire,
    Play,
    PulseProgramIR,
    ShiftPhase,
    check_pulse_program,
    dump_pulse_program,
    native_schedule_ref,
)


@pytest.mark.parametrize(
    "body",
    [
        "sx q[0]; rz(0.7) q[0]; sx q[0];",
        "h q[0]; h q[0];",
        "rz(0.3) q[0]; z q[0];",
        "cz q[0], q[1]; rz(0.2) q[0];",
    ],
)
def test_check_accepts_lowered_program(body: str) -> None:
    """正控：测试内降级得到的程序通过检查，含同刻同帧的多条 ShiftPhase。"""
    native = schedule(body)
    check_pulse_program(lower_to_l1(native), native)


BODY = "sx q[0]; rz(0.7) q[0]; cz q[0], q[1];"
CONDITIONAL = "rz(0) q[1];"


def _base() -> tuple[NativeScheduleIR, PulseProgramIR]:
    native = schedule(BODY, conditional_body=CONDITIONAL)
    return native, lower_to_l1(native)


def _index(native: NativeScheduleIR, kind: str) -> int:
    return next(i for i, op in enumerate(native.operations) if op.kind == kind)


def _edit(
    select: Callable[[Any], bool], change: Callable[[Any], Any | None]
) -> Callable[[NativeScheduleIR, PulseProgramIR], PulseProgramIR]:
    """把满足 ``select`` 的第 1 条指令替换为 ``change`` 的结果。结果为 None 时删除该指令。"""

    def apply(native: NativeScheduleIR, base: PulseProgramIR) -> PulseProgramIR:
        items = list(base.instructions)
        position = next(i for i, item in enumerate(items) if select(item))
        replaced = change(items[position])
        if replaced is None:
            del items[position]
        else:
            items[position] = replaced
        return rebuild(base, items)

    return apply


def _is(kind: type, **fields: Any) -> Callable[[Any], bool]:
    return lambda item: type(item) is kind and all(getattr(item, k) == v for k, v in fields.items())


def _conditional_shift(item: Any) -> bool:
    return type(item) is ShiftPhase and item.condition_id is not None


def _source_of(kind: str) -> Callable[[NativeScheduleIR, PulseProgramIR], PulseProgramIR]:
    """把第 1 个 RX90 的 Play 改为回溯到 ``kind`` 操作。"""

    def apply(native: NativeScheduleIR, base: PulseProgramIR) -> PulseProgramIR:
        target = _index(native, kind)
        rx90 = _index(native, "RX90")
        return _edit(_is(Play, source=rx90), lambda p: dataclasses.replace(p, source=target))(
            native, base
        )

    return apply


def _shift_source_rx90(native: NativeScheduleIR, base: PulseProgramIR) -> PulseProgramIR:
    rx90 = _index(native, "RX90")
    return _edit(_is(ShiftPhase, delta_rad=-0.7), lambda s: dataclasses.replace(s, source=rx90))(
        native, base
    )


MISMATCH: list[tuple[str, Any, str, str]] = [
    (
        "schedule-ref",
        lambda n, b: dataclasses.replace(
            b, source_schedule_ref=lower_to_l1(schedule("")).source_schedule_ref
        ),
        "SCHEDULE_REF",
        "/source_schedule_ref",
    ),
    ("end", lambda n, b: dataclasses.replace(b, end_ns=b.end_ns + 1), "END", "/end_ns"),
    (
        "conditions",
        lambda n, b: dataclasses.replace(
            b, conditions=tuple((c, s - 1, e) for c, s, e in b.conditions)
        ),
        "CONDITIONS",
        "/conditions",
    ),
    (
        "play-time",
        _edit(_is(Play, frame="f01"), lambda p: dataclasses.replace(p, start_ns=p.start_ns + 1)),
        "TIME",
        "/instructions/2",
    ),
    (
        "source-range",
        _edit(_is(Play, frame="f01"), lambda p: dataclasses.replace(p, source=99)),
        "SOURCE",
        "/instructions/2/source",
    ),
    (
        "condition",
        _edit(_conditional_shift, lambda s: dataclasses.replace(s, condition_id=None)),
        "CONDITION",
        "/instructions/5/condition_id",
    ),
    ("play-source", _source_of("RZ"), "PLAY_SOURCE", "/instructions/0/source"),
    ("shift-source", _shift_source_rx90, "SHIFT_SOURCE", "/instructions/1/source"),
    (
        "shift-delta",
        _edit(_is(ShiftPhase, delta_rad=-0.7), lambda s: dataclasses.replace(s, delta_rad=0.7)),
        "SHIFT_DELTA",
        "/instructions/1/delta_rad",
    ),
    (
        "shift-frames",
        _edit(_conditional_shift, lambda s: None),
        "SHIFT_FRAMES",
        "/instructions",
    ),
    ("play-missing", _edit(_is(Play, frame="d0"), lambda p: None), "PLAY_MISSING", "/instructions"),
    (
        "readout",
        lambda n, b: rebuild(
            b,
            [
                *b.instructions,
                *[
                    dataclasses.replace(p, start_ns=p.start_ns + 1, duration_ns=p.duration_ns - 1)
                    for p in b.instructions
                    if _is(Play, frame="r0")(p)
                ],
            ],
        ),
        "READOUT",
        "/instructions",
    ),
    (
        "rx90-frame",
        _edit(_is(Play, frame="d0"), lambda p: dataclasses.replace(p, frame="d1")),
        "TARGET",
        "/instructions/0/frame",
    ),
    (
        "cz-frame",
        _edit(_is(Play, frame="f01"), lambda p: dataclasses.replace(p, frame="d0")),
        "TARGET",
        "/instructions/2/frame",
    ),
    (
        "measure-frame",
        _edit(_is(Play, frame="r0"), lambda p: dataclasses.replace(p, frame="r1")),
        "TARGET",
        "/instructions/4/frame",
    ),
    (
        "acquire-port",
        _edit(_is(Acquire), lambda a: dataclasses.replace(a, port="a1")),
        "TARGET",
        "/instructions/3/port",
    ),
    (
        "event-ref",
        _edit(_is(Acquire), lambda a: dataclasses.replace(a, event_id="m9")),
        "EVENT_REF",
        "/instructions/3/event_id",
    ),
    ("event-missing", _edit(_is(Acquire), lambda a: None), "EVENT_MISSING", "/instructions"),
]


def test_check_accepts_same_time_conditions() -> None:
    """同刻的多个条件区间按 L2 顺序镜像：c9、c10、c11 不按字典序。"""
    text = HEAD + "x q[1];\n" * 8 + "c[0] = measure q[0];\n"
    text += "if (c[0] == 1) { rz(0) q[1]; }\n" * 3
    native = lower_to_native(from_qasm3(text), config())
    assert [r.condition_id for r in native.conditions] == ["c9", "c10", "c11"]
    assert len({r.start_ns for r in native.conditions}) == 1  # 夹具前提：三个区间同刻
    check_pulse_program(lower_to_l1(native), native)


def test_type_guards() -> None:
    """入口拒收错误类型。"""
    native, base = _base()
    rejects("TYPE", "", check_pulse_program, None, native)
    rejects("TYPE", "", check_pulse_program, base, None)
    rejects("TYPE", "", dump_pulse_program, None)
    rejects("TYPE", "", native_schedule_ref, None)


def test_mismatch_base_program_is_accepted() -> None:
    """正控：拒收用例的基准程序通过检查，且各用例引用的下标符合预期。"""
    native, base = _base()
    check_pulse_program(base, native)
    kinds = [(type(item).__name__, getattr(item, "frame", None)) for item in base.instructions]
    assert kinds[:3] == [("Play", "d0"), ("ShiftPhase", "d0"), ("Play", "f01")]
    assert type(base.instructions[3]) is Acquire and kinds[5] == ("ShiftPhase", "d1")


@pytest.mark.parametrize(
    ("mutate", "code", "path"),
    [case[1:] for case in MISMATCH],
    ids=[case[0] for case in MISMATCH],
)
def test_check_rejects_mismatch(mutate: Any, code: str, path: str) -> None:
    """每个不一致由对应检查拒收。改动后的程序本身仍满足 L1 不变量。"""
    native, base = _base()
    changed = mutate(native, base)
    rejects(code, path, check_pulse_program, changed, native)
