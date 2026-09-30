# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""电路与门的值语义契约。"""

import math
from dataclasses import FrozenInstanceError

import pytest

from factories import bell_circuit, feedforward_circuit, ghz_circuit
from qaiji.constants import DEFAULT_TOLERANCE
from qaiji.core.circuit import (
    CANONICAL_ALIASES,
    PARAM_REQUIREMENTS,
    SINGLE_QUBIT_GATES,
    TWO_QUBIT_GATES,
    Circuit,
    Gate,
    GateType,
    _tau_multiple_exponent,
)
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure

EXPECTED_GATE_NAMES = (
    "I",
    "X",
    "Y",
    "Z",
    "H",
    "S",
    "T",
    "RX",
    "RY",
    "RZ",
    "U3",
    "CNOT",
    "CX",
    "CZ",
    "SWAP",
    "RX90",
    "RX180",
    "ISWAP",
    "SQISWAP",
)


def test_gate_type_tables_define_the_complete_gate_model() -> None:
    assert tuple(gate.name for gate in GateType) == EXPECTED_GATE_NAMES
    assert all(gate.value == gate.name for gate in GateType)
    assert SINGLE_QUBIT_GATES == {
        GateType.I,
        GateType.X,
        GateType.Y,
        GateType.Z,
        GateType.H,
        GateType.S,
        GateType.T,
        GateType.RX,
        GateType.RY,
        GateType.RZ,
        GateType.U3,
        GateType.RX90,
        GateType.RX180,
    }
    assert TWO_QUBIT_GATES == {
        GateType.CNOT,
        GateType.CX,
        GateType.CZ,
        GateType.SWAP,
        GateType.ISWAP,
        GateType.SQISWAP,
    }
    assert set(PARAM_REQUIREMENTS) == set(GateType)
    assert {gate for gate, bounds in PARAM_REQUIREMENTS.items() if bounds == (1, 1)} == {
        GateType.RX,
        GateType.RY,
        GateType.RZ,
        GateType.RX90,
        GateType.RX180,
    }
    assert PARAM_REQUIREMENTS[GateType.U3] == (3, 3)
    assert all(
        bounds == (0, 0)
        for gate, bounds in PARAM_REQUIREMENTS.items()
        if gate
        not in {GateType.RX, GateType.RY, GateType.RZ, GateType.RX90, GateType.RX180, GateType.U3}
    )
    assert CANONICAL_ALIASES == {GateType.CNOT: GateType.CX}


@pytest.mark.parametrize(
    ("gate_type", "qubits", "params"),
    [
        (GateType.H, (), ()),
        (GateType.H, (0, 1), ()),
        (GateType.CX, (0,), ()),
        (GateType.CX, (0, 0), ()),
        (GateType.RX, (0,), ()),
        (GateType.H, (0,), (0.25,)),
        (GateType.U3, (0,), (0.1, 0.2)),
        (GateType.RZ, (0,), (math.inf,)),
        (GateType.RY, (0,), (math.nan,)),
    ],
)
def test_gate_rejects_invalid_construction(
    gate_type: GateType,
    qubits: tuple[int, ...],
    params: tuple[float, ...],
) -> None:
    with pytest.raises(ValueError):
        Gate(gate_type, qubits, params)


def test_gate_normalizes_sequences_and_has_no_mutation_surface() -> None:
    gate = Gate(GateType.RX, [0], [0.25])

    assert gate.qubits == (0,)
    assert gate.params == (0.25,)
    assert not hasattr(gate.qubits, "append")
    assert not hasattr(gate.params, "append")
    with pytest.raises(FrozenInstanceError):
        gate.qubits = (1,)


def test_gate_structural_equality_does_not_apply_aliases() -> None:
    assert Gate(GateType.CNOT, (0, 1)) != Gate(GateType.CX, (0, 1))


def test_alias_canonicalization_returns_cx_without_mutating_source() -> None:
    source = Gate(GateType.CNOT, (0, 1))

    canonical = source.canonicalize()

    assert canonical == Gate(GateType.CX, (0, 1))
    assert source.gate_type is GateType.CNOT


@pytest.mark.parametrize("gate_type", [GateType.RX, GateType.RY, GateType.RZ])
def test_rotation_canonicalization_normalizes_angles_and_elides_zero(
    gate_type: GateType,
) -> None:
    normalized = Gate(gate_type, (0,), (2 * math.pi + 0.25,)).canonicalize()
    identity = Gate(gate_type, (0,), (2 * math.pi,)).canonicalize()

    assert normalized.gate_type is gate_type
    assert normalized.qubits == (0,)
    assert normalized.params == pytest.approx((0.25,))
    assert identity == Gate(GateType.I, (0,))


def test_copy_preserves_equality_for_paramless_gates() -> None:
    circuit = Circuit(2)
    circuit.h(0)
    circuit.cnot(0, 1)
    register_marker = object()
    circuit.cregs.append(register_marker)

    copied = circuit.copy()

    assert copied == circuit
    assert copied is not circuit
    assert copied.gates is not circuit.gates
    assert copied.cregs is not circuit.cregs
    assert copied.gates[0] is circuit.gates[0]
    assert copied.cregs[0] is register_marker


def test_circuit_equality_is_reflexive_and_symmetric() -> None:
    left = Circuit(1)
    left.rx(0, 0.25)
    right = Circuit(1)
    right.rx(0, 0.25)

    assert left == left
    assert right == right
    assert left == right
    assert right == left


def test_circuit_equality_uses_parameter_tolerance_without_canonicalizing() -> None:
    reference = Circuit(1)
    reference.rz(0, 0.25)
    close = Circuit(1)
    close.rz(0, 0.25 + DEFAULT_TOLERANCE / 2)
    far = Circuit(1)
    far.rz(0, 0.25 + 2 * DEFAULT_TOLERANCE)
    different_gate = Circuit(1)
    different_gate.rx(0, 0.25)

    assert reference == close
    assert close == reference
    assert reference != far
    assert reference != different_gate


def test_circuit_equality_observes_width_registers_and_node_order() -> None:
    reference = Circuit(2)
    reference.h(0)
    reference.cx(0, 1)
    different_width = Circuit(3)
    different_width.h(0)
    different_width.cx(0, 1)
    different_registers = reference.copy()
    different_registers.cregs.append(object())
    different_order = Circuit(2)
    different_order.cx(0, 1)
    different_order.h(0)

    assert reference != object()
    assert reference != different_width
    assert reference != different_registers
    assert reference != different_order
    with pytest.raises(TypeError):
        hash(reference)


def test_gate_hash_eq_contract() -> None:
    tuple_gate = Gate(GateType.H, (0,))
    list_gate = Gate(GateType.H, [0])

    assert tuple_gate == list_gate
    assert hash(tuple_gate) == hash(list_gate)


def test_rx90_default_phase_is_zero() -> None:
    circuit = Circuit(1)

    circuit.rx90(0)

    assert len(circuit.gates) == 1
    assert circuit.gates[0].params == (0.0,)


@pytest.mark.parametrize("num_qubits", [0, -1])
def test_circuit_rejects_non_positive_width(num_qubits: int) -> None:
    with pytest.raises(ValueError):
        Circuit(num_qubits)


@pytest.mark.parametrize("qubit", [-1, 2])
def test_add_gate_rejects_qubits_outside_circuit(qubit: int) -> None:
    circuit = Circuit(2)

    with pytest.raises(ValueError):
        circuit.add_gate(Gate(GateType.H, (qubit,)))


@pytest.mark.parametrize(
    ("method_name", "args", "expected"),
    [
        ("h", (0,), Gate(GateType.H, (0,))),
        ("x", (0,), Gate(GateType.X, (0,))),
        ("y", (0,), Gate(GateType.Y, (0,))),
        ("z", (0,), Gate(GateType.Z, (0,))),
        ("s", (0,), Gate(GateType.S, (0,))),
        ("t", (0,), Gate(GateType.T, (0,))),
        ("rx", (0,), Gate(GateType.RX, (0,), (math.pi,))),
        ("ry", (0, 0.2), Gate(GateType.RY, (0,), (0.2,))),
        ("rz", (0, 0.3), Gate(GateType.RZ, (0,), (0.3,))),
        ("rx90", (0,), Gate(GateType.RX90, (0,), (0.0,))),
        ("rx180", (0,), Gate(GateType.RX180, (0,), (0.0,))),
        ("u3", (0, 0.1, 0.2, 0.3), Gate(GateType.U3, (0,), (0.1, 0.2, 0.3))),
        ("cnot", (0, 1), Gate(GateType.CNOT, (0, 1))),
        ("cx", (0, 1), Gate(GateType.CX, (0, 1))),
        ("cz", (0, 1), Gate(GateType.CZ, (0, 1))),
    ],
)
def test_convenience_builder_appends_expected_gate(
    method_name: str,
    args: tuple[float | int, ...],
    expected: Gate,
) -> None:
    circuit = Circuit(2)

    result = getattr(circuit, method_name)(*args)

    assert result is None
    assert circuit.gates == [expected]


def test_length_and_string_rendering_describe_circuit() -> None:
    circuit = Circuit(2)
    circuit.h(0)
    circuit.rz(1, 0.25)

    assert len(circuit) == 2
    assert str(circuit) == (
        "Circuit(2 qubits)\n   0: H -> qubits [0]\n   1: RZ(0.2500) -> qubits [1]"
    )


@pytest.mark.parametrize("winding", [0, 1, 2, -1, -3, 100_000, 1_000_000])
def test_tau_multiple_exponent_returns_the_winding_number(winding: int) -> None:
    """整个包共用一套"theta == 0 (mod 2*pi)"的代数。

    注册表中 RZ 的特例、保持性的 R3/R4 规则、以及门折叠，问的都是同一个问题；这个
    判据若有第二种写法，就会让两个层对"某个旋转是不是恒等"各执一词。
    """
    assert _tau_multiple_exponent(winding * math.tau) == winding


@pytest.mark.parametrize("theta", [0.7, math.pi, math.tau + 0.7, 1e6 * math.tau + 0.7])
def test_tau_multiple_exponent_rejects_non_multiples(theta: float) -> None:
    assert _tau_multiple_exponent(theta) is None


def test_zero_winding_number_is_reported_as_zero_not_none() -> None:
    """调用方必须以 ``is not None`` 分支，绝不能靠真值判断。

    theta == 0 是最常见的恒等等价旋转，而它的绕数是 0 —— 一个假值 int。写成
    ``if k:`` 的调用方，恰恰会静默地不再折叠那个最重要的情形。
    """
    result = _tau_multiple_exponent(0.0)

    assert result == 0
    assert result is not None


@pytest.mark.physics
@pytest.mark.parametrize("winding", [0, 1])
def test_tau_multiple_exponent_boundary_residual_tracks_atol(winding: int) -> None:
    """只有在 k 较小时，容差带才落在浮点网格可达的范围内。

    在 theta ~ 1e6*tau 处一个 ULP 约为 9.3e-10，比 atol=1e-10 高出一个数量级：
    "theta = k*tau + 5e-11"在那里根本无法表示，构造出的残差会被舍入抹掉，这个用例
    等于什么都没断言。大 k 的情形改由上面那对"恰为整数倍 / 偏离整数倍"的用例覆盖。
    """
    inside = winding * math.tau + DEFAULT_TOLERANCE / 2
    outside = winding * math.tau + DEFAULT_TOLERANCE * 5

    assert _tau_multiple_exponent(inside) == winding
    assert _tau_multiple_exponent(outside) is None


@pytest.mark.physics
@pytest.mark.parametrize("winding", [1, 100_000, 1_000_000])
@pytest.mark.parametrize("gate_type", [GateType.RX, GateType.RY, GateType.RZ])
def test_rotation_folds_at_every_whole_turn(gate_type: GateType, winding: int) -> None:
    """整数圈在任意量级下都是恒等。

    被取代的旧判据是拿 ``theta % tau`` 去比容差，而在 theta = 1e6*tau 处它会留下
    约 2e-10 的残差 —— 超过 atol，于是这个门作为旋转存活了下来，尽管 1e6 个整圈
    精确地就是恒等（相位 (-1)**1e6 = +1）。在原始角度上检验判据正是本测试的用意：
    先归一化就把证据毁掉了。
    """
    folded = Gate(gate_type, (0,), (winding * math.tau,)).canonicalize()

    assert folded == Gate(GateType.I, (0,))


@pytest.mark.physics
def test_large_off_multiple_angle_still_normalizes_instead_of_folding() -> None:
    """在原始角度上做折叠，不得把大的非整数倍角一并吞掉。"""
    gate = Gate(GateType.RZ, (0,), (1e6 * math.tau + 0.7,)).canonicalize()

    assert gate.gate_type is GateType.RZ
    assert gate.params[0] == pytest.approx(0.7, abs=1e-8)


# --- Circuit.canonicalize()（ADR-204）---------------------------------------


def test_circuit_canonicalize_preserves_order_length_and_domain_preconditions() -> None:
    """AH-204：check_preservation 第 2 步所要求的那组前置条件。"""
    circuit = feedforward_circuit()
    circuit.rz(1, 2 * math.pi)

    canonical = circuit.canonicalize()

    assert canonical.num_qubits == circuit.num_qubits
    assert canonical.cregs == circuit.cregs
    assert len(canonical.gates) == len(circuit.gates)
    assert [type(op) for op in canonical.gates] == [type(op) for op in circuit.gates]


def test_circuit_canonicalize_leaves_measurements_as_the_same_object() -> None:
    circuit = feedforward_circuit()

    canonical = circuit.canonicalize()

    original_measure = next(op for op in circuit.gates if isinstance(op, Measure))
    canonical_measure = next(op for op in canonical.gates if isinstance(op, Measure))
    assert canonical_measure is original_measure


def test_circuit_canonicalize_maps_conditional_body_gate_by_gate() -> None:
    register = ClassicalRegister("c", 1)
    circuit = Circuit(1)
    circuit.add_register(register)
    circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
    circuit.add_conditional(Conditional(register, 1, (Gate(GateType.RZ, (0,), (2 * math.pi,)),)))

    canonical = circuit.canonicalize()

    conditional = canonical.gates[1]
    assert isinstance(conditional, Conditional)
    assert conditional.register == register
    assert conditional.value == 1
    assert conditional.body == (Gate(GateType.I, (0,)),)


def test_circuit_canonicalize_is_idempotent() -> None:
    circuit = ghz_circuit()
    circuit.rz(0, 2 * math.pi + 0.3)

    once = circuit.canonicalize()
    twice = once.canonicalize()

    assert twice == once


def test_circuit_canonicalize_matches_gate_canonicalize_position_for_position() -> None:
    circuit = bell_circuit()
    circuit.rz(0, 4 * math.pi)

    canonical = circuit.canonicalize()

    for original_op, canonical_op in zip(circuit.gates, canonical.gates, strict=True):
        if isinstance(original_op, Gate):
            assert canonical_op == original_op.canonicalize()
        else:
            assert canonical_op == original_op
