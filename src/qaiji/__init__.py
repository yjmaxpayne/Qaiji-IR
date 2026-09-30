# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Qaiji-IR：一个共享的量子—经典中间表示。

发布名 ``qaiji-ir`` / 导入名 ``qaiji``。包根对外暴露稳定的电路、经典控制、异常与
OpenQASM 编解码器接口。
"""

from qaiji.codec import from_qasm3, to_qasm3
from qaiji.core import (
    Circuit,
    ClassicalBit,
    ClassicalRegister,
    Conditional,
    Gate,
    GateType,
    Measure,
)
from qaiji.exceptions import (
    ConventionViolationError,
    QaijiIRError,
    Qasm3ParseError,
    Qasm3UnsupportedConstructError,
    Qasm3UnsupportedGateError,
    UnsupportedEquivLevelError,
)
from qaiji.version import __version__

# IR schema 版本号 —— 只要 OpenQASM 3 往返契约发生变化就要递增。
IR_SCHEMA_VERSION = "qaiji.ir.v0"
"""对外公开的 OpenQASM 往返 schema 契约的版本号。"""

__all__ = [
    "IR_SCHEMA_VERSION",
    "Circuit",
    "ClassicalBit",
    "ClassicalRegister",
    "Conditional",
    "ConventionViolationError",
    "Gate",
    "GateType",
    "Measure",
    "QaijiIRError",
    "Qasm3ParseError",
    "Qasm3UnsupportedConstructError",
    "Qasm3UnsupportedGateError",
    "UnsupportedEquivLevelError",
    "__version__",
    "from_qasm3",
    "to_qasm3",
]
