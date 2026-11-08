# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""用独立摘要与真实控制树固定不变量的输入绑定。"""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import json

import pytest

import qaiji.core.program as programs
from _pulse_fixtures import config, lower_to_l1
from factories import bell_circuit, feedforward_circuit
from qaiji.core import Circuit
from qaiji.core.native import lower_to_native
from qaiji.core.program import (
    ExperimentMetadata,
    ProgramIR,
    ProgramValidationError,
    QuantumInvocation,
    ResultOutput,
    validate_program,
)
from qaiji.core.program_native import NativeBinding, bridge_program_native
from qaiji.core.pulse import dump_pulse_program

BELL_HASH = "sha256:afe9bc2fd0c5ae8b243a4a8615bbe457adde36c1753835884557bc2d31e043d1"


def checker():
    assert importlib.util.find_spec("qaiji.core.invariants") is not None, (
        "The invariant checker must bind real contextual inputs."
    )
    return importlib.import_module("qaiji.core.invariants")


def structured(depth=0, *, count=1, outputs=(0,)):
    assert hasattr(programs, "ProgramIRV1"), "A program must own its nested control structure."
    circuit = bell_circuit()
    ref = BELL_HASH
    tail = ()
    for _ in range(depth):
        tail = (
            programs.ProgramIf(
                invocation_index=0,
                register_name="c",
                value=0,
                then_body=tail,
                else_body=(),
            ),
        )
    program = programs.ProgramIRV1(
        quantum_invocations=tuple(QuantumInvocation(ref) for _ in range(count)),
        experiment_metadata=ExperimentMetadata(1),
        result_outputs=tuple(ResultOutput(i, "c") for i in outputs),
        control_flow=(programs.ProgramCall(invocation_index=0), *tail),
    )
    return program, {ref: circuit}


def results(report, id):
    assert all(
        item.layer == id.split("-")[1].split(".")[0] for item in report.results if item.id == id
    )
    return [(r.verdict, r.path) for r in report.results if r.id == id]


@pytest.mark.parametrize("depth", [0, 1, 4, 5])
def test_program_owns_depth_and_roundtrips(depth):
    module = checker()
    program, kernels = structured(depth)
    validate_program(program, kernels)  # 不变量入口检查深度，构造器不检查深度。
    raw = programs.dump_program(program)
    assert programs.dump_program(programs.load_program(raw)) == raw
    report = module.check_invariants(
        module.ProgramInvariantInput(program=raw, kernels=kernels),
        layer="L5",
    )
    if depth <= 4:
        assert report.ok
        assert results(report, "I-L5.4") == [("pass", "")]
    else:
        assert not report.ok
        path = "/program/control_flow/1" + "/then_body/0" * 4
        assert results(report, "I-L5.4") == [("fail", path)]


def test_old_program_bytes_stay_exact_and_cannot_certify_depth():
    module = checker()
    original = ProgramIR(
        quantum_invocations=(QuantumInvocation(BELL_HASH),),
        experiment_metadata=ExperimentMetadata(1),
        result_outputs=(ResultOutput(0, "c"),),
    )
    raw = original.to_json().encode()
    assert programs.dump_program(programs.load_program(raw)) == raw
    assert type(programs.load_program(raw)) is ProgramIR
    report = module.check_invariants(
        module.ProgramInvariantInput(program=original, kernels={BELL_HASH: bell_circuit()}),
        layer="L5",
    )
    assert results(report, "I-L5.4") == [("fail", "/program/control_flow")]


@pytest.mark.parametrize("fault", ["missing_call", "duplicate", "forward_read", "output"])
def test_control_tree_binding_fails_before_depth(fault):
    module = checker()
    program, kernels = structured(count=2 if fault == "output" else 1)
    call = programs.ProgramCall(invocation_index=0)
    branch = programs.ProgramIf(
        invocation_index=0,
        register_name="c",
        value=0,
        then_body=(),
        else_body=(),
    )
    tree = {
        "missing_call": (),
        "duplicate": (call, call),
        "forward_read": (branch, call),
        "output": (
            call,
            dataclasses.replace(
                branch,
                then_body=(programs.ProgramCall(invocation_index=1),),
            ),
        ),
    }[fault]
    program = dataclasses.replace(program, control_flow=tree)
    if fault == "output":
        program = dataclasses.replace(program, result_outputs=(ResultOutput(1, "c"),))
    with pytest.raises(ProgramValidationError, match="CONTROL_FLOW"):
        validate_program(program, kernels)
    report = module.check_invariants(
        module.ProgramInvariantInput(program=program, kernels=kernels),
        layer="L5",
    )
    assert not report.ok
    assert any(r.id == "UNREGISTERED" for r in report.results)
    assert all(r.verdict == "fail" for r in report.results)


@pytest.mark.parametrize("fault", ["unknown", "boolean", "duplicate_key"])
def test_structured_program_json_rejects_malformed_nodes(fault):
    program, _ = structured()
    raw = programs.dump_program(program)
    payload = json.loads(raw)
    if fault == "unknown":
        payload["control_flow"][0]["extra"] = 1
    elif fault == "boolean":
        payload["control_flow"][0]["invocation_index"] = True
    else:
        raw = raw.replace(b'"kind":"call"', b'"kind":"call","kind":"call"')
    with pytest.raises(ValueError):
        programs.load_program(raw if fault == "duplicate_key" else json.dumps(payload).encode())


def test_bridge_supports_linear_program_and_refuses_conditional_program():
    program, kernels = structured()
    circuit = kernels[BELL_HASH]
    schedule = lower_to_native(circuit, config())
    bindings = {0: NativeBinding(schedule=schedule, config=config())}
    assert bridge_program_native(program, kernels, bindings).outputs
    program, kernels = structured(1)
    with pytest.raises(ProgramValidationError, match="CONTROL_FLOW_UNSUPPORTED"):
        bridge_program_native(program, kernels, bindings)


def test_summary_uses_frozen_independent_hash():
    module = checker()
    circuit = bell_circuit()
    source = module.L4InvariantInput(circuit=circuit, recorded_summary_hash=BELL_HASH)
    assert module.check_invariants(source, layer="L4").ok
    bad = dataclasses.replace(source, recorded_summary_hash="sha256:" + "0" * 64)
    assert results(module.check_invariants(bad, layer="L4"), "I-L4.3") == [
        ("fail", "/recorded_summary_hash"),
    ]
    circuit.x(0)
    assert not module.check_invariants(source, layer="L4").ok


def test_missing_summary_and_schedule_do_not_report_pass():
    module = checker()
    report = module.check_invariants(bell_circuit(), layer="L4")
    assert results(report, "I-L4.3") == [("fail", "/recorded_summary_hash")]
    circuit = feedforward_circuit()
    schedule = lower_to_native(circuit, config())
    pulse = lower_to_l1(schedule)
    for raw in (pulse, dump_pulse_program(pulse)):
        report = module.check_invariants(raw, layer="L1")
        assert results(report, "I-L1.6") == [("fail", "/schedule")]
        assert results(report, "I-L1.7") == [("fail", "/schedule")]
    assert module.check_invariants(
        module.L1InvariantInput(pulse=pulse, schedule=schedule),
        layer="L1",
    ).ok


def test_duplicate_acquire_maps_constructor_diagnostic_to_event_invariant():
    module = checker()
    schedule = lower_to_native(bell_circuit(), config())
    pulse = lower_to_l1(schedule)
    payload = json.loads(dump_pulse_program(pulse))
    acquires = [i for i in payload["instructions"] if i["kind"] == "acquire"]
    assert len(acquires) == 2
    acquires[1]["event_id"] = acquires[0]["event_id"]
    report = module.check_invariants(
        module.L1InvariantInput(
            pulse=json.dumps(payload).encode(),
            schedule=schedule,
        ),
        layer="L1",
    )
    assert not report.ok
    assert any(r.id == "I-L1.7" and r.path.endswith("/event_id") for r in report.results)


def test_native_timing_reuses_serial_and_readiness_rules():
    module = checker()
    circuit = feedforward_circuit()
    schedule = lower_to_native(circuit, config())
    source = module.L2InvariantInput(circuit=circuit, schedule=schedule, config=config())
    assert module.check_invariants(source, layer="L2").ok
    report = module.check_invariants(schedule, layer="L2")
    assert not report.ok
    assert all(r.verdict == "fail" for r in report.results)
    region = schedule.conditions[0]
    bad_schedule = dataclasses.replace(
        schedule,
        conditions=(
            dataclasses.replace(
                region,
                start_ns=region.start_ns - 1,
            ),
        ),
    )
    report = module.check_invariants(dataclasses.replace(source, schedule=bad_schedule), layer="L2")
    assert results(report, "I-L2.7") == [("fail", "/schedule/conditions/0/start_ns")]


def test_l2_missing_configuration_cannot_certify_timing():
    module = checker()
    circuit = feedforward_circuit()
    schedule = lower_to_native(circuit, config())
    report = module.check_invariants(
        module.L2InvariantInput(circuit=circuit, schedule=schedule),
        layer="L2",
    )
    for id in ("I-L2.6", "I-L2.7"):
        assert results(report, id) == [("fail", "/config")]


def test_native_timing_preserves_global_serial_rule_across_distinct_resources():
    module = checker()
    circuit = Circuit(2)
    circuit.h(0)
    circuit.h(1)
    schedule = lower_to_native(circuit, config())
    source = module.L2InvariantInput(circuit=circuit, schedule=schedule, config=config())
    assert module.check_invariants(source, layer="L2").ok
    # 尾部间隙违反全局串行时序，不会造成资源重叠。
    op = schedule.operations[-1]
    changed = dataclasses.replace(
        schedule,
        operations=(
            *schedule.operations[:-1],
            dataclasses.replace(op, start_ns=op.start_ns + 1),
        ),
        end_ns=schedule.end_ns + 1,
    )
    report = module.check_invariants(dataclasses.replace(source, schedule=changed), layer="L2")
    assert results(report, "I-L2.6") == [
        ("fail", f"/schedule/operations/{len(schedule.operations) - 1}/start_ns"),
    ]
    assert any("serial_time" in r.message for r in report.results)


def test_deep_object_tree_returns_depth_failure_without_recursion_error():
    module = checker()
    program, kernels = structured(1100)
    report = module.check_invariants(
        module.ProgramInvariantInput(program=program, kernels=kernels),
        layer="L5",
    )
    assert results(report, "I-L5.4") == [
        ("fail", "/program/control_flow/1" + "/then_body/0" * 4),
    ]


@pytest.mark.parametrize("layer", ["L1", "L2"])
def test_context_carriers_reject_wrong_record_types(layer):
    module = checker()
    source = (
        module.L1InvariantInput(pulse=object(), schedule=object())
        if layer == "L1"
        else module.L2InvariantInput(circuit=object(), schedule=object(), config=object())
    )
    with pytest.raises(TypeError):
        module.check_invariants(source, layer=layer)


def test_l5_requires_kernel_binding_and_allows_local_conditional_results():
    module = checker()
    program, kernels = structured(count=2)
    inner = programs.ProgramIf(
        invocation_index=1,
        register_name="c",
        value=0,
        then_body=(),
        else_body=(),
    )
    outer = programs.ProgramIf(
        invocation_index=0,
        register_name="c",
        value=0,
        then_body=(programs.ProgramCall(invocation_index=1), inner),
        else_body=(),
    )
    program = dataclasses.replace(program, control_flow=(program.control_flow[0], outer))
    assert module.check_invariants(
        module.ProgramInvariantInput(program=program, kernels=kernels),
        layer="L5",
    ).ok
    assert results(module.check_invariants(program, layer="L5"), "I-L5.4") == [
        ("fail", "/kernels"),
    ]
