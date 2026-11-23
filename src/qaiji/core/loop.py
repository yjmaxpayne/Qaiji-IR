# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""有界循环的电路容器，以及把它展开成平坦电路的规则。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Never

from qaiji.core._codec import canonical_json, f64_from_hex, f64_to_hex
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.exceptions import LoopedCircuitError, LoopNotExpandedError

__all__ = [
    "BoundedLoop",
    "ConditionalTemplate",
    "ExpandedCircuit",
    "GateTemplate",
    "LoopIndex",
    "LoopedCircuit",
    "MeasureTemplate",
    "OperationProvenance",
    "SourceSpan",
]

LOOPED_CIRCUIT_SCHEMA = "qaiji.looped_circuit/0.1"


@dataclass(frozen=True, slots=True)
class LoopIndex:
    """把循环变量用作整数下标。"""


QubitRef = int | LoopIndex
BitRef = int | LoopIndex


@dataclass(frozen=True, slots=True)
class GateTemplate:
    """循环体内的门；比特可以是循环变量。"""

    gate_type: GateType
    qubits: tuple[QubitRef, ...]
    params: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class MeasureTemplate:
    """循环体内的测量；寄存器按名称引用。"""

    qubit: QubitRef
    register: str
    bit: BitRef


@dataclass(frozen=True, slots=True)
class ConditionalTemplate:
    """循环体内的条件体；寄存器按名称引用。"""

    register: str
    value: int
    body: tuple[GateTemplate, ...]
    bit: BitRef | None = None


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """节点在源文本中的位置。不参与相等比较。"""

    line: int
    column: int
    end_line: int
    end_column: int


BodyNode = GateTemplate | MeasureTemplate | ConditionalTemplate


@dataclass(frozen=True, slots=True)
class BoundedLoop:
    """整数区间上的有界循环。区间含两端。"""

    variable: str
    start: int
    stop: int
    """上界，含在区间内。``stop < start`` 表示 0 次迭代。"""
    registers: tuple[ClassicalRegister, ...]
    """循环体声明的寄存器。第 ``k`` 次迭代展开为 ``<名称>__k``。"""
    body: tuple[BodyNode, ...]
    span: SourceSpan = field(compare=False)

    @property
    def values(self) -> tuple[int, ...]:
        """按迭代顺序返回循环变量的取值。"""
        return tuple(range(self.start, self.stop + 1))


@dataclass(frozen=True, slots=True)
class OperationProvenance:
    """展开后一个操作的来源：region 结构路径与迭代序号。"""

    region_id: str | None
    iteration: int | None


@dataclass(frozen=True)
class ExpandedCircuit:
    """展开结果；``provenance`` 与 ``circuit.gates`` 逐项对齐。"""

    circuit: Circuit
    provenance: tuple[OperationProvenance, ...]


Operation = Gate | Measure | Conditional | BoundedLoop


@dataclass(frozen=True)
class LoopedCircuit:
    """含有界循环的电路。读取平坦操作序列前须先调用 :meth:`expand`。

    Example:
        >>> from qaiji.core.circuit import GateType
        >>> loop = BoundedLoop("i", 0, 1, (), (GateTemplate(GateType.X, (LoopIndex(),)),),
        ...                    SourceSpan(1, 0, 1, 0))
        >>> len(LoopedCircuit(2, (), (loop,)).expand().circuit.gates)
        2
    """

    num_qubits: int
    cregs: tuple[ClassicalRegister, ...]
    operations: tuple[Operation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cregs", tuple(self.cregs))
        object.__setattr__(self, "operations", tuple(self.operations))

    @property
    def gates(self) -> Never:
        """总是抛出 :class:`LoopNotExpandedError`。"""
        raise LoopNotExpandedError("LoopedCircuit has no flat gate list; call expand() first")

    def expand(self) -> ExpandedCircuit:
        """按迭代顺序展开全部循环。

        寄存器顺序：先是顶层寄存器，再按循环顺序、迭代序号、循环内声明顺序排列。

        Returns:
            平坦电路，以及与 ``circuit.gates`` 对齐的来源。

        Raises:
            LoopedCircuitError: 展开名与已声明名称或其他展开名相同。
        """
        circuit = Circuit(self.num_qubits)
        for register in self.cregs:
            circuit.add_register(register)
        scopes = self._declare_loop_registers(circuit)

        provenance: list[OperationProvenance] = []
        for position, node in enumerate(self.operations):
            if isinstance(node, BoundedLoop):
                for iteration, value in enumerate(node.values):
                    scope = scopes[(position, iteration)]
                    for body_position, template in enumerate(node.body):
                        _add(circuit, _instantiate(template, value, scope))
                        region = f"loop:{position}"
                        if isinstance(template, ConditionalTemplate):
                            region += f"/if:{body_position}"
                        provenance.append(OperationProvenance(region, iteration))
                continue
            _add(circuit, node)
            region_id = f"if:{position}" if isinstance(node, Conditional) else None
            provenance.append(OperationProvenance(region_id, None))
        return ExpandedCircuit(circuit, tuple(provenance))

    def _declare_loop_registers(
        self, circuit: Circuit
    ) -> dict[tuple[int, int], dict[str, ClassicalRegister]]:
        top_level = {register.name: register for register in self.cregs}
        loops = [
            (position, node)
            for position, node in enumerate(self.operations)
            if isinstance(node, BoundedLoop)
        ]
        taken = set(top_level)
        taken.update(register.name for _, loop in loops for register in loop.registers)

        scopes: dict[tuple[int, int], dict[str, ClassicalRegister]] = {}
        for position, loop in loops:
            for iteration in range(len(loop.values)):
                scope = dict(top_level)
                for register in loop.registers:
                    name = f"{register.name}__{iteration}"
                    if name in taken:
                        raise LoopedCircuitError(
                            f"Expanded register name {name!r} is already declared"
                        )
                    taken.add(name)
                    scope[register.name] = ClassicalRegister(name, register.size)
                    circuit.add_register(scope[register.name])
                scopes[(position, iteration)] = scope
        return scopes

    def to_json(self) -> bytes:
        """编码为规范 JSON，schema 为 ``qaiji.looped_circuit/0.1``。

        浮点参数写成 binary64 十六进制。``span`` 写入输出，尽管它不参与相等比较。

        Returns:
            UTF-8 字节；同一电路在任何进程中得到相同字节。
        """
        return canonical_json(
            {
                "schema": LOOPED_CIRCUIT_SCHEMA,
                "num_qubits": self.num_qubits,
                "cregs": [_register_tree(register) for register in self.cregs],
                "operations": [_operation_tree(node) for node in self.operations],
            }
        )

    @classmethod
    def from_json(cls, data: bytes) -> LoopedCircuit:
        """解码 :meth:`to_json` 的输出。

        Args:
            data: schema 为 ``qaiji.looped_circuit/0.1`` 的 UTF-8 JSON。

        Returns:
            与编码前相等的电路，``span`` 一并恢复。

        Raises:
            LoopedCircuitError: 文档不是合法 JSON、schema 不同、某个对象有未知键或缺键，
                或字段值不合法。
        """
        try:
            tree = json.loads(data)
        except ValueError as exc:
            raise LoopedCircuitError(f"document is not valid JSON: {exc}") from exc
        found = tree.get("schema") if isinstance(tree, dict) else None
        if found != LOOPED_CIRCUIT_SCHEMA:
            raise LoopedCircuitError(
                f"unknown schema {found!r}; expected {LOOPED_CIRCUIT_SCHEMA!r}"
            )
        tree = _object("circuit", tree, {"schema", "num_qubits", "cregs", "operations"})
        try:
            return cls(
                tree["num_qubits"],
                tuple(_register_of(item) for item in tree["cregs"]),
                tuple(_operation_of(item) for item in tree["operations"]),
            )
        except LoopedCircuitError:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise LoopedCircuitError(f"malformed document: {exc}") from exc


def _register_tree(register: ClassicalRegister) -> dict[str, Any]:
    return {"name": register.name, "size": register.size}


def _ref_tree(ref: int | LoopIndex | None) -> Any:
    return {"kind": "loop_index"} if isinstance(ref, LoopIndex) else ref


def _gate_tree(gate: Gate | GateTemplate) -> dict[str, Any]:
    return {
        "kind": "gate",
        "gate_type": gate.gate_type.value,
        "qubits": [_ref_tree(qubit) for qubit in gate.qubits],
        "params": [f64_to_hex(param) for param in gate.params],
    }


def _template_tree(template: BodyNode) -> dict[str, Any]:
    if isinstance(template, GateTemplate):
        return _gate_tree(template)
    if isinstance(template, MeasureTemplate):
        return {
            "kind": "measure",
            "qubit": _ref_tree(template.qubit),
            "register": template.register,
            "bit": _ref_tree(template.bit),
        }
    return {
        "kind": "if",
        "register": template.register,
        "value": template.value,
        "bit": _ref_tree(template.bit),
        "body": [_gate_tree(gate) for gate in template.body],
    }


def _operation_tree(node: Operation) -> dict[str, Any]:
    if isinstance(node, Gate):
        return _gate_tree(node)
    if isinstance(node, Measure):
        return {
            "kind": "measure",
            "qubit": node.qubit,
            "register": _register_tree(node.target.register),
            "bit": node.target.index,
        }
    if isinstance(node, Conditional):
        return {
            "kind": "if",
            "register": _register_tree(node.register),
            "value": node.value,
            "bit": node.bit_index,
            "body": [_gate_tree(gate) for gate in node.body],
        }
    span = node.span
    return {
        "kind": "loop",
        "variable": node.variable,
        "start": node.start,
        "stop": node.stop,
        "registers": [_register_tree(register) for register in node.registers],
        "body": [_template_tree(template) for template in node.body],
        "span": {
            "line": span.line,
            "column": span.column,
            "end_line": span.end_line,
            "end_column": span.end_column,
        },
    }


_KEYS = {
    "gate": {"kind", "gate_type", "qubits", "params"},
    "measure": {"kind", "qubit", "register", "bit"},
    "if": {"kind", "register", "value", "bit", "body"},
    "loop": {"kind", "variable", "start", "stop", "registers", "body", "span"},
}


def _object(where: str, tree: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(tree, dict):
        raise LoopedCircuitError(f"{where} must be a JSON object")
    missing, unknown = keys - set(tree), set(tree) - keys
    if missing or unknown:
        raise LoopedCircuitError(
            f"{where}: missing keys {sorted(missing)}, unknown {sorted(unknown)}"
        )
    return tree


def _node(tree: Any) -> tuple[str, dict[str, Any]]:
    kind = tree.get("kind") if isinstance(tree, dict) else None
    if kind not in _KEYS:
        raise LoopedCircuitError(f"unknown node kind {kind!r}")
    return kind, _object(kind, tree, _KEYS[kind])


def _register_of(tree: Any) -> ClassicalRegister:
    tree = _object("register", tree, {"name", "size"})
    return ClassicalRegister(tree["name"], tree["size"])


def _ref_of(tree: Any) -> int | LoopIndex:
    if isinstance(tree, int):
        return tree
    tree = _object("loop index", tree, {"kind"})
    if tree["kind"] != "loop_index":
        raise LoopedCircuitError(f"unknown index kind {tree['kind']!r}")
    return LoopIndex()


def _gate_node(tree: Any) -> dict[str, Any]:
    kind, node = _node(tree)
    if kind != "gate":
        raise LoopedCircuitError(f"conditional body holds a {kind!r} node; expected 'gate'")
    return node


def _params_of(tree: list[Any]) -> tuple[float, ...]:
    params = []
    for text in tree:
        value = f64_from_hex(text)
        if value is None:
            raise LoopedCircuitError(f"params must be 16-digit binary64 hex strings, got {text!r}")
        params.append(value)
    return tuple(params)


def _gate_of(tree: Any) -> Gate:
    tree = _gate_node(tree)
    return Gate(GateType(tree["gate_type"]), tuple(tree["qubits"]), _params_of(tree["params"]))


def _gate_template_of(tree: Any) -> GateTemplate:
    tree = _gate_node(tree)
    qubits = tuple(_ref_of(qubit) for qubit in tree["qubits"])
    return GateTemplate(GateType(tree["gate_type"]), qubits, _params_of(tree["params"]))


def _template_of(tree: Any) -> BodyNode:
    kind, tree = _node(tree)
    if kind == "gate":
        return _gate_template_of(tree)
    if kind == "measure":
        return MeasureTemplate(_ref_of(tree["qubit"]), tree["register"], _ref_of(tree["bit"]))
    if kind == "if":
        bit = None if tree["bit"] is None else _ref_of(tree["bit"])
        body = tuple(_gate_template_of(item) for item in tree["body"])
        return ConditionalTemplate(tree["register"], tree["value"], body, bit)
    raise LoopedCircuitError("a loop body cannot hold a loop")


def _operation_of(tree: Any) -> Operation:
    kind, tree = _node(tree)
    if kind == "gate":
        return _gate_of(tree)
    if kind == "measure":
        target = ClassicalBit(_register_of(tree["register"]), tree["bit"])
        return Measure(tree["qubit"], target)
    if kind == "if":
        body = tuple(_gate_of(item) for item in tree["body"])
        return Conditional(_register_of(tree["register"]), tree["value"], body, tree["bit"])
    span = _object("span", tree["span"], {"line", "column", "end_line", "end_column"})
    return BoundedLoop(
        tree["variable"],
        tree["start"],
        tree["stop"],
        tuple(_register_of(item) for item in tree["registers"]),
        tuple(_template_of(item) for item in tree["body"]),
        SourceSpan(span["line"], span["column"], span["end_line"], span["end_column"]),
    )


def _add(circuit: Circuit, node: Gate | Measure | Conditional) -> None:
    if isinstance(node, Gate):
        circuit.add_gate(node)
    elif isinstance(node, Measure):
        circuit.add_measure(node)
    else:
        circuit.add_conditional(node)


def _index(ref: int | LoopIndex, value: int) -> int:
    return value if isinstance(ref, LoopIndex) else ref


def _register(scope: dict[str, ClassicalRegister], name: str) -> ClassicalRegister:
    if name not in scope:
        raise LoopedCircuitError(f"Loop body uses undeclared register {name!r}")
    return scope[name]


def _gate(template: GateTemplate, value: int) -> Gate:
    qubits = tuple(_index(qubit, value) for qubit in template.qubits)
    return Gate(template.gate_type, qubits, template.params)


def _instantiate(
    template: BodyNode, value: int, scope: dict[str, ClassicalRegister]
) -> Gate | Measure | Conditional:
    if isinstance(template, GateTemplate):
        return _gate(template, value)
    if isinstance(template, MeasureTemplate):
        target = ClassicalBit(_register(scope, template.register), _index(template.bit, value))
        return Measure(_index(template.qubit, value), target)
    bit = None if template.bit is None else _index(template.bit, value)
    body = tuple(_gate(gate, value) for gate in template.body)
    return Conditional(_register(scope, template.register), template.value, body, bit)
