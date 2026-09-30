# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""使用手算时间表验证真实源决定的经典读取绑定。"""

from dataclasses import replace

import pytest

from qaiji.core.circuit import Circuit
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.native.config import OperationSpec, QubitResource, ScheduleConfig
from qaiji.core.native.model import (
    ConditionRead,
    ConditionRegion,
    MeasurementEvent,
    NativeOperation,
    NativeScheduleIR,
    RegisterDecl,
    SourceGroup,
    SourceLocation,
)
from qaiji.core.native.rules import _expand_source
from qaiji.core.native.scheduler import _schedule_source, _SchedulingError
from qaiji.core.native.source import _capture_source
from qaiji.core.native.timing import _check_source_layout, _check_timing


def repeated():
    register = ClassicalRegister("r", 1)
    circuit = Circuit(1)
    circuit.cregs = [register]
    circuit.gates = [
        Measure(0, ClassicalBit(register, 0)),
        Measure(0, ClassicalBit(register, 0)),
        Conditional(register, 1, ()),
    ]
    source = _capture_source(circuit)
    config = ScheduleConfig(
        qubit_resources=(QubitResource(qubit=0, resource="q0"),),
        operation_specs=(
            OperationSpec(
                kind="MEASURE",
                qubits=(0,),
                duration_ns=3,
                resources=("q0", "bus"),
                result_latency_ns=5,
            ),
        ),
        cz_couplings=(),
    )
    locations = tuple(SourceLocation(gate_index=i, body_offset=None) for i in range(2))
    ops = tuple(
        NativeOperation(
            kind="MEASURE",
            qubits=(0,),
            params=(),
            source=loc,
            ordinal=0,
            start_ns=3 * i,
            duration_ns=3,
            resources=("q0", "bus"),
            condition_id=None,
        )
        for i, loc in enumerate(locations)
    )
    groups = tuple(
        SourceGroup(source=loc, rule_id="cz.v0.MEASURE", op_start=i, op_stop=i + 1, phase_rad=0.0)
        for i, loc in enumerate(locations)
    )
    events = tuple(
        MeasurementEvent(
            event_id=f"m{i}",
            source=loc,
            operation_index=i,
            qubit=0,
            register_name="r",
            bit_index=0,
            end_ns=3 * (i + 1),
            ready_ns=3 * (i + 1) + 5,
        )
        for i, loc in enumerate(locations)
    )
    condition = ConditionRegion(
        condition_id="c2",
        gate_index=2,
        register_name="r",
        width=1,
        value=1,
        reads=(ConditionRead(bit_index=0, event_id="m1"),),
        op_start=2,
        op_stop=2,
        start_ns=11,
        end_ns=11,
    )
    schedule = NativeScheduleIR(
        source_kernel_ref=source.source_kernel_ref,
        num_qubits=1,
        registers=(RegisterDecl(name="r", size=1),),
        operations=ops,
        groups=groups,
        events=events,
        conditions=(condition,),
        end_ns=11,
    )
    return source, schedule, config


def test_all_bits_latest_preceding_write():
    source, good, config = repeated()
    bad = replace(
        good,
        conditions=(
            replace(good.conditions[0], reads=(ConditionRead(bit_index=0, event_id="m0"),)),
        ),
    )
    check = _check_timing(source, bad, config)
    assert check.code == "condition_binding"
    assert check.path == "$.conditions[0].reads[0].event_id"
    assert check.source == SourceLocation(gate_index=2, body_offset=None)
    assert _check_timing(source, good, config).code is None


def multibit(value=2):
    """显式手算两位、重复写、跨寄存器、未来写和空条件时间表。"""
    from qaiji.core.circuit import Gate, GateType

    r, s = ClassicalRegister("r", 2), ClassicalRegister("s", 1)
    t = ClassicalRegister("t", 2)
    circuit = Circuit(2)
    circuit.cregs = [r, s, t]
    circuit.gates = [
        Measure(1, ClassicalBit(r, 1)),
        Measure(0, ClassicalBit(r, 0)),
        Measure(1, ClassicalBit(r, 1)),
        Measure(0, ClassicalBit(s, 0)),
        Conditional(r, value, (Gate(GateType.Z, (0,)), Gate(GateType.RX90, (0,), (0.0,)))),
        Measure(0, ClassicalBit(r, 0)),
        Conditional(r, value, ()),
        Gate(GateType.RX90, (1,), (0.0,)),
    ]
    source = _capture_source(circuit)
    # kind, qubit, gate, body, start, duration, condition
    rows = [
        ("MEASURE", 1, 0, None, 0, 4, None),
        ("MEASURE", 0, 1, None, 4, 3, None),
        ("MEASURE", 1, 2, None, 7, 4, None),
        ("MEASURE", 0, 3, None, 11, 3, None),
        ("Z", 0, 4, 0, 14, 0, "c4"),
        ("RX90", 0, 4, 1, 14, 2, "c4"),
        ("MEASURE", 0, 5, None, 16, 3, None),
        ("RX90", 1, 7, None, 24, 5, None),
    ]
    operations = tuple(
        NativeOperation(
            kind=kind,
            qubits=(q,),
            params=(0.0,) if kind == "RX90" else (),
            source=SourceLocation(gate_index=gate, body_offset=body),
            ordinal=0,
            start_ns=start,
            duration_ns=duration,
            resources=(f"q{q}",),
            condition_id=cond,
        )
        for kind, q, gate, body, start, duration, cond in rows
    )
    groups = tuple(
        SourceGroup(
            source=op.source, rule_id=f"cz.v0.{op.kind}", op_start=i, op_stop=i + 1, phase_rad=0.0
        )
        for i, op in enumerate(operations)
    )
    events = tuple(
        MeasurementEvent(
            event_id=f"m{i}",
            source=operations[index].source,
            operation_index=index,
            qubit=operations[index].qubits[0],
            register_name=reg,
            bit_index=bit,
            end_ns=end,
            ready_ns=ready,
        )
        for i, (index, reg, bit, end, ready) in enumerate(
            [
                (0, "r", 1, 4, 6),
                (1, "r", 0, 7, 12),
                (2, "r", 1, 11, 13),
                (3, "s", 0, 14, 19),
                (6, "r", 0, 19, 24),
            ]
        )
    )
    conditions = tuple(
        ConditionRegion(
            condition_id=f"c{gate}",
            gate_index=gate,
            register_name="r",
            width=2,
            value=value,
            reads=tuple(ConditionRead(bit_index=b, event_id=e) for b, e in enumerate(reads)),
            op_start=start,
            op_stop=stop,
            start_ns=t0,
            end_ns=t1,
        )
        for gate, reads, start, stop, t0, t1 in [
            (4, ("m1", "m2"), 4, 6, 14, 16),
            (6, ("m4", "m2"), 7, 7, 24, 24),
        ]
    )
    specs = tuple(
        OperationSpec(
            kind=kind,
            qubits=(q,),
            duration_ns=duration,
            resources=(f"q{q}",),
            result_latency_ns=latency,
        )
        for kind, q, duration, latency in [
            ("MEASURE", 0, 3, 5),
            ("MEASURE", 1, 4, 2),
            ("Z", 0, 0, 0),
            ("RX90", 0, 2, 0),
            ("RX90", 1, 5, 0),
        ]
    )
    config = ScheduleConfig(
        qubit_resources=(
            QubitResource(qubit=0, resource="q0"),
            QubitResource(qubit=1, resource="q1"),
        ),
        operation_specs=specs,
        cz_couplings=(),
    )
    schedule = NativeScheduleIR(
        source_kernel_ref=source.source_kernel_ref,
        num_qubits=2,
        registers=(
            RegisterDecl(name="r", size=2),
            RegisterDecl(name="s", size=1),
            RegisterDecl(name="t", size=2),
        ),
        operations=operations,
        groups=groups,
        events=events,
        conditions=conditions,
        end_ns=29,
    )
    return source, schedule, config


@pytest.mark.parametrize(
    "fault,bit,event",
    [
        ("stale", 1, "m0"),
        ("future", 0, "m4"),
        ("cross_register", 0, "m3"),
        ("wrong_bit", 0, "m2"),
        ("missing", 0, "m1"),
    ],
)
def test_stale_future_missing_cross_register(fault, bit, event):
    source, good, config = multibit()
    if fault == "missing":
        # 真实源在 c4 前未写 r[0]，其后仍有对此位的测量。
        gates = list(source.gates)
        gates[1] = Measure(0, ClassicalBit(source.cregs[1], 0))
        circuit = Circuit(source.num_qubits)
        circuit.cregs = list(source.cregs)
        circuit.gates = gates
        source = _capture_source(circuit)
        good = replace(good, source_kernel_ref=source.source_kernel_ref)
        good = replace(
            good,
            events=tuple(
                replace(e, register_name="s") if i == 1 else e for i, e in enumerate(good.events)
            ),
        )
    reads = list(good.conditions[0].reads)
    reads[bit] = ConditionRead(bit_index=bit, event_id=event)
    bad = replace(
        good, conditions=(replace(good.conditions[0], reads=tuple(reads)), good.conditions[1])
    )
    result = _check_timing(source, bad, config)
    assert (result.code, result.path, result.source, result.operation_index) == (
        "condition_binding",
        f"$.conditions[0].reads[{bit}].event_id",
        SourceLocation(gate_index=4, body_offset=None),
        None,
    )
    if fault == "missing":
        with pytest.raises(_SchedulingError) as error:
            _schedule_source(source, config, _expand_source(source))
        assert (
            error.value.code,
            error.value.path,
            error.value.source,
            error.value.operation_index,
        ) == (result.code, result.path, result.source, None)
    else:
        assert _check_timing(source, good, config).code is None


@pytest.mark.parametrize("value", [0, 1, 2, 3])
def test_bit_weight_and_condition_value(value):
    source, good, config = multibit(value)
    assert _schedule_source(source, config, _expand_source(source)) == good
    assert _check_timing(source, good, config).code is None
    assert tuple(r.event_id for r in good.conditions[0].reads) == ("m1", "m2")
    bad = replace(
        good, conditions=(replace(good.conditions[0], value=value ^ 1), good.conditions[1])
    )
    check = _check_source_layout(source, bad)
    assert (check.code, check.path, check.source, check.operation_index) == (
        "source_conditions",
        "$.conditions[0].value",
        SourceLocation(gate_index=4, body_offset=None),
        4,
    )


@pytest.mark.parametrize("fault", ["none", "early", "late", "end", "lost", "reads", "cursor_later"])
def test_empty_body_waits_and_preserves_region(fault):
    source, good, config = repeated()
    region = good.conditions[0]
    if fault == "cursor_later":
        config = replace(
            config, operation_specs=(replace(config.operation_specs[0], result_latency_ns=0),)
        )
        good = replace(
            good,
            events=tuple(replace(e, ready_ns=e.end_ns) for e in good.events),
            conditions=(replace(region, start_ns=6, end_ns=6),),
            end_ns=6,
        )
        assert _schedule_source(source, config, _expand_source(source)) == good
        assert _check_timing(source, good, config).all_results_ready_ns == 6
        return
    if fault == "none":
        assert _schedule_source(source, config, _expand_source(source)) == good
        assert _check_source_layout(source, good).code is None
        assert _check_timing(source, good, config).all_results_ready_ns == 11
        return
    if fault == "lost":
        bad = replace(good, conditions=())
        check = _check_source_layout(source, bad)
        assert (check.code, check.path, check.source, check.operation_index) == (
            "source_conditions",
            "$.conditions[0]",
            SourceLocation(gate_index=2, body_offset=None),
            None,
        )
        return
    if fault == "reads":
        region = replace(region, reads=(ConditionRead(bit_index=0, event_id="m0"),))
        code, field = "condition_binding", "reads[0].event_id"
    elif fault == "early":
        region = replace(region, start_ns=6, end_ns=6)
        code, field = "result_not_ready", "start_ns"
    elif fault == "late":
        region = replace(region, start_ns=12, end_ns=12)
        code, field = "condition_slot", "start_ns"
    else:
        region = replace(region, end_ns=12)
        code, field = "condition_slot", "end_ns"
    check = _check_timing(source, replace(good, conditions=(region,)), config)
    assert (check.code, check.path, check.source, check.operation_index) == (
        code,
        "$.conditions[0]." + field,
        SourceLocation(gate_index=2, body_offset=None),
        None,
    )


@pytest.mark.parametrize("value", [0, 1, 2, 3])
def test_both_branches_reserve_time(value):
    source, good, config = multibit(value)
    assert _schedule_source(source, config, _expand_source(source)) == good
    assert good.conditions[0].end_ns == 16
    assert good.operations[6].start_ns == 16
    # 区域本身正确等待，但实际体槽在读取就绪之前开始。
    bad = replace(
        good,
        operations=tuple(
            replace(op, start_ns=12) if i in (4, 5) else op for i, op in enumerate(good.operations)
        ),
    )
    check = _check_timing(source, bad, config)
    assert (check.code, check.path, check.source, check.operation_index) == (
        "result_not_ready",
        "$.operations[4].start_ns",
        SourceLocation(gate_index=4, body_offset=0),
        4,
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra",
        "order",
        "gate",
        "register",
        "span",
        "group_order",
        "group_missing",
        "extra_group",
    ],
)
def test_missing_and_extra_conditions(fault):
    source, good, _config = multibit()
    if fault == "missing":
        bad = replace(good, conditions=good.conditions[:1])  # 遗漏空 c6 仍符合 V0
        code, path, gate, index = "source_conditions", "$.conditions[1]", 6, None
    elif fault == "extra":
        extra = ConditionRegion(
            condition_id="c8",
            gate_index=8,
            register_name="r",
            width=2,
            value=0,
            reads=good.conditions[1].reads,
            op_start=8,
            op_stop=8,
            start_ns=29,
            end_ns=29,
        )
        bad = replace(good, conditions=(*good.conditions, extra))
        code, path, gate, index = "source_conditions", "$.conditions[2]", 8, None
    elif fault == "order":
        bad = replace(good, conditions=tuple(reversed(good.conditions)))
        code, path, gate, index = "source_conditions", "$.conditions[0].gate_index", 4, 4
    elif fault == "gate":
        bad = replace(
            good,
            conditions=(
                good.conditions[0],
                replace(good.conditions[1], gate_index=9, condition_id="c9"),
            ),
        )
        code, path, gate, index = "source_conditions", "$.conditions[1].gate_index", 6, None
    elif fault == "register":
        # 改为另一已声明同宽寄存器，保持 V0 引用合法。
        bad = replace(
            good, conditions=(replace(good.conditions[0], register_name="t"), good.conditions[1])
        )
        code, path, gate, index = "source_conditions", "$.conditions[0].register_name", 4, 4
    elif fault == "span":
        bad = replace(
            good,
            conditions=(good.conditions[0], replace(good.conditions[1], op_start=8, op_stop=8)),
        )
        code, path, gate, index = "source_conditions", "$.conditions[1].op_start", 6, None
    elif fault == "extra_group":
        from .test_timing import straight

        source, good, _config = straight([("Z", (0,), 0, 0)])
        loc = SourceLocation(gate_index=1, body_offset=None)
        op = replace(good.operations[0], source=loc)
        group = replace(good.groups[0], source=loc, op_start=1, op_stop=2)
        bad = replace(good, operations=(*good.operations, op), groups=(*good.groups, group))
        code, path, gate, index = "source_groups", "$.groups[1]", 1, 1
    elif fault == "group_order":
        # 同时重命名组和操作来源，保持 V0 完整分区。
        locations = [op.source for op in good.operations]
        locations[0], locations[1] = locations[1], locations[0]
        bad = replace(
            good,
            operations=tuple(
                replace(op, source=loc) for op, loc in zip(good.operations, locations, strict=True)
            ),
            groups=tuple(
                replace(g, source=loc) for g, loc in zip(good.groups, locations, strict=True)
            ),
            events=tuple(replace(e, source=locations[e.operation_index]) for e in good.events),
        )
        code, path, gate, index = "source_groups", "$.groups[0].source", 0, 0
    else:
        # 合法空产物对应非空源；V1 必须在 V4 之前拒收。
        bad = replace(good, operations=(), groups=(), events=(), conditions=(), end_ns=0)
        code, path, gate, index = "source_groups", "$.groups[0]", 0, None
    check = _check_source_layout(source, bad)
    assert (check.code, check.path, check.source, check.operation_index) == (
        code,
        path,
        SourceLocation(gate_index=gate, body_offset=None),
        index,
    )
