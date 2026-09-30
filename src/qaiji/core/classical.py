# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""用于测量与前馈控制的不可变经典值。"""

from dataclasses import dataclass

from qaiji.core.circuit import Gate

__all__ = [
    "ClassicalBit",
    "ClassicalRegister",
    "Conditional",
    "Measure",
]


@dataclass(frozen=True)
class ClassicalRegister:
    """一个具名的定宽经典寄存器。"""

    name: str
    size: int

    def __post_init__(self) -> None:
        if not self.name or not self.name.isidentifier():
            raise ValueError("Classical register name must be a non-empty identifier")
        if self.size < 1:
            raise ValueError("Classical register size must be at least one")


@dataclass(frozen=True)
class ClassicalBit:
    """经典寄存器内按下标定位的一个比特。"""

    register: ClassicalRegister
    index: int

    def __post_init__(self) -> None:
        if self.index < 0 or self.index >= self.register.size:
            raise ValueError(
                f"Classical bit index {self.index} is outside register "
                f"{self.register.name!r} of size {self.register.size}"
            )


@dataclass(frozen=True)
class Measure:
    """一次从单个量子比特到单个经典比特的测量。"""

    qubit: int
    target: ClassicalBit

    def __post_init__(self) -> None:
        if self.qubit < 0:
            raise ValueError("Measurement qubit must be non-negative")


@dataclass(frozen=True)
class Conditional:
    """当寄存器等于某个值时执行的门序列。"""

    register: ClassicalRegister
    value: int
    body: tuple[Gate, ...]

    def __post_init__(self) -> None:
        body = tuple(self.body)
        object.__setattr__(self, "body", body)

        if self.value < 0:
            raise ValueError("Conditional value must be non-negative")
        if any(not isinstance(operation, Gate) for operation in body):
            raise ValueError("Conditional body may only contain gates")
