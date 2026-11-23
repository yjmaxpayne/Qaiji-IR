# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""对外公开的电路与经典控制前端对象模型。"""

from qaiji.core.circuit import (
    CANONICAL_ALIASES,
    PARAM_REQUIREMENTS,
    SINGLE_QUBIT_GATES,
    TWO_QUBIT_GATES,
    Circuit,
    Gate,
    GateType,
)
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.loop import (
    BoundedLoop,
    ConditionalTemplate,
    ExpandedCircuit,
    GateTemplate,
    LoopedCircuit,
    LoopIndex,
    MeasureTemplate,
    OperationProvenance,
    SourceSpan,
)

__all__ = [
    "CANONICAL_ALIASES",
    "PARAM_REQUIREMENTS",
    "SINGLE_QUBIT_GATES",
    "TWO_QUBIT_GATES",
    "BoundedLoop",
    "Circuit",
    "ClassicalBit",
    "ClassicalRegister",
    "Conditional",
    "ConditionalTemplate",
    "ExpandedCircuit",
    "Gate",
    "GateTemplate",
    "GateType",
    "LoopIndex",
    "LoopedCircuit",
    "Measure",
    "MeasureTemplate",
    "OperationProvenance",
    "SourceSpan",
]
