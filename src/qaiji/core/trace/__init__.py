# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""T 层：轨迹日志、保持证书、容差表的值类型与规范编解码。"""

from qaiji.core.trace.codec import (
    dump_certificate,
    dump_tolerances,
    dump_trace_log,
    load_certificate,
    load_tolerances,
    load_trace_log,
)
from qaiji.core.trace.model import (
    CERTIFICATE_SCHEMA,
    TOLERANCES_SCHEMA,
    TRACE_LOG_SCHEMA,
    Assumptions,
    Comparison,
    Exclusion,
    PreservationCertificate,
    ResultLatency,
    SymbolicLevel,
    ToleranceEntry,
    ToleranceSource,
    ToleranceTable,
    TraceEvent,
    TraceInputError,
    TraceLog,
    TraceSource,
    numerical_verdict_of,
)

__all__ = [
    "CERTIFICATE_SCHEMA",
    "TOLERANCES_SCHEMA",
    "TRACE_LOG_SCHEMA",
    "Assumptions",
    "Comparison",
    "Exclusion",
    "PreservationCertificate",
    "ResultLatency",
    "SymbolicLevel",
    "ToleranceEntry",
    "ToleranceSource",
    "ToleranceTable",
    "TraceEvent",
    "TraceInputError",
    "TraceLog",
    "TraceSource",
    "dump_certificate",
    "dump_tolerances",
    "dump_trace_log",
    "load_certificate",
    "load_tolerances",
    "load_trace_log",
    "numerical_verdict_of",
]
