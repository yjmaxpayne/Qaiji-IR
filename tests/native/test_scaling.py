# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""独立变化规模维度，保留分阶段计时、峰值和源码访问次数。"""

import hashlib
import json
import os
import statistics
import sys
import time
import tracemalloc
from collections import Counter
from dataclasses import replace
from functools import partial
from itertools import pairwise
from pathlib import Path

import pytest

import qaiji.core.native.matrix as matrix
import qaiji.core.program_native.bridge as bridge
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.native import (
    NativeInputError,
    NativeScheduleIR,
    OperationSpec,
    QubitResource,
    ScheduleConfig,
    lower_to_native,
)
from qaiji.core.native.rules import _expand_source
from qaiji.core.native.scheduler import _schedule_source
from qaiji.core.native.source import _capture_source
from qaiji.core.native.validation import _validate_snapshot
from qaiji.core.program import (
    ExperimentMetadata,
    ProgramIR,
    QuantumInvocation,
    ResultOutput,
    compute_kernel_ref,
    validate_program,
)
from qaiji.core.program_native import NativeBinding, bridge_program_native
from qaiji.core.semantics import build_dataflow_summary

ROOT = Path(__file__).resolve().parents[2]


def _measure(action):
    """每阶段在 tracemalloc 开启下采样三次；源码计数另跑一轮。"""
    times, peaks = [], []
    for _ in range(3):
        tracemalloc.start()
        start = time.perf_counter_ns()
        try:
            action()
        finally:
            times.append(time.perf_counter_ns() - start)
            peaks.append(tracemalloc.get_traced_memory()[1])
            tracemalloc.stop()
    visits = Counter()

    def trace(frame, event, arg):
        filename = frame.f_code.co_filename.replace("\\", "/")
        if "/src/qaiji/" not in filename:
            return None
        if event == "line":
            visits[filename.split("/src/", 1)[1]] += 1
        return trace

    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        action()
    finally:
        sys.settrace(previous)
    return {
        "raw_ns": times,
        "median_ns": statistics.median(times),
        "raw_peak_bytes": peaks,
        "peak_bytes": max(peaks),
        "line_visits": dict(sorted(visits.items())),
    }


def _save(name, rows):
    """持久记录内容指纹；未设证据目录时不写文件，并发 pytest worker 各自只写其独立实验文件。"""
    evidence = os.environ.get("QM5_SCALE_EVIDENCE")
    if not evidence:
        return
    out = Path(evidence)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted([*ROOT.glob("src/qaiji/**/*.py"), Path(__file__)])
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    payload = {"python": sys.version, "inputs_sha256": hashes, "rows": rows}
    (out / (name + ".json")).write_text(json.dumps(payload, indent=2) + "\n")


def _config(width=1, resources=1):
    return ScheduleConfig(
        qubit_resources=tuple(QubitResource(qubit=q, resource=f"q{q}") for q in range(width)),
        operation_specs=tuple(
            OperationSpec(
                kind=kind,
                qubits=(q,),
                duration_ns=3 if kind in ("RX90", "MEASURE") else 0,
                resources=(f"q{q}", *(f"aux{i}" for i in range(resources - 1))),
                result_latency_ns=7 if kind == "MEASURE" else 0,
            )
            for q in range(width)
            for kind in ("I", "Z", "RZ", "RX90", "MEASURE")
        ),
        cz_couplings=(),
    )


def _circuit(*, gates=0, declarations=1, conditions=0, bits=1, history=1, width=1):
    circuit = Circuit(width)
    reg = ClassicalRegister("c", bits)
    circuit.cregs = [reg, *(ClassicalRegister(f"unused{i}", 1) for i in range(declarations - 1))]
    circuit.gates = [Measure(0, ClassicalBit(reg, i % bits)) for i in range(max(bits, history))]
    circuit.gates += [Gate(GateType.U3, (0,), (0.7, 0.2, -0.4)) for _ in range(gates)]
    circuit.gates += [Conditional(reg, 0, ()) for _ in range(conditions)]
    return circuit


class _ObservedTuple(tuple):
    """仅统计实际遍历/索引，原样返回元素，保留 tuple 的全部值语义。"""

    def __new__(cls, values):
        value = super().__new__(cls, values)
        value.visits = 0
        value.lookups = 0
        return value

    def __iter__(self):
        for value in super().__iter__():
            self.visits += 1
            yield value

    def __getitem__(self, index):
        self.lookups += 1
        return super().__getitem__(index)


def _scheduler_accesses(snapshot, config, groups, expected):
    """计数器只包装私有阶段输入，生成内容须与原输入逐字段相等。"""
    gates, registers, specs, observed_groups = map(
        _ObservedTuple, (snapshot.gates, snapshot.cregs, config.operation_specs, groups)
    )
    observed_snapshot = replace(snapshot, gates=gates, cregs=registers)

    class ConfigurationView:
        operation_specs = specs
        cz_couplings = config.cz_couplings

    result = _schedule_source(observed_snapshot, ConfigurationView(), observed_groups)
    assert result == expected
    assert gates.visits == len(snapshot.gates)
    assert registers.visits == len(snapshot.cregs)
    assert specs.visits == len(config.operation_specs)
    assert observed_groups.lookups == len(groups)
    return {
        "source_nodes": gates.visits,
        "declarations": registers.visits,
        "configuration_specs": specs.visits,
        "group_lookups": observed_groups.lookups,
    }


def _stages(circuit, config):
    snapshot = _capture_source(circuit)
    groups = _expand_source(snapshot)
    schedule = _schedule_source(snapshot, config, groups)
    assert _validate_snapshot(snapshot, schedule, config).valid
    return schedule, {
        "inherited_ref": lambda: compute_kernel_ref(circuit),
        "snapshot_including_ref": lambda: _capture_source(circuit),
        "rules": lambda: _expand_source(snapshot),
        "scheduler": lambda: _schedule_source(snapshot, config, groups),
        "certification": lambda: _validate_snapshot(snapshot, schedule, config),
        "end_to_end": lambda: lower_to_native(circuit, config),
    }


def _native_visits(stages):
    """旧 ref 成本单列，仅对新增 L2 源码访问数施加增长界。"""
    return sum(
        count
        for name, count in stages["end_to_end"]["line_visits"].items()
        if name.startswith("qaiji/core/native/")
    )


def _linear(rows):
    for left, right in pairwise(rows):
        ratio = right["size"] / left["size"]
        assert _native_visits(right["stages"]) <= (ratio + 0.2) * _native_visits(left["stages"])


@pytest.mark.parametrize("gate_kind, slots, dimension", [("U3", 5, 2), ("SQISWAP", 46, 4)])
def test_bounded_expansion_and_local_matrix_dimension(monkeypatch, gate_kind, slots, dimension):
    rows = []
    original = matrix._multiply
    for n in (10, 100, 1000):
        circuit = _circuit(gates=n)
        config = _config()
        if dimension == 4:
            circuit.num_qubits = 2
            circuit.gates[1:] = [Gate(GateType.SQISWAP, (1, 0)) for _ in range(n)]
            config = _config(width=2)
            config = replace(
                config,
                operation_specs=config.operation_specs
                + tuple(
                    OperationSpec(
                        kind="CZ",
                        qubits=qubits,
                        duration_ns=4,
                        resources=("q0", "q1"),
                        result_latency_ns=0,
                    )
                    for qubits in ((0, 1), (1, 0))
                ),
                cz_couplings=((0, 1),),
            )
        schedule, actions = _stages(circuit, config)
        assert len(schedule.operations) == 1 + slots * n
        assert len(schedule.operations) <= 46 * (n + 1)
        calls = []

        def counted(left, right, calls=calls):
            calls.append((len(left), len(right)))
            return original(left, right)

        with monkeypatch.context() as patch:
            patch.setattr(matrix, "_multiply", counted)
            assert _validate_snapshot(_capture_source(circuit), schedule, config).valid
        assert len(calls) == slots * n
        assert set(calls) == {(dimension, dimension)}
        rows.append(
            {
                "size": n,
                "multiplications": len(calls),
                "dimensions": sorted(set(calls)),
                "stages": {name: _measure(action) for name, action in actions.items()},
            }
        )
    _linear(rows)
    _save("rules-and-matrices-" + gate_kind, rows)


@pytest.mark.parametrize("dimension", ["K", "C", "B", "R", "D"])
def test_linear_new_work_including_empty_conditions(dimension):
    rows = []
    for n in (8, 16, 32):
        kwargs = {"declarations": n} if dimension == "K" else {}
        if dimension == "C":
            kwargs["conditions"] = n
        if dimension == "B":
            kwargs.update(bits=n, conditions=1)
        if dimension == "D":
            kwargs["width"] = n
        circuit = _circuit(**kwargs)
        config = _config(width=n if dimension == "D" else 1, resources=n if dimension == "R" else 1)
        schedule, actions = _stages(circuit, config)
        if dimension == "C":
            assert len(schedule.conditions) == n
            assert all(
                c.op_start == c.op_stop == 1 and c.start_ns == 10 for c in schedule.conditions
            )
        if dimension == "B":
            assert len(schedule.conditions[0].reads) == n
        rows.append(
            {
                "size": n,
                "dimension": dimension,
                "accesses": _scheduler_accesses(
                    _capture_source(circuit),
                    config,
                    _expand_source(_capture_source(circuit)),
                    schedule,
                ),
                "stages": {name: _measure(action) for name, action in actions.items()},
            }
        )
    _linear(rows)
    _save("independent-" + dimension, rows)


def test_inherited_ref_edge_cross_product():
    rows = []
    for n in (8, 16, 32, 64):
        circuit = _circuit(conditions=n, history=n)
        dataflow = build_dataflow_summary(circuit)
        # 每一条件依赖同寄存器全部历史写：旧摘要保留 C×E 声明边。
        edges = dataflow["classical_edges"]
        assert len(edges) == n * n
        schedule, actions = _stages(circuit, _config())
        assert len(schedule.events) == n and len(schedule.conditions) == n
        rows.append(
            {
                "size": n,
                "C": n,
                "E": n,
                "declared_edges": len(edges),
                "stages": {name: _measure(action) for name, action in actions.items()},
            }
        )
    _linear(rows)
    _save("inherited-ref", rows)


def _program(circuit, config, invocations, outputs):
    ref = compute_kernel_ref(circuit)
    program = ProgramIR(
        quantum_invocations=tuple(QuantumInvocation(ref) for _ in range(invocations)),
        experiment_metadata=ExperimentMetadata(1, "opaque", "opaque"),
        result_outputs=tuple(ResultOutput(i, "c") for i in range(outputs)),
    )
    binding = NativeBinding(schedule=lower_to_native(circuit, config), config=config)
    return program, {ref: circuit}, dict.fromkeys(range(invocations), binding)


def _bridge_breakdown(program, kernels, bindings, monkeypatch):
    """包装原函数保留返回值，B1 为总时间扣除 B0/B2 的认证及编排耗时。"""
    original_validate, original_outputs = bridge.validate_program, bridge._map_outputs
    samples = {
        "B0_legacy_validation": [],
        "B1_authentication_including_ref": [],
        "B2_output_index": [],
    }
    for _ in range(3):
        elapsed = {}

        def timed_validate(*args, elapsed=elapsed):
            start = time.perf_counter_ns()
            try:
                return original_validate(*args)
            finally:
                elapsed["B0_legacy_validation"] = time.perf_counter_ns() - start

        def timed_outputs(*args, elapsed=elapsed):
            start = time.perf_counter_ns()
            try:
                return original_outputs(*args)
            finally:
                elapsed["B2_output_index"] = time.perf_counter_ns() - start

        with monkeypatch.context() as patch:
            patch.setattr(bridge, "validate_program", timed_validate)
            patch.setattr(bridge, "_map_outputs", timed_outputs)
            tracemalloc.start()
            start = time.perf_counter_ns()
            actual = bridge_program_native(program, kernels, bindings)
            total = time.perf_counter_ns() - start
            tracemalloc.stop()
        assert len(actual.outputs) == len(program.result_outputs)
        elapsed["B1_authentication_including_ref"] = total - sum(elapsed.values())
        for name, duration in elapsed.items():
            samples[name].append(duration)
    return {
        name: {"raw_ns": values, "median_ns": statistics.median(values)}
        for name, values in samples.items()
    }


@pytest.mark.parametrize("dimension", ["L", "O", "unmeasured_registers", "history"])
def test_bridge_old_validation_and_output_index_cost(dimension, monkeypatch):
    rows = []
    for n in (8, 16, 32):
        circuit = _circuit(
            declarations=n if dimension == "unmeasured_registers" else 1,
            history=n if dimension == "history" else 1,
        )
        invocations = n if dimension == "L" else 32 if dimension == "O" else 1
        outputs = n if dimension == "O" else 1
        program, kernels, bindings = _program(circuit, _config(), invocations, outputs)
        authenticated = {i: b.schedule for i, b in bindings.items()}
        mapped = bridge._map_outputs(program, authenticated)
        assert len(mapped.outputs) == outputs
        assert len(mapped.outputs[0].history) == (n if dimension == "history" else 1)
        observed_events = {
            i: _ObservedTuple(schedule.events) for i, schedule in authenticated.items()
        }
        register_accesses = []

        class ScheduleView:
            def __init__(
                self,
                index,
                events=observed_events,
                accesses=register_accesses,
                schedules=authenticated,
            ):
                self.index = index
                self._events, self._accesses, self._schedules = events, accesses, schedules

            @property
            def events(self):
                return self._events[self.index]

            @property
            def registers(self):
                self._accesses.append(self.index)
                return self._schedules[self.index].registers

        observed_result = bridge._map_outputs(program, {i: ScheduleView(i) for i in authenticated})
        assert observed_result == mapped
        event_visits = sum(events.visits for events in observed_events.values())
        assert event_visits == sum(len(schedule.events) for schedule in authenticated.values())
        assert register_accesses == []
        stages = {
            "inherited_validate_program": _measure(partial(validate_program, program, kernels)),
            "output_index": _measure(partial(bridge._map_outputs, program, authenticated)),
            "end_to_end": _measure(partial(bridge_program_native, program, kernels, bindings)),
        }
        visits = stages["output_index"]["line_visits"]
        output_visits = sum(visits.values())
        rows.append(
            {
                "size": n,
                "L": invocations,
                "O": outputs,
                "dimension": dimension,
                "output_visits": output_visits,
                "event_visits": event_visits,
                "register_accesses": len(register_accesses),
                "phase_times": _bridge_breakdown(program, kernels, bindings, monkeypatch),
                "stages": stages,
            }
        )
    for left, right in pairwise(rows):
        if dimension == "unmeasured_registers":
            assert right["output_visits"] == left["output_visits"]
        else:
            assert right["output_visits"] <= 2.2 * left["output_visits"]
    _save("bridge-" + dimension, rows)


def _reject_integer_budget(text):
    with pytest.raises(NativeInputError) as caught:
        NativeScheduleIR.from_json(text)
    assert caught.value.code == "json_integer_limit"


def test_peak_memory_and_json_character_budget():
    rows = []
    for n in (10, 100, 1000):
        schedule = lower_to_native(_circuit(gates=n), _config())
        text = schedule.to_json()
        assert NativeScheduleIR.from_json(text) == schedule
        rows.append(
            {
                "size": n,
                "characters": len(text),
                "stages": {
                    "write": _measure(schedule.to_json),
                    "read": _measure(partial(NativeScheduleIR.from_json, text)),
                },
            }
        )
    for left, right in pairwise(rows):
        ratio = right["characters"] / left["characters"]
        for stage in ("read", "write"):
            a = sum(left["stages"][stage]["line_visits"].values())
            b = sum(right["stages"][stage]["line_visits"].values())
            assert b <= (ratio + 0.5) * a
    schedule = lower_to_native(_circuit(), _config())
    # 使用图中不参与时间相等结构判决的事件 ready 值隔离十进制整数预算。
    integer_rows = []
    for digits in (4095, 4096, 4097):
        text = schedule.to_json().replace('"ready_ns":10', '"ready_ns":' + "9" * digits)
        assert len(text) > digits
        if digits == 4097:
            _reject_integer_budget(text)
            action = partial(_reject_integer_budget, text)
        else:
            assert NativeScheduleIR.from_json(text).events[0].ready_ns == 10**digits - 1
            action = partial(NativeScheduleIR.from_json, text)
        integer_rows.append(
            {
                "digits": digits,
                "characters": len(text),
                "expected": "json_integer_limit" if digits == 4097 else "accepted",
                "stages": {"parse": _measure(action)},
            }
        )
    _save("json-and-memory", rows)
    _save("integer-budget", integer_rows)
