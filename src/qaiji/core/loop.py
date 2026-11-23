# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""有界循环的电路容器，以及把它展开成平坦电路的规则。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Never

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
