# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""OpenQASM 输入的接受契约与带类型的拒绝契约。"""

import math
import re
from dataclasses import FrozenInstanceError

import pytest

from qaiji.codec import qasm3 as qasm3_module
from qaiji.codec.qasm3 import _GATE_REGISTRY, GateSpec, from_qasm3, to_qasm3
from qaiji.core.circuit import CANONICAL_ALIASES, Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.exceptions import (
    QaijiIRError,
    Qasm3ParseError,
    Qasm3UnsupportedConstructError,
    Qasm3UnsupportedGateError,
)


def _assert_rejected(
    source: str,
    error_type: type[QaijiIRError],
    construct: str,
) -> QaijiIRError:
    with pytest.raises(error_type) as raised:
        from_qasm3(source)

    error = raised.value
    assert isinstance(error, QaijiIRError)
    assert construct.lower() in str(error).lower()
    assert re.search(r" at \d+:\d+: ", str(error))
    return error


def test_for_loop_is_rejected() -> None:
    source = "OPENQASM 3.0; qubit q; for int i in [0:3] { x q[0]; }"

    _assert_rejected(source, Qasm3UnsupportedConstructError, "for")


def test_while_loop_is_rejected() -> None:
    source = "OPENQASM 3.0; bit c; qubit q; while (c == 0) { c = 1; }"

    _assert_rejected(source, Qasm3UnsupportedConstructError, "while")


@pytest.mark.parametrize(
    ("construct", "statement"),
    [
        ("defcal", "defcal x $0 { play(drive, gaussian(1, 2, 3)); }"),
        ("cal", "cal { shift_phase(drive, pi/2); }"),
        ("defcalgrammar", 'defcalgrammar "openpulse";'),
    ],
)
def test_pulse_construct_is_rejected(construct: str, statement: str) -> None:
    _assert_rejected(
        f"OPENQASM 3.0; {statement}",
        Qasm3UnsupportedConstructError,
        construct,
    )


@pytest.mark.parametrize("construct", ["barrier", "reset"])
def test_quantum_directive_is_rejected(construct: str) -> None:
    source = f"OPENQASM 3.0; qubit q; {construct} q;"

    _assert_rejected(source, Qasm3UnsupportedConstructError, construct)


def test_else_branch_is_rejected() -> None:
    source = "OPENQASM 3.0; qubit q; bit c; if (c == 1) { x q[0]; } else { h q[0]; }"

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "if")
    assert "else branch" in str(error)


def test_non_equality_condition_is_rejected() -> None:
    source = "OPENQASM 3.0; qubit q; bit c; if (c >= 1) { x q[0]; }"

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "if")
    assert "non-equality condition" in str(error)


@pytest.mark.parametrize("size", [2, 3])
@pytest.mark.parametrize("extra", ["", "bit d;"])
def test_multi_bit_register_bit_condition_is_rejected(size, extra):
    _assert_exact_rejection(
        f"qubit q; bit[{size}] c; {extra} if (c[0] == 1) {{ x q[0]; }}",
        Qasm3UnsupportedConstructError,
        "if",
        "bit-level condition on a multi-bit register is not supported",
    )


def test_compound_condition_is_rejected() -> None:
    source = "OPENQASM 3.0; qubit q; bit c; bit d; if (c == 1 && d == 0) { x q[0]; }"

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "if")
    assert "non-equality condition" in str(error)


def test_missing_version_header_is_accepted() -> None:
    try:
        actual = from_qasm3("qubit q;")
    except QaijiIRError as exc:
        raise AssertionError("headerless program was rejected") from exc
    assert actual == from_qasm3("OPENQASM 3.0; qubit q;")


def test_unsupported_version_is_rejected() -> None:
    _assert_rejected("OPENQASM 9.9; qubit q;", Qasm3ParseError, "OPENQASM")


def test_syntax_error_is_wrapped_with_cause() -> None:
    error = _assert_rejected("OPENQASM 3.0; qubit[2 q;", Qasm3ParseError, "source")

    assert error.__cause__ is not None


@pytest.mark.parametrize(
    "name", ["gpi", "gpi2", "ms", "phasedx", "cphase", "xy", "rx90", "rx180", "cnot"]
)
def test_unregistered_gate_name_is_rejected(name):
    _assert_exact_rejection(
        f"qubit q; {name} q[0];",
        Qasm3UnsupportedGateError,
        name,
        "gate is not registered",
    )


def test_registry_removal_exercises_unregistered_gate_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(_GATE_REGISTRY, "h")
    source = 'OPENQASM 3.0; include "stdgates.inc"; qubit q; h q[0];'

    _assert_rejected(source, Qasm3UnsupportedGateError, "h")


def test_duplicate_qubit_declaration_is_rejected() -> None:
    _assert_exact_rejection(
        "OPENQASM 3.0; qubit q; qubit q;",
        Qasm3UnsupportedConstructError,
        "qubit",
        "qubit register 'q' is already declared",
        ValueError,
        (1, 24),
    )


def test_custom_include_is_rejected() -> None:
    source = 'OPENQASM 3.0; include "custom.inc"; qubit q;'

    _assert_rejected(source, Qasm3UnsupportedConstructError, "include")


def test_inverse_gate_modifier_is_rejected() -> None:
    source = 'OPENQASM 3.0; include "stdgates.inc"; qubit q; inv @ s q[0];'

    _assert_rejected(source, Qasm3UnsupportedGateError, "s")


def test_control_gate_modifier_is_rejected() -> None:
    source = 'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; ctrl @ x q[0], q[1];'

    _assert_rejected(source, Qasm3UnsupportedGateError, "x")


def test_power_gate_modifier_is_rejected() -> None:
    source = 'OPENQASM 3.0; include "stdgates.inc"; qubit q; pow(2) @ x q[0];'

    _assert_rejected(source, Qasm3UnsupportedGateError, "x")


@pytest.mark.parametrize("conditional", [False, True])
def test_gate_broadcast_size_mismatch_is_rejected(conditional):
    operation = "cx a, b;"
    if conditional:
        operation = "if (c == 1) { " + operation + " }"
    _assert_exact_rejection(
        "qubit[2] a; qubit[3] b; bit c; " + operation,
        Qasm3UnsupportedConstructError,
        "cx",
        "broadcast operands have different register sizes",
    )


@pytest.mark.parametrize("operation", ["c = measure q;", "measure q -> c;"])
def test_measurement_broadcast_size_mismatch_is_rejected(operation):
    _assert_exact_rejection(
        "qubit[2] q; bit[3] c; " + operation,
        Qasm3UnsupportedConstructError,
        "measure",
        "broadcast operands have different register sizes",
    )


def test_discarded_measurement_is_rejected() -> None:
    source = "OPENQASM 3.0; qubit q; measure q[0];"

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "measure")
    assert "target" in str(error)


def test_gate_parameter_count_error_is_wrapped_with_core_cause() -> None:
    source = 'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(0.1, 0.2) q[0];'

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "rx")
    assert isinstance(error.__cause__, ValueError)


def test_repeated_gate_qubit_error_is_wrapped_with_core_cause() -> None:
    source = 'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; cx q[0], q[0];'

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "cx")
    assert isinstance(error.__cause__, ValueError)


def test_gate_registry_is_the_complete_serializable_mapping() -> None:
    expected = {
        "id": GateSpec("id", GateType.I, 1, 0),
        "x": GateSpec("x", GateType.X, 1, 0),
        "y": GateSpec("y", GateType.Y, 1, 0),
        "z": GateSpec("z", GateType.Z, 1, 0),
        "h": GateSpec("h", GateType.H, 1, 0),
        "s": GateSpec("s", GateType.S, 1, 0),
        "t": GateSpec("t", GateType.T, 1, 0),
        "rx": GateSpec("rx", GateType.RX, 1, 1),
        "ry": GateSpec("ry", GateType.RY, 1, 1),
        "rz": GateSpec("rz", GateType.RZ, 1, 1),
        "u3": GateSpec("u3", GateType.U3, 1, 3),
        "cx": GateSpec("cx", GateType.CX, 2, 0),
        "cz": GateSpec("cz", GateType.CZ, 2, 0),
        "swap": GateSpec("swap", GateType.SWAP, 2, 0),
    }
    serializable = {spec.gate_type for spec in _GATE_REGISTRY.values()} | set(CANONICAL_ALIASES)

    assert _GATE_REGISTRY == expected
    assert len(_GATE_REGISTRY) == 14
    assert serializable == set(GateType) - {
        GateType.RX90,
        GateType.RX180,
        GateType.ISWAP,
        GateType.SQISWAP,
    }
    with pytest.raises(FrozenInstanceError):
        _GATE_REGISTRY["h"].arity = 2


@pytest.mark.parametrize(
    ("gate_type", "num_qubits", "qubits", "params"),
    [
        (GateType.RX90, 1, (0,), (0.0,)),
        (GateType.RX180, 1, (0,), (0.0,)),
        (GateType.ISWAP, 2, (0, 1), ()),
        (GateType.SQISWAP, 2, (0, 1), ()),
    ],
)
def test_gate_without_stdgates_mapping_is_rejected_on_serialization(
    gate_type: GateType,
    num_qubits: int,
    qubits: tuple[int, ...],
    params: tuple[float, ...],
) -> None:
    circuit = Circuit(num_qubits)
    circuit.add_gate(Gate(gate_type, qubits, params))

    with pytest.raises(Qasm3UnsupportedGateError) as raised:
        to_qasm3(circuit)

    assert gate_type.value in str(raised.value)


def test_unknown_circuit_operation_is_rejected_on_serialization() -> None:
    circuit = Circuit(1)
    circuit.gates.append(object())

    with pytest.raises(Qasm3UnsupportedConstructError) as raised:
        to_qasm3(circuit)

    assert "object" in str(raised.value)


@pytest.mark.parametrize(
    "source",
    [
        (
            'OPENQASM 2.0; include "qelib1.inc"; qreg q[2]; creg c[2]; '
            "h q[0]; cx q[0], q[1]; measure q[0] -> c[0]; measure q[1] -> c[1];"
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; bit[2] c; '
            "h q[0]; cx q[0], q[1]; c[0] = measure q[0]; c[1] = measure q[1];"
        ),
    ],
)
def test_supported_versions_parse_bell_circuit(source: str) -> None:
    register = ClassicalRegister("c", 2)
    expected = Circuit(2)
    expected.add_register(register)
    expected.add_gate(Gate(GateType.H, (0,)))
    expected.add_gate(Gate(GateType.CX, (0, 1)))
    expected.add_measure(Measure(0, ClassicalBit(register, 0)))
    expected.add_measure(Measure(1, ClassicalBit(register, 1)))

    assert from_qasm3(source) == expected


def test_bare_declarations_parameter_expressions_and_conditional_are_supported() -> None:
    source = (
        'OPENQASM 3.0; include "stdgates.inc"; qubit q; bit c; '
        "rx(-pi) q[0]; c[0] = measure q[0]; "
        "if (c == 1) { U3((pi + e) * 2, tau - π, τ / 2) q[0]; }"
    )

    circuit = from_qasm3(source)

    assert circuit.num_qubits == 1
    assert circuit.cregs == [ClassicalRegister("c", 1)]
    assert circuit.gates[0] == Gate(GateType.RX, (0,), (-math.pi,))
    assert circuit.gates[1] == Measure(0, ClassicalBit(circuit.cregs[0], 0))
    assert isinstance(circuit.gates[2], Conditional)
    assert circuit.gates[2].body[0].gate_type is GateType.U3
    assert circuit.gates[2].body[0].params == pytest.approx(
        ((math.pi + math.e) * 2, math.tau - math.pi, math.tau / 2)
    )


def test_division_by_zero_parameter_is_a_parse_error() -> None:
    source = 'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(1 / 0) q[0];'

    error = _assert_rejected(source, Qasm3ParseError, "parameter")
    assert isinstance(error.__cause__, ZeroDivisionError)


def test_unsupported_parameter_expression_is_rejected() -> None:
    source = 'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(pi ** 2) q[0];'

    _assert_rejected(source, Qasm3UnsupportedConstructError, "parameter")


def test_non_gate_statement_in_conditional_body_is_rejected() -> None:
    source = "OPENQASM 3.0; qubit q; bit c; if (c == 1) { c[0] = measure q[0]; }"

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "if")
    assert "non-gate statement in if body" in str(error)


def test_non_literal_conditional_rhs_is_rejected() -> None:
    source = "OPENQASM 3.0; qubit q; bit c; if (c == 1 + 0) { x q[0]; }"

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "if")
    assert "non-literal rhs" in str(error)


@pytest.mark.parametrize("index", ["0:1", "{0, 1}", "i"])
def test_non_literal_gate_index_is_rejected(index: str) -> None:
    source = f'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; h q[{index}];'

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "h")
    assert "single literal index" in str(error)


def test_multiple_gate_indices_are_rejected() -> None:
    source = 'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; h q[0][1];'

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "h")
    assert "single literal index" in str(error)


@pytest.mark.parametrize("lhs", ["c[0, 1]", "c[0][1]"])
def test_malformed_bit_level_condition_index_is_rejected(lhs: str) -> None:
    source = f"OPENQASM 3.0; qubit q; bit[2] c; if ({lhs} == 1) {{ x q[0]; }}"

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "if")
    assert "single literal index" in str(error)


def test_non_bit_classical_declaration_is_rejected() -> None:
    source = "OPENQASM 3.0; int[8] counter; qubit q;"

    _assert_rejected(source, Qasm3UnsupportedConstructError, "classical declaration")


def test_initialized_bit_declaration_is_rejected() -> None:
    source = "OPENQASM 3.0; bit c = 1; qubit q;"

    _assert_rejected(source, Qasm3UnsupportedConstructError, "classical declaration")


def test_non_literal_register_size_is_rejected() -> None:
    source = "OPENQASM 3.0; qubit[1 + 1] q;"

    _assert_rejected(source, Qasm3UnsupportedConstructError, "qubit")


def test_gate_duration_is_rejected() -> None:
    source = 'OPENQASM 3.0; include "stdgates.inc"; qubit q; x[10ns] q[0];'

    error = _assert_rejected(source, Qasm3UnsupportedGateError, "x")
    assert "duration" in str(error)


def test_gate_operand_must_name_the_declared_qubit_register() -> None:
    source = 'OPENQASM 3.0; include "stdgates.inc"; qubit q; h other[0];'

    _assert_rejected(source, Qasm3UnsupportedConstructError, "h")


def test_measurement_target_must_name_a_declared_classical_register() -> None:
    source = "OPENQASM 3.0; qubit q; bit c; other[0] = measure q[0];"

    _assert_rejected(source, Qasm3UnsupportedConstructError, "measure")


def test_program_without_qubit_declaration_is_rejected() -> None:
    source = "OPENQASM 3.0; bit c;"

    _assert_rejected(source, Qasm3UnsupportedConstructError, "qubit declaration")


def test_operation_before_qubit_declaration_is_rejected() -> None:
    source = "OPENQASM 3.0; h q[0]; qubit q;"

    _assert_rejected(source, Qasm3UnsupportedConstructError, "h")


def test_duplicate_classical_declaration_is_wrapped() -> None:
    source = "OPENQASM 3.0; bit c; bit c; qubit q;"

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "classical declaration")
    assert isinstance(error.__cause__, ValueError)


def test_statement_annotation_is_rejected() -> None:
    source = "OPENQASM 3.0;\n@hardware_hint\nqubit q;"

    error = _assert_rejected(source, Qasm3UnsupportedConstructError, "qubit")
    assert "annotation" in str(error)


@pytest.mark.parametrize("expression", ["unknown", "~1", "10ns"])
def test_other_unsupported_parameter_forms_are_rejected(expression: str) -> None:
    source = f'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx({expression}) q[0];'

    _assert_rejected(source, Qasm3UnsupportedConstructError, "parameter")


def test_parameter_evaluator_accepts_unary_plus_ast_shape() -> None:
    class UnaryPlus:
        name = "+"

    expression = qasm3_module.ast.UnaryExpression(
        op=UnaryPlus(),
        expression=qasm3_module.ast.IntegerLiteral(2),
    )

    assert qasm3_module._evaluate_parameter(expression) == 2.0


def test_non_register_conditional_lhs_is_rejected() -> None:
    source = "OPENQASM 3.0; qubit q; if (1 == 1) { x q[0]; }"

    _assert_rejected(source, Qasm3UnsupportedConstructError, "if")


def test_undeclared_conditional_register_is_rejected() -> None:
    source = "OPENQASM 3.0; qubit q; if (c == 1) { x q[0]; }"

    _assert_rejected(source, Qasm3UnsupportedConstructError, "if")


def test_non_numeric_parser_version_is_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidVersionProgram:
        span = None
        statements: tuple[object, ...] = ()
        version = "not-a-version"

    monkeypatch.setattr(
        qasm3_module.openqasm3,
        "parse",
        lambda source: InvalidVersionProgram(),
    )

    error = _assert_rejected("ignored", Qasm3ParseError, "OPENQASM")
    assert isinstance(error.__cause__, ValueError)


@pytest.mark.parametrize(
    ("source", "construct"),
    [
        ("OPENQASM 3.0; qubit[0] q;", "qubit"),
        ("OPENQASM 3.0; qubit q; bit[0] c;", "classical declaration"),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; h q[1];',
            "h",
        ),
        ("OPENQASM 3.0; qubit q; bit c; c[1] = measure q[0];", "measure"),
        ("OPENQASM 3.0; qubit q; bit c; c[0] = measure q[1];", "measure"),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; bit c; if (c == 1) { x q[1]; }',
            "if",
        ),
    ],
)
def test_core_invariant_errors_are_wrapped(source: str, construct: str) -> None:
    error = _assert_rejected(source, Qasm3UnsupportedConstructError, construct)

    assert isinstance(error.__cause__, ValueError)


def _assert_exact_rejection(source, error_type, construct, detail, cause_type=None, location=None):
    with pytest.raises(QaijiIRError) as raised:
        from_qasm3(source)
    error = raised.value
    assert type(error) is error_type, "rejection type changed"
    match = re.fullmatch(rf"{re.escape(construct)} at (\d+):(\d+): (.+)", str(error))
    assert match is not None, "rejection construct or location changed"
    assert match[3] == detail, "rejection detail changed"
    assert type(error.__cause__) is cause_type if cause_type else error.__cause__ is None, (
        "rejection cause changed"
    )
    if location is not None:
        assert (int(match[1]), int(match[2])) == location, "rejection location changed"
    return error


@pytest.mark.parametrize("version", ["1.0", "4.0"])
def test_major_version_outside_two_and_three_is_rejected(version):
    _assert_exact_rejection(
        f"OPENQASM {version}; qubit q;",
        Qasm3ParseError,
        "OPENQASM",
        f"unsupported version {version!r}",
    )


@pytest.mark.parametrize(
    ("source", "construct", "detail"),
    [
        (
            "OPENQASM 2.0; qreg a[1]; qreg b[2]; x a[1];",
            "x",
            "index 1 is outside qubit register 'a' of size 1",
        ),
        (
            "OPENQASM 3.0; qubit[1] a; qubit[2] b; cx a[1], b[0];",
            "cx",
            "index 1 is outside qubit register 'a' of size 1",
        ),
        (
            "OPENQASM 3.0; qubit[1] a; qubit[2] b; bit c; c[0] = measure a[1];",
            "measure",
            "index 1 is outside qubit register 'a' of size 1",
        ),
        (
            "OPENQASM 2.0; qreg a[1]; qreg b[2]; creg c[1]; measure a[1] -> c[0];",
            "measure",
            "index 1 is outside qubit register 'a' of size 1",
        ),
        (
            "OPENQASM 3.0; qubit[1] a; qubit[2] b; bit c; if (c == 1) { x a[1]; }",
            "if",
            "index 1 is outside qubit register 'a' of size 1",
        ),
        (
            "OPENQASM 3.0; qubit[1] a; qubit[2] b; bit c; if (c == 1) { cx a[1], b[0]; }",
            "if",
            "index 1 is outside qubit register 'a' of size 1",
        ),
        (
            "OPENQASM 3.0; qubit[2] a; qubit[1] b; bit c; if (c == 1) { x a[2]; x b[1]; }",
            "if",
            "index 2 is outside qubit register 'a' of size 2",
        ),
        ("OPENQASM 3.0; qubit q; x q[1];", "x", "index 1 is outside qubit register 'q' of size 1"),
    ],
    ids=[
        "gate-cross",
        "gate-alias",
        "measure-cross",
        "measure-arrow",
        "if-cross",
        "if-alias",
        "if-first",
        "single-register",
    ],
)
def test_gate_index_outside_its_register_is_rejected(source, construct, detail):
    _assert_exact_rejection(source, Qasm3UnsupportedConstructError, construct, detail, ValueError)


@pytest.mark.parametrize(
    "source",
    [
        "OPENQASM 3.0; qubit[2] a; qubit[0] b;",
        "OPENQASM 3.0; qubit[0] a; qubit[2] b;",
        "OPENQASM 3.0; qubit a; qubit[0] b;",
    ],
)
def test_zero_size_register_among_others_is_rejected(source):
    _assert_exact_rejection(
        source,
        Qasm3UnsupportedConstructError,
        "qubit",
        "Circuit must have at least one qubit",
        ValueError,
    )


@pytest.mark.parametrize(
    ("operation", "construct"),
    [
        ("x b[0];", "x"),
        ("c[0] = measure b[0];", "measure"),
        ("if (c == 1) { x b[0]; }", "x"),
    ],
)
def test_register_used_before_declaration_is_rejected(operation, construct):
    _assert_exact_rejection(
        "OPENQASM 3.0; qubit a; bit c; " + operation + " qubit b;",
        Qasm3UnsupportedConstructError,
        construct,
        "qubit register 'b' is not declared",
    )


@pytest.mark.parametrize(
    ("source", "error_type", "construct", "detail", "cause_type", "location"),
    [
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit a; x a[1]; qubit[0] z;',
            "Qasm3UnsupportedConstructError",
            "x",
            "index 1 is outside qubit register 'a' of size 1",
            "ValueError",
            (1, 48),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; h q[5]; qubit q;',
            "Qasm3UnsupportedConstructError",
            "h",
            "index 5 is outside qubit register 'q' of size 1",
            "ValueError",
            (1, 48),
        ),
        (
            'OPENQASM 3.0; include "custom.inc"; qubit q; qubit q;',
            "Qasm3UnsupportedConstructError",
            "include",
            "'custom.inc' is not supported",
            None,
            (1, 15),
        ),
        (
            "OPENQASM 3.0; int[8] n; qubit[1 + 1] q;",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "only bit declarations are supported",
            None,
            (1, 15),
        ),
        (
            "OPENQASM 3.0; const int n = 2; qubit[n] q;",
            "Qasm3UnsupportedConstructError",
            "ConstantDeclaration",
            "construct is not supported",
            None,
            (1, 15),
        ),
        (
            "OPENQASM 3.0; qubit q; barrier q; qubit[1 + 1] r;",
            "Qasm3UnsupportedConstructError",
            "barrier",
            "construct is not supported",
            None,
            (1, 24),
        ),
        (
            "OPENQASM 3.0; qubit q; for int i in [0:1] { } qubit q;",
            "Qasm3UnsupportedConstructError",
            "for",
            "construct is not supported",
            None,
            (1, 24),
        ),
        (
            "OPENQASM 3.0; qubit q;\n@a\nqubit q;",
            "Qasm3UnsupportedConstructError",
            "qubit",
            "annotations are not supported",
            None,
            (2, 1),
        ),
        (
            "OPENQASM 3.0; defcal x $0 { play(drive, gaussian(1, 2, 3)); }",
            "Qasm3UnsupportedConstructError",
            "defcal",
            "construct is not supported",
            None,
            (1, 15),
        ),
        (
            "OPENQASM 3.0; cal { shift_phase(drive, pi/2); }",
            "Qasm3UnsupportedConstructError",
            "cal",
            "construct is not supported",
            None,
            (1, 15),
        ),
        (
            'OPENQASM 3.0; defcalgrammar "openpulse";',
            "Qasm3UnsupportedConstructError",
            "defcalgrammar",
            "construct is not supported",
            None,
            (1, 15),
        ),
        (
            'OPENQASM 3.0; include "custom.inc";',
            "Qasm3UnsupportedConstructError",
            "include",
            "'custom.inc' is not supported",
            None,
            (1, 15),
        ),
        (
            "OPENQASM 3.0; int[8] counter;",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "only bit declarations are supported",
            None,
            (1, 15),
        ),
        (
            "OPENQASM 3.0; h q[0];",
            "Qasm3UnsupportedConstructError",
            "h",
            "a qubit declaration must precede operations",
            None,
            (1, 15),
        ),
        (
            "OPENQASM 3.0; qubit[0] q; h q[0];",
            "Qasm3UnsupportedConstructError",
            "qubit",
            "Circuit must have at least one qubit",
            "ValueError",
            (1, 15),
        ),
        (
            "OPENQASM 3.0; barrier q;",
            "Qasm3UnsupportedConstructError",
            "barrier",
            "construct is not supported",
            None,
            (1, 15),
        ),
        (
            "OPENQASM 3.0;\n@a\nbit c;",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "annotations are not supported",
            None,
            (2, 1),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; cx q[0:1];',
            "Qasm3UnsupportedConstructError",
            "cx",
            "operand requires a single literal index",
            None,
            (1, 54),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; h(0.1) q[0:1];',
            "Qasm3UnsupportedConstructError",
            "h",
            "operand requires a single literal index",
            None,
            (1, 58),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; cx other[0];',
            "Qasm3UnsupportedConstructError",
            "cx",
            "qubit register 'other' is not declared",
            None,
            (1, 48),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(theta) other[0];',
            "Qasm3UnsupportedConstructError",
            "rx",
            "qubit register 'other' is not declared",
            None,
            (1, 48),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; cx q[5];',
            "Qasm3UnsupportedConstructError",
            "cx",
            "Gate cx requires 2 qubit operands",
            "ValueError",
            (1, 48),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx q[5];',
            "Qasm3UnsupportedConstructError",
            "rx",
            "Gate rx requires 1 parameters",
            "ValueError",
            (1, 48),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(1/0) q[5];',
            "Qasm3ParseError",
            "parameter",
            "division by zero",
            "ZeroDivisionError",
            (1, 51),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; cx q[1], q[1];',
            "Qasm3UnsupportedConstructError",
            "cx",
            "Gate qubits must be unique",
            "ValueError",
            (1, 51),
        ),
        (
            "OPENQASM 3.0; qubit q; bit c; c[5] = measure q[5];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "Classical bit index 5 is outside register 'c' of size 1",
            "ValueError",
            (1, 31),
        ),
        (
            "OPENQASM 3.0; qubit q; other[0] = measure q[5];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "target register 'other' is not declared",
            None,
            (1, 24),
        ),
        (
            "OPENQASM 3.0; qubit q; other[0] = measure r[0];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "qubit register 'r' is not declared",
            None,
            (1, 24),
        ),
        (
            "OPENQASM 3.0; qubit q; bit[2] c; if (c[0, 1] == 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "operand requires a single literal index",
            None,
            (1, 38),
        ),
        (
            "OPENQASM 3.0; qubit q; bit[2] c; if (c[0] == 1) { x q[5]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "bit-level condition on a multi-bit register is not supported",
            None,
            (1, 34),
        ),
        (
            "OPENQASM 3.0; qubit q; bit c; if (c >= 1) { c[0] = measure q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "non-gate statement in if body",
            None,
            (1, 31),
        ),
        (
            "OPENQASM 3.0; qubit q; bit c; if (c[1] == 2) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "Classical bit index 1 is outside register 'c' of size 1",
            "ValueError",
            (1, 31),
        ),
        (
            "OPENQASM 3.0; qubit q; bit c; if (c == 1) { gpi(0.1) q[0]; x q[5]; }",
            "Qasm3UnsupportedGateError",
            "gpi",
            "gate is not registered",
            None,
            (1, 45),
        ),
        (
            "OPENQASM 3.0; qubit q; bit c; if (c == 1) { x q[5]; gpi(0.1) q[0]; }",
            "Qasm3UnsupportedGateError",
            "gpi",
            "gate is not registered",
            None,
            (1, 53),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; cx q[5], q[5];',
            "Qasm3UnsupportedConstructError",
            "cx",
            "Gate qubits must be unique",
            "ValueError",
            (1, 51),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(1e400) q[3];',
            "Qasm3UnsupportedConstructError",
            "rx",
            "Gate parameters must be finite",
            "ValueError",
            (1, 48),
        ),
        (
            "OPENQASM 3.0; qubit q; bit c; c[5] = measure q[5];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "Classical bit index 5 is outside register 'c' of size 1",
            "ValueError",
            (1, 31),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; bit c; if (c == 1) { x q[5]; cx q[0], q[0]; }',
            "Qasm3UnsupportedConstructError",
            "cx",
            "Gate qubits must be unique",
            "ValueError",
            (1, 80),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; h q[0:1]; qubit[2] q;',
            "Qasm3UnsupportedConstructError",
            "h",
            "a qubit declaration must precede operations",
            None,
            (1, 39),
        ),
        (
            "OPENQASM 3.0; bit[2] c; c[0] = measure q[0:1]; qubit[2] q;",
            "Qasm3UnsupportedConstructError",
            "measure",
            "a qubit declaration must precede operations",
            None,
            (1, 25),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; bit c; if (c == 1) { cx q[5], q[5]; }',
            "Qasm3UnsupportedConstructError",
            "cx",
            "Gate qubits must be unique",
            "ValueError",
            (1, 72),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit[1] q; x q[2]; qubit[3] q;',
            "Qasm3UnsupportedConstructError",
            "x",
            "index 2 is outside qubit register 'q' of size 1",
            "ValueError",
            (1, 51),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; if (d == 1) { x q[0]; }',
            "Qasm3UnsupportedConstructError",
            "if",
            "condition register 'd' is not declared",
            None,
            (1, 39),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; cx other[0], q[0:1];',
            "Qasm3UnsupportedConstructError",
            "cx",
            "operand requires a single literal index",
            None,
            (1, 61),
        ),
        (
            "OPENQASM 3.0; qubit q; bit c; other[0] = measure r[0:1];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "operand requires a single literal index",
            None,
            (1, 50),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q;\n@a\ninv @ s q[0];',
            "Qasm3UnsupportedConstructError",
            "s",
            "annotations are not supported",
            None,
            (2, 1),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; inv @ x[10ns] q[0];',
            "Qasm3UnsupportedGateError",
            "x",
            "gate modifiers are not supported",
            None,
            (1, 48),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; foo[10ns] q[0];',
            "Qasm3UnsupportedGateError",
            "foo",
            "gate duration is not supported",
            None,
            (1, 48),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; foo q[0];',
            "Qasm3UnsupportedGateError",
            "foo",
            "gate is not registered",
            None,
            (1, 39),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; rx(theta) q[0], q[1];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unknown constant 'theta'",
            None,
            (1, 54),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; rx(1e400) q[0], q[1];',
            "Qasm3UnsupportedConstructError",
            "rx",
            "Gate rx requires 1 qubit operands",
            "ValueError",
            (1, 51),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; h other[0:1];',
            "Qasm3UnsupportedConstructError",
            "h",
            "operand requires a single literal index",
            None,
            (1, 50),
        ),
        (
            "OPENQASM 3.0; qubit q;\n@a\nmeasure q[0];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "annotations are not supported",
            None,
            (2, 1),
        ),
        (
            "OPENQASM 3.0; measure q[0];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "measurement target is required",
            None,
            (1, 15),
        ),
        (
            "OPENQASM 3.0; qubit[2] q; bit[2] c; c[0:1] = measure q[0:1];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "operand requires a single literal index",
            None,
            (1, 54),
        ),
        (
            "OPENQASM 3.0; qubit q; bit[2] c; c[0:1] = measure r[0];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "operand requires a single literal index",
            None,
            (1, 34),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; bit c;\n@a\nif (c == 1) { x q[0]; } else { x q[0]; }',
            "Qasm3UnsupportedConstructError",
            "if",
            "annotations are not supported",
            None,
            (2, 1),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; bit c; if (c == 1) { c[0] = measure q[0]; } else { x q[0]; }',
            "Qasm3UnsupportedConstructError",
            "if",
            "else branch is not supported",
            None,
            (1, 55),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; bit c; if (c >= 1 + 0) { x q[0]; }',
            "Qasm3UnsupportedConstructError",
            "if",
            "non-equality condition",
            None,
            (1, 55),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; bit[2] c; if (c[0, 1] == 1 + 0) { x q[0]; }',
            "Qasm3UnsupportedConstructError",
            "if",
            "non-literal rhs",
            None,
            (1, 58),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; bit c; if (c == 1) { foo q[0]; }',
            "Qasm3UnsupportedConstructError",
            "if",
            "a qubit declaration must precede operations",
            None,
            (1, 46),
        ),
        (
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; bit c; if (c == 1) { x q[1]; }',
            "Qasm3UnsupportedConstructError",
            "if",
            "index 1 is outside qubit register 'q' of size 1",
            "ValueError",
            (1, 55),
        ),
        (
            "qubit[2] q; crx(1e400) q[0], q[0];",
            "Qasm3UnsupportedConstructError",
            "crx",
            "Gate parameters must be finite",
            "ValueError",
            (1, 13),
        ),
        (
            "qubit[2] a; qubit[3] b; bit c; if (c == 1) { x a[4]; cx a, b; }",
            "Qasm3UnsupportedConstructError",
            "cx",
            "broadcast operands have different register sizes",
            None,
            (1, 54),
        ),
    ],
    ids=[
        "precedence-01",
        "precedence-02",
        "precedence-03",
        "precedence-04",
        "precedence-05",
        "precedence-06",
        "precedence-07",
        "precedence-08",
        "precedence-09",
        "precedence-10",
        "precedence-11",
        "precedence-12",
        "precedence-13",
        "precedence-14",
        "precedence-15",
        "precedence-16",
        "precedence-17",
        "shape-before-arity",
        "shape-before-parameter-count",
        "declaration-before-arity",
        "declaration-before-parameter",
        "precedence-22",
        "precedence-23",
        "precedence-24",
        "precedence-25",
        "precedence-26",
        "precedence-27",
        "precedence-28",
        "precedence-29",
        "precedence-30",
        "precedence-31",
        "precedence-32",
        "precedence-33",
        "precedence-34",
        "duplicate-before-bounds",
        "finite-before-bounds",
        "target-before-source-bounds",
        "precedence-38",
        "gate-declaration-before-shape",
        "measure-declaration-before-shape",
        "precedence-41",
        "later-larger-duplicate",
        "precedence-43",
        "precedence-44",
        "precedence-45",
        "precedence-46",
        "precedence-47",
        "precedence-48",
        "precedence-49",
        "precedence-50",
        "precedence-51",
        "precedence-52",
        "precedence-53",
        "precedence-54",
        "measure-source-shape-before-target",
        "precedence-56",
        "precedence-57",
        "precedence-58",
        "precedence-59",
        "precedence-60",
        "precedence-61",
        "precedence-62",
        "finite-before-duplicate-expansion",
        "if-deferred-bounds-before-later-mismatch",
    ],
)
def test_statement_error_precedence_matches_slice_a(
    source, error_type, construct, detail, cause_type, location
):
    error_type = {
        "Qasm3UnsupportedConstructError": Qasm3UnsupportedConstructError,
        "Qasm3UnsupportedGateError": Qasm3UnsupportedGateError,
        "Qasm3ParseError": Qasm3ParseError,
    }[error_type]
    cause_type = {"ValueError": ValueError, "ZeroDivisionError": ZeroDivisionError, None: None}[
        cause_type
    ]
    _assert_exact_rejection(source, error_type, construct, detail, cause_type, location)


@pytest.mark.parametrize(
    ("source", "detail"),
    [
        ("OPENQASM 3.0; qubit q; qubit[0] q;", "Circuit must have at least one qubit"),
        ("OPENQASM 3.0; qubit q; qubit[1 + 1] q;", "register size must be an integer literal"),
        ("OPENQASM 3.0; qubit q;\n@a\nqubit[0] q;", "annotations are not supported"),
    ],
)
def test_declaration_errors_are_reported_in_source_order(source, detail):
    _assert_exact_rejection(
        source,
        Qasm3UnsupportedConstructError,
        "qubit",
        detail,
        ValueError if "at least" in detail else None,
    )


@pytest.mark.parametrize(
    ("source", "error_type", "construct", "detail", "cause_type"),
    [
        (
            "OPENQASM 3.0; for int i in [0:3] { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "for",
            "construct is not supported",
            None,
        ),
        (
            "OPENQASM 3.0; while (c == 0) { c = 1; }",
            "Qasm3UnsupportedConstructError",
            "while",
            "construct is not supported",
            None,
        ),
        (
            "OPENQASM 3.0; defcal x $0 { play(drive, gaussian(1, 2, 3)); }",
            "Qasm3UnsupportedConstructError",
            "defcal",
            "construct is not supported",
            None,
        ),
        (
            "OPENQASM 3.0; cal { shift_phase(drive, pi/2); }",
            "Qasm3UnsupportedConstructError",
            "cal",
            "construct is not supported",
            None,
        ),
        (
            'OPENQASM 3.0; defcalgrammar "openpulse";',
            "Qasm3UnsupportedConstructError",
            "defcalgrammar",
            "construct is not supported",
            None,
        ),
        (
            "OPENQASM 3.0; barrier q;",
            "Qasm3UnsupportedConstructError",
            "barrier",
            "construct is not supported",
            None,
        ),
        (
            "OPENQASM 3.0; reset q;",
            "Qasm3UnsupportedConstructError",
            "reset",
            "construct is not supported",
            None,
        ),
        (
            "OPENQASM 3.0; qubit[0] q;",
            "Qasm3UnsupportedConstructError",
            "qubit",
            "Circuit must have at least one qubit",
            "ValueError",
        ),
        (
            "OPENQASM 3.0; qubit q; bit c; if (c == 1) { x q[1]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "index 1 is outside qubit register 'q' of size 1",
            "ValueError",
        ),
        (
            "OPENQASM 3.0; qubit q; bit c; if (c == 1) { cx q[0]; }",
            "Qasm3UnsupportedConstructError",
            "cx",
            "Gate cx requires 2 qubit operands",
            "ValueError",
        ),
        (
            "OPENQASM 3.0; qubit q; bit c; if (c == 1) { foo q[0]; }",
            "Qasm3UnsupportedGateError",
            "foo",
            "gate is not registered",
            None,
        ),
        (
            "qubit[2] a; qubit[3] b; bit c; if (c == 1) { cx a, b; }",
            "Qasm3UnsupportedConstructError",
            "cx",
            "broadcast operands have different register sizes",
            None,
        ),
        (
            "qubit[2] q; bit c; if (c == 1) { cy q[0]; }",
            "Qasm3UnsupportedConstructError",
            "cy",
            "Gate cy requires 2 qubit operands",
            "ValueError",
        ),
    ],
)
def test_rejection_construct_tokens_are_exact(source, error_type, construct, detail, cause_type):
    error_type = {
        "Qasm3UnsupportedConstructError": Qasm3UnsupportedConstructError,
        "Qasm3UnsupportedGateError": Qasm3UnsupportedGateError,
        "Qasm3ParseError": Qasm3ParseError,
    }[error_type]
    cause_type = {"ValueError": ValueError, "ZeroDivisionError": ZeroDivisionError, None: None}[
        cause_type
    ]
    _assert_exact_rejection(source, error_type, construct, detail, cause_type)


@pytest.mark.parametrize(
    ("source", "construct", "kind"),
    [
        ("OPENQASM 3.0;\nqubit q;\nbit q;", "classical declaration", "qubit"),
        ("OPENQASM 3.0;\nbit q;\nqubit q;", "qubit", "classical"),
        ("OPENQASM 2.0;\nqreg q[1];\ncreg q[1];", "classical declaration", "qubit"),
        ("OPENQASM 2.0;\ncreg q[1];\nqreg q[1];", "qubit", "classical"),
    ],
    ids=["qubit-first", "classical-first", "qreg-first", "creg-first"],
)
def test_quantum_and_classical_register_names_must_differ(source, construct, kind):
    _assert_exact_rejection(
        source,
        Qasm3UnsupportedConstructError,
        construct,
        f"name 'q' is already declared as a {kind} register",
        ValueError,
        (3, 1),
    )


@pytest.mark.parametrize("operands", ["a, b", "b, a"])
def test_size_one_register_is_not_a_single_qubit_operand(operands):
    _assert_exact_rejection(
        "qubit[1] a; qubit[2] b; cx " + operands + ";",
        Qasm3UnsupportedConstructError,
        "cx",
        "broadcast operands have different register sizes",
    )


@pytest.mark.parametrize("operands", ["q, q", "q, q[0]", "q[1], q"])
def test_broadcast_duplicate_qubit_is_wrapped(operands):
    _assert_exact_rejection(
        "qubit[2] q; cx " + operands + ";",
        Qasm3UnsupportedConstructError,
        "cx",
        "Gate qubits must be unique",
        ValueError,
    )


@pytest.mark.parametrize("size", [1, 2])
@pytest.mark.parametrize(
    "operation",
    ["c[0] = measure q;", "c = measure q[0];", "measure q -> c[0];", "measure q[0] -> c;"],
)
def test_mixed_measurement_forms_follow_length_rule(size, operation):
    source = f"qubit[{size}] q; bit[{size}] c; " + operation
    if size != 1:
        _assert_exact_rejection(
            source,
            Qasm3UnsupportedConstructError,
            "measure",
            "broadcast operands have different register sizes",
        )
    else:
        c = ClassicalRegister("c", 1)
        expected = Circuit(1)
        expected.add_register(c)
        expected.add_measure(Measure(0, ClassicalBit(c, 0)))
        try:
            actual = from_qasm3(source)
        except QaijiIRError as exc:
            raise AssertionError("length-one mixed measurement was rejected") from exc
        assert actual == expected, "mixed measurement changed"


@pytest.mark.parametrize(
    ("operation", "name", "detail"),
    [
        ("cy q[0];", "cy", "Gate cy requires 2 qubit operands"),
        ("ccx q[0], q[1];", "ccx", "Gate ccx requires 3 qubit operands"),
        ("sx q[0], q[1];", "sx", "Gate sx requires 1 qubit operands"),
        ("cp q[0], q[1];", "cp", "Gate cp requires 1 parameters"),
        ("cu3(0.2, 0.4) q[0], q[1];", "cu3", "Gate cu3 requires 3 parameters"),
        ("sx(0.2) q[0];", "sx", "Gate sx requires 0 parameters"),
        ("crx(1e400) q[0], q[0];", "crx", "Gate parameters must be finite"),
    ],
    ids=[
        "cy-arity",
        "ccx-arity",
        "sx-arity",
        "cp-params",
        "cu3-params",
        "sx-params",
        "finite-before-duplicate",
    ],
)
@pytest.mark.parametrize("conditional", [False, True])
def test_expansion_arity_and_parameter_errors_are_wrapped(operation, name, detail, conditional):
    if conditional:
        operation = "if (c == 1) { " + operation + " }"
    _assert_exact_rejection(
        "qubit[3] q; bit c; " + operation,
        Qasm3UnsupportedConstructError,
        name,
        detail,
        ValueError,
    )


@pytest.mark.parametrize("value", [2, 3, 100])
def test_bit_condition_value_must_be_zero_or_one(value):
    _assert_exact_rejection(
        f"qubit q; bit c; if (c[0] == {value}) {{ x q[0]; }}",
        Qasm3UnsupportedConstructError,
        "if",
        "bit condition value must be 0 or 1",
    )


@pytest.mark.parametrize("index", [1, 2])
def test_bit_condition_index_outside_register_is_rejected(index):
    _assert_exact_rejection(
        f"qubit q; bit c; if (c[{index}] == 1) {{ x q[0]; }}",
        Qasm3UnsupportedConstructError,
        "if",
        f"Classical bit index {index} is outside register 'c' of size 1",
        ValueError,
    )


def test_bit_condition_on_undeclared_register_is_rejected():
    _assert_exact_rejection(
        "qubit q; bit c; if (d[0] == 1) { x q[0]; }",
        Qasm3UnsupportedConstructError,
        "if",
        "condition register 'd' is not declared",
    )


@pytest.mark.parametrize(
    ("declarations", "condition", "detail", "cause"),
    [
        ("", "d[0:1] == 1", "operand requires a single literal index", None),
        (
            "bit[2] c;",
            "c[2] == 1",
            "bit-level condition on a multi-bit register is not supported",
            None,
        ),
        (
            "bit c;",
            "c[1] == 2",
            "Classical bit index 1 is outside register 'c' of size 1",
            "ValueError",
        ),
    ],
    ids=["shape-before-declaration", "width-before-range", "range-before-value"],
)
def test_bit_condition_check_order_is_contractual(declarations, condition, detail, cause):
    cause = {None: None, "ValueError": ValueError}[cause]
    _assert_exact_rejection(
        f"qubit q; {declarations} if ({condition}) {{ x q[0]; }}",
        Qasm3UnsupportedConstructError,
        "if",
        detail,
        cause,
    )


@pytest.fixture
def bounded_recursion_limit():
    import sys

    original = sys.getrecursionlimit()
    frame = sys._getframe()
    depth = 0
    while frame is not None:
        depth += 1
        frame = frame.f_back
    sys.setrecursionlimit(depth + 200)
    try:
        yield
    finally:
        sys.setrecursionlimit(original)


def test_parser_recursion_limit_is_a_parse_error(bounded_recursion_limit):
    source = "qubit q; rx(" + "(" * 400 + "1" + ")" * 400 + ") q[0];"
    _assert_exact_rejection(
        source,
        Qasm3ParseError,
        "source",
        "expression nesting exceeds parser limit",
        RecursionError,
        (1, 1),
    )
    expected = Circuit(1)
    expected.add_gate(Gate(GateType.RX, (0,), (1.0,)))
    assert from_qasm3("qubit q; rx(1) q[0];") == expected


def test_evaluator_recursion_limit_is_a_parse_error(monkeypatch, bounded_recursion_limit):
    ast = qasm3_module.ast
    source = "qubit q; rx(1) q[0];"
    program = qasm3_module.openqasm3.parse(source)
    expression = ast.IntegerLiteral(1)
    for _ in range(400):
        expression = ast.UnaryExpression(ast.UnaryOperator["-"], expression)
    program.statements[-1].arguments[0] = expression
    monkeypatch.setattr(qasm3_module.openqasm3, "parse", lambda _: program)
    _assert_exact_rejection(
        source,
        Qasm3ParseError,
        "source",
        "expression nesting exceeds parser limit",
        RecursionError,
        (1, 1),
    )
    program.statements[-1].arguments[0] = ast.IntegerLiteral(1)
    expected = Circuit(1)
    expected.add_gate(Gate(GateType.RX, (0,), (1.0,)))
    assert from_qasm3(source) == expected


@pytest.mark.parametrize(
    "source",
    ["", " ", "\n", "// c", "/* c */", " // c\n /* c */ \t", "OPENQASM 3.0;"],
    ids=["empty", "space", "newline", "line-comment", "block-comment", "mixed", "header"],
)
def test_empty_or_comment_only_source_has_no_qubit_declaration(source):
    _assert_exact_rejection(
        source,
        Qasm3UnsupportedConstructError,
        "qubit declaration",
        "program has no qubit declaration",
        location=(1, 1),
    )


def test_unexpected_parser_attribute_error_is_a_parse_error(monkeypatch):
    error = AttributeError("injected parser failure")

    def fail_parse(source):
        raise error

    monkeypatch.setattr(qasm3_module.openqasm3, "parse", fail_parse)
    actual = _assert_exact_rejection(
        "qubit q;",
        Qasm3ParseError,
        "source",
        "invalid OpenQASM syntax",
        AttributeError,
        (1, 1),
    )
    assert actual.__cause__ is error, "parser error cause identity changed"


@pytest.mark.parametrize("error_type", ["AttributeError", "RuntimeError"])
def test_attribute_error_during_traversal_is_not_a_syntax_error(monkeypatch, error_type):
    error_type = {"AttributeError": AttributeError, "RuntimeError": RuntimeError}[error_type]
    error = error_type("injected traversal failure")

    def fail_handler(statement, state):
        raise error

    monkeypatch.setattr(qasm3_module, "_handle_gate", fail_handler)
    with pytest.raises(Exception) as raised:
        from_qasm3("qubit q; x q[0];")
    assert type(raised.value) is error_type, "traversal error type changed"
    assert raised.value is error, "traversal error identity changed"


@pytest.mark.parametrize(
    ("case_id", "source", "error_name", "construct", "detail", "cause_name"),
    [
        (
            "NS-001",
            "OPENQASM 3.0; qubit[2 q;",
            "Qasm3ParseError",
            "source",
            "invalid OpenQASM syntax",
            "QASM3ParsingError",
        ),
        (
            "NS-002",
            "OPENQASM 3.0; qubit q; h q[0]",
            "Qasm3ParseError",
            "source",
            "invalid OpenQASM syntax",
            "QASM3ParsingError",
        ),
        (
            "NS-003",
            'OPENQASM 3.0; include "stdgates.inc',
            "Qasm3ParseError",
            "source",
            "invalid OpenQASM syntax",
            "QASM3ParsingError",
        ),
        (
            "NS-004",
            "OPENQASM 3.0; qubit q\x00;",
            "Qasm3ParseError",
            "source",
            "invalid OpenQASM syntax",
            "QASM3ParsingError",
        ),
        (
            "NS-005",
            "",
            "Qasm3UnsupportedConstructError",
            "qubit declaration",
            "program has no qubit declaration",
            None,
        ),
        (
            "NS-006",
            "// comment only",
            "Qasm3UnsupportedConstructError",
            "qubit declaration",
            "program has no qubit declaration",
            None,
        ),
        (
            "NS-007",
            "  \n  ",
            "Qasm3UnsupportedConstructError",
            "qubit declaration",
            "program has no qubit declaration",
            None,
        ),
        (
            "NS-015",
            "OPENQASM 1.0; qubit q;",
            "Qasm3ParseError",
            "OPENQASM",
            "unsupported version '1.0'",
            None,
        ),
        (
            "NS-016",
            "OPENQASM 4.0; qubit q;",
            "Qasm3ParseError",
            "OPENQASM",
            "unsupported version '4.0'",
            None,
        ),
        (
            "NS-017",
            "OPENQASM 9.9; qubit q;",
            "Qasm3ParseError",
            "OPENQASM",
            "unsupported version '9.9'",
            None,
        ),
        (
            "NS-018",
            "OPENQASM 3.0.1; qubit q;",
            "Qasm3ParseError",
            "source",
            "invalid OpenQASM syntax",
            "QASM3ParsingError",
        ),
        (
            "NS-019",
            "OPENQASM three; qubit q;",
            "Qasm3ParseError",
            "source",
            "invalid OpenQASM syntax",
            "QASM3ParsingError",
        ),
        (
            "NS-020",
            "qubit q; OPENQASM 3.0;",
            "Qasm3ParseError",
            "source",
            "invalid OpenQASM syntax",
            "QASM3ParsingError",
        ),
        (
            "NS-021",
            "<patched parse: version='not-a-version'>",
            "Qasm3ParseError",
            "OPENQASM",
            "invalid version 'not-a-version'",
            "ValueError",
        ),
        (
            "NS-025",
            'OPENQASM 3.0; include "custom.inc"; qubit q;',
            "Qasm3UnsupportedConstructError",
            "include",
            "'custom.inc' is not supported",
            None,
        ),
        (
            "NS-030",
            'OPENQASM 3.0; @a include "stdgates.inc"; qubit q;',
            "Qasm3ParseError",
            "source",
            "invalid OpenQASM syntax",
            "QASM3ParsingError",
        ),
        (
            "NS-038",
            "OPENQASM 3.0; qubit[0] q;",
            "Qasm3UnsupportedConstructError",
            "qubit",
            "Circuit must have at least one qubit",
            "ValueError",
        ),
        (
            "NS-039",
            "OPENQASM 3.0; qubit[0] a; qubit b;",
            "Qasm3UnsupportedConstructError",
            "qubit",
            "Circuit must have at least one qubit",
            "ValueError",
        ),
        (
            "NS-042",
            "OPENQASM 3.0; qubit[1 + 1] q;",
            "Qasm3UnsupportedConstructError",
            "qubit",
            "register size must be an integer literal",
            None,
        ),
        (
            "NS-043",
            "OPENQASM 3.0; qubit[n] q;",
            "Qasm3UnsupportedConstructError",
            "qubit",
            "register size must be an integer literal",
            None,
        ),
        (
            "NS-044",
            "OPENQASM 3.0; qubit[-1] q;",
            "Qasm3UnsupportedConstructError",
            "qubit",
            "register size must be an integer literal",
            None,
        ),
        (
            "NS-048",
            "OPENQASM 3.0;\n@hardware_hint\nqubit q;",
            "Qasm3UnsupportedConstructError",
            "qubit",
            "annotations are not supported",
            None,
        ),
        (
            "NS-049",
            "OPENQASM 3.0; qubit a;\n@hw\nqubit b;",
            "Qasm3UnsupportedConstructError",
            "qubit",
            "annotations are not supported",
            None,
        ),
        (
            "NS-054",
            "OPENQASM 3.0; int[8] counter; qubit q;",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "only bit declarations are supported",
            None,
        ),
        (
            "NS-055",
            "OPENQASM 3.0; float x; qubit q;",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "only bit declarations are supported",
            None,
        ),
        (
            "NS-056",
            "OPENQASM 3.0; bool b; qubit q;",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "only bit declarations are supported",
            None,
        ),
        (
            "NS-057",
            "OPENQASM 3.0; bit c = 1; qubit q;",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "initialized declarations are not supported",
            None,
        ),
        (
            "NS-058",
            "OPENQASM 3.0; bit c; bit c; qubit q;",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "Classical register 'c' is already declared",
            "ValueError",
        ),
        (
            "NS-059",
            'OPENQASM 2.0; include "qelib1.inc"; qreg q[1]; creg c[2]; creg c[3];',
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "Classical register 'c' is already declared",
            "ValueError",
        ),
        (
            "NS-060",
            "OPENQASM 3.0; qubit q; bit[2] c; creg c[2];",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "Classical register 'c' is already declared",
            "ValueError",
        ),
        (
            "NS-061",
            "OPENQASM 3.0; qubit q; bit[0] c;",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "Classical register size must be at least one",
            "ValueError",
        ),
        (
            "NS-062",
            "OPENQASM 3.0; qubit q; bit[n] c;",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "register size must be an integer literal",
            None,
        ),
        (
            "NS-063",
            "OPENQASM 3.0; qubit q;\n@a\nbit c;",
            "Qasm3UnsupportedConstructError",
            "classical declaration",
            "annotations are not supported",
            None,
        ),
        (
            "NS-064",
            "OPENQASM 3.0; const int n = 1; qubit q;",
            "Qasm3UnsupportedConstructError",
            "ConstantDeclaration",
            "construct is not supported",
            None,
        ),
        (
            "NS-065",
            "OPENQASM 3.0; input float theta; qubit q;",
            "Qasm3UnsupportedConstructError",
            "IODeclaration",
            "construct is not supported",
            None,
        ),
        (
            "NS-110",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; gpi(0.1) q[0];',
            "Qasm3UnsupportedGateError",
            "gpi",
            "gate is not registered",
            None,
        ),
        (
            "NS-111",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; gpi2(0.1) q[0];',
            "Qasm3UnsupportedGateError",
            "gpi2",
            "gate is not registered",
            None,
        ),
        (
            "NS-112",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; ms(0.1, 0.2) q[0], q[1];',
            "Qasm3UnsupportedGateError",
            "ms",
            "gate is not registered",
            None,
        ),
        (
            "NS-113",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; phasedx(0.1, 0.2) q[0];',
            "Qasm3UnsupportedGateError",
            "phasedx",
            "gate is not registered",
            None,
        ),
        (
            "NS-114",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; cphase(0.1) q[0], q[1];',
            "Qasm3UnsupportedGateError",
            "cphase",
            "gate is not registered",
            None,
        ),
        (
            "NS-115",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; xy(0.1) q[0], q[1];',
            "Qasm3UnsupportedGateError",
            "xy",
            "gate is not registered",
            None,
        ),
        (
            "NS-116",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; rx90 q[0];',
            "Qasm3UnsupportedGateError",
            "rx90",
            "gate is not registered",
            None,
        ),
        (
            "NS-117",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; rx180 q[0];',
            "Qasm3UnsupportedGateError",
            "rx180",
            "gate is not registered",
            None,
        ),
        (
            "NS-118",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; cnot q[0], q[1];',
            "Qasm3UnsupportedGateError",
            "cnot",
            "gate is not registered",
            None,
        ),
        (
            "NS-119",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; u0(1) q[0];',
            "Qasm3UnsupportedGateError",
            "u0",
            "gate is not registered",
            None,
        ),
        (
            "NS-120",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; rxx(0.1) q[0], q[1];',
            "Qasm3UnsupportedGateError",
            "rxx",
            "gate is not registered",
            None,
        ),
        (
            "NS-121",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; iswap q[0], q[1];',
            "Qasm3UnsupportedGateError",
            "iswap",
            "gate is not registered",
            None,
        ),
        (
            "NS-122",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; bit c; if (c == 1) { gpi(0.1) q[0]; }',
            "Qasm3UnsupportedGateError",
            "gpi",
            "gate is not registered",
            None,
        ),
        (
            "NS-123",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; ctrl @ x q[0], q[1];',
            "Qasm3UnsupportedGateError",
            "x",
            "gate modifiers are not supported",
            None,
        ),
        (
            "NS-124",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; inv @ s q[0];',
            "Qasm3UnsupportedGateError",
            "s",
            "gate modifiers are not supported",
            None,
        ),
        (
            "NS-125",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; pow(2) @ x q[0];',
            "Qasm3UnsupportedGateError",
            "x",
            "gate modifiers are not supported",
            None,
        ),
        (
            "NS-126",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; negctrl @ x q[0], q[1];',
            "Qasm3UnsupportedGateError",
            "x",
            "gate modifiers are not supported",
            None,
        ),
        (
            "NS-127",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; inv @ sx q[0];',
            "Qasm3UnsupportedGateError",
            "sx",
            "gate modifiers are not supported",
            None,
        ),
        (
            "NS-128",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; x[10ns] q[0];',
            "Qasm3UnsupportedGateError",
            "x",
            "gate duration is not supported",
            None,
        ),
        (
            "NS-129",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; sx[10ns] q[0];',
            "Qasm3UnsupportedGateError",
            "sx",
            "gate duration is not supported",
            None,
        ),
        (
            "NS-130",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q;\n@a\nx q[0];',
            "Qasm3UnsupportedConstructError",
            "x",
            "annotations are not supported",
            None,
        ),
        (
            "NS-131",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q;\n@a\nsx q[0];',
            "Qasm3UnsupportedConstructError",
            "sx",
            "annotations are not supported",
            None,
        ),
        (
            "NS-132",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; cx q[0];',
            "Qasm3UnsupportedConstructError",
            "cx",
            "Gate cx requires 2 qubit operands",
            "ValueError",
        ),
        (
            "NS-133",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; x q[0], q[1];',
            "Qasm3UnsupportedConstructError",
            "x",
            "Gate x requires 1 qubit operands",
            "ValueError",
        ),
        (
            "NS-134",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx q[0];',
            "Qasm3UnsupportedConstructError",
            "rx",
            "Gate rx requires 1 parameters",
            "ValueError",
        ),
        (
            "NS-135",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(0.1, 0.2) q[0];',
            "Qasm3UnsupportedConstructError",
            "rx",
            "Gate rx requires 1 parameters",
            "ValueError",
        ),
        (
            "NS-136",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; h(0.1) q[0];',
            "Qasm3UnsupportedConstructError",
            "h",
            "Gate h requires 0 parameters",
            "ValueError",
        ),
        (
            "NS-137",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; u3(0.1, 0.2) q[0];',
            "Qasm3UnsupportedConstructError",
            "u3",
            "Gate u3 requires 3 parameters",
            "ValueError",
        ),
        (
            "NS-162",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; h q[0:1];',
            "Qasm3UnsupportedConstructError",
            "h",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-163",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; h q[{0, 1}];',
            "Qasm3UnsupportedConstructError",
            "h",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-164",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; h q[i];',
            "Qasm3UnsupportedConstructError",
            "h",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-165",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; h q[0][1];',
            "Qasm3UnsupportedConstructError",
            "h",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-166",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; h q[0, 1];',
            "Qasm3UnsupportedConstructError",
            "h",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-167",
            'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; h q[-1];',
            "Qasm3UnsupportedConstructError",
            "h",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-170",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; bit c; x c[0];',
            "Qasm3UnsupportedConstructError",
            "x",
            "qubit register 'c' is not declared",
            None,
        ),
        (
            "NS-171",
            "OPENQASM 3.0; h q[0]; qubit q;",
            "Qasm3UnsupportedConstructError",
            "h",
            "a qubit declaration must precede operations",
            None,
        ),
        (
            "NS-172",
            "OPENQASM 3.0; qubit a; x b[0]; qubit b;",
            "Qasm3UnsupportedConstructError",
            "x",
            "qubit register 'b' is not declared",
            None,
        ),
        (
            "NS-173",
            "OPENQASM 3.0; qubit q; x $0;",
            "Qasm3UnsupportedConstructError",
            "x",
            "qubit register '$0' is not declared",
            None,
        ),
        (
            "NS-187",
            "OPENQASM 3.0; qubit q; measure q[0];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "measurement target is required",
            None,
        ),
        (
            "NS-188",
            "OPENQASM 3.0; qubit[2] q; measure q;",
            "Qasm3UnsupportedConstructError",
            "measure",
            "measurement target is required",
            None,
        ),
        (
            "NS-189",
            "OPENQASM 3.0; qubit q; bit c; other[0] = measure q[0];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "target register 'other' is not declared",
            None,
        ),
        (
            "NS-191",
            "OPENQASM 3.0; qubit q; bit c; c[1] = measure q[0];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "Classical bit index 1 is outside register 'c' of size 1",
            "ValueError",
        ),
        (
            "NS-194",
            "OPENQASM 3.0; qubit q; bit c;\n@a\nc[0] = measure q[0];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "annotations are not supported",
            None,
        ),
        (
            "NS-195",
            "OPENQASM 3.0; qubit[2] q; bit[2] c; c = measure q[0:1];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-196",
            "OPENQASM 3.0; qubit[2] q; bit[2] c; c[0:1] = measure q[0];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-197",
            "OPENQASM 3.0; qubit[2] q; q[0] = measure q[1];",
            "Qasm3UnsupportedConstructError",
            "measure",
            "target register 'q' is not declared",
            None,
        ),
        (
            "NS-212",
            "OPENQASM 3.0; qubit q; bit[2] c; if (c[0, 1] == 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-213",
            "OPENQASM 3.0; qubit q; bit[2] c; if (c[0][1] == 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-214",
            "OPENQASM 3.0; qubit q; bit c; if (c[0, 1] == 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-215",
            "OPENQASM 3.0; qubit q; bit c; if (c[i] == 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-216",
            "OPENQASM 3.0; qubit q; bit c; if (c[0:0] == 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "operand requires a single literal index",
            None,
        ),
        (
            "NS-219",
            "OPENQASM 3.0; qubit q; bit c; if (c == 1) { x q[0]; } else { h q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "else branch is not supported",
            None,
        ),
        (
            "NS-220",
            "OPENQASM 3.0; qubit q; bit c; if (c >= 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "non-equality condition",
            None,
        ),
        (
            "NS-221",
            "OPENQASM 3.0; qubit q; bit c; if (c != 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "non-equality condition",
            None,
        ),
        (
            "NS-222",
            "OPENQASM 3.0; qubit q; bit c; if (c) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "non-equality condition",
            None,
        ),
        (
            "NS-223",
            "OPENQASM 3.0; qubit q; bit c; if (!c) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "non-equality condition",
            None,
        ),
        (
            "NS-224",
            "OPENQASM 3.0; qubit q; bit c; if (c == 1 + 0) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "non-literal rhs",
            None,
        ),
        (
            "NS-225",
            "OPENQASM 3.0; qubit q; bit c; if (c == -1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "non-literal rhs",
            None,
        ),
        (
            "NS-226",
            "OPENQASM 3.0; qubit q; bit c; bit d; if (c == 1 && d == 0) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "non-equality condition",
            None,
        ),
        (
            "NS-227",
            "OPENQASM 3.0; qubit q; if (1 == 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "condition lhs must be a whole register",
            None,
        ),
        (
            "NS-228",
            "OPENQASM 3.0; qubit q; if (c == 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "condition register 'c' is not declared",
            None,
        ),
        (
            "NS-229",
            "OPENQASM 3.0; qubit q; if (c == 1) { x q[0]; } bit c;",
            "Qasm3UnsupportedConstructError",
            "if",
            "condition register 'c' is not declared",
            None,
        ),
        (
            "NS-230",
            "OPENQASM 3.0; qubit q; if (q == 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "condition register 'q' is not declared",
            None,
        ),
        (
            "NS-231",
            "OPENQASM 3.0; qubit q; bit c;\n@a\nif (c == 1) { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "annotations are not supported",
            None,
        ),
        (
            "NS-232",
            "OPENQASM 3.0; qubit q; bit c; if (c == 1) {\n@a\nx q[0];\n}",
            "Qasm3UnsupportedConstructError",
            "x",
            "annotations are not supported",
            None,
        ),
        (
            "NS-233",
            "OPENQASM 3.0; qubit q; bit c; if (c == 1) { c[0] = measure q[0]; }",
            "Qasm3UnsupportedConstructError",
            "if",
            "non-gate statement in if body",
            None,
        ),
        (
            "NS-234",
            "OPENQASM 3.0; qubit q; bit c; if (c == 1) { if (c == 1) { x q[0]; } }",
            "Qasm3UnsupportedConstructError",
            "if",
            "non-gate statement in if body",
            None,
        ),
        (
            "NS-240",
            "OPENQASM 3.0; qubit[2] q; bit c; if (c == 1) { cx q[0]; }",
            "Qasm3UnsupportedConstructError",
            "cx",
            "Gate cx requires 2 qubit operands",
            "ValueError",
        ),
        (
            "NS-241",
            "OPENQASM 3.0; qubit q; bit c; if (c == 1) { rx q[0]; }",
            "Qasm3UnsupportedConstructError",
            "rx",
            "Gate rx requires 1 parameters",
            "ValueError",
        ),
        (
            "NS-245",
            "OPENQASM 3.0; bit c; if (c == 1) { x q[0]; } qubit q;",
            "Qasm3UnsupportedConstructError",
            "if",
            "a qubit declaration must precede operations",
            None,
        ),
        (
            "NS-246",
            "OPENQASM 3.0; qubit q; barrier q;",
            "Qasm3UnsupportedConstructError",
            "barrier",
            "construct is not supported",
            None,
        ),
        (
            "NS-247",
            "OPENQASM 3.0; qubit q; reset q;",
            "Qasm3UnsupportedConstructError",
            "reset",
            "construct is not supported",
            None,
        ),
        (
            "NS-248",
            "OPENQASM 3.0; qubit q; for int i in [0:3] { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "for",
            "construct is not supported",
            None,
        ),
        (
            "NS-249",
            "OPENQASM 3.0; bit c; qubit q; while (c == 0) { c = 1; }",
            "Qasm3UnsupportedConstructError",
            "while",
            "construct is not supported",
            None,
        ),
        (
            "NS-250",
            "OPENQASM 3.0; qubit q; defcal x $0 { play(drive, gaussian(1, 2, 3)); }",
            "Qasm3UnsupportedConstructError",
            "defcal",
            "construct is not supported",
            None,
        ),
        (
            "NS-251",
            "OPENQASM 3.0; defcal x $0 { play(drive, gaussian(1, 2, 3)); }",
            "Qasm3UnsupportedConstructError",
            "defcal",
            "construct is not supported",
            None,
        ),
        (
            "NS-252",
            "OPENQASM 3.0; cal { shift_phase(drive, pi/2); }",
            "Qasm3UnsupportedConstructError",
            "cal",
            "construct is not supported",
            None,
        ),
        (
            "NS-253",
            'OPENQASM 3.0; defcalgrammar "openpulse";',
            "Qasm3UnsupportedConstructError",
            "defcalgrammar",
            "construct is not supported",
            None,
        ),
        (
            "NS-254",
            "OPENQASM 3.0; qubit q; extern f(int) -> int;",
            "Qasm3UnsupportedConstructError",
            "ExternDeclaration",
            "construct is not supported",
            None,
        ),
        (
            "NS-255",
            "OPENQASM 3.0; qubit q; pragma foo bar;",
            "Qasm3UnsupportedConstructError",
            "Pragma",
            "construct is not supported",
            None,
        ),
        (
            "NS-256",
            "OPENQASM 3.0; qubit q; gate g a { x a; }",
            "Qasm3UnsupportedConstructError",
            "QuantumGateDefinition",
            "construct is not supported",
            None,
        ),
        (
            "NS-257",
            'OPENQASM 2.0; include "qelib1.inc"; qreg q[1]; gate g a { x a; }',
            "Qasm3UnsupportedConstructError",
            "QuantumGateDefinition",
            "construct is not supported",
            None,
        ),
        (
            "NS-258",
            "OPENQASM 3.0; qubit q; box { x q[0]; }",
            "Qasm3UnsupportedConstructError",
            "Box",
            "construct is not supported",
            None,
        ),
        (
            "NS-259",
            "OPENQASM 3.0; qubit q; delay[10ns] q[0];",
            "Qasm3UnsupportedConstructError",
            "DelayInstruction",
            "construct is not supported",
            None,
        ),
        (
            "NS-260",
            "OPENQASM 3.0; qubit q; def f() { }",
            "Qasm3UnsupportedConstructError",
            "SubroutineDefinition",
            "construct is not supported",
            None,
        ),
        (
            "NS-261",
            "OPENQASM 3.0; qubit[2] q; let a = q;",
            "Qasm3UnsupportedConstructError",
            "AliasStatement",
            "construct is not supported",
            None,
        ),
        (
            "NS-262",
            "OPENQASM 3.0; qubit q; bit c; c = 1;",
            "Qasm3UnsupportedConstructError",
            "ClassicalAssignment",
            "construct is not supported",
            None,
        ),
        (
            "NS-263",
            "OPENQASM 3.0; qubit q; 1;",
            "Qasm3UnsupportedConstructError",
            "ExpressionStatement",
            "construct is not supported",
            None,
        ),
        (
            "NS-264",
            "OPENQASM 3.0; qubit q; bit c; switch (c) { case 0 { } }",
            "Qasm3UnsupportedConstructError",
            "SwitchStatement",
            "construct is not supported",
            None,
        ),
        (
            "NS-265",
            "OPENQASM 3.0; qubit q; end;",
            "Qasm3UnsupportedConstructError",
            "EndStatement",
            "construct is not supported",
            None,
        ),
        (
            "NS-266",
            "OPENQASM 3.0; qubit q; gphase(pi);",
            "Qasm3UnsupportedConstructError",
            "QuantumPhase",
            "construct is not supported",
            None,
        ),
        (
            "NS-267",
            'OPENQASM 2.0; include "qelib1.inc"; qreg q[1]; opaque g a;',
            "Qasm3ParseError",
            "source",
            "invalid OpenQASM syntax",
            "QASM3ParsingError",
        ),
        (
            "NS-268",
            "OPENQASM 3.0; qubit q; break;",
            "Qasm3ParseError",
            "source",
            "invalid OpenQASM syntax",
            "QASM3ParsingError",
        ),
        (
            "NS-280",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(+pi) q[0];',
            "Qasm3ParseError",
            "source",
            "invalid OpenQASM syntax",
            "QASM3ParsingError",
        ),
        (
            "NS-281",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(euler) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unknown constant 'euler'",
            None,
        ),
        (
            "NS-282",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(ℇ) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unknown constant 'ℇ'",
            None,
        ),
        (
            "NS-283",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(pi ** 2) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unsupported binary expression",
            None,
        ),
        (
            "NS-284",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(3 % 2) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unsupported binary expression",
            None,
        ),
        (
            "NS-285",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(~1) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unsupported unary expression",
            None,
        ),
        (
            "NS-286",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(!1) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unsupported unary expression",
            None,
        ),
        (
            "NS-287",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(sin(pi)) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unsupported expression FunctionCall",
            None,
        ),
        (
            "NS-288",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(10ns) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unsupported expression DurationLiteral",
            None,
        ),
        (
            "NS-289",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(theta) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unknown constant 'theta'",
            None,
        ),
        (
            "NS-290",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(true) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unsupported expression BooleanLiteral",
            None,
        ),
        (
            "NS-291",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(1im) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unsupported expression ImaginaryLiteral",
            None,
        ),
        (
            "NS-292",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(float(1)) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unsupported expression Cast",
            None,
        ),
        (
            "NS-293",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(1 << 2) q[0];',
            "Qasm3UnsupportedConstructError",
            "parameter",
            "unsupported binary expression",
            None,
        ),
        (
            "NS-294",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(1 / 0) q[0];',
            "Qasm3ParseError",
            "parameter",
            "division by zero",
            "ZeroDivisionError",
        ),
        (
            "NS-295",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(1e400) q[0];',
            "Qasm3UnsupportedConstructError",
            "rx",
            "Gate parameters must be finite",
            "ValueError",
        ),
        (
            "NS-296",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(-1e400) q[0];',
            "Qasm3UnsupportedConstructError",
            "rx",
            "Gate parameters must be finite",
            "ValueError",
        ),
        (
            "NS-297",
            'OPENQASM 3.0; include "stdgates.inc"; qubit q; rx(1e308 * 10) q[0];',
            "Qasm3UnsupportedConstructError",
            "rx",
            "Gate parameters must be finite",
            "ValueError",
        ),
        (
            "NS-300",
            "OPENQASM 3.0; bit c;",
            "Qasm3UnsupportedConstructError",
            "qubit declaration",
            "program has no qubit declaration",
            None,
        ),
        (
            "NS-301",
            "OPENQASM 2.0;",
            "Qasm3UnsupportedConstructError",
            "qubit declaration",
            "program has no qubit declaration",
            None,
        ),
        (
            "NS-302",
            'OPENQASM 3.0; include "stdgates.inc";',
            "Qasm3UnsupportedConstructError",
            "qubit declaration",
            "program has no qubit declaration",
            None,
        ),
        (
            "EXP-cy-arity",
            "qubit[3] q; cy q[0];",
            "Qasm3UnsupportedConstructError",
            "cy",
            "Gate cy requires 2 qubit operands",
            "ValueError",
        ),
        (
            "EXP-ccx-arity",
            "qubit[3] q; ccx q[0], q[1];",
            "Qasm3UnsupportedConstructError",
            "ccx",
            "Gate ccx requires 3 qubit operands",
            "ValueError",
        ),
        (
            "EXP-sx-arity",
            "qubit[3] q; sx q[0], q[1];",
            "Qasm3UnsupportedConstructError",
            "sx",
            "Gate sx requires 1 qubit operands",
            "ValueError",
        ),
        (
            "EXP-cp-params",
            "qubit[3] q; cp q[0], q[1];",
            "Qasm3UnsupportedConstructError",
            "cp",
            "Gate cp requires 1 parameters",
            "ValueError",
        ),
        (
            "EXP-cu3-params",
            "qubit[3] q; cu3(0.2, 0.4) q[0], q[1];",
            "Qasm3UnsupportedConstructError",
            "cu3",
            "Gate cu3 requires 3 parameters",
            "ValueError",
        ),
        (
            "EXP-sx-params",
            "qubit[3] q; sx(0.2) q[0];",
            "Qasm3UnsupportedConstructError",
            "sx",
            "Gate sx requires 0 parameters",
            "ValueError",
        ),
    ],
    ids=[
        "NS-001",
        "NS-002",
        "NS-003",
        "NS-004",
        "NS-005",
        "NS-006",
        "NS-007",
        "NS-015",
        "NS-016",
        "NS-017",
        "NS-018",
        "NS-019",
        "NS-020",
        "NS-021",
        "NS-025",
        "NS-030",
        "NS-038",
        "NS-039",
        "NS-042",
        "NS-043",
        "NS-044",
        "NS-048",
        "NS-049",
        "NS-054",
        "NS-055",
        "NS-056",
        "NS-057",
        "NS-058",
        "NS-059",
        "NS-060",
        "NS-061",
        "NS-062",
        "NS-063",
        "NS-064",
        "NS-065",
        "NS-110",
        "NS-111",
        "NS-112",
        "NS-113",
        "NS-114",
        "NS-115",
        "NS-116",
        "NS-117",
        "NS-118",
        "NS-119",
        "NS-120",
        "NS-121",
        "NS-122",
        "NS-123",
        "NS-124",
        "NS-125",
        "NS-126",
        "NS-127",
        "NS-128",
        "NS-129",
        "NS-130",
        "NS-131",
        "NS-132",
        "NS-133",
        "NS-134",
        "NS-135",
        "NS-136",
        "NS-137",
        "NS-162",
        "NS-163",
        "NS-164",
        "NS-165",
        "NS-166",
        "NS-167",
        "NS-170",
        "NS-171",
        "NS-172",
        "NS-173",
        "NS-187",
        "NS-188",
        "NS-189",
        "NS-191",
        "NS-194",
        "NS-195",
        "NS-196",
        "NS-197",
        "NS-212",
        "NS-213",
        "NS-214",
        "NS-215",
        "NS-216",
        "NS-219",
        "NS-220",
        "NS-221",
        "NS-222",
        "NS-223",
        "NS-224",
        "NS-225",
        "NS-226",
        "NS-227",
        "NS-228",
        "NS-229",
        "NS-230",
        "NS-231",
        "NS-232",
        "NS-233",
        "NS-234",
        "NS-240",
        "NS-241",
        "NS-245",
        "NS-246",
        "NS-247",
        "NS-248",
        "NS-249",
        "NS-250",
        "NS-251",
        "NS-252",
        "NS-253",
        "NS-254",
        "NS-255",
        "NS-256",
        "NS-257",
        "NS-258",
        "NS-259",
        "NS-260",
        "NS-261",
        "NS-262",
        "NS-263",
        "NS-264",
        "NS-265",
        "NS-266",
        "NS-267",
        "NS-268",
        "NS-280",
        "NS-281",
        "NS-282",
        "NS-283",
        "NS-284",
        "NS-285",
        "NS-286",
        "NS-287",
        "NS-288",
        "NS-289",
        "NS-290",
        "NS-291",
        "NS-292",
        "NS-293",
        "NS-294",
        "NS-295",
        "NS-296",
        "NS-297",
        "NS-300",
        "NS-301",
        "NS-302",
        "EXP-cy-arity",
        "EXP-ccx-arity",
        "EXP-sx-arity",
        "EXP-cp-params",
        "EXP-cu3-params",
        "EXP-sx-params",
    ],
)
def test_rejection_matrix(case_id, source, error_name, construct, detail, cause_name, monkeypatch):
    from openqasm3.parser import QASM3ParsingError

    if case_id == "NS-021":
        program = qasm3_module.openqasm3.parse("qubit q;")
        monkeypatch.setattr(program, "version", "not-a-version")
        monkeypatch.setattr(qasm3_module.openqasm3, "parse", lambda _: program)
        source = "qubit q;"
    error_type = {
        "Qasm3ParseError": Qasm3ParseError,
        "Qasm3UnsupportedConstructError": Qasm3UnsupportedConstructError,
        "Qasm3UnsupportedGateError": Qasm3UnsupportedGateError,
    }[error_name]
    cause_type = {
        None: None,
        "ValueError": ValueError,
        "ZeroDivisionError": ZeroDivisionError,
        "QASM3ParsingError": QASM3ParsingError,
    }[cause_name]
    _assert_exact_rejection(source, error_type, construct, detail, cause_type)
