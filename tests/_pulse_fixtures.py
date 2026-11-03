# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1 脉冲测试共用的夹具：L2 调度、测试内的 L2→L1 降级与诊断断言。

测试内的降级只用于构造输入。它按 VZ 规则把 RZ(θ) 写成 ShiftPhase(−θ)，Z 写成
ShiftPhase(−π)。生产降级在 EmuPlat，不在本包。
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Iterable
from typing import Any

import pytest

from qaiji.codec import from_qasm3
from qaiji.core.native import (
    NativeScheduleIR,
    OperationSpec,
    QubitResource,
    ScheduleConfig,
    lower_to_native,
)
from qaiji.core.pulse import (
    Acquire,
    Envelope,
    Frame,
    Play,
    Port,
    PulseContractError,
    PulseDiagnostic,
    PulseProgramIR,
    ShiftPhase,
    native_schedule_ref,
)

REF = "sha256:" + "0" * 64
HEAD = "OPENQASM 3.0;\nqubit[2] q;\nbit[1] c;\n"
GAUSS = Envelope(shape="gaussian", rel_sigma=5.0)
FLAT = Envelope(shape="constant")
DRAG = Envelope(shape="drag", rel_sigma=5.0, beta_ns=0.7)
_RANK = {ShiftPhase: 0, Play: 1, Acquire: 2}


def config() -> ScheduleConfig:
    """两比特合成配置：RX90 40 ns，CZ 96 ns，MEASURE 1000 ns，结果延迟 200 ns。"""
    durations = {"I": 0, "Z": 0, "RZ": 0, "RX90": 40, "MEASURE": 1000}
    specs = [
        OperationSpec(
            kind=kind,
            qubits=(q,),
            duration_ns=duration,
            resources=(f"q{q}",),
            result_latency_ns=200 if kind == "MEASURE" else 0,
        )
        for q in (0, 1)
        for kind, duration in durations.items()
    ]
    specs += [
        OperationSpec(
            kind="CZ", qubits=pair, duration_ns=96, resources=("q0", "q1"), result_latency_ns=0
        )
        for pair in ((0, 1), (1, 0))
    ]
    return ScheduleConfig(
        qubit_resources=tuple(QubitResource(qubit=q, resource=f"q{q}") for q in (0, 1)),
        operation_specs=tuple(specs),
        cz_couplings=((0, 1),),
    )


def schedule(body: str, conditional_body: str | None = None) -> NativeScheduleIR:
    """降级 ``body``。给出 ``conditional_body`` 时，先测量 q[0]，再把它放进条件体。"""
    text = HEAD + body
    if conditional_body is not None:
        text += "\nc[0] = measure q[0];\nif (c[0] == 1) { " + conditional_body + " }\n"
    return lower_to_native(from_qasm3(text), config())


def ports_frames() -> tuple[tuple[Port, ...], tuple[Frame, ...]]:
    """两比特的端口与帧，按 id 排序。帧 id 与端口 id 相同。"""
    ports = [Port(id="f01", role="coupler_flux", targets=(0, 1))]
    frames = [Frame(id="f01", port="f01", frequency_hz=0, phase_rad=0.0)]
    for q in (0, 1):
        ports += [
            Port(id=f"a{q}", role="acquire", targets=(q,)),
            Port(id=f"d{q}", role="drive", targets=(q,)),
            Port(id=f"r{q}", role="readout", targets=(q,)),
            Port(id=f"z{q}", role="flux", targets=(q,)),
        ]
        frames += [
            Frame(id=f"d{q}", port=f"d{q}", frequency_hz=4_900_000_123 + q, phase_rad=0.0),
            Frame(id=f"r{q}", port=f"r{q}", frequency_hz=7_000_000_000, phase_rad=0.0),
            Frame(id=f"z{q}", port=f"z{q}", frequency_hz=0, phase_rad=0.0),
        ]
    return tuple(sorted(ports, key=lambda p: p.id)), tuple(sorted(frames, key=lambda f: f.id))


def sort_key(item: Any) -> tuple[int, str, int, int]:
    """指令的排序键：时刻、帧或端口、种类、source。source 为 None 时排在前。"""
    time = item.at_ns if isinstance(item, ShiftPhase) else item.start_ns
    target = item.port if isinstance(item, Acquire) else item.frame
    source = getattr(item, "source", None)
    return time, target, _RANK[type(item)], -1 if source is None else source


def program(
    instructions: Iterable[Any] = (),
    conditions: Iterable[tuple[str, int, int]] = (),
    *,
    end_ns: int = 2000,
    frames: tuple[Frame, ...] | None = None,
    **changes: Any,
) -> PulseProgramIR:
    """构造两比特程序。指令按给定顺序保留，不重排。"""
    ports, default_frames = ports_frames()
    values: dict[str, Any] = dict(
        source_schedule_ref=REF,
        ports=ports,
        frames=default_frames if frames is None else frames,
        instructions=tuple(instructions),
        conditions=tuple(conditions),
        end_ns=end_ns,
    )
    values.update(changes)
    return PulseProgramIR(**values)


def play(**changes: Any) -> Play:
    values: dict[str, Any] = dict(
        frame="d0", start_ns=0, duration_ns=40, envelope=GAUSS, amplitude=0.5, phase_rad=0.0
    )
    return Play(**(values | changes))


def shift(**changes: Any) -> ShiftPhase:
    values: dict[str, Any] = dict(frame="d0", at_ns=0, delta_rad=-0.3, origin="gate")
    return ShiftPhase(**(values | changes))


def acquire(**changes: Any) -> Acquire:
    values: dict[str, Any] = dict(port="a0", start_ns=0, duration_ns=1000, event_id="m0")
    return Acquire(**(values | changes))


def lower_to_l1(schedule_ir: NativeScheduleIR) -> PulseProgramIR:
    """测试内的 L2→L1 降级。每个 Z、RZ 在比特的驱动帧上产生 1 条 ShiftPhase。"""
    items: list[Any] = []
    for index, op in enumerate(schedule_ir.operations):
        q, cond = op.qubits[0], op.condition_id
        timing = dict(start_ns=op.start_ns, duration_ns=op.duration_ns, condition_id=cond)
        if op.kind in ("Z", "RZ"):
            theta = math.pi if op.kind == "Z" else op.params[0]
            items.append(
                shift(
                    frame=f"d{q}",
                    at_ns=op.start_ns,
                    delta_rad=-theta,
                    condition_id=cond,
                    source=index,
                )
            )
        elif op.kind == "RX90":
            items.append(play(frame=f"d{q}", phase_rad=op.params[0], source=index, **timing))
        elif op.kind == "CZ":
            items.append(play(frame="f01", envelope=FLAT, amplitude=0.3, source=index, **timing))
        elif op.kind == "MEASURE":
            (event,) = [e for e in schedule_ir.events if e.operation_index == index]
            items.append(play(frame=f"r{q}", envelope=FLAT, source=index, **timing))
            items.append(acquire(port=f"a{q}", event_id=event.event_id, **timing))
    return rebuild(
        program(
            conditions=[(r.condition_id, r.start_ns, r.end_ns) for r in schedule_ir.conditions],
            end_ns=schedule_ir.end_ns,
            source_schedule_ref=native_schedule_ref(schedule_ir),
        ),
        items,
    )


def rebuild(base: PulseProgramIR, instructions: Iterable[Any], **changes: Any) -> PulseProgramIR:
    """用新指令重建程序，指令按排序键排序。"""
    ordered = tuple(sorted(instructions, key=sort_key))
    return dataclasses.replace(base, instructions=ordered, **changes)


def rejects(code: str, path: str, call: Callable[..., Any], *args: Any) -> PulseDiagnostic:
    """断言 ``call`` 只给出 1 条诊断，且诊断码与 JSON Pointer 路径符合预期。"""
    with pytest.raises(PulseContractError) as caught:
        call(*args)
    (diagnostic,) = caught.value.diagnostics
    assert (diagnostic.code, diagnostic.path) == (code, path), diagnostic
    return diagnostic
