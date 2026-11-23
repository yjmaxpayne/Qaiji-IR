# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""支持可选版本头、多寄存器、广播及标准门展开的 OpenQASM 解析器。"""

from __future__ import annotations

import copy
import math
import operator
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, fields
from functools import partial
from typing import Any, Literal, Never, overload

import openqasm3
from openqasm3 import ast
from openqasm3.parser import QASM3ParsingError

from qaiji.codec._stdgates import _EXPANSIONS, _Expansion
from qaiji.core.circuit import CANONICAL_ALIASES, Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.loop import (
    MAX_LOOP_ITERATIONS,
    BodyNode,
    BoundedLoop,
    ConditionalTemplate,
    GateTemplate,
    LoopedCircuit,
    LoopIndex,
    MeasureTemplate,
    Operation,
    SourceSpan,
)
from qaiji.exceptions import (
    LoopedCircuitError,
    Qasm3ParseError,
    Qasm3UnsupportedConstructError,
    Qasm3UnsupportedGateError,
)

__all__ = [
    "GateSpec",
    "OperationOrigin",
    "ParsedLoopedQasm3",
    "ParsedQasm3",
    "from_qasm3",
    "parse_looped_qasm3",
    "parse_qasm3",
    "to_qasm3",
]


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
_INTEGER_OPERATORS: dict[str, Callable[[int, int], int]] = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
}


@dataclass(frozen=True)
class OperationOrigin:
    """一个电路操作在源码中的来历；只读元数据，不进入电路的相等、摘要或规范化。

    行号从 1 起；列号从 1 起、两端闭区间，按 Unicode code point 计，
    与错误消息 ``at line:column`` 同一约定。
    ``statement_index`` 是顶层语句序号，条件体内的门沿用所属 ``if`` 的序号；
    同一语句展开或广播出的多个操作共享 span，以两个下标区分。展开为零个门的语句
    不留 origin，因此序号可能有空缺。``raw_name`` 对门是源码原样拼写，对测量与条件
    是构造名 ``"measure"`` / ``"if"``；只有条件 origin 的 ``body`` 非空。

    Example:
        >>> origin = parse_qasm3("qubit[2] q; h q;").origins[1]
        >>> (origin.raw_name, origin.line, origin.column, origin.broadcast_index)
        ('h', 1, 13, 1)
    """

    statement_index: int
    raw_name: str
    line: int
    column: int
    end_line: int
    end_column: int
    broadcast_index: int = 0
    expansion_index: int = 0
    body: tuple[OperationOrigin, ...] = ()


@dataclass(frozen=True)
class ParsedQasm3:
    """一次解析的产物：电路，加上与 ``circuit.gates`` 逐位对齐的源码旁表。

    ``circuit`` 仍是可变容器：调用方一旦增删或替换其中的操作，``origins`` 即告失效，
    本记录不做运行期防护。记录本身不可哈希，``==`` 同时比较电路与旁表，
    比较语义时请只比较 ``.circuit``。``declared_version`` 是版本头原文，缺头为 ``None``。

    Example:
        >>> parsed = parse_qasm3("OPENQASM 3.0; qubit q; x q;")
        >>> (parsed.declared_version, len(parsed.origins) == len(parsed.circuit.gates))
        ('3.0', True)
    """

    circuit: Circuit
    origins: tuple[OperationOrigin, ...]
    declared_version: str | None

    @property
    def version_header_present(self) -> bool:
        """源码是否写了 ``OPENQASM`` 版本头。"""
        return self.declared_version is not None


@dataclass(frozen=True)
class ParsedLoopedQasm3:
    """``parse_looped_qasm3`` 的产物：保留有界循环的电路，加上声明的版本。

    ``declared_version`` 是版本头原文，缺头为 ``None``。

    Example:
        >>> parsed = parse_looped_qasm3("qubit[2] q; for int i in [0:1] { x q[i]; }")
        >>> (parsed.declared_version, len(parsed.circuit.expand().circuit.gates))
        (None, 2)
    """

    circuit: LoopedCircuit
    declared_version: str | None


@dataclass
class _ParseState:
    circuit: Circuit | None = None
    total_qubits: int = 0
    next_qubit: int = 0
    qubit_registers: dict[str, tuple[int, int]] = field(default_factory=dict)
    registers: dict[str, ClassicalRegister] = field(default_factory=dict)
    statement_index: int = 0
    origins: list[OperationOrigin] = field(default_factory=list)
    constants: dict[str, tuple[int, ast.ConstantDeclaration]] = field(default_factory=dict)
    used_constants: set[str] = field(default_factory=set)
    loop_names: set[str] = field(default_factory=set)
    loop_variables: set[str] = field(default_factory=set)
    """已用的循环变量名与计数器名：之后的同名寄存器或 const 声明无法写回，所以拒收。"""
    loops: list[tuple[int, int, BoundedLoop]] = field(default_factory=list)
    """每个循环在平坦操作序列中的起止位置与循环节点。"""
    counter: ast.ClassicalDeclaration | None = None
    """尚未被计数器 ``while`` 使用的计数器声明。"""


def _span(node: object) -> tuple[int, int, int, int]:
    span = getattr(node, "span", None)
    if span is None:
        return (1, 1, 1, 1)
    # openqasm3 的列从 0 起、end 指向末记号首字符；统一加 1 成为从 1 起的闭区间。
    return (
        int(span.start_line),
        int(span.start_column) + 1,
        int(span.end_line),
        int(span.end_column) + 1,
    )


def _location(node: object) -> tuple[int, int]:
    line, column, _, _ = _span(node)
    return (line, column)


def _origin(
    node: object,
    state: _ParseState,
    raw_name: str,
    broadcast_index: int = 0,
    expansion_index: int = 0,
    body: tuple[OperationOrigin, ...] = (),
) -> OperationOrigin:
    return OperationOrigin(
        state.statement_index,
        raw_name,
        *_span(node),
        broadcast_index=broadcast_index,
        expansion_index=expansion_index,
        body=body,
    )


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


def _decimal_limit_error(value: int) -> ValueError | None:
    """错误消息与 ``to_qasm3`` 都要把整数写成十进制；写不出时返回解释器的原生错误。"""
    try:
        str(value)
    except ValueError as exc:
        return exc
    return None


def _checked_int(node: ast.IntegerLiteral, construct: str) -> int:
    # 十六/二/八进制字面量不受解析期位数上限约束，故在每个取值点按十进制化能力拒收。
    value = int(node.value)
    error = _decimal_limit_error(value)
    if error is not None:
        raise Qasm3ParseError(_message(node, construct, str(error))) from error
    return value


def _literal_size(value: object, node: object, construct: str) -> int:
    if value is None:
        return 1
    if not isinstance(value, ast.IntegerLiteral):
        _raise_unsupported(node, construct, "register size must be an integer literal")
    return _checked_int(value, construct)


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
    # to_qasm3 以十进制写出总 qubit 数，所以总数同样受上限约束，报在使总数越限的声明上。
    total_error = _decimal_limit_error(state.next_qubit + size)
    if total_error is not None:
        raise Qasm3ParseError(_message(stmt, "qubit", str(total_error))) from total_error

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
    return (name, _checked_int(index, construct))


def _evaluate_parameter(expression: object) -> float:
    if isinstance(expression, ast.IntegerLiteral):
        try:
            return float(_checked_int(expression, "parameter"))
        except OverflowError:
            # 超出 float 范围的整数按 inf 交给有限性检查，与 1e400 的浮点写法同判。
            return math.inf
    if isinstance(expression, ast.FloatLiteral):
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
    indexed_qubits: tuple[tuple[str, int | LoopIndex | None], ...],
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


def _gate_spec(stmt: ast.QuantumGate, state: _ParseState) -> tuple[str, GateSpec | _Expansion]:
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
    return gate_name, spec


def _build_gate(
    stmt: ast.QuantumGate,
    state: _ParseState,
) -> tuple[tuple[Gate, ...], tuple[OperationOrigin, ...], ValueError | None]:
    raw_name = str(stmt.name.name)
    gate_name, spec = _gate_spec(stmt, state)
    indexed_qubits = tuple(_gate_operand(qubit, gate_name) for qubit in stmt.qubits)
    for register_name, _ in indexed_qubits:
        _require_qubit_register(stmt, gate_name, register_name, state)
    parameters = tuple(_evaluate_parameter(argument) for argument in stmt.arguments)
    _core_call(stmt, gate_name, lambda: _validate_gate_operands(spec, indexed_qubits, parameters))
    scalar_qubits = tuple((name, index) for name, index in indexed_qubits if index is not None)
    bounds_error = _qubit_bounds_error(scalar_qubits, state)
    if bounds_error is not None:
        return (), (), bounds_error
    register_sizes = {
        state.qubit_registers[name][1] for name, index in indexed_qubits if index is None
    }
    if len(register_sizes) > 1:
        _raise_unsupported(stmt, gate_name, "broadcast operands have different register sizes")
    width = next(iter(register_sizes), 1)
    gates: list[Gate] = []
    origins: list[OperationOrigin] = []
    built: tuple[Gate, ...]
    for i in range(width):
        qubits = tuple(
            state.qubit_registers[name][0] + (i if index is None else index)
            for name, index in indexed_qubits
        )
        if isinstance(spec, GateSpec):
            gate_type = spec.gate_type
            built = (_core_call(stmt, gate_name, partial(Gate, gate_type, qubits, parameters)),)
        else:
            build = spec.build
            built = _core_call(stmt, gate_name, partial(build, qubits, parameters))
        gates.extend(built)
        origins.extend(_origin(stmt, state, raw_name, i, k) for k in range(len(built)))
    return tuple(gates), tuple(origins), None


def _handle_gate(stmt: ast.QuantumGate, state: _ParseState) -> None:
    gates, origins, bounds_error = _build_gate(stmt, state)
    gate_name = str(stmt.name.name).lower()
    if bounds_error is not None:
        raise Qasm3UnsupportedConstructError(
            _message(stmt, gate_name, str(bounds_error))
        ) from bounds_error
    circuit = _require_circuit(state, stmt, gate_name)
    for gate in gates:
        _core_call(stmt, gate_name, partial(circuit.add_gate, gate))
    state.origins.extend(origins)


def _handle_measurement(stmt: ast.QuantumMeasurementStatement, state: _ParseState) -> None:
    construct = "measure"
    _reject_annotations(stmt, construct)
    if stmt.target is None:
        _raise_unsupported(stmt, construct, "measurement target is required")
    if not isinstance(stmt.measure, ast.QuantumMeasurement):
        _raise_unsupported(
            stmt,
            construct,
            "only qubit measurement is supported, not a measurement call",
        )

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
    for i, (index, target) in enumerate(zip(source_indices, targets, strict=True)):
        measurement = _core_call(stmt, construct, partial(Measure, offset + index, target))
        _core_call(stmt, construct, partial(circuit.add_measure, measurement))
        state.origins.append(_origin(stmt, state, construct, i))


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
        _core_call(stmt, construct, partial(ClassicalBit, register, bit_index))
        if _checked_int(stmt.condition.rhs, construct) not in {0, 1}:
            _raise_unsupported(stmt, construct, "bit condition value must be 0 or 1")
    circuit = _require_circuit(state, stmt, construct)
    body: list[Gate] = []
    body_origins: list[OperationOrigin] = []
    first_bounds_error = None
    for operation in body_statements:
        gates, origins, bounds_error = _build_gate(operation, state)
        if first_bounds_error is None:
            first_bounds_error = bounds_error
        body.extend(gates)
        body_origins.extend(origins)
    if first_bounds_error is not None:
        raise Qasm3UnsupportedConstructError(
            _message(stmt, construct, str(first_bounds_error))
        ) from first_bounds_error
    register = state.registers[register_name]
    value = _checked_int(stmt.condition.rhs, construct)
    conditional = _core_call(
        stmt, construct, lambda: Conditional(register, value, tuple(body), bit_index)
    )
    _core_call(stmt, construct, lambda: circuit.add_conditional(conditional))
    state.origins.append(_origin(stmt, state, construct, body=tuple(body_origins)))


def _descendants(node: object) -> Iterator[ast.QASMNode]:
    """按先序遍历语法节点及其全部子节点。"""
    if isinstance(node, list):
        for item in node:
            yield from _descendants(item)
    elif isinstance(node, ast.QASMNode):
        yield node
        for node_field in fields(node):
            yield from _descendants(getattr(node, node_field.name))


def _single_index(node: object) -> tuple[str, object] | None:
    """``name[index]`` 形态返回名称与唯一下标节点，其他形态返回 ``None``。"""
    if isinstance(node, ast.IndexedIdentifier) and len(node.indices) == 1:
        group = node.indices[0]
        if isinstance(group, list) and len(group) == 1:
            return str(node.name.name), group[0]
    if isinstance(node, ast.IndexExpression) and isinstance(node.collection, ast.Identifier):
        if isinstance(node.index, list) and len(node.index) == 1:
            return str(node.collection.name), node.index[0]
    return None


def _is_variable(node: object, variable: str) -> bool:
    return isinstance(node, ast.Identifier) and str(node.name) == variable


def _sole_index(node: object, variable: str) -> int | None:
    """循环变量作 ``name[i]`` 的唯一下标时，返回该变量节点的 id。"""
    indexed = _single_index(node)
    if indexed is not None and _is_variable(indexed[1], variable):
        return id(indexed[1])
    return None


def _declared_names(state: _ParseState) -> set[str]:
    return {*state.qubit_registers, *state.registers, *state.constants, *state.loop_names}


def _is_reserved(name: str, declared: set[str]) -> bool:
    """判断 const、计数器或循环变量的名称是否与已声明名称、门名或内置常量相同。

    门名按小写比对，与门的查找一致。
    """
    gate = name.lower()
    return name in declared or name in _CONSTANTS or gate in _GATE_REGISTRY or gate in _EXPANSIONS


def _integer_value(expression: object, state: _ParseState, construct: str) -> int:
    """求整数常量表达式：字面量、已声明的 const、一元负号与 ``+ - *``。"""
    if isinstance(expression, ast.IntegerLiteral):
        return _checked_int(expression, construct)
    if isinstance(expression, ast.Identifier) and str(expression.name) in state.constants:
        name = str(expression.name)
        state.used_constants.add(name)
        return state.constants[name][0]
    if isinstance(expression, ast.UnaryExpression) and expression.op.name == "-":
        value = -_integer_value(expression.expression, state, construct)
    elif isinstance(expression, ast.BinaryExpression) and expression.op.name in _INTEGER_OPERATORS:
        left = _integer_value(expression.lhs, state, construct)
        right = _integer_value(expression.rhs, state, construct)
        value = _INTEGER_OPERATORS[expression.op.name](left, right)
    else:
        _raise_unsupported(
            expression,
            construct,
            f"unsupported integer expression {type(expression).__name__}",
        )
    error = _decimal_limit_error(value)
    if error is not None:
        raise Qasm3ParseError(_message(expression, construct, str(error))) from error
    return value


def _handle_const(stmt: ast.ConstantDeclaration, state: _ParseState) -> None:
    construct = "const"
    _reject_annotations(stmt, construct)
    if not isinstance(stmt.type, ast.IntType) or stmt.type.size is not None:
        _raise_unsupported(stmt, construct, "only unsized int constants are supported")
    name = str(stmt.identifier.name)
    if _is_reserved(name, {*_declared_names(state), *state.loop_variables}):
        _raise_unsupported(stmt, construct, f"const {name!r} has a declared, gate or constant name")
    value = _integer_value(stmt.init_expression, state, construct)
    state.constants[name] = (value, stmt)


def _loop_operand(
    node: object, construct: str, variable: str
) -> tuple[str, int | LoopIndex | None]:
    indexed = _single_index(node)
    if indexed is not None and _is_variable(indexed[1], variable):
        return indexed[0], LoopIndex()
    return _gate_operand(node, construct)


def _gate_templates(
    stmt: ast.QuantumGate,
    state: _ParseState,
    variable: str,
    bounds_owner: ast.Statement | None = None,
) -> tuple[GateTemplate, ...]:
    """构造一条门语句的循环体模板。

    字面量下标越界时按 ``bounds_owner`` 报告；它是 ``if`` 语句时，消息与平坦程序相同。
    """
    gate_name, spec = _gate_spec(stmt, state)
    operands = tuple(_loop_operand(qubit, gate_name, variable) for qubit in stmt.qubits)
    for register_name, _ in operands:
        _require_qubit_register(stmt, gate_name, register_name, state)
    parameters = tuple(_evaluate_parameter(argument) for argument in stmt.arguments)
    _core_call(stmt, gate_name, lambda: _validate_gate_operands(spec, operands, parameters))
    literal = tuple((name, index) for name, index in operands if isinstance(index, int))
    bounds_error = _qubit_bounds_error(literal, state)
    if bounds_error is not None:
        owner, construct = (stmt, gate_name) if bounds_owner is None else (bounds_owner, "if")
        raise Qasm3UnsupportedConstructError(
            _message(owner, construct, str(bounds_error))
        ) from bounds_error
    # 循环只允许一个量子寄存器，它的偏移为 0，所以寄存器内下标就是电路比特号。
    ((_, size),) = state.qubit_registers.values()
    width = size if any(index is None for _, index in operands) else 1
    templates: list[GateTemplate] = []
    for i in range(width):
        refs = tuple(i if index is None else index for _, index in operands)
        if isinstance(spec, GateSpec):
            templates.append(GateTemplate(spec.gate_type, refs, parameters))
            continue
        # 展开式在占位比特 0..arity-1 上构造，再把占位比特映射回操作数。
        build = spec.build
        built = _core_call(stmt, gate_name, partial(build, tuple(range(spec.arity)), parameters))
        templates.extend(
            GateTemplate(gate.gate_type, tuple(refs[q] for q in gate.qubits), gate.params)
            for gate in built
        )
    return tuple(templates)


def _measure_templates(
    stmt: ast.QuantumMeasurementStatement,
    state: _ParseState,
    variable: str,
    scope: dict[str, ClassicalRegister],
) -> tuple[MeasureTemplate, ...]:
    construct = "measure"
    _reject_annotations(stmt, construct)
    if stmt.target is None:
        _raise_unsupported(stmt, construct, "measurement target is required")
    if not isinstance(stmt.measure, ast.QuantumMeasurement):
        _raise_unsupported(
            stmt,
            construct,
            "only qubit measurement is supported, not a measurement call",
        )
    _require_circuit(state, stmt, construct)
    source_name, qubit = _loop_operand(stmt.measure.qubit, construct, variable)
    target_name, bit = _loop_operand(stmt.target, construct, variable)
    _require_qubit_register(stmt, construct, source_name, state)
    if target_name not in scope:
        _raise_unsupported(stmt, construct, f"target register {target_name!r} is not declared")
    register = scope[target_name]
    if isinstance(bit, int):
        _core_call(stmt, construct, partial(ClassicalBit, register, bit))
    if isinstance(qubit, int):
        bounds_error = _qubit_bounds_error(((source_name, qubit),), state)
        if bounds_error is not None:
            raise Qasm3UnsupportedConstructError(
                _message(stmt, construct, str(bounds_error))
            ) from bounds_error
    _, size = state.qubit_registers[source_name]
    qubits: tuple[int | LoopIndex, ...] = tuple(range(size)) if qubit is None else (qubit,)
    bits: tuple[int | LoopIndex, ...] = tuple(range(register.size)) if bit is None else (bit,)
    if len(qubits) != len(bits):
        _raise_unsupported(stmt, construct, "broadcast operands have different register sizes")
    return tuple(
        MeasureTemplate(source, target_name, target)
        for source, target in zip(qubits, bits, strict=True)
    )


def _conditional_template(
    stmt: ast.BranchingStatement,
    state: _ParseState,
    variable: str,
    scope: dict[str, ClassicalRegister],
) -> ConditionalTemplate:
    construct = "if"
    _reject_annotations(stmt, construct)
    if stmt.else_block:
        _raise_unsupported(stmt, construct, "else branch is not supported")
    body_statements = _conditional_gate_body(stmt)
    condition = stmt.condition
    if not isinstance(condition, ast.BinaryExpression) or condition.op.name != "==":
        _raise_unsupported(stmt, construct, "non-equality condition")
    if not isinstance(condition.rhs, ast.IntegerLiteral):
        _raise_unsupported(stmt, construct, "non-literal rhs")
    if not isinstance(condition.lhs, ast.IndexExpression | ast.Identifier):
        _raise_unsupported(stmt, construct, "condition lhs must be a whole register")
    register_name, bit = _loop_operand(condition.lhs, construct, variable)
    if register_name not in scope:
        _raise_unsupported(stmt, construct, f"condition register {register_name!r} is not declared")
    value = _checked_int(condition.rhs, construct)
    if bit is not None:
        if isinstance(bit, int):
            _core_call(stmt, construct, partial(ClassicalBit, scope[register_name], bit))
        if value not in {0, 1}:
            _raise_unsupported(stmt, construct, "bit condition value must be 0 or 1")
    _require_circuit(state, stmt, construct)
    body = tuple(
        template
        for operation in body_statements
        for template in _gate_templates(operation, state, variable, stmt)
    )
    return ConditionalTemplate(register_name, value, body, bit)


def _bind_loop_variable(node: Any, variable: str, value: int) -> Any:
    """复制语法树，把循环变量换成携带原位置的整数字面量。"""
    if isinstance(node, list):
        return [_bind_loop_variable(item, variable, value) for item in node]
    if not isinstance(node, ast.QASMNode):
        return node
    if _is_variable(node, variable):
        literal = ast.IntegerLiteral(value)
        literal.span = node.span
        return literal
    # span 与 annotations 不是 init 字段，dataclasses.replace 会丢掉它们，所以逐字段复制。
    bound = copy.copy(node)
    for node_field in fields(node):
        setattr(
            bound,
            node_field.name,
            _bind_loop_variable(getattr(node, node_field.name), variable, value),
        )
    return bound


def _loop_body_allowed(operation: object) -> bool:
    if isinstance(operation, ast.ClassicalDeclaration):
        return isinstance(operation.type, ast.BitType)
    return isinstance(
        operation,
        ast.QuantumGate | ast.QuantumMeasurementStatement | ast.BranchingStatement,
    )


def _loop_register(
    operation: ast.ClassicalDeclaration, count: int, taken: set[str], loop_construct: str
) -> ClassicalRegister:
    """检查循环体寄存器的声明形态，及其名称与各轮展开名是否已被占用。"""
    base = str(operation.identifier.name)
    names = {base, *(f"{base}__{k}" for k in range(count))}
    if names & taken:
        _raise_unsupported(
            operation,
            loop_construct,
            f"loop register {base!r} or its expanded name is already declared",
        )
    taken.update(names)
    construct = "classical declaration"
    _reject_annotations(operation, construct)
    if operation.init_expression is not None:
        _raise_unsupported(operation, construct, "initialized declarations are not supported")
    if not isinstance(operation.type, ast.BitType):
        _raise_unsupported(
            operation, construct, "only bit registers may be declared in a loop body"
        )
    size = _literal_size(operation.type.size, operation, construct)
    return _core_call(operation, construct, lambda: ClassicalRegister(base, size))


def _handle_for(stmt: ast.ForInLoop, state: _ParseState) -> None:
    """解析一个有界 ``for`` 循环：检查循环头与区间，再交给 :func:`_add_loop`。"""
    construct = "for"
    _reject_annotations(stmt, construct)
    if not isinstance(stmt.type, ast.IntType) or stmt.type.size is not None:
        _raise_unsupported(stmt, construct, "loop variable must be an unsized int")
    bounds = stmt.set_declaration
    if (
        not isinstance(bounds, ast.RangeDefinition)
        or bounds.step is not None
        or bounds.start is None
        or bounds.end is None
    ):
        _raise_unsupported(stmt, construct, "loop range must be [start:stop] without a step")
    start = _integer_value(bounds.start, state, construct)
    stop = _integer_value(bounds.end, state, construct)
    variable = str(stmt.identifier.name)
    _add_loop(stmt, state, construct, variable, (start, stop), list(stmt.block))


def _handle_counter(stmt: ast.ClassicalDeclaration, state: _ParseState) -> None:
    """记下计数器声明 ``int i = a;``；它必须紧跟一个使用它的计数器 ``while``。"""
    construct = "int"
    _reject_annotations(stmt, construct)
    if (
        not isinstance(stmt.type, ast.IntType)
        or stmt.type.size is not None
        or stmt.init_expression is None
    ):
        _raise_unsupported(stmt, construct, "a loop counter must be declared as 'int i = start;'")
    name = str(stmt.identifier.name)
    if _is_reserved(name, _declared_names(state)):
        _raise_unsupported(
            stmt, construct, f"loop counter {name!r} has a declared, gate or constant name"
        )
    state.counter = stmt


def _raise_unused_counter(counter: ast.ClassicalDeclaration) -> Never:
    _raise_unsupported(counter, "int", "a loop counter must be followed directly by its while loop")


def _handle_while(stmt: ast.WhileLoop, state: _ParseState) -> None:
    """把计数器 ``while`` 解析为与等价 ``for`` 相同的循环节点。

    计数器声明必须紧邻其前。条件是 ``i < b`` 或 ``i <= b``，循环体末句是 ``i += 1``。
    末句之外的循环体按 ``for`` 的规则检查，所以其他语句不能写 ``i``。
    """
    construct = "while"
    _reject_annotations(stmt, construct)
    counter, state.counter = state.counter, None
    if counter is None:
        _raise_unsupported(
            stmt, construct, "a while loop must directly follow its counter declaration"
        )
    variable = str(counter.identifier.name)
    condition = stmt.while_condition
    if (
        not isinstance(condition, ast.BinaryExpression)
        or condition.op.name not in ("<", "<=")
        or not _is_variable(condition.lhs, variable)
    ):
        _raise_unsupported(
            condition, construct, f"loop condition must be '{variable} < b' or '{variable} <= b'"
        )
    block = list(stmt.block)
    step = block[-1] if block else None
    if not (
        isinstance(step, ast.ClassicalAssignment)
        and _is_variable(step.lvalue, variable)
        and step.op.name == "+="
        and isinstance(step.rvalue, ast.IntegerLiteral)
        and step.rvalue.value == 1
    ):
        _raise_unsupported(
            stmt, construct, f"the last statement of the loop body must be '{variable} += 1;'"
        )
    start = _integer_value(counter.init_expression, state, construct)
    stop = _integer_value(condition.rhs, state, construct)
    if condition.op.name == "<":
        stop -= 1
    _add_loop(stmt, state, construct, variable, (start, stop), block[:-1])


def _add_loop(
    stmt: ast.ForInLoop | ast.WhileLoop,
    state: _ParseState,
    construct: str,
    variable: str,
    bounds: tuple[int, int],
    body: list[ast.Statement],
) -> None:
    """检查并实例化一个区间含两端的有界循环，把循环节点记入解析状态。

    先由边界算出迭代数并检查循环体，再按取值逐轮实例化，交给既有处理器校验与添加操作。
    循环变量与已声明名称、门名或常量（如 ``x``、``pi``）同名时一律拒收。
    0 次迭代的循环只做模板检查（形状、存在性、字面量下标、元数与参数）。
    """
    start, stop = bounds
    # 不在消息中写出迭代数：超过 4300 位的整数无法转成十进制。
    if stop - start + 1 > MAX_LOOP_ITERATIONS:
        _raise_unsupported(
            stmt, construct, f"loop range has more than {MAX_LOOP_ITERATIONS} iterations"
        )
    count = max(0, stop - start + 1)
    circuit = _require_circuit(state, stmt, construct)
    if len(state.qubit_registers) != 1:
        _raise_unsupported(stmt, construct, "a loop requires exactly one quantum register")
    if _is_reserved(variable, _declared_names(state)):
        _raise_unsupported(
            stmt, construct, f"loop variable {variable!r} has a declared, gate or constant name"
        )

    for operation in body:
        if not _loop_body_allowed(operation) or any(
            isinstance(node, ast.ForInLoop) for node in _descendants(operation)
        ):
            _raise_unsupported(
                operation, construct, f"{type(operation).__name__} is not allowed in a loop body"
            )
    nodes = list(_descendants(body))
    indexes = {index for node in nodes if (index := _sole_index(node, variable)) is not None}
    for node in nodes:
        if _is_variable(node, variable) and id(node) not in indexes:
            _raise_unsupported(
                node, construct, f"loop variable {variable!r} may only be a single index"
            )

    taken = _declared_names(state)
    scope = dict(state.registers)
    registers: list[ClassicalRegister] = []
    templates: list[BodyNode] = []
    for operation in body:
        if isinstance(operation, ast.ClassicalDeclaration):
            register = _loop_register(operation, count, taken, construct)
            registers.append(register)
            scope[register.name] = register
        elif isinstance(operation, ast.QuantumGate):
            templates.extend(_gate_templates(operation, state, variable))
        elif isinstance(operation, ast.QuantumMeasurementStatement):
            templates.extend(_measure_templates(operation, state, variable, scope))
        elif isinstance(operation, ast.BranchingStatement):
            templates.append(_conditional_template(operation, state, variable, scope))
    state.loop_names.update(taken - _declared_names(state))
    state.loop_variables.add(variable)

    begin = len(circuit.gates)
    for iteration, value in enumerate(range(start, stop + 1)):
        for operation in body:
            bound = _bind_loop_variable(operation, variable, value)
            if isinstance(bound, ast.ClassicalDeclaration):
                base = str(bound.identifier.name)
                size = scope[base].size
                register = _core_call(
                    bound, construct, partial(ClassicalRegister, f"{base}__{iteration}", size)
                )
                _core_call(bound, construct, partial(circuit.add_register, register))
                state.registers[base] = register
            elif isinstance(bound, ast.QuantumGate):
                _handle_gate(bound, state)
            elif isinstance(bound, ast.QuantumMeasurementStatement):
                _handle_measurement(bound, state)
            else:
                _handle_branching(bound, state)
    for register in registers:
        state.registers.pop(register.name, None)
    loop = BoundedLoop(
        variable, start, stop, tuple(registers), tuple(templates), SourceSpan(*_span(stmt))
    )
    state.loops.append((begin, len(circuit.gates), loop))


def _declaration_name(statement: object) -> str | None:
    if isinstance(statement, ast.QubitDeclaration):
        return str(statement.qubit.name)
    if isinstance(statement, ast.ClassicalDeclaration):
        return str(statement.identifier.name)
    return None


def _looped_statement(statement: object, state: _ParseState) -> bool:
    """处理循环语法独有的语句；返回 ``True`` 表示语句已处理完毕。"""
    if state.counter is not None and not isinstance(statement, ast.WhileLoop):
        _raise_unused_counter(state.counter)
    if isinstance(statement, ast.WhileLoop):
        _handle_while(statement, state)
        return True
    if isinstance(statement, ast.ClassicalDeclaration) and isinstance(statement.type, ast.IntType):
        _handle_counter(statement, state)
        return True
    if isinstance(statement, ast.ForInLoop):
        _handle_for(statement, state)
        return True
    if isinstance(statement, ast.ConstantDeclaration):
        _handle_const(statement, state)
        return True
    if isinstance(statement, ast.BranchingStatement) and any(
        isinstance(node, ast.ForInLoop)
        for node in _descendants([statement.if_block, statement.else_block])
    ):
        _raise_unsupported(statement, "for", "a loop inside an if body is not supported")
    if isinstance(statement, ast.QubitDeclaration) and state.loops:
        _raise_unsupported(statement, "for", "every qubit declaration must precede the loops")
    name = _declaration_name(statement)
    if name in state.constants:
        _raise_unsupported(statement, "const", f"name {name!r} is already declared as a const")
    if name in state.loop_names or name in state.loop_variables:
        _raise_unsupported(statement, "for", f"name {name!r} is already used by a loop")
    return False


def _looped_circuit(state: _ParseState, circuit: Circuit) -> LoopedCircuit:
    """检查计数器与 const 都已使用，再把每个循环的平坦操作段换成循环节点。"""
    if state.counter is not None:
        _raise_unused_counter(state.counter)
    for name, (_, declaration) in state.constants.items():
        if name not in state.used_constants:
            _raise_unsupported(declaration, "const", f"const {name!r} is not used in a loop bound")
    operations: list[Operation] = []
    position = 0
    for begin, end, loop in state.loops:
        operations.extend(circuit.gates[position:begin])
        operations.append(loop)
        position = end
    operations.extend(circuit.gates[position:])
    return LoopedCircuit(circuit.num_qubits, tuple(state.registers.values()), tuple(operations))


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


def _index_to_ast(index: int | LoopIndex, variable: str) -> ast.Expression:
    if isinstance(index, LoopIndex):
        return ast.Identifier(variable)
    return ast.IntegerLiteral(index)


def _indexed_identifier(
    name: str, index: int | LoopIndex, variable: str = ""
) -> ast.IndexedIdentifier:
    return ast.IndexedIdentifier(
        name=ast.Identifier(name),
        indices=[[_index_to_ast(index, variable)]],
    )


def _register_declaration(register: ClassicalRegister) -> ast.ClassicalDeclaration:
    return ast.ClassicalDeclaration(
        type=ast.BitType(size=ast.IntegerLiteral(register.size)),
        identifier=ast.Identifier(register.name),
        init_expression=None,
    )


def _qasm_gate_name(gate: Gate | GateTemplate) -> str:
    try:
        return _QASM_NAME_BY_GATE_TYPE[gate.gate_type]
    except KeyError as exc:
        raise Qasm3UnsupportedGateError(
            f"Gate {gate.gate_type.value} has no stdgates mapping; "
            "serialization requires native-layer lowering"
        ) from exc


def _gate_to_ast(gate: Gate | GateTemplate, qubit_name: str, variable: str = "") -> ast.QuantumGate:
    return ast.QuantumGate(
        modifiers=[],
        name=ast.Identifier(_qasm_gate_name(gate)),
        arguments=[ast.FloatLiteral(parameter) for parameter in gate.params],
        qubits=[_indexed_identifier(qubit_name, qubit, variable) for qubit in gate.qubits],
        duration=None,
    )


def _measure_to_ast(
    qubit: int | LoopIndex,
    target: tuple[str, int | LoopIndex],
    qubit_name: str,
    variable: str = "",
) -> ast.QuantumMeasurementStatement:
    return ast.QuantumMeasurementStatement(
        measure=ast.QuantumMeasurement(qubit=_indexed_identifier(qubit_name, qubit, variable)),
        target=_indexed_identifier(*target, variable),
    )


def _conditional_to_ast(
    condition: tuple[str, int | LoopIndex | None, int],
    body: tuple[Gate, ...] | tuple[GateTemplate, ...],
    qubit_name: str,
    variable: str = "",
) -> ast.BranchingStatement:
    register, bit, value = condition
    lhs: ast.Expression = ast.Identifier(register)
    if bit is not None:
        lhs = ast.IndexExpression(collection=lhs, index=[_index_to_ast(bit, variable)])
    return ast.BranchingStatement(
        condition=ast.BinaryExpression(
            op=ast.BinaryOperator["=="],
            lhs=lhs,
            rhs=ast.IntegerLiteral(value),
        ),
        if_block=[_gate_to_ast(gate, qubit_name, variable) for gate in body],
        else_block=[],
    )


def _template_to_ast(node: BodyNode, qubit_name: str, variable: str) -> ast.Statement:
    if isinstance(node, GateTemplate):
        return _gate_to_ast(node, qubit_name, variable)
    if isinstance(node, MeasureTemplate):
        return _measure_to_ast(node.qubit, (node.register, node.bit), qubit_name, variable)
    return _conditional_to_ast(
        (node.register, node.bit, node.value), node.body, qubit_name, variable
    )


def _loop_to_ast(loop: BoundedLoop, qubit_name: str) -> ast.ForInLoop:
    """把循环写成 ``for int v in [start:stop]``；计数器 ``while`` 解析后也是此节点。"""
    block: list[ast.Statement] = [_register_declaration(register) for register in loop.registers]
    block.extend(_template_to_ast(node, qubit_name, loop.variable) for node in loop.body)
    return ast.ForInLoop(
        type=ast.IntType(size=None),
        identifier=ast.Identifier(loop.variable),
        set_declaration=ast.RangeDefinition(
            start=ast.IntegerLiteral(loop.start),
            end=ast.IntegerLiteral(loop.stop),
            step=None,
        ),
        block=block,
    )


def _operation_to_ast(operation: Operation, qubit_name: str) -> ast.Statement:
    if isinstance(operation, Gate):
        return _gate_to_ast(operation, qubit_name)
    if isinstance(operation, Measure):
        target = operation.target
        return _measure_to_ast(operation.qubit, (target.register.name, target.index), qubit_name)
    if isinstance(operation, Conditional):
        condition = (operation.register.name, operation.bit_index, operation.value)
        return _conditional_to_ast(condition, operation.body, qubit_name)
    if isinstance(operation, BoundedLoop):
        return _loop_to_ast(operation, qubit_name)
    raise Qasm3UnsupportedConstructError(
        f"Circuit operation {type(operation).__name__} is not serializable"
    )


def from_qasm3(src: str) -> Circuit:
    """把一段受支持的 OpenQASM 程序解析为电路，否则大声拒绝。"""
    # 不委托 parse_qasm3：多一层栈帧会让递归上限附近两个入口的拒收结果不同。
    try:
        return _parse_source(src).circuit
    except RecursionError as exc:
        raise Qasm3ParseError("source at 1:1: expression nesting exceeds parser limit") from exc


def parse_qasm3(src: str) -> ParsedQasm3:
    """一次解析同时得到电路与源码旁表；接受面与拒收面和 ``from_qasm3`` 完全相同。

    Args:
        src: OpenQASM 2/3 源码，版本头可缺省。

    Returns:
        电路、与 ``circuit.gates`` 逐位对齐的 ``OperationOrigin`` 元组，以及声明的版本。

    Raises:
        Qasm3ParseError: 语法错误、版本不受支持、表达式嵌套过深，
            或整数字面量、qubit 总数无法写成十进制。
        Qasm3UnsupportedConstructError: 构造、门或操作数不受支持。
    """
    try:
        return _parse_source(src)
    except RecursionError as exc:
        raise Qasm3ParseError("source at 1:1: expression nesting exceeds parser limit") from exc


def parse_looped_qasm3(src: str) -> ParsedLoopedQasm3:
    """解析含有界 ``for`` 循环与 ``const int`` 的程序，保留循环结构。

    不含循环的程序与 ``parse_qasm3`` 的接受面相同。循环受以下限制：

    1. 区间写成 ``[start:stop]``，两端含在内，不带步长；边界是整数常量表达式。
    2. 迭代数不超过 :data:`~qaiji.core.loop.MAX_LOOP_ITERATIONS`，在实例化前由边界算出。
    3. 程序只有一个量子寄存器，并且在所有循环之前声明。
    4. 循环体只含门、测量、``if`` 与 ``bit`` 声明；循环不得嵌套，也不得位于 ``if`` 体内。
    5. 循环变量只能作单个下标；与已声明名称、门名或常量（如 ``x``、``pi``）同名时拒收。
    6. 循环体的 ``bit`` 寄存器第 ``k`` 轮展开为 ``<名称>__k``，不得与已声明名称相同。
    7. ``const`` 必须是不带宽度的 ``int``，并且必须用于循环边界。

    Args:
        src: OpenQASM 3 源码，版本头可缺省。

    Returns:
        保留循环节点的电路，以及声明的版本。

    Raises:
        Qasm3ParseError: 语法错误、版本不受支持、表达式嵌套过深，或整数无法写成十进制。
        Qasm3UnsupportedConstructError: 构造、门或操作数不受支持，或循环超出上述限制。
    """
    try:
        return _parse_source(src, allow_loops=True)
    except RecursionError as exc:
        raise Qasm3ParseError("source at 1:1: expression nesting exceeds parser limit") from exc


@overload
def _parse_source(src: str) -> ParsedQasm3: ...


@overload
def _parse_source(src: str, *, allow_loops: Literal[True]) -> ParsedLoopedQasm3: ...


def _parse_source(src: str, *, allow_loops: bool = False) -> ParsedQasm3 | ParsedLoopedQasm3:
    try:
        program = openqasm3.parse(src, ignore_version=True)
    except QASM3ParsingError as exc:
        raise Qasm3ParseError(_message(src, "source", "invalid OpenQASM syntax")) from exc
    except ValueError as exc:
        # 解析器内部的 ValueError，典型是十进制字面量超出解释器的整数位数上限。
        raise Qasm3ParseError(_message(src, "source", str(exc))) from exc
    except AttributeError as exc:
        if re.sub(r"//[^\n]*|/\*.*?\*/", "", src, flags=re.DOTALL).strip():
            raise Qasm3ParseError(_message(src, "source", "invalid OpenQASM syntax")) from exc
        program = ast.Program(statements=[])

    _validate_version(program)
    state = _ParseState(total_qubits=_count_qubits(program.statements))
    for statement_index, statement in enumerate(program.statements):
        state.statement_index = statement_index
        if allow_loops and _looped_statement(statement, state):
            continue
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
    if allow_loops:
        return ParsedLoopedQasm3(_looped_circuit(state, state.circuit), program.version)
    return ParsedQasm3(state.circuit, tuple(state.origins), program.version)


def _check_writable(circuit: LoopedCircuit) -> None:
    """检查循环电路写出的文本能被 :func:`parse_looped_qasm3` 接受。

    先展开，检查寄存器名冲突与比特越界。再按解析器的规则检查每个循环变量名。

    Raises:
        LoopedCircuitError: 展开失败，或循环变量名不是标识符、与之前声明的名称、
            本循环的寄存器名、门名或内置常量相同。
    """
    try:
        circuit.expand()
    except LoopedCircuitError:
        raise
    except ValueError as fault:
        raise LoopedCircuitError(f"LoopedCircuit cannot be expanded: {fault}") from fault
    taken = {register.name for register in circuit.cregs}
    for loop in circuit.operations:
        if not isinstance(loop, BoundedLoop):
            continue
        own = {register.name for register in loop.registers}
        if not loop.variable.isidentifier() or _is_reserved(loop.variable, taken | own):
            raise LoopedCircuitError(
                f"loop variable {loop.variable!r} is not an identifier or has a declared, "
                "gate or constant name"
            )
        taken |= own
        taken.update(f"{name}__{k}" for name in own for k in range(len(loop.values)))


def to_qasm3(circuit: Circuit | LoopedCircuit) -> str:
    """把一个受支持的电路序列化为规范化的 OpenQASM 3 源码。

    循环写成 ``for int v in [start:stop]``，循环体寄存器在循环体内声明；计数器 ``while``
    解析后与等价 ``for`` 是同一个节点，所以也写成 ``for``。量子寄存器名避开全部经典寄存器名
    与循环变量名。不含循环的电路输出与只接受 :class:`Circuit` 时逐字节相同。

    Raises:
        LoopedCircuitError: 循环电路写出的文本会被 :func:`parse_looped_qasm3` 拒收。
    """
    if isinstance(circuit, LoopedCircuit):
        _check_writable(circuit)
        operations: tuple[Operation, ...] = circuit.operations
    else:
        operations = tuple(circuit.gates)
    loops = [operation for operation in operations if isinstance(operation, BoundedLoop)]
    reserved = {register.name for register in circuit.cregs}
    reserved.update(loop.variable for loop in loops)
    reserved.update(register.name for loop in loops for register in loop.registers)
    qubit_name = "q"
    suffix = 0
    while qubit_name in reserved:
        qubit_name = f"q{suffix}"
        suffix += 1
    statements: list[ast.Statement | ast.Pragma] = [
        ast.Include("stdgates.inc"),
        ast.QubitDeclaration(
            qubit=ast.Identifier(qubit_name),
            size=ast.IntegerLiteral(circuit.num_qubits),
        ),
    ]
    statements.extend(_register_declaration(register) for register in circuit.cregs)
    statements.extend(_operation_to_ast(operation, qubit_name) for operation in operations)
    return openqasm3.dumps(ast.Program(statements=statements, version="3.0"))
