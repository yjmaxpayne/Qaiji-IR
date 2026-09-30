# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""OpenQASM 往返契约：黄金样例与属性测试。"""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from factories import bell_circuit, feedforward_circuit, ghz_circuit
from qaiji.codec.qasm3 import _GATE_REGISTRY, from_qasm3, to_qasm3
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.semantics.preservation import check_preservation

pytestmark = pytest.mark.integration

_BELL_QASM2 = """OPENQASM 2.0;
include "qelib1.inc";
qreg source[2];
creg result[2];
h source[0];
cx source[0], source[1];
measure source[0] -> result[0];
measure source[1] -> result[1];
"""

_FEEDFORWARD_QASM3 = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] source;
bit outcome;
rx(pi / 2) source[0];
outcome[0] = measure source[0];
if (outcome == 1) {
  x source[1];
}
"""

_CANONICAL_SPECS = tuple({spec.gate_type: spec for spec in _GATE_REGISTRY.values()}.values())
_FINITE_ANGLE = st.floats(
    min_value=-2 * math.pi,
    max_value=2 * math.pi,
    allow_nan=False,
    allow_infinity=False,
)


def _roundtrip_circuit(circuit: Circuit) -> Circuit:
    return from_qasm3(to_qasm3(circuit))


def _roundtrip_text(source: str) -> str:
    return to_qasm3(from_qasm3(source))


@st.composite
def _gate_for_width(draw: st.DrawFn, num_qubits: int) -> Gate:
    eligible = tuple(spec for spec in _CANONICAL_SPECS if spec.arity <= num_qubits)
    spec = draw(st.sampled_from(eligible))
    qubits = draw(
        st.lists(
            st.integers(min_value=0, max_value=num_qubits - 1),
            min_size=spec.arity,
            max_size=spec.arity,
            unique=True,
        )
    )
    params = draw(
        st.lists(
            _FINITE_ANGLE,
            min_size=spec.n_params,
            max_size=spec.n_params,
        )
    )
    return Gate(spec.gate_type, tuple(qubits), tuple(params))


@st.composite
def _codec_circuits(
    draw: st.DrawFn,
    *,
    min_qubits: int = 1,
    max_nodes: int = 20,
) -> Circuit:
    num_qubits = draw(st.integers(min_value=min_qubits, max_value=5))
    circuit = Circuit(num_qubits)
    register_sizes = draw(st.lists(st.integers(min_value=1, max_value=5), min_size=1, max_size=3))
    registers = tuple(
        ClassicalRegister(f"c{index}", size) for index, size in enumerate(register_sizes)
    )
    for register in registers:
        circuit.add_register(register)

    node_count = draw(st.integers(min_value=0, max_value=max_nodes))
    for _ in range(node_count):
        node_kind = draw(st.sampled_from(("gate", "measure", "conditional")))
        if node_kind == "gate":
            circuit.add_gate(draw(_gate_for_width(num_qubits)))
        elif node_kind == "measure":
            register = draw(st.sampled_from(registers))
            circuit.add_measure(
                Measure(
                    draw(st.integers(min_value=0, max_value=num_qubits - 1)),
                    ClassicalBit(
                        register,
                        draw(st.integers(min_value=0, max_value=register.size - 1)),
                    ),
                )
            )
        else:
            register = draw(st.sampled_from(registers))
            body = draw(
                st.lists(
                    _gate_for_width(num_qubits),
                    min_size=0,
                    max_size=3,
                )
            )
            circuit.add_conditional(
                Conditional(
                    register,
                    draw(
                        st.integers(
                            min_value=0,
                            max_value=(1 << register.size) - 1,
                        )
                    ),
                    tuple(body),
                )
            )
    return circuit


@st.composite
def _circuits_with_cnot(draw: st.DrawFn) -> Circuit:
    alias_count = draw(st.integers(min_value=1, max_value=3))
    circuit = draw(_codec_circuits(min_qubits=2, max_nodes=20 - alias_count))
    for _ in range(alias_count):
        control = draw(st.integers(min_value=0, max_value=circuit.num_qubits - 1))
        target = draw(
            st.sampled_from(tuple(qubit for qubit in range(circuit.num_qubits) if qubit != control))
        )
        position = draw(st.integers(min_value=0, max_value=len(circuit.gates)))
        circuit.gates.insert(position, Gate(GateType.CNOT, (control, target)))
    return circuit


def _collapse_cnot(circuit: Circuit) -> Circuit:
    collapsed = Circuit(circuit.num_qubits)
    for register in circuit.cregs:
        collapsed.add_register(register)
    for operation in circuit.gates:
        if isinstance(operation, Gate):
            gate_type = GateType.CX if operation.gate_type is GateType.CNOT else operation.gate_type
            collapsed.add_gate(Gate(gate_type, operation.qubits, operation.params))
        elif isinstance(operation, Measure):
            collapsed.add_measure(operation)
        else:
            body = tuple(
                Gate(
                    GateType.CX if gate.gate_type is GateType.CNOT else gate.gate_type,
                    gate.qubits,
                    gate.params,
                )
                for gate in operation.body
            )
            collapsed.add_conditional(Conditional(operation.register, operation.value, body))
    return collapsed


@pytest.mark.parametrize(
    "factory",
    [bell_circuit, ghz_circuit, feedforward_circuit],
    ids=("bell", "ghz", "feedforward"),
)
def test_golden_circuit_roundtrip_is_a_fixed_point(
    factory: Callable[[], Circuit],
) -> None:
    circuit = factory()
    roundtripped = _roundtrip_circuit(circuit)

    # 两条正交的 L4 裁决坐标轴（ARCH-002 §2.3）：结构相等问的是"这是不是同一棵
    # 树？"，语义保持问的是"变换之后算符是否仍然相等（可差全局相位）？"。
    # RZ(2*pi) 对测量统计*分类器*而言是 IDENTITY，对*保持性*裁决而言却是
    # UP_TO_PHASE —— 两条断言都保留，正是本测试的用意所在。
    assert roundtripped == circuit  # QM1 结构性契约（未变）
    verdict = check_preservation(circuit, roundtripped, stage="codec_roundtrip")
    assert verdict.status == "passed"


def test_qasm2_input_is_reemitted_as_qasm3() -> None:
    emitted = _roundtrip_text(_BELL_QASM2)

    assert emitted.startswith("OPENQASM 3.0;\n")
    assert 'include "stdgates.inc";' in emitted
    assert from_qasm3(emitted) == from_qasm3(_BELL_QASM2)


def test_text_roundtrip_preserves_circuit_semantics() -> None:
    assert from_qasm3(_roundtrip_text(_FEEDFORWARD_QASM3)) == from_qasm3(_FEEDFORWARD_QASM3)


def test_text_roundtrip_is_idempotent_after_one_pass() -> None:
    first = _roundtrip_text(_FEEDFORWARD_QASM3)

    assert _roundtrip_text(first) == first


def test_cnot_alias_collapses_to_cx_without_changing_other_nodes() -> None:
    source = bell_circuit()
    source.gates.insert(1, Gate(GateType.CNOT, (1, 0)))

    assert _roundtrip_circuit(source) == _collapse_cnot(source)
    assert source.gates[1] == Gate(GateType.CNOT, (1, 0))


@pytest.mark.pbt
@settings(deadline=None)
@given(circuit=_codec_circuits())
def test_codec_canonical_circuits_are_roundtrip_fixed_points(circuit: Circuit) -> None:
    assert len(circuit.gates) <= 20
    assert _roundtrip_circuit(circuit) == circuit


@pytest.mark.pbt
@settings(deadline=None)
@given(circuit=_circuits_with_cnot())
def test_cnot_alias_collapse_is_idempotent(circuit: Circuit) -> None:
    assert len(circuit.gates) <= 20
    once = _roundtrip_circuit(circuit)

    assert once == _collapse_cnot(circuit)
    assert _roundtrip_circuit(once) == once
