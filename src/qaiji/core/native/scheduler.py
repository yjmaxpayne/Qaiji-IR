# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""根据已验证源快照及配套规则展开进行串行排程。"""

from __future__ import annotations

from qaiji.core.classical import Conditional, Measure

from .config import ScheduleConfig
from .model import (
    ConditionRead,
    ConditionRegion,
    MeasurementEvent,
    NativeOperation,
    NativeScheduleIR,
    RegisterDecl,
    SourceGroup,
    SourceLocation,
    _uint,
)
from .rules import _UnscheduledGroup
from .source import _SourceSnapshot


class _SchedulingError(ValueError):
    """产物生成前的语义失败，由后续认证编排包装。"""

    def __init__(
        self,
        code: str,
        path: str,
        source: SourceLocation,
        operation_index: int | None,
        message: str,
    ) -> None:
        self.code, self.path = code, path
        self.source, self.operation_index = source, operation_index
        super().__init__(message)


def _schedule_source(
    snapshot: _SourceSnapshot, config: ScheduleConfig, groups: tuple[_UnscheduledGroup, ...]
) -> NativeScheduleIR:
    """消费与快照配套的规则展开；条件和测量目标直接来自完整源序。"""
    specs = {(spec.kind, spec.qubits): spec for spec in config.operation_specs}
    couplings = set(config.cz_couplings)
    operations: list[NativeOperation] = []
    scheduled_groups: list[SourceGroup] = []
    events: list[MeasurementEvent] = []
    conditions: list[ConditionRegion] = []
    latest: dict[tuple[str, int], MeasurementEvent] = {}
    cursor = 0
    group_index = 0

    def emit_group(condition_id: str | None) -> None:
        nonlocal cursor, group_index
        group = groups[group_index]
        group_index += 1
        start = len(operations)
        for slot in group.operations:
            index = len(operations)
            path = f"$.operations[{index}]"
            spec = specs.get((slot.kind, slot.qubits))
            if spec is None:
                raise _SchedulingError(
                    "config_missing",
                    path,
                    group.source,
                    index,
                    "Missing ordered operation specification.",
                )
            if slot.kind == "CZ" and tuple(sorted(slot.qubits)) not in couplings:
                raise _SchedulingError(
                    "coupling_missing",
                    path + ".qubits",
                    group.source,
                    index,
                    "Missing CZ coupling.",
                )
            end = _uint(cursor + spec.duration_ns, path + ".end_ns")
            operations.append(
                NativeOperation(
                    kind=slot.kind,
                    qubits=slot.qubits,
                    params=slot.params,
                    source=group.source,
                    ordinal=slot.ordinal,
                    start_ns=cursor,
                    duration_ns=spec.duration_ns,
                    resources=spec.resources,
                    condition_id=condition_id,
                )
            )
            cursor = end
        scheduled_groups.append(
            SourceGroup(
                source=group.source,
                rule_id=group.rule_id,
                phase_rad=group.phase_rad,
                op_start=start,
                op_stop=len(operations),
            )
        )

    for gate_index, node in enumerate(snapshot.gates):
        if isinstance(node, Conditional):
            source = SourceLocation(gate_index=gate_index, body_offset=None)
            reads = []
            for bit in range(node.register.size):
                event = latest.get((node.register.name, bit))
                if event is None:
                    raise _SchedulingError(
                        "condition_binding",
                        f"$.conditions[{len(conditions)}].reads[{bit}].event_id",
                        source,
                        None,
                        "Condition bit has no preceding measurement.",
                    )
                reads.append(ConditionRead(bit_index=bit, event_id=event.event_id))
                cursor = max(cursor, event.ready_ns)
            start_ns, op_start = cursor, len(operations)
            condition_id = f"c{gate_index}"
            for _ in node.body:
                emit_group(condition_id)
            conditions.append(
                ConditionRegion(
                    condition_id=condition_id,
                    gate_index=gate_index,
                    register_name=node.register.name,
                    width=node.register.size,
                    value=node.value,
                    reads=tuple(reads),
                    op_start=op_start,
                    op_stop=len(operations),
                    start_ns=start_ns,
                    end_ns=cursor,
                )
            )
        else:
            emit_group(None)
            if isinstance(node, Measure):
                index = len(operations) - 1
                spec = specs[("MEASURE", (node.qubit,))]
                ready = _uint(cursor + spec.result_latency_ns, f"$.events[{len(events)}].ready_ns")
                event = MeasurementEvent(
                    event_id=f"m{len(events)}",
                    source=operations[index].source,
                    operation_index=index,
                    qubit=node.qubit,
                    register_name=node.target.register.name,
                    bit_index=node.target.index,
                    end_ns=cursor,
                    ready_ns=ready,
                )
                events.append(event)
                latest[node.target.register.name, node.target.index] = event
    return NativeScheduleIR(
        source_kernel_ref=snapshot.source_kernel_ref,
        num_qubits=snapshot.num_qubits,
        registers=tuple(RegisterDecl(name=reg.name, size=reg.size) for reg in snapshot.cregs),
        operations=tuple(operations),
        groups=tuple(scheduled_groups),
        events=tuple(events),
        conditions=tuple(conditions),
        end_ns=cursor,
    )
