# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""手算整数时间表分别验证串行、重叠及就绪判据。"""

from dataclasses import replace

import pytest

from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.native.config import OperationSpec, QubitResource, ScheduleConfig
from qaiji.core.native.errors import NativeInputError
from qaiji.core.native.model import NativeOperation, NativeScheduleIR, SourceGroup, SourceLocation
from qaiji.core.native.rules import _expand_source
from qaiji.core.native.scheduler import _schedule_source, _SchedulingError
from qaiji.core.native.source import _capture_source
from qaiji.core.native.timing import _check_source_layout, _check_timing

from .test_conditions import multibit, repeated


def straight(rows, shared=False):
    """每行显式给出 kind、qubits、start 和 duration，不推算期望 cursor。"""
    circuit = Circuit(2)
    circuit.gates = [
        Gate(GateType(kind), qubits, (0.0,) if kind in ("RZ", "RX90") else ())
        for kind, qubits, _, _ in rows
    ]
    source = _capture_source(circuit)
    specs = {}
    operations = []
    groups = []
    for i, (kind, qubits, start, duration) in enumerate(rows):
        resources = tuple(f"q{q}" for q in qubits) + (("bus",) if shared else ())
        loc = SourceLocation(gate_index=i, body_offset=None)
        specs[kind, qubits] = OperationSpec(
            kind=kind, qubits=qubits, duration_ns=duration, resources=resources, result_latency_ns=0
        )
        operations.append(
            NativeOperation(
                kind=kind,
                qubits=qubits,
                params=(0.0,) if kind in ("RZ", "RX90") else (),
                source=loc,
                ordinal=0,
                start_ns=start,
                duration_ns=duration,
                resources=resources,
                condition_id=None,
            )
        )
        groups.append(
            SourceGroup(
                source=loc, rule_id=f"cz.v0.{kind}", op_start=i, op_stop=i + 1, phase_rad=0.0
            )
        )
    config = ScheduleConfig(
        qubit_resources=tuple(QubitResource(qubit=q, resource=f"q{q}") for q in range(2)),
        operation_specs=tuple(specs.values()),
        cz_couplings=((0, 1),),
    )
    schedule = NativeScheduleIR(
        source_kernel_ref=source.source_kernel_ref,
        num_qubits=2,
        registers=(),
        operations=tuple(operations),
        groups=tuple(groups),
        events=(),
        conditions=(),
        end_ns=rows[-1][2] + rows[-1][3] if rows else 0,
    )
    return source, schedule, config


def assert_issue(check, code, path, gate_index, operation_index, body_offset=None):
    assert (check.code, check.path, check.source, check.operation_index) == (
        code,
        path,
        SourceLocation(gate_index=gate_index, body_offset=body_offset),
        operation_index,
    )
    assert check.all_results_ready_ns is None


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "missing_forward",
        "missing_reverse",
        "coupling",
        "duration",
        "order",
        "subset",
        "extra",
    ],
)
def test_explicit_ordered_configuration(fault):
    source, good, config = straight([("CZ", (0, 1), 0, 7), ("CZ", (1, 0), 7, 11)], True)
    bad = good
    if fault.startswith("missing"):
        keep = 1 if fault == "missing_forward" else 0
        config = replace(config, operation_specs=(config.operation_specs[keep],))
        index = 1 - keep
        code, field = "config_missing", ""
    elif fault == "coupling":
        config = replace(config, cz_couplings=())
        index, code, field = 0, "coupling_missing", ".qubits"
    elif fault != "none":
        index = 1
        op = good.operations[index]
        if fault == "duration":
            op = replace(op, duration_ns=12)
            code, field = "duration_mismatch", ".duration_ns"
        else:
            resources = {
                "order": ("bus", "q1", "q0"),
                "subset": ("q1", "q0"),
                "extra": ("q1", "q0", "bus", "other"),
            }[fault]
            op = replace(op, resources=resources)
            code, field = "resources_mismatch", ".resources"
        bad = replace(good, operations=(good.operations[0], op))
    if fault == "none":
        assert _schedule_source(source, config, _expand_source(source)) == good
        assert _check_timing(source, good, config).code is None
    else:
        assert_issue(
            _check_timing(source, bad, config), code, f"$.operations[{index}]" + field, index, index
        )
        if fault.startswith("missing") or fault == "coupling":
            with pytest.raises(_SchedulingError) as error:
                _schedule_source(source, config, _expand_source(source))
            assert (
                error.value.code,
                error.value.path,
                error.value.source,
                error.value.operation_index,
            ) == (code, f"$.operations[{index}]" + field, good.operations[index].source, index)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [("I", (0,), 0, 0)],
        [("RX90", (0,), 0, 3), ("Z", (1,), 3, 0), ("RZ", (0,), 3, 0), ("RX90", (1,), 3, 5)],
        [("I", (0,), 0, 0), ("RX90", (0,), 0, 3), ("I", (0,), 3, 0)],
    ],
)
def test_serial_earliest_cursor_and_zero_duration(rows):
    source, good, config = straight(rows)
    assert _schedule_source(source, config, _expand_source(source)) == good
    assert _check_source_layout(source, good).code is None
    assert _check_timing(source, good, config).code is None


@pytest.mark.parametrize(
    "shared,second,code,zero",
    [
        (True, 3, None, False),
        (True, 2, "resource_overlap", False),
        (False, 2, "serial_time", False),
        (False, 4, "serial_time", False),
        (False, 2, "serial_time", True),
    ],
)
def test_half_open_shared_resource_occupancy(shared, second, code, zero):
    second_row = ("Z", (0,), 3, 0) if zero else ("RX90", (1,), 3, 5)
    source, good, config = straight([("RX90", (0,), 0, 3), second_row], shared)
    bad = replace(
        good, operations=(good.operations[0], replace(good.operations[1], start_ns=second))
    )
    check = _check_timing(source, bad, config)
    if code:
        assert_issue(check, code, "$.operations[1].start_ns", 1, 1)
    else:
        assert check.code is None


@pytest.mark.parametrize(
    "starts,shared,code,index",
    [
        ((0, 3, 2), True, "serial_time", 2),
        ((0, 2, 8), True, "resource_overlap", 1),
        ((0, 2, 8), False, "serial_time", 1),
        ((0, 4, 8), False, "serial_time", 1),
    ],
)
def test_nondecreasing_before_overlap_before_exact_time(starts, shared, code, index):
    source, good, config = straight(
        [("RX90", (0,), 0, 3), ("RX90", (1,), 3, 5), ("RX90", (0,), 8, 3)], shared
    )
    bad = replace(
        good,
        operations=tuple(
            replace(op, start_ns=start) for op, start in zip(good.operations, starts, strict=True)
        ),
    )
    assert_issue(
        _check_timing(source, bad, config), code, f"$.operations[{index}].start_ns", index, index
    )


@pytest.mark.parametrize("fault", ["none", "end", "ready", "event_end", "earlier_ready_max"])
def test_end_and_all_results_ready_are_distinct(fault):
    if fault == "earlier_ready_max":
        source, good, config = multibit()
        circuit = Circuit(source.num_qubits)
        circuit.cregs = list(source.cregs)
        circuit.gates = list(source.gates[:4])
        source = _capture_source(circuit)
        config = replace(
            config,
            operation_specs=tuple(
                replace(spec, result_latency_ns=100)
                if spec.kind == "MEASURE" and spec.qubits == (1,)
                else spec
                for spec in config.operation_specs
            ),
        )
        good = replace(
            good,
            source_kernel_ref=source.source_kernel_ref,
            operations=good.operations[:4],
            groups=good.groups[:4],
            conditions=(),
            end_ns=14,
            events=tuple(
                replace(e, ready_ns=e.end_ns + 100) if e.qubit == 1 else e for e in good.events[:4]
            ),
        )
        assert _schedule_source(source, config, _expand_source(source)) == good
        assert _check_timing(source, good, config).all_results_ready_ns == 111
        return
    source, good, config = repeated()
    circuit = Circuit(source.num_qubits)
    circuit.cregs = list(source.cregs)
    circuit.gates = list(source.gates[:2])
    source = _capture_source(circuit)
    good = replace(good, source_kernel_ref=source.source_kernel_ref, conditions=(), end_ns=6)
    if fault == "end":
        good = replace(good, end_ns=11)
    elif fault in ("ready", "event_end"):
        event = replace(good.events[1], **({"ready_ns": 12} if fault == "ready" else {"end_ns": 7}))
        good = replace(good, events=(good.events[0], event))
    check = _check_timing(source, good, config)
    if fault == "none":
        assert check.code is None
        assert check.all_results_ready_ns == 11
        assert _schedule_source(source, config, _expand_source(source)) == good
    elif fault == "end":
        assert (check.code, check.path, check.source, check.operation_index) == (
            "end_time",
            "$.end_ns",
            None,
            None,
        )
    else:
        field = "ready_ns" if fault == "ready" else "end_ns"
        assert_issue(check, "measurement_events", f"$.events[1].{field}", 1, 1)


@pytest.mark.parametrize("boundary", ["valid", "duration_sum", "ready_sum", "config"])
def test_configuration_and_accumulator_integer_bounds(boundary):
    limit = 10**4096
    if boundary == "config":
        with pytest.raises(NativeInputError) as error:
            OperationSpec(
                kind="RX90", qubits=(0,), duration_ns=limit, resources=("q0",), result_latency_ns=0
            )
        assert (error.value.code, error.value.path) == ("range", "$.duration_ns")
        return
    if boundary == "ready_sum":
        source, good, config = repeated()
        config = replace(
            config,
            operation_specs=(replace(config.operation_specs[0], result_latency_ns=limit - 3),),
        )
    else:
        source, good, config = straight([("RX90", (0,), 0, limit - 1)])
        if boundary == "duration_sum":
            # 单个字段符合 V0；其派生终点超出预算。
            op = replace(good.operations[0], start_ns=1)
            good = replace(good, operations=(op,))
            # 生成器用两个操作触发累加溢出；检查器使用移动后的终点。
            circuit = Circuit(2)
            circuit.gates = [Gate(GateType.RX90, (0,), (0.0,)), Gate(GateType.RX90, (0,), (0.0,))]
            generation_source = _capture_source(circuit)
    if boundary == "valid":
        assert _schedule_source(source, config, _expand_source(source)) == good
        assert _check_timing(source, good, config).all_results_ready_ns == limit - 1
    else:
        with pytest.raises(NativeInputError) as error:
            _check_timing(source, good, config)
        timing_path = (
            "$.operations[0].end_ns" if boundary == "duration_sum" else "$.events[0].ready_ns"
        )
        assert (error.value.code, error.value.path) == ("range", timing_path)
        with pytest.raises(NativeInputError) as error:
            generated_source = generation_source if boundary == "duration_sum" else source
            _schedule_source(generated_source, config, _expand_source(generated_source))
        scheduler_path = (
            "$.operations[1].end_ns" if boundary == "duration_sum" else "$.events[0].ready_ns"
        )
        assert (error.value.code, error.value.path) == ("range", scheduler_path)
