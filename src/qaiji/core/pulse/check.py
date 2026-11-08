# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1 程序与 L2 原生调度的一致性检查。"""

from __future__ import annotations

import math
from typing import Any, NoReturn

from qaiji.core.native import NativeOperation, NativeScheduleIR

from .codec import native_schedule_ref
from .errors import _fail
from .model import Acquire, Play, Port, PulseProgramIR
from .phase import phases_equal

_PULSED = ("RX90", "CZ", "MEASURE")
_VIRTUAL = ("Z", "RZ")
_PLAY_ROLES = {
    "RX90": ("drive",),
    "MEASURE": ("readout",),
    "CZ": ("flux", "coupler_flux", "two_body_drive"),
}


def check_pulse_program(program: PulseProgramIR, schedule: NativeScheduleIR) -> None:
    """检查 L1 程序与生成它的 L2 调度一致。

    检查项：

    1. ``source_schedule_ref`` 等于 ``native_schedule_ref(schedule)``，``end_ns`` 与条件区间相同。
    2. 每条带 ``source`` 的记录落在对应 L2 操作的时间内，条件与该操作相同。
    3. 来源：``Play`` 只来自 RX90、CZ、MEASURE。``origin="gate"`` 的 ``ShiftPhase`` 只来自
       Z、RZ，时刻等于操作起点，增量与 −θ 按 ``phases_equal`` 相等（Z 取 θ = π）。
       ``origin="correction"`` 的 ``ShiftPhase`` 只来自 CZ，帧在 CZ 的比特上。
    4. 目标：RX90 的 ``Play`` 在本比特的驱动帧上，MEASURE 的在本比特的读出帧上，CZ 的在
       flux 类帧上且帧的比特属于 CZ，或在目标恰为 CZ 比特对的两体驱动帧上。
       ``Acquire`` 的端口属于被测比特。
    5. 覆盖：每个 Z、RZ 在比特 q 的每个 ``targets == (q,)`` 的驱动帧上各有 1 条 gate
       ``ShiftPhase``。每个 RX90、CZ、MEASURE 至少有 1 条 ``Play``。
    6. 测量：每个 MEASURE 有 1 条读出 ``Play``。``Acquire`` 与 L2 测量事件一一对应。

    Args:
        program: 待检查的 L1 程序。
        schedule: 生成该程序的 L2 调度。

    Raises:
        PulseContractError: 程序与调度不一致，类别为 ``SCHEDULE_MISMATCH``。
    """
    if type(program) is not PulseProgramIR:
        _mismatch("TYPE", "", "Expected PulseProgramIR.")
    if type(schedule) is not NativeScheduleIR:
        _mismatch("TYPE", "", "Expected NativeScheduleIR.")
    if program.source_schedule_ref != native_schedule_ref(schedule):
        _mismatch("SCHEDULE_REF", "/source_schedule_ref", "Reference differs from the schedule.")
    if program.end_ns != schedule.end_ns:
        _mismatch("END", "/end_ns", "End time differs from the schedule.")
    windows = tuple((r.condition_id, r.start_ns, r.end_ns) for r in schedule.conditions)
    if program.conditions != windows:
        _mismatch("CONDITIONS", "/conditions", "Condition regions differ from the schedule.")
    plays, shifts = _check_records(program, schedule)
    _check_coverage(program, schedule, plays, shifts)


def _mismatch(code: str, path: str, message: str) -> NoReturn:
    _fail(code, path, message, "SCHEDULE_MISMATCH")


def _check_records(
    program: PulseProgramIR, schedule: NativeScheduleIR
) -> tuple[dict[int, list[Play]], dict[int, set[str]]]:
    ops, events = schedule.operations, {e.event_id: e for e in schedule.events}
    ports = {port.id: port for port in program.ports}
    frame_ports = {frame.id: ports[frame.port] for frame in program.frames}
    plays: dict[int, list[Play]] = {}
    shifts: dict[int, set[str]] = {}
    acquired: set[str] = set()
    for index, item in enumerate(program.instructions):
        path = f"/instructions/{index}"
        if isinstance(item, Acquire):
            event = events.get(item.event_id)
            if event is None:
                _mismatch("EVENT_REF", path + "/event_id", "Unknown measurement event.")
            acquired.add(item.event_id)
            op = ops[event.operation_index]
            if ports[item.port].targets != op.qubits:
                _mismatch("TARGET", path + "/port", "Acquire port does not match the qubit.")
            _check_op(item, op, path)
            continue
        if item.source is None or not 0 <= item.source < len(ops):
            _mismatch("SOURCE", path + "/source", "Expected an operation index of the schedule.")
        op = ops[item.source]
        if isinstance(item, Play):
            if op.kind not in _PULSED:
                _mismatch(
                    "PLAY_SOURCE", path + "/source", "Play must come from RX90, CZ or MEASURE."
                )
            _check_target(frame_ports[item.frame], op, path + "/frame")
            plays.setdefault(item.source, []).append(item)
        elif item.origin == "gate":
            if op.kind not in _VIRTUAL:
                _mismatch(
                    "SHIFT_SOURCE", path + "/source", "Gate ShiftPhase must come from Z or RZ."
                )
            if item.at_ns != op.start_ns:
                _mismatch("TIME", path, "Gate ShiftPhase must occur at the operation start.")
            theta = math.pi if op.kind == "Z" else op.params[0]
            if not phases_equal(item.delta_rad, -theta):
                _mismatch("SHIFT_DELTA", path + "/delta_rad", "Expected delta_rad = -theta.")
            shifts.setdefault(item.source, set()).add(item.frame)
        elif op.kind != "CZ":
            _mismatch("SHIFT_SOURCE", path + "/source", "Correction ShiftPhase must come from CZ.")
        elif not set(frame_ports[item.frame].targets) <= set(op.qubits):
            _mismatch("TARGET", path + "/frame", "Correction frame is not on a CZ qubit.")
        _check_op(item, op, path)
    if set(events) - acquired:
        _mismatch("EVENT_MISSING", "/instructions", "A measurement event has no Acquire.")
    return plays, shifts


def _check_target(port: Port, op: NativeOperation, path: str) -> None:
    """检查单比特目标、flux 子集与两体驱动的精确比特对。"""
    if op.kind == "CZ" and port.role == "two_body_drive":
        fits = len(port.targets) == 2 and sorted(port.targets) == sorted(op.qubits)
    elif op.kind == "CZ":
        fits = set(port.targets) <= set(op.qubits)
    else:
        fits = port.targets == op.qubits
    if port.role not in _PLAY_ROLES[op.kind] or not fits:
        _mismatch("TARGET", path, "Play frame does not match the operation qubits and role.")


def _check_op(item: Any, op: NativeOperation, path: str) -> None:
    start = getattr(item, "at_ns", None)
    if start is None:
        start, stop = item.start_ns, item.start_ns + item.duration_ns
    else:
        stop = start
    if start < op.start_ns or stop > op.start_ns + op.duration_ns:
        _mismatch("TIME", path, "Record lies outside its operation.")
    if item.condition_id != op.condition_id:
        _mismatch("CONDITION", path + "/condition_id", "Condition differs from the operation.")


def _check_coverage(
    program: PulseProgramIR,
    schedule: NativeScheduleIR,
    plays: dict[int, list[Play]],
    shifts: dict[int, set[str]],
) -> None:
    ports = {port.id: port for port in program.ports}
    frame_ports = {frame.id: ports[frame.port] for frame in program.frames}
    for index, op in enumerate(schedule.operations):
        if op.kind in _VIRTUAL:
            drive = {
                frame
                for frame, port in frame_ports.items()
                if port.role == "drive" and port.targets == op.qubits
            }
            if shifts.get(index, set()) != drive:
                _mismatch(
                    "SHIFT_FRAMES", "/instructions", f"Operation {index} misses drive frames."
                )
        elif op.kind in _PULSED and not plays.get(index):
            _mismatch("PLAY_MISSING", "/instructions", f"Operation {index} has no Play.")
        if op.kind == "MEASURE":
            readout = [p for p in plays.get(index, []) if frame_ports[p.frame].role == "readout"]
            if len(readout) != 1:
                _mismatch("READOUT", "/instructions", f"Operation {index} needs one readout Play.")
