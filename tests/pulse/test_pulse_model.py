# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1 记录的字段守卫与程序不变量。每个负例只违反一条规则。"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

from _pulse_fixtures import acquire, play, ports_frames, program, rejects, shift
from qaiji.core.pulse import PULSE_SCHEMA, Envelope, Frame, Port, PulseProgramIR


def test_valid_program_and_amplitude_bounds_are_accepted() -> None:
    """正控：幅度取 ±1 的合法程序可以构造，schema 取默认值。"""
    built = program([play(amplitude=-1.0), play(frame="d1", amplitude=1.0)])
    assert built.schema == PULSE_SCHEMA == "qaiji.pulse/0.1"
    assert built.instructions[1].amplitude == 1.0


FIELD_CASES: list[tuple[str, Any, dict[str, Any], str, str]] = [
    ("duration-zero", play, dict(duration_ns=0), "DURATION", "/duration_ns"),
    ("duration-negative", play, dict(duration_ns=-1), "DURATION", "/duration_ns"),
    ("acquire-duration", acquire, dict(duration_ns=0), "DURATION", "/duration_ns"),
    ("bool-start", play, dict(start_ns=True), "INTEGER", "/start_ns"),
    ("negative-start", play, dict(start_ns=-1), "TIME", "/start_ns"),
    ("negative-at", shift, dict(at_ns=-1), "TIME", "/at_ns"),
    ("amplitude-high", play, dict(amplitude=1.0000001), "AMPLITUDE", "/amplitude"),
    ("amplitude-low", play, dict(amplitude=-1.0000001), "AMPLITUDE", "/amplitude"),
    ("amplitude-nan", play, dict(amplitude=math.nan), "NONFINITE", "/amplitude"),
    ("phase-inf", play, dict(phase_rad=math.inf), "NONFINITE", "/phase_rad"),
    ("delta-nan", shift, dict(delta_rad=math.nan), "NONFINITE", "/delta_rad"),
    ("amplitude-text", play, dict(amplitude="0.5"), "NUMBER", "/amplitude"),
    ("negative-source", play, dict(source=-1), "INTEGER", "/source"),
    ("envelope-type", play, dict(envelope="gaussian"), "TYPE", "/envelope"),
    ("origin", shift, dict(origin="user"), "ORIGIN", "/origin"),
    ("event-empty", acquire, dict(event_id=""), "TEXT", "/event_id"),
    ("condition-empty", play, dict(condition_id=""), "TEXT", "/condition_id"),
]


@pytest.mark.parametrize(
    ("factory", "changes", "code", "path"),
    [case[1:] for case in FIELD_CASES],
    ids=[case[0] for case in FIELD_CASES],
)
def test_record_field_guards(factory: Any, changes: dict[str, Any], code: str, path: str) -> None:
    """字段守卫：整数、时长、幅度、有限值、枚举与文本。"""
    rejects(code, path, lambda: factory(**changes))


DECLARATION_CASES: list[tuple[str, Any, dict[str, Any], str, str]] = [
    ("role", Port, dict(id="p", role="control", targets=(0,)), "ROLE", "/role"),
    ("targets-empty", Port, dict(id="p", role="drive", targets=()), "TARGETS", "/targets"),
    ("targets-repeat", Port, dict(id="p", role="drive", targets=(0, 0)), "TARGETS", "/targets"),
    ("targets-negative", Port, dict(id="p", role="drive", targets=(-1,)), "TARGETS", "/targets"),
    ("port-id", Port, dict(id="", role="drive", targets=(0,)), "TEXT", "/id"),
    (
        "frequency-float",
        Frame,
        dict(id="f", port="p", frequency_hz=5.0, phase_rad=0.0),
        "INTEGER",
        "/frequency_hz",
    ),
    ("shape", Envelope, dict(shape="samples"), "ENVELOPE", "/shape"),
    ("gaussian-sigma", Envelope, dict(shape="gaussian"), "ENVELOPE", "/rel_sigma"),
    ("sigma-zero", Envelope, dict(shape="gaussian", rel_sigma=0.0), "ENVELOPE", "/rel_sigma"),
    ("constant-sigma", Envelope, dict(shape="constant", rel_sigma=5.0), "ENVELOPE", "/rel_sigma"),
    ("drag-beta", Envelope, dict(shape="drag", rel_sigma=5.0), "ENVELOPE", "/beta_ns"),
    (
        "gaussian-beta",
        Envelope,
        dict(shape="gaussian", rel_sigma=5.0, beta_ns=0.1),
        "ENVELOPE",
        "/beta_ns",
    ),
]


@pytest.mark.parametrize(
    ("cls", "values", "code", "path"),
    [case[1:] for case in DECLARATION_CASES],
    ids=[case[0] for case in DECLARATION_CASES],
)
def test_declaration_guards(cls: Any, values: dict[str, Any], code: str, path: str) -> None:
    """端口、帧与包络的字段守卫。"""
    rejects(code, path, lambda: cls(**values))


def _replace_frame(index_id: str, **changes: Any) -> tuple[Frame, ...]:
    _, frames = ports_frames()
    return tuple(dataclasses.replace(f, **changes) if f.id == index_id else f for f in frames)


def _frame_path(frame_id: str, name: str) -> str:
    _, frames = ports_frames()
    return f"/frames/{[f.id for f in frames].index(frame_id)}/{name}"


PROGRAM_CASES: list[tuple[str, Any, str, str]] = [
    ("schema", lambda: program(schema="qaiji.pulse/0.2"), "SCHEMA", "/schema"),
    (
        "reference",
        lambda: program(source_schedule_ref="sha256:XYZ"),
        "REFERENCE",
        "/source_schedule_ref",
    ),
    ("end", lambda: program(end_ns=-1), "TIME", "/end_ns"),
    ("port-order", lambda: program(ports=tuple(reversed(ports_frames()[0]))), "ORDER", "/ports/1"),
    (
        "frame-order",
        lambda: program(frames=tuple(reversed(ports_frames()[1]))),
        "ORDER",
        "/frames/1",
    ),
    (
        "frame-port",
        lambda: program(frames=_replace_frame("d1", port="zz")),
        "PORT_REF",
        _frame_path("d1", "port"),
    ),
    (
        "coupler-frequency",
        lambda: program(frames=_replace_frame("f01", frequency_hz=1)),
        "FREQUENCY",
        _frame_path("f01", "frequency_hz"),
    ),
    (
        "flux-frequency",
        lambda: program(frames=_replace_frame("z1", frequency_hz=-1)),
        "FREQUENCY",
        _frame_path("z1", "frequency_hz"),
    ),
    ("frame-ref", lambda: program([play(frame="nope")]), "FRAME_REF", "/instructions/0/frame"),
    (
        "acquire-port-ref",
        lambda: program([acquire(port="nope")]),
        "PORT_REF",
        "/instructions/0/port",
    ),
    (
        "condition-ref",
        lambda: program([play(condition_id="c9")]),
        "CONDITION_REF",
        "/instructions/0/condition_id",
    ),
    ("shift-readout", lambda: program([shift(frame="r0")]), "SHIFT_PORT", "/instructions/0/frame"),
    ("shift-coupler", lambda: program([shift(frame="f01")]), "SHIFT_PORT", "/instructions/0/frame"),
    ("acquire-role", lambda: program([acquire(port="r0")]), "ACQUIRE_PORT", "/instructions/0/port"),
    ("play-end", lambda: program([play(start_ns=1990)]), "END", "/instructions/0"),
    ("shift-end", lambda: program([shift(at_ns=2001)]), "END", "/instructions/0"),
    (
        "window-before",
        lambda: program([play(start_ns=99, condition_id="c1")], [("c1", 100, 200)]),
        "WINDOW",
        "/instructions/0",
    ),
    (
        "window-after",
        lambda: program([play(start_ns=161, condition_id="c1")], [("c1", 100, 200)]),
        "WINDOW",
        "/instructions/0",
    ),
    (
        "event-repeat",
        lambda: program([acquire(), acquire(port="a1")]),
        "EVENT",
        "/instructions/1/event_id",
    ),
    ("window-inverted", lambda: program(conditions=[("c1", 20, 10)]), "CONDITION", "/conditions/0"),
    ("window-end", lambda: program(conditions=[("c1", 0, 2001)]), "CONDITION", "/conditions/0"),
    (
        "condition-repeat",
        lambda: program(conditions=[("c1", 0, 10), ("c1", 20, 30)]),
        "CONDITION",
        "/conditions/1",
    ),
    (
        "condition-text",
        lambda: program(conditions=[("", 0, 10)]),
        "TEXT",
        "/conditions/0/condition_id",
    ),
    (
        "condition-start",
        lambda: program(conditions=[("c1", -1, 10)]),
        "TIME",
        "/conditions/0/start_ns",
    ),
    ("instruction-type", lambda: program([{"frame": "d0"}]), "TYPE", "/instructions/0"),
    (
        "instruction-order",
        lambda: program([play(start_ns=40), play(start_ns=0)]),
        "ORDER",
        "/instructions/1",
    ),
]


@pytest.mark.parametrize(
    ("build", "code", "path"),
    [case[1:] for case in PROGRAM_CASES],
    ids=[case[0] for case in PROGRAM_CASES],
)
def test_program_invariants(build: Any, code: str, path: str) -> None:
    """程序级不变量：引用、端口角色、flux 帧频率、时间范围、条件区间与排序。"""
    rejects(code, path, build)


def test_conditions_keep_schedule_order() -> None:
    """条件区间按 L2 顺序镜像，不按 id 字典序：同刻的 c9、c10 接受。"""
    built = program(conditions=[("c9", 20, 30), ("c10", 20, 30)])
    assert [c[0] for c in built.conditions] == ["c9", "c10"]


def test_window_edges_are_inside() -> None:
    """正控：条件记录恰好贴住区间两端时接受。"""
    program(
        [play(start_ns=100, condition_id="c1"), play(start_ns=160, condition_id="c1")],
        [("c1", 100, 200)],
    )


def test_instruction_order() -> None:
    """指令排序：同刻同帧 ShiftPhase 在 Play 前。同刻同帧多条 ShiftPhase 按 source 升序。"""
    program([shift(source=None), play()])
    rejects("ORDER", "/instructions/1", lambda: program([play(), shift()]))
    program([shift(source=2), shift(source=3)])
    program([shift(source=None), shift(source=2)])
    rejects("ORDER", "/instructions/1", lambda: program([shift(source=3), shift(source=2)]))
    rejects("ORDER", "/instructions/1", lambda: program([shift(source=2), shift(source=None)]))
    rejects("ORDER", "/instructions/1", lambda: program([shift(source=2), shift(source=2)]))
    rejects("ORDER", "/instructions/1", lambda: program([play(source=1), play(source=1)]))


def test_records_are_immutable_and_unhashable() -> None:
    """记录不可修改，也不可哈希（与原生层记录一致）。"""
    built = program([play()])
    with pytest.raises(dataclasses.FrozenInstanceError):
        built.end_ns = 1  # type: ignore[misc]
    with pytest.raises(TypeError):
        hash(built)
    assert isinstance(built.instructions, tuple)
    assert isinstance(PulseProgramIR, type)
