# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L5 程序表达面，本仓不解释实验元数据中的不透明引用。

程序专用错误类型由本子包导出而非包根，以免包根为构建异常公开面而加载
L5 及其 L4 依赖；包根异常与 exceptions 模块保持双射。
"""

from qaiji.core.program.model import (
    PROGRAM_SCHEMA_VERSION,
    ExperimentMetadata,
    ProgramIR,
    QuantumInvocation,
    ResultOutput,
)
from qaiji.core.program.validation import (
    ProgramValidationError,
    compute_kernel_ref,
    validate_program,
)

__all__ = [
    "PROGRAM_SCHEMA_VERSION",
    "ExperimentMetadata",
    "ProgramIR",
    "ProgramValidationError",
    "QuantumInvocation",
    "ResultOutput",
    "compute_kernel_ref",
    "validate_program",
]
