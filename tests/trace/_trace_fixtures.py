# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""T 层字节等价夹具：同一组文档，交给任一实现编码。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from qaiji.core.semantics import EquivLevel

FIXTURE_NAMES = (
    "trace_log_incubation_events",
    "trace_log_irregular_branches",
    "certificate_within",
    "certificate_exceeded",
    "tolerances_ladder",
)


def documents(api: Any) -> dict[str, bytes]:
    """用 ``api`` 提供的类型与 dump 函数编码全部夹具。

    Args:
        api: 提供 T 层类型与 ``dump_*`` 函数的模块或命名空间。

    Returns:
        夹具名到编码字节的映射，键序与 ``FIXTURE_NAMES`` 相同。
    """
    a = SimpleNamespace(**{name: getattr(api, name) for name in dir(api)})
    source = a.TraceSource(
        kind="cross_layer_record/0.2", digest="sha256:" + "ab" * 32, program_ref="k-1", layer="l0"
    )

    def measure(event_id: str, qubit: int) -> Any:
        return a.TraceEvent(
            id=event_id, kind="measurement", qubit=qubit, register="s", bit_index=qubit
        )

    def branch(key: str, weight: float, path: float = -0.0, pruned: bool = False) -> Any:
        return a.TraceEvent(
            id=f"b:{key}", kind="branch", conditional_weight=weight, path_weight=path, pruned=pruned
        )

    def observe(name: str, value: float) -> Any:
        return a.TraceEvent(
            id=f"o:{name}", kind="observable", value=value, result_digest="sha256:cd"
        )

    incubation_events = [
        measure("m0", 2),
        measure("m10", 0),
        measure("m2", 1),
        branch("0", 0.1),
        branch("1", 1 / 3, pruned=True),
        branch("01", 2.5e-17),
        branch("10", 0.9),
        branch("110", 1.0),
        observe("encoded_population", 0.1),
        observe("z_parity", -0.0),
    ]
    # 权重和为 0.9，分支键不等于下标。
    irregular_events = [
        measure("m0", 1),
        measure("m1", 0),
        branch("01", 0.3, path=0.3),
        branch("10", 0.6, path=0.6),
        observe("population", 0.1 + 0.2),
    ]

    def comparison(verdict: str, name: str = "population") -> Any:
        return a.Comparison(
            name=name,
            kind="cross_layer",
            tolerance=0.1,
            delta=1 / 3 if verdict == "exceeded" else 2.5e-17,
            verdict=verdict,
            evidence_refs=(("sha256:aa", "o:encoded_population"), ("sha256:bb", "b:01")),
        )

    def certificate(verdict: str) -> Any:
        unbounded = a.Comparison(
            name="hash",
            kind="cross_layer",
            tolerance=None,
            delta=2.5e-17,
            verdict="within",
            evidence_refs=(("sha256:aa", "o:encoded_population"), ("sha256:bb", "b:01")),
        )
        return a.PreservationCertificate(
            program_ref="k-1",
            expected_key="110",
            symbolic=a.SymbolicLevel(
                level=EquivLevel.UP_TO_PHASE, stage="native_lowering", ruleset_version="v1"
            ),
            comparisons=(comparison(verdict), unbounded),
            exclusions=(),
            numerical_verdict=verdict,
            tolerance_source=a.ToleranceSource(rule="max_spread", digest="sha256:ee"),
            assumptions=a.Assumptions(
                result_latency_ns=a.ResultLatency(value=200, source="config")
            ),
        )

    tolerances = a.ToleranceTable(
        comparisons={
            "population": a.ToleranceEntry(max_abs_delta=3e-7, tolerance=1e-6),
            "相位": a.ToleranceEntry(max_abs_delta=2.5e-17, tolerance=1e-10),
        },
        calibration_records=("sha256:" + "01" * 32, "sha256:" + "fe" * 32),
    )
    return {
        "trace_log_incubation_events": a.dump_trace_log(
            a.TraceLog(source=source, events=incubation_events)
        ),
        "trace_log_irregular_branches": a.dump_trace_log(
            a.TraceLog(source=source, events=irregular_events)
        ),
        "certificate_within": a.dump_certificate(certificate("within")),
        "certificate_exceeded": a.dump_certificate(certificate("exceeded")),
        "tolerances_ladder": a.dump_tolerances(tolerances),
    }
