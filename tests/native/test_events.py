# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""事件与真实源测量双向对应；坏候选仍通过 V0 和 V1。"""

from dataclasses import replace

import pytest

from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.native.config import OperationSpec
from qaiji.core.native.model import MeasurementEvent, SourceLocation
from qaiji.core.native.rules import _expand_source
from qaiji.core.native.scheduler import _schedule_source
from qaiji.core.native.source import _capture_source
from qaiji.core.native.timing import _check_source_layout, _check_timing

from .test_conditions import multibit, repeated
from .test_timing import assert_issue


@pytest.mark.parametrize("fixture", [repeated, multibit])
def test_measure_event_bijection(fixture):
    source, good, config = fixture()
    assert _schedule_source(source, config, _expand_source(source)) == good
    assert _check_source_layout(source, good).code is None
    assert _check_timing(source, good, config).code is None
    assert tuple(e.event_id for e in good.events) == tuple(f"m{i}" for i in range(len(good.events)))


def test_repeated_measurement_history():
    source, good, config = repeated()
    generated = _schedule_source(source, config, _expand_source(source))
    assert generated == good
    assert [(e.event_id, e.operation_index, e.end_ns, e.ready_ns) for e in generated.events] == [
        ("m0", 0, 3, 8),
        ("m1", 1, 6, 11),
    ]
    assert _check_timing(source, good, config).code is None


@pytest.mark.parametrize("fault", ["loss", "extra", "order", "target", "wide_group", "wrong_kind"])
def test_event_loss_extra_order_target(fault):
    source, good, config = multibit()
    if fault in ("wide_group", "wrong_kind"):
        source, good, config = repeated()
        circuit = Circuit(1)
        circuit.cregs = list(source.cregs)
        circuit.gates = [source.gates[0]]
        measurement = good.operations[0]
        event = good.events[0]
        config = replace(
            config,
            operation_specs=(
                *config.operation_specs,
                OperationSpec(
                    kind="Z",
                    qubits=(0,),
                    duration_ns=0,
                    resources=("q0", "bus"),
                    result_latency_ns=0,
                ),
            ),
        )
        if fault == "wide_group":
            # 组首 kind 正确，仅组宽度从 1 改为 2；两槽共享源且 ordinal 连续。
            zero = replace(measurement, kind="Z", duration_ns=0, ordinal=1, start_ns=3)
            operations = (measurement, zero)
            groups = (replace(good.groups[0], op_stop=2),)
        else:
            # 组宽度都为 1，源 [Measure,Z] 的实际流改为 [Z,MEASURE]。
            circuit.gates.append(Gate(GateType.Z, (0,)))
            second = SourceLocation(gate_index=1, body_offset=None)
            zero = replace(measurement, kind="Z", duration_ns=0)
            operations = (zero, replace(measurement, source=second))
            groups = (good.groups[0], replace(good.groups[1], rule_id="cz.v0.Z"))
            event = replace(event, source=second, operation_index=1)
        source = _capture_source(circuit)
        bad = replace(
            good,
            source_kernel_ref=source.source_kernel_ref,
            operations=operations,
            groups=groups,
            events=(event,),
            conditions=(),
            end_ns=3,
        )
        path, gate, index = "$.events[0].operation_index", 0, 0
    elif fault == "loss":
        # 源仍是 Measure，实际槽改为 Z 且删事件。规则失败不应阻断 V4。
        ops = tuple(
            replace(op, kind="Z", duration_ns=0) if i == 3 else op
            for i, op in enumerate(good.operations)
        )
        events = tuple(
            replace(e, event_id=f"m{i}")
            for i, e in enumerate(e for e in good.events if e.operation_index != 3)
        )
        conditions = (
            good.conditions[0],
            replace(
                good.conditions[1],
                reads=(
                    replace(good.conditions[1].reads[0], event_id="m3"),
                    good.conditions[1].reads[1],
                ),
            ),
        )
        bad = replace(good, operations=ops, events=events, conditions=conditions)
        path, gate, index = "$.events", 3, 3
    elif fault == "extra":
        # 源末尾普通 RX90 改为 MEASURE 并增事件；V0一一对应仍成立。
        op = replace(good.operations[-1], kind="MEASURE", params=(), duration_ns=4)
        extra = MeasurementEvent(
            event_id="m5",
            source=op.source,
            operation_index=7,
            qubit=1,
            register_name="s",
            bit_index=0,
            end_ns=28,
            ready_ns=30,
        )
        bad = replace(good, operations=(*good.operations[:-1], op), events=(*good.events, extra))
        path, gate, index = "$.events", 7, 7
    elif fault == "order":
        events = list(good.events)
        events[0], events[1] = replace(events[1], event_id="m0"), replace(events[0], event_id="m1")
        bad = replace(good, events=tuple(events))
        path, gate, index = "$.events[0].source", 0, 0
    else:
        bad = replace(good, events=(replace(good.events[0], bit_index=0), *good.events[1:]))
        path, gate, index = "$.events[0].bit_index", 0, 0
    assert _check_source_layout(source, bad).code is None
    assert_issue(_check_timing(source, bad, config), "measurement_events", path, gate, index)


@pytest.mark.parametrize("fault", ["register", "bit", "qubit"])
def test_source_targets_are_authoritative(fault):
    source, good, config = multibit()
    if fault == "register":
        bad = replace(
            good,
            events=tuple(
                replace(e, register_name="r") if i == 3 else e for i, e in enumerate(good.events)
            ),
        )
        path, gate, index = "$.events[3].register_name", 3, 3
    elif fault == "bit":
        bad = replace(good, events=(replace(good.events[0], bit_index=0), *good.events[1:]))
        path, gate, index = "$.events[0].bit_index", 0, 0
    else:
        # 操作和事件共同改目标，不能以彼此相等代替真实源目标。
        op = replace(good.operations[0], qubits=(0,), resources=("q0",), duration_ns=3)
        event = replace(good.events[0], qubit=0, end_ns=3, ready_ns=8)
        bad = replace(good, operations=(op, *good.operations[1:]), events=(event, *good.events[1:]))
        path, gate, index = "$.events[0].qubit", 0, 0
    assert _check_source_layout(source, bad).code is None
    assert_issue(_check_timing(source, bad, config), "measurement_events", path, gate, index)
