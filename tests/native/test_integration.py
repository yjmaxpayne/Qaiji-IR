# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""以独立语义预期验证公开 JSON 到 L5 完整链。"""

import ast
import math
import re
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from qaiji.codec import from_qasm3, to_qasm3
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.native import (
    NativeScheduleIR,
    NativeValidationError,
    OperationSpec,
    QubitResource,
    ScheduleConfig,
    SourceLocation,
    lower_to_native,
    qubic_mapping,
    validate_native_schedule,
)
from qaiji.core.program import (
    ExperimentMetadata,
    ProgramIR,
    QuantumInvocation,
    ResultOutput,
    compute_kernel_ref,
)
from qaiji.core.program_native import (
    NativeBinding,
    ProgramNativeValidationError,
    bridge_program_native,
)
from qaiji.exceptions import Qasm3UnsupportedGateError


def synthetic_config():
    """显式整数时间仅用于合成示例，不代表设备校准值。"""
    return ScheduleConfig(
        qubit_resources=(
            QubitResource(qubit=0, resource="q0"),
            QubitResource(qubit=1, resource="q1"),
        ),
        operation_specs=(
            *tuple(
                OperationSpec(
                    kind=kind,
                    qubits=(q,),
                    duration_ns=duration,
                    resources=(f"q{q}",),
                    result_latency_ns=latency,
                )
                for q in (0, 1)
                for kind, duration, latency in (("RZ", 0, 0), ("RX90", 4, 0), ("MEASURE", 10, 6))
            ),
            OperationSpec(
                kind="CZ", qubits=(0, 1), duration_ns=8, resources=("q0", "q1"), result_latency_ns=0
            ),
        ),
        cz_couplings=((0, 1),),
    )


def journey(circuit, outputs=()):
    config = synthetic_config()
    original = lower_to_native(circuit, config)
    restored = NativeScheduleIR.from_json(original.to_json())
    assert restored == original and restored is not original
    report = validate_native_schedule(circuit, restored, config)
    assert report.valid
    assert (report.source.status, report.rules.status, report.schedule.status) == (
        "pass",
        "pass",
        "pass",
    )
    projection = qubic_mapping(circuit, restored, config)
    ref = compute_kernel_ref(circuit)
    program = ProgramIR(
        quantum_invocations=(QuantumInvocation(ref), QuantumInvocation(ref)),
        experiment_metadata=ExperimentMetadata(7, "synthetic", "synthetic"),
        result_outputs=outputs,
    )
    bindings = {i: NativeBinding(schedule=restored, config=config) for i in (0, 1)}
    mapping = bridge_program_native(program, {ref: circuit}, bindings)
    return restored, projection, mapping, program, bindings


def output_rows(mapping):
    return tuple(
        (
            o.invocation_index,
            o.register_name,
            tuple((e.invocation_index, e.event_id) for e in o.history),
            tuple((b.bit_index, b.event.invocation_index, b.event.event_id) for b in o.final_bits),
        )
        for o in mapping.outputs
    )


def test_qasm_bell_json_validate_project_bridge():
    circuit = from_qasm3("""OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
bit[2] c;
h q[0];
cx q[0], q[1];
c[1] = measure q[0];
c[0] = measure q[1];
""")
    schedule, projection, mapping, program, bindings = journey(
        circuit, (ResultOutput(1, "c"), ResultOutput(0, "c"))
    )
    assert tuple(
        (e.event_id, e.operation_index, e.qubit, e.bit_index, e.end_ns, e.ready_ns)
        for e in schedule.events
    ) == (("m0", 10, 0, 1, 30, 36), ("m1", 11, 1, 0, 40, 46))
    assert (projection.end_ns, projection.all_results_ready_ns) == (40, 46)
    assert tuple(
        (op.operation_index, op.labels, op.event_id) for op in projection.operations[-2:]
    ) == (
        (10, ("PULSE_READOUT", "REGISTER_RESULT"), "m0"),
        (11, ("PULSE_READOUT", "REGISTER_RESULT"), "m1"),
    )
    assert output_rows(mapping) == (
        (1, "c", ((1, "m0"), (1, "m1")), ((0, 1, "m1"), (1, 1, "m0"))),
        (0, "c", ((0, "m0"), (0, "m1")), ((0, 0, "m1"), (1, 0, "m0"))),
    )
    # 结构合法的载体仅改一个时长槽，反序列化后必须拒绝。
    damaged = replace(
        schedule,
        operations=(
            schedule.operations[0],
            replace(schedule.operations[1], duration_ns=5),
            *schedule.operations[2:],
        ),
    )
    damaged = NativeScheduleIR.from_json(damaged.to_json())
    config = bindings[0].config
    report = validate_native_schedule(circuit, damaged, config)
    assert not report.valid
    assert tuple((i.code, i.path, i.source, i.operation_index) for i in report.schedule.issues) == (
        (
            "duration_mismatch",
            "$.operations[1].duration_ns",
            SourceLocation(gate_index=0, body_offset=None),
            1,
        ),
    )
    with pytest.raises(NativeValidationError) as rejected:
        qubic_mapping(circuit, damaged, config)
    assert type(rejected.value) is NativeValidationError
    assert rejected.value.report == report
    bindings[1] = NativeBinding(schedule=damaged, config=config)
    with pytest.raises(ProgramNativeValidationError) as caught:
        bridge_program_native(program, {compute_kernel_ref(circuit): circuit}, bindings)
    assert type(caught.value) is ProgramNativeValidationError
    assert tuple(
        (i.invocation_index, i.code, i.input_code, i.input_path) for i in caught.value.issues
    ) == ((1, "native_invalid", None, None),)
    assert caught.value.issues[0].native_report == report


def test_python_four_gates_json_validate_project_bridge():
    circuit = Circuit(2)
    circuit.gates = [
        Gate(GateType.RX90, (0,), (0.25,)),
        Gate(GateType.RX180, (1,), (-0.5,)),
        Gate(GateType.ISWAP, (0, 1)),
        Gate(GateType.SQISWAP, (0, 1)),
    ]
    register = ClassicalRegister("c", 1)
    circuit.cregs = [register]
    circuit.gates.append(Measure(0, ClassicalBit(register, 0)))
    schedule, projection, mapping, _, _ = journey(circuit, (ResultOutput(0, "c"),))
    assert tuple((g.rule_id, g.op_start, g.op_stop) for g in schedule.groups[:4]) == (
        ("cz.v0.RX90", 0, 1),
        ("cz.v0.RX180", 1, 3),
        ("cz.v0.ISWAP", 3, 49),
        ("cz.v0.SQISWAP", 49, 95),
    )
    assert tuple((op.kind, op.qubits, op.params) for op in schedule.operations[:3]) == (
        ("RX90", (0,), (0.25,)),
        ("RX90", (1,), (-0.5,)),
        ("RX90", (1,), (-0.5,)),
    )
    assert tuple(schedule.operations[i].params for i in (16, 39, 62, 85)) == (
        (-math.pi / 2,),
        (-math.pi / 2,),
        (-math.pi / 4,),
        (-math.pi / 4,),
    )
    assert len(projection.operations) == 96
    assert tuple(op.labels for op in projection.operations[:3]) == (("PULSE",),) * 3
    assert projection.conditions == ()
    assert output_rows(mapping) == ((0, "c", ((0, "m0"),), ((0, 0, "m0"),)),)
    assert {op.operation.kind for op in projection.operations} == {"RZ", "RX90", "CZ", "MEASURE"}
    for gate in circuit.gates[:4]:
        isolated = Circuit(2)
        isolated.gates = [gate]
        with pytest.raises(Qasm3UnsupportedGateError, match="no stdgates mapping"):
            to_qasm3(isolated)


def test_measurement_feedforward_json_validate_project_bridge():
    register = ClassicalRegister("c", 1)
    circuit = Circuit(2)
    circuit.cregs = [register]
    circuit.gates = [
        Measure(0, ClassicalBit(register, 0)),
        Conditional(register, 1, (Gate(GateType.X, (1,)),)),
        Measure(1, ClassicalBit(register, 0)),
    ]
    schedule, projection, mapping, program, bindings = journey(circuit, (ResultOutput(1, "c"),))
    assert tuple(
        (op.kind, op.start_ns, op.duration_ns, op.condition_id) for op in schedule.operations
    ) == (
        ("MEASURE", 0, 10, None),
        ("RX90", 16, 4, "c1"),
        ("RX90", 20, 4, "c1"),
        ("MEASURE", 24, 10, None),
    )
    (condition,) = schedule.conditions
    assert (condition.condition_id, condition.register_name, condition.value) == ("c1", "c", 1)
    assert tuple((r.bit_index, r.event_id) for r in condition.reads) == ((0, "m0"),)
    assert tuple(
        (e.event_id, e.operation_index, e.end_ns, e.ready_ns) for e in projection.events
    ) == (("m0", 0, 10, 16), ("m1", 3, 34, 40))
    assert (projection.end_ns, projection.all_results_ready_ns) == (34, 40)
    assert output_rows(mapping) == ((1, "c", ((1, "m0"), (1, "m1")), ((0, 1, "m1"),)),)
    # 只伪造首次测量的就绪时间，保留前馈读取绑定与其他所有字段。
    damaged = replace(
        schedule, events=(replace(schedule.events[0], ready_ns=17), schedule.events[1])
    )
    damaged = NativeScheduleIR.from_json(damaged.to_json())
    report = validate_native_schedule(circuit, damaged, bindings[1].config)
    assert not report.valid
    assert tuple((i.code, i.path, i.source, i.operation_index) for i in report.schedule.issues) == (
        (
            "measurement_events",
            "$.events[0].ready_ns",
            SourceLocation(gate_index=0, body_offset=None),
            0,
        ),
    )
    bindings[1] = replace(bindings[1], schedule=damaged)
    with pytest.raises(ProgramNativeValidationError) as rejected:
        bridge_program_native(program, {compute_kernel_ref(circuit): circuit}, bindings)
    assert type(rejected.value) is ProgramNativeValidationError
    (issue,) = rejected.value.issues
    assert (issue.invocation_index, issue.code, issue.input_code, issue.input_path) == (
        1,
        "native_invalid",
        None,
        None,
    )
    assert issue.native_report == report


def test_tutorial_uses_explicit_synthetic_configuration():
    tutorial = (
        Path(__file__).resolve().parents[2] / "doc/source/getting-started/native-schedule.rst"
    )
    text = tutorial.read_text(encoding="utf-8")
    blocks = re.findall(
        r"^\.\. testcode:: native-schedule\n\n((?:[ \t]+.*\n|\n)+)", text, re.MULTILINE
    )
    assert blocks, "The tutorial must include executable native-schedule testcode"
    code = "\n".join(textwrap.dedent(block) for block in blocks)
    calls = [node for node in ast.walk(ast.parse(code)) if isinstance(node, ast.Call)]
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "ScheduleConfig" for call in calls
    )
    specs = [
        call
        for call in calls
        if isinstance(call.func, ast.Name) and call.func.id == "OperationSpec"
    ]
    assert specs and all(
        {"duration_ns", "result_latency_ns"} <= {k.arg for k in call.keywords} for call in specs
    )
    namespace = {}
    exec(compile(code, str(tutorial), "exec"), namespace)
    config = namespace["config"]
    expected = synthetic_config()
    assert config.qubit_resources == expected.qubit_resources
    assert config.cz_couplings == ((0, 1),)
    assert {(spec.kind, spec.qubits): spec for spec in config.operation_specs} == {
        (spec.kind, spec.qubits): spec for spec in expected.operation_specs
    }
    assert namespace["report"].valid
    assert namespace["restored"] == namespace["schedule"]
    assert namespace["restored"] is not namespace["schedule"]
    assert (namespace["projection"].end_ns, namespace["projection"].all_results_ready_ns) == (
        40,
        46,
    )
    assert len(namespace["mapping"].outputs) == 1
