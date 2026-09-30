# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""不可变的门值对象，以及电路级的量子容器。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from qaiji.constants import DEFAULT_TOLERANCE

if TYPE_CHECKING:
    from qaiji.core.classical import ClassicalRegister, Conditional, Measure

__all__ = [
    "CANONICAL_ALIASES",
    "PARAM_REQUIREMENTS",
    "SINGLE_QUBIT_GATES",
    "TWO_QUBIT_GATES",
    "Circuit",
    "Gate",
    "GateType",
]


class GateType(Enum):
    """电路级 IR 能够表示的门类型。"""

    I = "I"  # noqa: E741 - 恒等门的标准记法
    X = "X"
    Y = "Y"
    Z = "Z"
    H = "H"
    S = "S"
    T = "T"
    RX = "RX"
    RY = "RY"
    RZ = "RZ"
    U3 = "U3"
    CNOT = "CNOT"
    CX = "CX"
    CZ = "CZ"
    SWAP = "SWAP"
    RX90 = "RX90"
    RX180 = "RX180"
    ISWAP = "ISWAP"
    SQISWAP = "SQISWAP"


SINGLE_QUBIT_GATES: frozenset[GateType] = frozenset(
    {
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
)
"""恰好作用在一个量子比特上的门类型。"""

TWO_QUBIT_GATES: frozenset[GateType] = frozenset(
    {
        GateType.CNOT,
        GateType.CX,
        GateType.CZ,
        GateType.SWAP,
        GateType.ISWAP,
        GateType.SQISWAP,
    }
)
"""恰好作用在两个不同量子比特上的门类型。"""

PARAM_REQUIREMENTS: dict[GateType, tuple[int, int]] = {
    GateType.I: (0, 0),
    GateType.X: (0, 0),
    GateType.Y: (0, 0),
    GateType.Z: (0, 0),
    GateType.H: (0, 0),
    GateType.S: (0, 0),
    GateType.T: (0, 0),
    GateType.RX: (1, 1),
    GateType.RY: (1, 1),
    GateType.RZ: (1, 1),
    GateType.U3: (3, 3),
    GateType.CNOT: (0, 0),
    GateType.CX: (0, 0),
    GateType.CZ: (0, 0),
    GateType.SWAP: (0, 0),
    GateType.RX90: (1, 1),
    GateType.RX180: (1, 1),
    GateType.ISWAP: (0, 0),
    GateType.SQISWAP: (0, 0),
}
"""每种门类型的参数个数上下界（闭区间）。"""

CANONICAL_ALIASES: dict[GateType, GateType] = {
    GateType.CNOT: GateType.CX,
}
"""结构上不同、但共享同一规范形式的门写法。"""

_ROTATION_GATES = frozenset({GateType.RX, GateType.RY, GateType.RZ})


def _tau_multiple_exponent(theta: float, *, atol: float = DEFAULT_TOLERANCE) -> int | None:
    """当 theta 为 2*pi*k 时返回绕数 k，否则返回 None。

    这是"theta == 0 (mod 2*pi)"这一判断的唯一真相来源：门折叠、注册表中 RZ 的特例、
    保持性相位规则三者都在问同一个问题，绝不能给出不同的答案。用 ``k * tau`` 反推
    残差可以让判据在任意量级下都保持精确，而取模的做法会随 theta 增大不断累积表示
    误差。

    Args:
        theta: 以弧度表示的角度，保持书写时的原值（未预先归一化）。
        atol: 残差的绝对容差。

    Returns:
        绕数 k；theta 不是整圈时返回 None。注意 k == 0 是合法结果：调用方必须用
        ``is not None`` 来判断。
    """
    winding = round(theta / math.tau)
    return winding if abs(theta - winding * math.tau) <= atol else None


@dataclass(frozen=True)
class Gate:
    """作用在一个或多个量子比特上的不可变门。"""

    gate_type: GateType
    qubits: tuple[int, ...]
    params: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        """归一化序列，并拒绝非法的门状态。"""
        object.__setattr__(self, "qubits", tuple(self.qubits))
        object.__setattr__(self, "params", tuple(self.params))

        if not self.qubits:
            raise ValueError("Gate must act on at least one qubit")
        if self.gate_type in SINGLE_QUBIT_GATES and len(self.qubits) != 1:
            raise ValueError(f"Single-qubit gate {self.gate_type.value} requires one qubit")
        if self.gate_type in TWO_QUBIT_GATES and len(self.qubits) != 2:
            raise ValueError(f"Two-qubit gate {self.gate_type.value} requires two qubits")

        minimum, maximum = PARAM_REQUIREMENTS[self.gate_type]
        if not minimum <= len(self.params) <= maximum:
            raise ValueError(
                f"Gate {self.gate_type.value} requires {minimum}-{maximum} parameters, "
                f"got {len(self.params)}"
            )
        if any(not math.isfinite(param) for param in self.params):
            raise ValueError("Gate parameters must be finite")
        if len(self.qubits) != len(set(self.qubits)):
            raise ValueError("Gate qubits must be unique")

    def canonicalize(self) -> Gate:
        """返回规范形式的门，且不改变结构相等性。"""
        gate_type = CANONICAL_ALIASES.get(self.gate_type, self.gate_type)
        params = self.params

        if gate_type in _ROTATION_GATES:
            # 折叠判据读取的是书写时的原始角度：先归一化会让大量级下的整圈被取模
            # 残差掩盖。归一化只施加于存活下来的那个旋转门。
            if _tau_multiple_exponent(params[0]) is not None:
                return Gate(GateType.I, self.qubits)
            params = (params[0] % math.tau, *params[1:])

        return Gate(gate_type, self.qubits, params)


def _node_eq(
    left: Gate | Measure | Conditional,
    right: Gate | Measure | Conditional,
) -> bool:
    """比较操作节点，并在所有门体内部一致地施加容差。"""
    from qaiji.core.classical import Conditional, Measure

    if isinstance(left, Gate) and isinstance(right, Gate):
        return (
            left.gate_type is right.gate_type
            and left.qubits == right.qubits
            and len(left.params) == len(right.params)
            and all(
                abs(left_param - right_param) <= DEFAULT_TOLERANCE
                for left_param, right_param in zip(left.params, right.params, strict=True)
            )
        )
    if isinstance(left, Measure) and isinstance(right, Measure):
        return left == right
    if isinstance(left, Conditional) and isinstance(right, Conditional):
        return (
            left.register == right.register
            and left.value == right.value
            and len(left.body) == len(right.body)
            and all(
                _node_eq(left_gate, right_gate)
                for left_gate, right_gate in zip(left.body, right.body, strict=True)
            )
        )
    return False


class Circuit:
    """定宽量子比特之上的有序操作序列。"""

    __hash__ = None  # type: ignore[assignment]  # 显式声明为不可哈希的值容器。

    def __init__(self, num_qubits: int):
        if num_qubits < 1:
            raise ValueError("Circuit must have at least one qubit")

        self.num_qubits = num_qubits
        self.gates: list[Gate | Measure | Conditional] = []
        self.cregs: list[ClassicalRegister] = []

    def _validate_gate_qubits(self, gate: Gate) -> None:
        for qubit in gate.qubits:
            if qubit < 0 or qubit >= self.num_qubits:
                raise ValueError(
                    f"Gate acts on qubit {qubit}, but circuit only has "
                    f"qubits 0-{self.num_qubits - 1}"
                )

    def _has_register(self, register: ClassicalRegister) -> bool:
        return any(existing is register or existing == register for existing in self.cregs)

    def add_register(self, register: ClassicalRegister) -> None:
        """追加一个寄存器，同时保证声明名称唯一。"""
        if any(existing.name == register.name for existing in self.cregs):
            raise ValueError(f"Classical register {register.name!r} is already declared")
        self.cregs.append(register)

    def add_gate(self, gate: Gate) -> None:
        """追加一个作用比特落在电路范围内的门。"""
        self._validate_gate_qubits(gate)
        self.gates.append(gate)

    def add_measure(self, measurement: Measure) -> None:
        """追加一次测量，要求比特在范围内且目标寄存器已声明。"""
        if measurement.qubit < 0 or measurement.qubit >= self.num_qubits:
            raise ValueError(
                f"Measurement uses qubit {measurement.qubit}, but circuit only has "
                f"qubits 0-{self.num_qubits - 1}"
            )
        if not self._has_register(measurement.target.register):
            raise ValueError("Measurement target register is not declared by this circuit")
        self.gates.append(measurement)

    def add_conditional(self, conditional: Conditional) -> None:
        """追加一个条件节点，其寄存器须已声明、体内门须在范围内。"""
        if not self._has_register(conditional.register):
            raise ValueError("Conditional register is not declared by this circuit")
        for gate in conditional.body:
            self._validate_gate_qubits(gate)
        self.gates.append(conditional)

    def h(self, qubit: int) -> None:
        """追加一个 Hadamard 门。"""
        self.add_gate(Gate(GateType.H, (qubit,)))

    def x(self, qubit: int) -> None:
        """追加一个 Pauli-X 门。"""
        self.add_gate(Gate(GateType.X, (qubit,)))

    def y(self, qubit: int) -> None:
        """追加一个 Pauli-Y 门。"""
        self.add_gate(Gate(GateType.Y, (qubit,)))

    def z(self, qubit: int) -> None:
        """追加一个 Pauli-Z 门。"""
        self.add_gate(Gate(GateType.Z, (qubit,)))

    def s(self, qubit: int) -> None:
        """追加一个 S 门。"""
        self.add_gate(Gate(GateType.S, (qubit,)))

    def t(self, qubit: int) -> None:
        """追加一个 T 门。"""
        self.add_gate(Gate(GateType.T, (qubit,)))

    def rx(self, qubit: int, angle: float = math.pi) -> None:
        """追加一个绕 X 轴的旋转。"""
        self.add_gate(Gate(GateType.RX, (qubit,), (angle,)))

    def ry(self, qubit: int, angle: float) -> None:
        """追加一个绕 Y 轴的旋转。"""
        self.add_gate(Gate(GateType.RY, (qubit,), (angle,)))

    def rz(self, qubit: int, angle: float) -> None:
        """追加一个绕 Z 轴的旋转。"""
        self.add_gate(Gate(GateType.RZ, (qubit,), (angle,)))

    def rx90(self, qubit: int, phase: float = 0.0) -> None:
        """追加一个带相位参数的四分之一圈 X 门。"""
        self.add_gate(Gate(GateType.RX90, (qubit,), (phase,)))

    def rx180(self, qubit: int, phase: float = 0.0) -> None:
        """追加一个带相位参数的半圈 X 门。"""
        self.add_gate(Gate(GateType.RX180, (qubit,), (phase,)))

    def u3(self, qubit: int, theta: float, phi: float, lam: float) -> None:
        """追加一个通用单比特门。"""
        self.add_gate(Gate(GateType.U3, (qubit,), (theta, phi, lam)))

    def cnot(self, control: int, target: int) -> None:
        """追加一个受控非门。"""
        self.add_gate(Gate(GateType.CNOT, (control, target)))

    def cx(self, control: int, target: int) -> None:
        """追加一个受控 X 门。"""
        self.add_gate(Gate(GateType.CX, (control, target)))

    def cz(self, control: int, target: int) -> None:
        """追加一个受控 Z 门。"""
        self.add_gate(Gate(GateType.CZ, (control, target)))

    def copy(self) -> Circuit:
        """复制可变容器，同时安全地共享不可变节点。"""
        copied = Circuit(self.num_qubits)
        copied.gates = list(self.gates)
        copied.cregs = list(self.cregs)
        return copied

    def canonicalize(self) -> Circuit:
        """返回一个新电路，其中每个门都被约化为规范形式。

        测量原样透传；每个 Conditional 都会用规范化后的体内门重建。``qaiji.codec``
        不消费本方法 —— OpenQASM 往返始终是结构性的，绝不做隐式归一化。

        Returns:
            一个新电路，其宽度、寄存器声明、节点数量与节点种类序列都与当前电路
            逐位置一致。
        """
        from qaiji.core.classical import Conditional, Measure

        canonical = Circuit(self.num_qubits)
        for register in self.cregs:
            canonical.add_register(register)
        for operation in self.gates:
            if isinstance(operation, Gate):
                canonical.add_gate(operation.canonicalize())
            elif isinstance(operation, Measure):
                canonical.add_measure(operation)
            else:
                body = tuple(gate.canonicalize() for gate in operation.body)
                canonical.add_conditional(Conditional(operation.register, operation.value, body))
        return canonical

    def __eq__(self, other: object) -> bool:
        """比较电路结构，其中门的数值参数按容差比较。"""
        return (
            isinstance(other, Circuit)
            and self.num_qubits == other.num_qubits
            and self.cregs == other.cregs
            and len(self.gates) == len(other.gates)
            and all(
                _node_eq(left, right) for left, right in zip(self.gates, other.gates, strict=True)
            )
        )

    def __len__(self) -> int:
        """返回电路中的操作数量。"""
        return len(self.gates)

    def __str__(self) -> str:
        """渲染一份紧凑的、人类可读的电路清单。"""
        lines = [f"Circuit({self.num_qubits} qubits)"]
        for index, operation in enumerate(self.gates):
            if isinstance(operation, Gate):
                params = ""
                if operation.params:
                    params = f"({', '.join(f'{param:.4f}' for param in operation.params)})"
                qubits = ", ".join(str(qubit) for qubit in operation.qubits)
                lines.append(
                    f"  {index:2d}: {operation.gate_type.value}{params} -> qubits [{qubits}]"
                )
            else:
                lines.append(f"  {index:2d}: {operation!r}")
        return "\n".join(lines)
