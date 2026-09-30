# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""经典值与异构电路操作的契约。"""

import math
from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from qaiji.constants import DEFAULT_TOLERANCE
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ClassicalRegister("", 1),
        lambda: ClassicalRegister("not valid", 1),
        lambda: ClassicalRegister("1counter", 1),
        lambda: ClassicalRegister("c", 0),
        lambda: ClassicalRegister("c", -1),
        lambda: ClassicalBit(ClassicalRegister("c", 2), -1),
        lambda: ClassicalBit(ClassicalRegister("c", 2), 2),
        lambda: Measure(-1, ClassicalBit(ClassicalRegister("c", 1), 0)),
        lambda: Conditional(ClassicalRegister("c", 1), -1, (Gate(GateType.X, (0,)),)),
    ],
)
def test_classical_values_reject_invalid_construction(factory: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        factory()


def test_conditional_normalizes_gate_sequences_to_tuple() -> None:
    register = ClassicalRegister("c", 1)
    gate = Gate(GateType.X, (0,))

    conditional = Conditional(register, 1, [gate])

    assert conditional.body == (gate,)
    assert isinstance(conditional.body, tuple)


def test_conditional_rejects_measurement_in_body() -> None:
    register = ClassicalRegister("c", 1)
    measurement = Measure(0, ClassicalBit(register, 0))

    with pytest.raises(ValueError):
        Conditional(register, 1, (measurement,))


def test_conditional_rejects_nested_conditional_in_body() -> None:
    register = ClassicalRegister("c", 1)
    inner = Conditional(register, 1, (Gate(GateType.X, (0,)),))

    with pytest.raises(ValueError):
        Conditional(register, 1, (inner,))


@pytest.mark.parametrize(
    ("factory", "field", "replacement"),
    [
        (lambda: ClassicalRegister("c", 1), "name", "d"),
        (lambda: ClassicalRegister("c", 1), "size", 2),
        (lambda: ClassicalBit(ClassicalRegister("c", 1), 0), "register", None),
        (lambda: ClassicalBit(ClassicalRegister("c", 1), 0), "index", 1),
        (lambda: Measure(0, ClassicalBit(ClassicalRegister("c", 1), 0)), "qubit", 1),
        (lambda: Measure(0, ClassicalBit(ClassicalRegister("c", 1), 0)), "target", None),
        (
            lambda: Conditional(ClassicalRegister("c", 1), 1, (Gate(GateType.X, (0,)),)),
            "register",
            None,
        ),
        (
            lambda: Conditional(ClassicalRegister("c", 1), 1, (Gate(GateType.X, (0,)),)),
            "value",
            0,
        ),
        (
            lambda: Conditional(ClassicalRegister("c", 1), 1, (Gate(GateType.X, (0,)),)),
            "body",
            (),
        ),
    ],
)
def test_classical_values_are_frozen(
    factory: Callable[[], object], field: str, replacement: object
) -> None:
    value = factory()

    with pytest.raises(FrozenInstanceError):
        setattr(value, field, replacement)


def test_add_register_preserves_order_and_rejects_duplicate_names() -> None:
    circuit = Circuit(1)
    first = ClassicalRegister("first", 1)
    second = ClassicalRegister("second", 2)

    assert circuit.add_register(first) is None
    assert circuit.add_register(second) is None
    assert circuit.cregs == [first, second]

    with pytest.raises(ValueError):
        circuit.add_register(ClassicalRegister("first", 3))


def test_add_measure_accepts_an_equal_registered_register() -> None:
    circuit = Circuit(2)
    registered = ClassicalRegister("c", 2)
    equal_register = ClassicalRegister("c", 2)
    measurement = Measure(1, ClassicalBit(equal_register, 0))
    circuit.add_register(registered)

    assert equal_register is not registered
    assert circuit.add_measure(measurement) is None
    assert circuit.gates == [measurement]


def test_add_measure_rejects_an_unregistered_register() -> None:
    circuit = Circuit(1)
    register = ClassicalRegister("c", 1)

    with pytest.raises(ValueError):
        circuit.add_measure(Measure(0, ClassicalBit(register, 0)))


def test_add_measure_rejects_qubit_outside_circuit() -> None:
    circuit = Circuit(1)
    register = ClassicalRegister("c", 1)
    circuit.add_register(register)

    with pytest.raises(ValueError):
        circuit.add_measure(Measure(1, ClassicalBit(register, 0)))


def test_single_register_condition_can_be_added_to_a_circuit() -> None:
    circuit = Circuit(1)
    register = ClassicalRegister("c", 1)
    conditional = Conditional(register, 1, (Gate(GateType.X, (0,)),))
    circuit.add_register(register)

    assert circuit.add_conditional(conditional) is None
    assert circuit.gates == [conditional]
    assert circuit == circuit


def test_add_conditional_rejects_an_unregistered_register() -> None:
    circuit = Circuit(1)
    register = ClassicalRegister("c", 1)
    conditional = Conditional(register, 1, (Gate(GateType.X, (0,)),))

    with pytest.raises(ValueError):
        circuit.add_conditional(conditional)


@pytest.mark.parametrize("qubit", [-1, 2])
def test_add_conditional_rejects_body_qubit_outside_circuit(qubit: int) -> None:
    circuit = Circuit(2)
    register = ClassicalRegister("c", 1)
    circuit.add_register(register)
    conditional = Conditional(register, 1, (Gate(GateType.X, (qubit,)),))

    with pytest.raises(ValueError):
        circuit.add_conditional(conditional)


def test_heterogeneous_operation_order_and_copy_are_structural() -> None:
    circuit = Circuit(2)
    register = ClassicalRegister("c", 1)
    gate = Gate(GateType.H, (0,))
    measurement = Measure(0, ClassicalBit(register, 0))
    conditional = Conditional(register, 1, (Gate(GateType.X, (1,)),))
    circuit.add_register(register)
    circuit.add_gate(gate)
    circuit.add_measure(measurement)
    circuit.add_conditional(conditional)

    copied = circuit.copy()
    reordered = Circuit(2)
    reordered.add_register(register)
    reordered.add_measure(measurement)
    reordered.add_gate(gate)
    reordered.add_conditional(conditional)

    assert copied == circuit
    assert copied.gates is not circuit.gates
    assert copied.cregs is not circuit.cregs
    assert all(left is right for left, right in zip(copied.gates, circuit.gates, strict=True))
    assert copied.cregs[0] is circuit.cregs[0]
    assert reordered != circuit


def test_conditional_gate_parameters_use_circuit_tolerance() -> None:
    register = ClassicalRegister("c", 1)

    def conditional_circuit(angle: float) -> Circuit:
        circuit = Circuit(1)
        circuit.add_register(register)
        circuit.add_conditional(Conditional(register, 1, (Gate(GateType.RZ, (0,), (angle,)),)))
        return circuit

    reference = conditional_circuit(math.pi)
    close = conditional_circuit(math.pi + DEFAULT_TOLERANCE / 2)
    far = conditional_circuit(math.pi + 2 * DEFAULT_TOLERANCE)

    assert reference == close
    assert close == reference
    assert reference != far


def test_conditional_register_and_value_comparison_is_strict() -> None:
    register = ClassicalRegister("c", 1)
    different_register = ClassicalRegister("d", 1)
    gate = Gate(GateType.X, (0,))

    reference = Circuit(1)
    reference.add_register(register)
    reference.add_conditional(Conditional(register, 1, (gate,)))

    different_value = Circuit(1)
    different_value.add_register(register)
    different_value.add_conditional(Conditional(register, 0, (gate,)))

    different_creg = Circuit(1)
    different_creg.add_register(different_register)
    different_creg.add_conditional(Conditional(different_register, 1, (gate,)))

    assert reference != different_value
    assert reference != different_creg


def test_string_rendering_supports_classical_operations() -> None:
    circuit = Circuit(1)
    register = ClassicalRegister("c", 1)
    measurement = Measure(0, ClassicalBit(register, 0))
    conditional = Conditional(register, 1, (Gate(GateType.X, (0,)),))
    circuit.add_register(register)
    circuit.add_measure(measurement)
    circuit.add_conditional(conditional)

    rendered = str(circuit)

    assert "Measure(qubit=0" in rendered
    assert "Conditional(register=ClassicalRegister(name='c', size=1), value=1" in rendered
