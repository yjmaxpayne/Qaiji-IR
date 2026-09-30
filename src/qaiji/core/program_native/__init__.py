# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""经过认证的 L5 / L2 调用与测量事件映射。"""

from .bridge import bridge_program_native
from .model import (
    FinalBitBinding,
    InvocationEventRef,
    NativeBinding,
    OutputMeasurementBinding,
    ProgramNativeIssue,
    ProgramNativeMap,
    ProgramNativeValidationError,
)

__all__ = [
    "FinalBitBinding",
    "InvocationEventRef",
    "NativeBinding",
    "OutputMeasurementBinding",
    "ProgramNativeIssue",
    "ProgramNativeMap",
    "ProgramNativeValidationError",
    "bridge_program_native",
]
