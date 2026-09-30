# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""支持可选版本头、多寄存器、广播及标准门展开的 OpenQASM 解析器。"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Never

import openqasm3
from openqasm3 import ast
from openqasm3.parser import QASM3ParsingError

from qaiji.codec._stdgates import _EXPANSIONS, _Expansion
from qaiji.core.circuit import CANONICAL_ALIASES, Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.exceptions import (
    Qasm3ParseError,
    Qasm3UnsupportedConstructError,
    Qasm3UnsupportedGateError,
)

__all__ = ["GateSpec", "from_qasm3", "to_qasm3"]


@dataclass(frozen=True)
class GateSpec:
    """一种标准门写法，及其在电路级的形状。"""

    qasm_name: str
    gate_type: GateType
    arity: int
    n_params: int


_GATE_REGISTRY: dict[str, GateSpec] = {
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
_QASM_NAME_BY_GATE_TYPE = {spec.gate_type: spec.qasm_name for spec in _GATE_REGISTRY.values()}
_QASM_NAME_BY_GATE_TYPE.update(
    {alias: _QASM_NAME_BY_GATE_TYPE[canonical] for alias, canonical in CANONICAL_ALIASES.items()}
)

_ALLOWED_INCLUDES = frozenset({"stdgates.inc", "qelib1.inc"})
_CONSTANTS = {
    "pi": math.pi,
    "π": math.pi,
    "e": math.e,
    "tau": math.tau,
    "τ": math.tau,
}
_FALLBACK_CONSTRUCT_NAMES = {
    "CalibrationDefinition": "defcal",
    "CalibrationGrammarDeclaration": "defcalgrammar",
    "CalibrationStatement": "cal",
    "ForInLoop": "for",
    "QuantumBarrier": "barrier",
    "QuantumReset": "reset",
    "WhileLoop": "while",
}


@dataclass
class _ParseState:
    circuit: Circuit | None = None
    total_qubits: int = 0
    next_qubit: int = 0
    qubit_registers: dict[str, tuple[int, int]] = field(default_factory=dict)
    registers: dict[str, ClassicalRegister] = field(default_factory=dict)


def _location(node: object) -> tuple[int, int]:
    span = getattr(node, "span", None)
    if span is None:
        return (1, 1)
    return (int(span.start_line), int(span.start_column) + 1)


def _message(node: object, construct: str, detail: str) -> str:
    line, column = _location(node)
    return f"{construct} at {line}:{column}: {detail}"


def _raise_unsupported(node: object, construct: str, detail: str) -> Never:
    raise Qasm3UnsupportedConstructError(_message(node, construct, detail))


def _raise_unsupported_gate(node: object, construct: str, detail: str) -> Never:
    raise Qasm3UnsupportedGateError(_message(node, construct, detail))


def _core_call[T](node: object, construct: str, call: Callable[[], T]) -> T:
    try:
        return call()
    except (ValueError, TypeError) as exc:
        raise Qasm3UnsupportedConstructError(_message(node, construct, str(exc))) from exc


def _reject_annotations(node: object, construct: str) -> None:
    if getattr(node, "annotations", []):
        _raise_unsupported(node, construct, "annotations are not supported")


def _literal_size(value: object, node: object, construct: str) -> int:
    if value is None:
        return 1
    if not isinstance(value, ast.IntegerLiteral):
        _raise_unsupported(node, construct, "register size must be an integer literal")
    return int(value.value)


def _require_circuit(state: _ParseState, node: object, construct: str) -> Circuit:
    if state.circuit is None:
        _raise_unsupported(node, construct, "a qubit declaration must precede operations")
    return state.circuit


def _raise_value_error(node: object, construct: str, detail: str) -> Never:
    error = ValueError(detail)
    raise Qasm3UnsupportedConstructError(_message(node, construct, detail)) from error


def _count_qubits(statements: list[ast.Statement | ast.Pragma]) -> int:
    """只统计正整数字面量宽度；所有错误留到逐语句处理时报告。"""
    return sum(
        1 if stmt.size is None else int(stmt.size.value)
        for stmt in statements
        if isinstance(stmt, ast.QubitDeclaration)
        and (
            stmt.size is None or (isinstance(stmt.size, ast.IntegerLiteral) and stmt.size.value > 0)
        )
    )


def _handle_qubit_declaration(stmt: ast.QubitDeclaration, state: _ParseState) -> None:
    _reject_annotations(stmt, "qubit")
    size = _literal_size(stmt.size, stmt, "qubit")
    if size < 1:
        _raise_value_error(stmt, "qubit", "Circuit must have at least one qubit")
    name = str(stmt.qubit.name)
    if name in state.qubit_registers:
        _raise_value_error(stmt, "qubit", f"qubit register {name!r} is already declared")
    if name in state.registers:
        _raise_value_error(
            stmt, "qubit", f"name {name!r} is already declared as a classical register"
        )

    if state.circuit is None:
        circuit = _core_call(stmt, "qubit", lambda: Circuit(state.total_qubits))
        state.circuit = circuit
        for register in state.registers.values():
            _core_call(stmt, "qubit", partial(circuit.add_register, register))
    state.qubit_registers[name] = (state.next_qubit, size)
    state.next_qubit += size


def _handle_classical_declaration(stmt: ast.ClassicalDeclaration, state: _ParseState) -> None:
    construct = "classical declaration"
    _reject_annotations(stmt, construct)
    if not isinstance(stmt.type, ast.BitType):
        _raise_unsupported(stmt, construct, "only bit declarations are supported")
    if stmt.init_expression is not None:
        _raise_unsupported(stmt, construct, "initialized declarations are not supported")

    name = str(stmt.identifier.name)
    if name in state.registers:
        error = ValueError(f"Classical register {name!r} is already declared")
        raise Qasm3UnsupportedConstructError(_message(stmt, construct, str(error))) from error

    if name in state.qubit_registers:
        _raise_value_error(
            stmt, construct, f"name {name!r} is already declared as a qubit register"
        )
    size = _literal_size(stmt.type.size, stmt, construct)
    register = _core_call(stmt, construct, lambda: ClassicalRegister(name, size))
    circuit = state.circuit
    if circuit is not None:
        _core_call(stmt, construct, lambda: circuit.add_register(register))
    state.registers[name] = register


def _handle_include(stmt: ast.Include) -> None:
    _reject_annotations(stmt, "include")
    if stmt.filename not in _ALLOWED_INCLUDES:
        _raise_unsupported(stmt, "include", f"{stmt.filename!r} is not supported")


def _single_literal_index(node: object, construct: str) -> tuple[str, int]:
    if isinstance(node, ast.IndexedIdentifier):
        name = str(node.name.name)
        if len(node.indices) != 1:
            _raise_unsupported(node, construct, "operand requires a single literal index")
        index_group = node.indices[0]
        if not isinstance(index_group, list) or len(index_group) != 1:
            _raise_unsupported(node, construct, "operand requires a single literal index")
        index = index_group[0]
    elif isinstance(node, ast.IndexExpression):
        if not isinstance(node.collection, ast.Identifier):
            _raise_unsupported(node, construct, "operand requires a single literal index")
        name = str(node.collection.name)
        if not isinstance(node.index, list) or len(node.index) != 1:
            _raise_unsupported(node, construct, "operand requires a single literal index")
        index = node.index[0]
    else:
        _raise_unsupported(
            node,
            construct,
            "register-level operand requires a single literal index",
        )

    if not isinstance(index, ast.IntegerLiteral):
        _raise_unsupported(node, construct, "operand requires a single literal index")
    return (name, int(index.value))


def _evaluate_parameter(expression: object) -> float:
    if isinstance(expression, (ast.IntegerLiteral, ast.FloatLiteral)):
        return float(expression.value)
    if isinstance(expression, ast.Identifier):
        name = str(expression.name)
        if name in _CONSTANTS:
            return _CONSTANTS[name]
        _raise_unsupported(expression, "parameter", f"unknown constant {name!r}")
    if isinstance(expression, ast.UnaryExpression):
        value = _evaluate_parameter(expression.expression)
        if expression.op.name == "-":
            return -value
        if expression.op.name == "+":
            return value
        _raise_unsupported(expression, "parameter", "unsupported unary expression")
    if isinstance(expression, ast.BinaryExpression):
        left = _evaluate_parameter(expression.lhs)
        right = _evaluate_parameter(expression.rhs)
        if expression.op.name == "+":
            return left + right
        if expression.op.name == "-":
            return left - right
        if expression.op.name == "*":
            return left * right
        if expression.op.name == "/":
            try:
                return left / right
            except ZeroDivisionError as exc:
                raise Qasm3ParseError(
                    _message(expression, "parameter", "division by zero")
                ) from exc
        _raise_unsupported(expression, "parameter", "unsupported binary expression")
    _raise_unsupported(
        expression,
        "parameter",
        f"unsupported expression {type(expression).__name__}",
    )


def _require_qubit_register(
    node: object,
    construct: str,
    name: str,
    state: _ParseState,
) -> None:
    if name not in state.qubit_registers:
        _raise_unsupported(node, construct, f"qubit register {name!r} is not declared")


def _qubit_bounds_error(
    indexed_qubits: tuple[tuple[str, int], ...],
    state: _ParseState,
) -> ValueError | None:
    for name, index in indexed_qubits:
        _, size = state.qubit_registers[name]
        if not 0 <= index < size:
            return ValueError(f"index {index} is outside qubit register {name!r} of size {size}")
    return None


def _gate_operand(node: object, construct: str) -> tuple[str, int | None]:
    if isinstance(node, ast.Identifier):
        return str(node.name), None
    return _single_literal_index(node, construct)


def _validate_gate_operands(
    spec: GateSpec | _Expansion,
    indexed_qubits: tuple[tuple[str, int | None], ...],
    parameters: tuple[float, ...],
) -> None:
    name = spec.qasm_name if isinstance(spec, GateSpec) else spec.name
    if len(indexed_qubits) != spec.arity:
        raise ValueError(f"Gate {name} requires {spec.arity} qubit operands")
    if len(parameters) != spec.n_params:
        raise ValueError(f"Gate {name} requires {spec.n_params} parameters")
    if any(not math.isfinite(parameter) for parameter in parameters):
        raise ValueError("Gate parameters must be finite")
    if len(indexed_qubits) != len(set(indexed_qubits)):
        raise ValueError("Gate qubits must be unique")


def _build_gate(
    stmt: ast.QuantumGate,
    state: _ParseState,
) -> tuple[tuple[Gate, ...], ValueError | None]:
    gate_name = str(stmt.name.name).lower()
    _reject_annotations(stmt, gate_name)
    if stmt.modifiers:
        _raise_unsupported_gate(stmt, gate_name, "gate modifiers are not supported")
    if stmt.duration is not None:
        _raise_unsupported_gate(stmt, gate_name, "gate duration is not supported")

    spec: GateSpec | _Expansion | None = _GATE_REGISTRY.get(gate_name)
    if spec is None:
        spec = _EXPANSIONS.get(gate_name)
    if spec is None:
        _raise_unsupported_gate(stmt, gate_name, "gate is not registered")

    _require_circuit(state, stmt, gate_name)
    indexed_qubits = tuple(_gate_operand(qubit, gate_name) for qubit in stmt.qubits)
    for register_name, _ in indexed_qubits:
        _require_qubit_register(stmt, gate_name, register_name, state)
    parameters = tuple(_evaluate_parameter(argument) for argument in stmt.arguments)
    _core_call(stmt, gate_name, lambda: _validate_gate_operands(spec, indexed_qubits, parameters))
    scalar_qubits = tuple((name, index) for name, index in indexed_qubits if index is not None)
    bounds_error = _qubit_bounds_error(scalar_qubits, state)
    if bounds_error is not None:
        return (), bounds_error
    register_sizes = {
        state.qubit_registers[name][1] for name, index in indexed_qubits if index is None
    }
    if len(register_sizes) > 1:
        _raise_unsupported(stmt, gate_name, "broadcast operands have different register sizes")
    width = next(iter(register_sizes), 1)
    gates: list[Gate] = []
    for i in range(width):
        qubits = tuple(
            state.qubit_registers[name][0] + (i if index is None else index)
            for name, index in indexed_qubits
        )
        if isinstance(spec, GateSpec):
            gate_type = spec.gate_type
            gates.append(_core_call(stmt, gate_name, partial(Gate, gate_type, qubits, parameters)))
        else:
            build = spec.build
            gates.extend(_core_call(stmt, gate_name, partial(build, qubits, parameters)))
    return tuple(gates), None


def _handle_gate(stmt: ast.QuantumGate, state: _ParseState) -> None:
    gates, bounds_error = _build_gate(stmt, state)
    gate_name = str(stmt.name.name).lower()
    if bounds_error is not None:
        raise Qasm3UnsupportedConstructError(
            _message(stmt, gate_name, str(bounds_error))
        ) from bounds_error
    circuit = _require_circuit(state, stmt, gate_name)
    for gate in gates:
        _core_call(stmt, gate_name, partial(circuit.add_gate, gate))


def _handle_measurement(stmt: ast.QuantumMeasurementStatement, state: _ParseState) -> None:
    construct = "measure"
    _reject_annotations(stmt, construct)
    if stmt.target is None:
        _raise_unsupported(stmt, construct, "measurement target is required")

    circuit = _require_circuit(state, stmt, construct)
    source_name, qubit = _gate_operand(stmt.measure.qubit, construct)
    target_name, bit_index = _gate_operand(stmt.target, construct)
    _require_qubit_register(stmt, construct, source_name, state)
    if target_name not in state.registers:
        _raise_unsupported(
            stmt,
            construct,
            f"target register {target_name!r} is not declared",
        )

    register = state.registers[target_name]
    target_indices = range(register.size) if bit_index is None else (bit_index,)
    targets = tuple(
        _core_call(stmt, construct, partial(ClassicalBit, register, index))
        for index in target_indices
    )
    offset, size = state.qubit_registers[source_name]
    source_indices = range(size) if qubit is None else (qubit,)
    bounds_error = _qubit_bounds_error(
        tuple((source_name, index) for index in source_indices), state
    )
    if bounds_error is not None:
        raise Qasm3UnsupportedConstructError(
            _message(stmt, construct, str(bounds_error))
        ) from bounds_error
    if len(source_indices) != len(targets):
        _raise_unsupported(stmt, construct, "broadcast operands have different register sizes")
    for index, target in zip(source_indices, targets, strict=True):
        measurement = _core_call(stmt, construct, partial(Measure, offset + index, target))
        _core_call(stmt, construct, partial(circuit.add_measure, measurement))


def _conditional_gate_body(stmt: ast.BranchingStatement) -> tuple[ast.QuantumGate, ...]:
    body: list[ast.QuantumGate] = []
    for operation in stmt.if_block:
        if not isinstance(operation, ast.QuantumGate):
            _raise_unsupported(stmt, "if", "non-gate statement in if body")
        body.append(operation)
    return tuple(body)


def _handle_branching(stmt: ast.BranchingStatement, state: _ParseState) -> None:
    construct = "if"
    _reject_annotations(stmt, construct)
    if stmt.else_block:
        _raise_unsupported(stmt, construct, "else branch is not supported")
    body_statements = _conditional_gate_body(stmt)
    if not isinstance(stmt.condition, ast.BinaryExpression) or stmt.condition.op.name != "==":
        _raise_unsupported(stmt, construct, "non-equality condition")
    if not isinstance(stmt.condition.rhs, ast.IntegerLiteral):
        _raise_unsupported(stmt, construct, "non-literal rhs")
    bit_index = None
    if isinstance(stmt.condition.lhs, ast.IndexExpression):
        register_name, bit_index = _single_literal_index(stmt.condition.lhs, construct)
    elif isinstance(stmt.condition.lhs, ast.Identifier):
        register_name = str(stmt.condition.lhs.name)
    else:
        _raise_unsupported(stmt, construct, "condition lhs must be a whole register")

    if register_name not in state.registers:
        _raise_unsupported(
            stmt,
            construct,
            f"condition register {register_name!r} is not declared",
        )
    if bit_index is not None:
        register = state.registers[register_name]
        if register.size != 1:
            _raise_unsupported(
                stmt, construct, "bit-level condition on a multi-bit register is not supported"
            )
        _core_call(stmt, construct, partial(ClassicalBit, register, bit_index))
        if stmt.condition.rhs.value not in {0, 1}:
            _raise_unsupported(stmt, construct, "bit condition value must be 0 or 1")
    circuit = _require_circuit(state, stmt, construct)
    body: list[Gate] = []
    first_bounds_error = None
    for operation in body_statements:
        gates, bounds_error = _build_gate(operation, state)
        if first_bounds_error is None:
            first_bounds_error = bounds_error
        body.extend(gates)
    if first_bounds_error is not None:
        raise Qasm3UnsupportedConstructError(
            _message(stmt, construct, str(first_bounds_error))
        ) from first_bounds_error
    register = state.registers[register_name]
    value = int(stmt.condition.rhs.value)
    conditional = _core_call(stmt, construct, lambda: Conditional(register, value, tuple(body)))
    _core_call(stmt, construct, lambda: circuit.add_conditional(conditional))


def _fallback_construct_name(statement: object) -> str:
    node_name = type(statement).__name__
    return _FALLBACK_CONSTRUCT_NAMES.get(node_name, node_name)


def _validate_version(program: ast.Program) -> None:
    if program.version is None:
        return
    try:
        major = int(str(program.version).split(".", maxsplit=1)[0])
    except ValueError as exc:
        raise Qasm3ParseError(
            _message(program, "OPENQASM", f"invalid version {program.version!r}")
        ) from exc
    if major not in {2, 3}:
        raise Qasm3ParseError(
            _message(program, "OPENQASM", f"unsupported version {program.version!r}")
        )


def _indexed_identifier(name: str, index: int) -> ast.IndexedIdentifier:
    return ast.IndexedIdentifier(
        name=ast.Identifier(name),
        indices=[[ast.IntegerLiteral(index)]],
    )


def _qasm_gate_name(gate: Gate) -> str:
    try:
        return _QASM_NAME_BY_GATE_TYPE[gate.gate_type]
    except KeyError as exc:
        raise Qasm3UnsupportedGateError(
            f"Gate {gate.gate_type.value} has no stdgates mapping; "
            "serialization requires native-layer lowering"
        ) from exc


def _gate_to_ast(gate: Gate, qubit_name: str) -> ast.QuantumGate:
    return ast.QuantumGate(
        modifiers=[],
        name=ast.Identifier(_qasm_gate_name(gate)),
        arguments=[ast.FloatLiteral(parameter) for parameter in gate.params],
        qubits=[_indexed_identifier(qubit_name, qubit) for qubit in gate.qubits],
        duration=None,
    )


def _measure_to_ast(measurement: Measure, qubit_name: str) -> ast.QuantumMeasurementStatement:
    return ast.QuantumMeasurementStatement(
        measure=ast.QuantumMeasurement(qubit=_indexed_identifier(qubit_name, measurement.qubit)),
        target=_indexed_identifier(
            measurement.target.register.name,
            measurement.target.index,
        ),
    )


def _conditional_to_ast(conditional: Conditional, qubit_name: str) -> ast.BranchingStatement:
    condition = ast.BinaryExpression(
        op=ast.BinaryOperator["=="],
        lhs=ast.Identifier(conditional.register.name),
        rhs=ast.IntegerLiteral(conditional.value),
    )
    return ast.BranchingStatement(
        condition=condition,
        if_block=[_gate_to_ast(gate, qubit_name) for gate in conditional.body],
        else_block=[],
    )


def _operation_to_ast(
    operation: Gate | Measure | Conditional,
    qubit_name: str,
) -> ast.Statement:
    if isinstance(operation, Gate):
        return _gate_to_ast(operation, qubit_name)
    if isinstance(operation, Measure):
        return _measure_to_ast(operation, qubit_name)
    if isinstance(operation, Conditional):
        return _conditional_to_ast(operation, qubit_name)
    raise Qasm3UnsupportedConstructError(
        f"Circuit operation {type(operation).__name__} is not serializable"
    )


def from_qasm3(src: str) -> Circuit:
    """把一段受支持的 OpenQASM 程序解析为电路，否则大声拒绝。"""
    try:
        return _parse_source(src)
    except RecursionError as exc:
        raise Qasm3ParseError("source at 1:1: expression nesting exceeds parser limit") from exc


def _parse_source(src: str) -> Circuit:
    try:
        program = openqasm3.parse(src)
    except QASM3ParsingError as exc:
        raise Qasm3ParseError(_message(src, "source", "invalid OpenQASM syntax")) from exc
    except AttributeError as exc:
        if re.sub(r"//[^\n]*|/\*.*?\*/", "", src, flags=re.DOTALL).strip():
            raise Qasm3ParseError(_message(src, "source", "invalid OpenQASM syntax")) from exc
        program = ast.Program(statements=[])

    _validate_version(program)
    state = _ParseState(total_qubits=_count_qubits(program.statements))
    for statement in program.statements:
        if isinstance(statement, ast.Include):
            _handle_include(statement)
        elif isinstance(statement, ast.QubitDeclaration):
            _handle_qubit_declaration(statement, state)
        elif isinstance(statement, ast.ClassicalDeclaration):
            _handle_classical_declaration(statement, state)
        elif isinstance(statement, ast.QuantumGate):
            _handle_gate(statement, state)
        elif isinstance(statement, ast.QuantumMeasurementStatement):
            _handle_measurement(statement, state)
        elif isinstance(statement, ast.BranchingStatement):
            _handle_branching(statement, state)
        else:
            construct = _fallback_construct_name(statement)
            _raise_unsupported(statement, construct, "construct is not supported")

    if state.circuit is None:
        _raise_unsupported(program, "qubit declaration", "program has no qubit declaration")
    return state.circuit


def to_qasm3(circuit: Circuit) -> str:
    """把一个受支持的电路序列化为规范化的 OpenQASM 3 源码。"""
    classical_names = {register.name for register in circuit.cregs}
    qubit_name = "q"
    suffix = 0
    while qubit_name in classical_names:
        qubit_name = f"q{suffix}"
        suffix += 1
    statements: list[ast.Statement | ast.Pragma] = [
        ast.Include("stdgates.inc"),
        ast.QubitDeclaration(
            qubit=ast.Identifier(qubit_name),
            size=ast.IntegerLiteral(circuit.num_qubits),
        ),
    ]
    statements.extend(
        ast.ClassicalDeclaration(
            type=ast.BitType(size=ast.IntegerLiteral(register.size)),
            identifier=ast.Identifier(register.name),
            init_expression=None,
        )
        for register in circuit.cregs
    )
    statements.extend(_operation_to_ast(operation, qubit_name) for operation in circuit.gates)
    return openqasm3.dumps(ast.Program(statements=statements, version="3.0"))
