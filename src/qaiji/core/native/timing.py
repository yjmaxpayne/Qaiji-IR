# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""不依赖生成器的独立源布局、经典因果和串行时间检查。"""

from __future__ import annotations

from dataclasses import dataclass

from qaiji.core.classical import Conditional, Measure

from .config import ScheduleConfig
from .model import NativeScheduleIR, SourceLocation, _uint
from .source import _SourceSnapshot


@dataclass(frozen=True, slots=True)
class _TimingCheck:
    code: str | None = None
    path: str | None = None
    source: SourceLocation | None = None
    operation_index: int | None = None
    all_results_ready_ns: int | None = None


def _check_source_layout(snapshot: _SourceSnapshot, schedule: NativeScheduleIR) -> _TimingCheck:
    """仅检查 V1 组和条件完整性；调用方先检查身份与头字段。"""
    expected_sources = []
    for gate_index, node in enumerate(snapshot.gates):
        offsets = range(len(node.body)) if isinstance(node, Conditional) else (None,)
        for offset in offsets:
            expected_sources.append(SourceLocation(gate_index=gate_index, body_offset=offset))
    for index, source in enumerate(expected_sources):
        if index >= len(schedule.groups):
            return _TimingCheck("source_groups", f"$.groups[{index}]", source)
        group = schedule.groups[index]
        if group.source != source:
            return _TimingCheck(
                "source_groups", f"$.groups[{index}].source", source, group.op_start
            )
    if len(schedule.groups) > len(expected_sources):
        index = len(expected_sources)
        group = schedule.groups[index]
        return _TimingCheck("source_groups", f"$.groups[{index}]", group.source, group.op_start)

    group_index = 0
    operation_index = 0
    condition_index = 0
    for gate_index, node in enumerate(snapshot.gates):
        if not isinstance(node, Conditional):
            operation_index = schedule.groups[group_index].op_stop
            group_index += 1
            continue
        source = SourceLocation(gate_index=gate_index, body_offset=None)
        start = operation_index
        for _ in node.body:
            operation_index = schedule.groups[group_index].op_stop
            group_index += 1
        diagnostic_index = start if node.body else None
        path = f"$.conditions[{condition_index}]"
        if condition_index >= len(schedule.conditions):
            return _TimingCheck("source_conditions", path, source, diagnostic_index)
        region = schedule.conditions[condition_index]
        expected = (
            ("gate_index", gate_index),
            ("condition_id", f"c{gate_index}"),
            ("register_name", node.register.name),
            ("width", node.register.size),
            ("value", node.value),
            ("op_start", start),
            ("op_stop", operation_index),
        )
        for field, value in expected:
            if getattr(region, field) != value:
                return _TimingCheck(
                    "source_conditions", path + "." + field, source, diagnostic_index
                )
        condition_index += 1
    if condition_index < len(schedule.conditions):
        region = schedule.conditions[condition_index]
        source = SourceLocation(gate_index=region.gate_index, body_offset=None)
        extra_index = region.op_start if region.op_start < region.op_stop else None
        return _TimingCheck(
            "source_conditions", f"$.conditions[{condition_index}]", source, extra_index
        )
    return _TimingCheck()


def _check_timing(
    snapshot: _SourceSnapshot, schedule: NativeScheduleIR, config: ScheduleConfig
) -> _TimingCheck:
    """V4 首错检查；前置为 V0 形状/图关系及完整 V1 源对应。

    规则和矩阵检查无需成功。派生整数时刻超预算沿用模型的 NativeInputError 契约。
    """
    specs = {(spec.kind, spec.qubits): spec for spec in config.operation_specs}
    couplings = set(config.cz_couplings)
    ends: list[int] = []
    for index, op in enumerate(schedule.operations):
        path = f"$.operations[{index}]"
        spec = specs.get((op.kind, op.qubits))
        if spec is None:
            return _TimingCheck("config_missing", path, op.source, index)
        if op.kind == "CZ" and tuple(sorted(op.qubits)) not in couplings:
            return _TimingCheck("coupling_missing", path + ".qubits", op.source, index)
        if op.duration_ns != spec.duration_ns:
            return _TimingCheck("duration_mismatch", path + ".duration_ns", op.source, index)
        if op.resources != spec.resources:
            return _TimingCheck("resources_mismatch", path + ".resources", op.source, index)
        ends.append(_uint(op.start_ns + op.duration_ns, path + ".end_ns"))

    # 从真实源 Measure 序列及其组推导期望目标。
    source_groups = {(g.source.gate_index, g.source.body_offset): g for g in schedule.groups}
    measurements = [(i, node) for i, node in enumerate(snapshot.gates) if isinstance(node, Measure)]
    if len(schedule.events) != len(measurements):
        expected_indices = {source_groups[i, None].op_start for i, _ in measurements}
        actual_indices = {event.operation_index for event in schedule.events}
        missing = next(
            (
                source_groups[i, None]
                for i, _ in measurements
                if source_groups[i, None].op_start not in actual_indices
            ),
            None,
        )
        if missing is not None:
            return _TimingCheck("measurement_events", "$.events", missing.source, missing.op_start)
        extra = next(
            event for event in schedule.events if event.operation_index not in expected_indices
        )
        return _TimingCheck("measurement_events", "$.events", extra.source, extra.operation_index)
    ready_times: list[int] = []
    for event_index, (gate_index, measurement) in enumerate(measurements):
        event = schedule.events[event_index]
        group = source_groups[gate_index, None]
        index = group.op_start
        source = SourceLocation(gate_index=gate_index, body_offset=None)
        path = f"$.events[{event_index}]"
        if group.op_stop != index + 1 or schedule.operations[index].kind != "MEASURE":
            return _TimingCheck("measurement_events", path + ".operation_index", source, index)
        op = schedule.operations[index]
        ready = _uint(ends[index] + specs[op.kind, op.qubits].result_latency_ns, path + ".ready_ns")
        expected = (
            ("event_id", f"m{event_index}"),
            ("source", source),
            ("operation_index", index),
            ("qubit", measurement.qubit),
            ("register_name", measurement.target.register.name),
            ("bit_index", measurement.target.index),
            ("end_ns", ends[index]),
            ("ready_ns", ready),
        )
        for field, value in expected:
            if getattr(event, field) != value:
                return _TimingCheck("measurement_events", path + "." + field, source, index)
        ready_times.append(ready)

    # 资源占用推导前先验证全局 start 非递减，包括零时长槽。
    for index in range(1, len(schedule.operations)):
        op = schedule.operations[index]
        if op.start_ns < schedule.operations[index - 1].start_ns:
            return _TimingCheck("serial_time", f"$.operations[{index}].start_ns", op.source, index)

    cursor = 0
    latest: dict[tuple[str, int], int] = {}
    last_end: dict[str, int] = {}
    event_index = 0
    condition_index = 0

    def consume(start: int, stop: int, ready: int = 0) -> _TimingCheck | None:
        nonlocal cursor
        for index in range(start, stop):
            op = schedule.operations[index]
            path = f"$.operations[{index}].start_ns"
            if op.start_ns < ready:
                return _TimingCheck("result_not_ready", path, op.source, index)
            if op.duration_ns:
                if any(op.start_ns < last_end.get(resource, 0) for resource in op.resources):
                    return _TimingCheck("resource_overlap", path, op.source, index)
                for resource in op.resources:
                    last_end[resource] = ends[index]
            if op.start_ns != cursor:
                return _TimingCheck("serial_time", path, op.source, index)
            cursor = _uint(cursor + op.duration_ns, f"$.operations[{index}].end_ns")
        return None

    for gate_index, node in enumerate(snapshot.gates):
        if isinstance(node, Conditional):
            region = schedule.conditions[condition_index]
            path = f"$.conditions[{condition_index}]"
            source = SourceLocation(gate_index=gate_index, body_offset=None)
            ready = 0
            for bit in range(node.register.size):
                preceding = latest.get((node.register.name, bit))
                if preceding is None or region.reads[bit].event_id != f"m{preceding}":
                    return _TimingCheck(
                        "condition_binding", path + f".reads[{bit}].event_id", source
                    )
                ready = max(ready, ready_times[preceding])
            if region.start_ns < ready:
                return _TimingCheck("result_not_ready", path + ".start_ns", source)
            cursor = max(cursor, ready)
            expected_start = cursor
            issue = consume(region.op_start, region.op_stop, ready)
            if issue:
                return issue
            if region.start_ns != expected_start:
                return _TimingCheck("condition_slot", path + ".start_ns", source)
            if region.end_ns != cursor:
                return _TimingCheck("condition_slot", path + ".end_ns", source)
            condition_index += 1
        else:
            group = source_groups[gate_index, None]
            issue = consume(group.op_start, group.op_stop)
            if issue:
                return issue
            if isinstance(node, Measure):
                latest[node.target.register.name, node.target.index] = event_index
                event_index += 1
    if schedule.end_ns != cursor:
        return _TimingCheck("end_time", "$.end_ns")
    return _TimingCheck(all_results_ready_ns=max([cursor, *ready_times]))
