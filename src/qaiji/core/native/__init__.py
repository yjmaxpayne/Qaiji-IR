# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""原生调度的不可修改记录、显式配置及认证接口。"""

from .api import lower_to_native
from .config import OperationSpec, QubitResource, ScheduleConfig
from .diagnostics import (
    CheckResult,
    GroupEvidence,
    NativeIssue,
    NativeValidationError,
    NativeValidationReport,
)
from .errors import NativeInputError
from .model import (
    NATIVE_RULESET_VERSION,
    NATIVE_SCHEDULE_SCHEMA_VERSION,
    ConditionRead,
    ConditionRegion,
    MeasurementEvent,
    NativeOperation,
    NativeScheduleIR,
    RegisterDecl,
    SourceGroup,
    SourceLocation,
)
from .projection import NativeProjection, ProjectedOperation, qubic_mapping
from .validation import validate_native_schedule

__all__ = [
    "NATIVE_RULESET_VERSION",
    "NATIVE_SCHEDULE_SCHEMA_VERSION",
    "CheckResult",
    "ConditionRead",
    "ConditionRegion",
    "GroupEvidence",
    "MeasurementEvent",
    "NativeInputError",
    "NativeIssue",
    "NativeOperation",
    "NativeProjection",
    "NativeScheduleIR",
    "NativeValidationError",
    "NativeValidationReport",
    "OperationSpec",
    "ProjectedOperation",
    "QubitResource",
    "RegisterDecl",
    "ScheduleConfig",
    "SourceGroup",
    "SourceLocation",
    "lower_to_native",
    "qubic_mapping",
    "validate_native_schedule",
]
