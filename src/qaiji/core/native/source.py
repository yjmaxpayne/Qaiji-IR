# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Validated private snapshots of mutable source circuits."""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.program import compute_kernel_ref

from .model import _LIMIT, _fail

_GATE_ARITY = MappingProxyType(
    {
        GateType.I: (1, 0),
        GateType.X: (1, 0),
        GateType.Y: (1, 0),
        GateType.Z: (1, 0),
        GateType.H: (1, 0),
        GateType.S: (1, 0),
        GateType.T: (1, 0),
        GateType.RX: (1, 1),
        GateType.RY: (1, 1),
        GateType.RZ: (1, 1),
        GateType.U3: (1, 3),
        GateType.RX90: (1, 1),
        GateType.RX180: (1, 1),
        GateType.CNOT: (2, 0),
        GateType.CX: (2, 0),
        GateType.CZ: (2, 0),
        GateType.SWAP: (2, 0),
        GateType.ISWAP: (2, 0),
        GateType.SQISWAP: (2, 0),
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class _SourceSnapshot:
    num_qubits: int
    cregs: tuple[ClassicalRegister, ...]
    gates: tuple[Gate | Measure | Conditional, ...]
    source_kernel_ref: str


def _sequence(value: Any, path: str) -> tuple[Any, ...]:
    if type(value) not in (list, tuple):
        _fail("source_container", path, "Expected a list or tuple.")
    return tuple(value)


def _integer(value: Any, path: str, code: str, minimum: int = 0) -> int:
    if type(value) is not int:
        _fail(code, path, "Expected a built-in integer.")
    if abs(value) >= _LIMIT:
        _fail("range", path, "Integer exceeds the decimal digit budget.")
    if value < minimum:
        _fail(code, path, "Integer is below its allowed minimum.")
    return cast(int, value)


def _register(value: Any, path: str, code: str) -> ClassicalRegister:
    if not isinstance(value, ClassicalRegister):
        _fail(code, path, "Expected a classical register.")
    name = value.name
    if type(name) is not str or not name.isidentifier():
        _fail(code, path + ".name", "Expected a built-in register identifier.")
    size = _integer(value.size, path + ".size", code, 1)
    return ClassicalRegister(name, size)


def _reference(value: Any, path: str, registers: dict[str, ClassicalRegister]) -> ClassicalRegister:
    register = _register(value, path, "source_reference")
    declared = registers.get(register.name)
    if declared is None or declared.size != register.size:
        _fail("source_reference", path, "Register declaration does not match this reference.")
    return declared


def _qubit(value: Any, path: str, width: int) -> int:
    result = _integer(value, path, "source_qubit")
    if result >= width:
        _fail("source_qubit", path, "Qubit is outside the source width.")
    return result


def _parameter(value: Any, path: str) -> int | float:
    if type(value) not in (int, float):
        _fail("source_parameter", path, "Expected a built-in number.")
    if type(value) is int and abs(value) >= _LIMIT:
        _fail("range", path, "Integer exceeds the decimal digit budget.")
    try:
        number = float(value)
    except OverflowError:
        _fail("source_parameter", path, "Parameter cannot be represented as binary64.")
    if not math.isfinite(number):
        _fail("source_parameter", path, "Parameter must be finite.")
    if abs(number) > math.tau:
        _fail("source_angle", path, "Angle exceeds one full turn.")
    return cast(int | float, value)


def _gate(value: Any, path: str, width: int) -> Gate:
    if not isinstance(value, Gate):
        _fail("source_node", path, "Expected a gate.")
    kind = value.gate_type
    if type(kind) is not GateType:
        _fail("source_node", path + ".gate_type", "Unknown source gate kind.")
    qubits = _sequence(value.qubits, path + ".qubits")
    params = _sequence(value.params, path + ".params")
    qubit_count, parameter_count = _GATE_ARITY[kind]
    if len(qubits) != qubit_count:
        _fail("source_arity", path + ".qubits", "Incorrect gate qubit count.")
    qubits = tuple(_qubit(item, f"{path}.qubits[{i}]", width) for i, item in enumerate(qubits))
    if len(set(qubits)) != len(qubits):
        _fail("source_qubit", path + ".qubits", "Gate qubits must be distinct.")
    if len(params) != parameter_count:
        _fail("source_parameter", path + ".params", "Incorrect gate parameter count.")
    params = tuple(_parameter(item, f"{path}.params[{i}]") for i, item in enumerate(params))
    # The legacy constructor reads mutable registries. These fields have already
    # been checked against the fixed native source contract above.
    result = object.__new__(Gate)
    object.__setattr__(result, "gate_type", kind)
    object.__setattr__(result, "qubits", qubits)
    object.__setattr__(result, "params", params)
    return result


def _node(
    value: Any, path: str, width: int, registers: dict[str, ClassicalRegister]
) -> Gate | Measure | Conditional:
    if isinstance(value, Gate):
        return _gate(value, path, width)
    if isinstance(value, Measure):
        qubit = _qubit(value.qubit, path + ".qubit", width)
        target = value.target
        if not isinstance(target, ClassicalBit):
            _fail("source_reference", path + ".target", "Expected a classical bit reference.")
        register = _reference(target.register, path + ".target.register", registers)
        index = _integer(target.index, path + ".target.index", "source_reference")
        if index >= register.size:
            _fail("source_reference", path + ".target.index", "Bit is outside its register.")
        return Measure(qubit, ClassicalBit(register, index))
    if isinstance(value, Conditional):
        register = _reference(value.register, path + ".register", registers)
        condition = _integer(value.value, path + ".value", "source_condition")
        if condition.bit_length() > register.size:
            _fail("source_condition", path + ".value", "Condition does not fit its register.")
        body = _sequence(value.body, path + ".body")
        return Conditional(
            register,
            condition,
            tuple(_gate(item, f"{path}.body[{i}]", width) for i, item in enumerate(body)),
        )
    _fail("source_node", path, "Unknown source operation.")


def _capture_source(circuit: Circuit) -> _SourceSnapshot:
    """Copy fixed base fields once and bind the existing identity recipe to them."""
    if not isinstance(circuit, Circuit):
        _fail("source_type", "$", "Expected a Circuit.")
    width = _integer(circuit.num_qubits, "$.num_qubits", "source_qubit", 1)
    source_registers = _sequence(circuit.cregs, "$.cregs")
    source_nodes = _sequence(circuit.gates, "$.gates")
    registers: dict[str, ClassicalRegister] = {}
    for i, value in enumerate(source_registers):
        register = _register(value, f"$.cregs[{i}]", "source_register")
        if register.name in registers:
            _fail("source_register", f"$.cregs[{i}].name", "Duplicate register declaration.")
        registers[register.name] = register
    nodes = tuple(
        _node(value, f"$.gates[{i}]", width, registers) for i, value in enumerate(source_nodes)
    )
    copied = Circuit(width)
    copied.cregs = list(registers.values())
    copied.gates = list(nodes)
    return _SourceSnapshot(
        num_qubits=width,
        cregs=tuple(copied.cregs),
        gates=nodes,
        source_kernel_ref=compute_kernel_ref(copied),
    )
