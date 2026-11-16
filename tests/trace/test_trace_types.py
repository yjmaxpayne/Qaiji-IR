# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""T 层值类型与规范编解码的契约测试。"""

from __future__ import annotations

import ast
import json
import math
import struct
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import qaiji.core.trace.codec as codec_module
import qaiji.core.trace.model as model_module
from qaiji.core.native import NativeValidationReport, equiv_level_of_native
from qaiji.core.native.diagnostics import CheckResult, GroupEvidence, NativeIssue
from qaiji.core.native.model import SourceLocation
from qaiji.core.semantics import EquivLevel
from qaiji.core.trace import (
    Assumptions,
    Comparison,
    Exclusion,
    PreservationCertificate,
    ResultLatency,
    SymbolicLevel,
    ToleranceSource,
    TraceEvent,
    TraceInputError,
    TraceLog,
    TraceSource,
    dump_certificate,
    dump_trace_log,
    load_certificate,
    load_trace_log,
)
from qaiji.exceptions import QaijiIRError

MODULE_PATHS = (Path(model_module.__file__), Path(codec_module.__file__))
SOURCE = TraceSource(
    kind="cross_layer_record/0.2", digest="sha256:" + "ab" * 32, program_ref="k-1", layer="l0"
)


def _measure(event_id: str, qubit: int) -> TraceEvent:
    return TraceEvent(id=event_id, kind="measurement", qubit=qubit, register="s", bit_index=qubit)


def _branch(key: str, weight: float, pruned: bool = False) -> TraceEvent:
    return TraceEvent(
        id=f"b:{key}", kind="branch", conditional_weight=weight, path_weight=-0.0, pruned=pruned
    )


def _observe(name: str, value: float) -> TraceEvent:
    return TraceEvent(id=f"o:{name}", kind="observable", value=value, result_digest="sha256:cd")


def _events() -> list[TraceEvent]:
    """返回规范序事件：id 为 m0 < m10 < m2，分支键按（长度，键）排序，观测名有序。"""
    return [
        _measure("m0", 2),
        _measure("m10", 0),
        _measure("m2", 1),
        _branch("0", 0.1),
        _branch("1", 1 / 3, pruned=True),
        _branch("01", 2.5e-17),
        _branch("10", 0.9),
        _branch("110", 1.0),
        _observe("encoded_population", 0.1),
        _observe("z_parity", -0.0),
    ]


def _comparison(verdict: str = "within", name: str = "population") -> Comparison:
    return Comparison(
        name=name,
        kind="cross_layer",
        tolerance=0.1,
        delta=1 / 3 if verdict == "exceeded" else 2.5e-17,
        verdict=verdict,
        evidence_refs=(("sha256:aa", "o:encoded_population"), ("sha256:bb", "b:01")),
    )


def _certificate(**changes: object) -> PreservationCertificate:
    fields = dict(
        program_ref="k-1",
        expected_key="110",
        symbolic=SymbolicLevel(
            level=EquivLevel.UP_TO_PHASE, stage="native_lowering", ruleset_version="v1"
        ),
        comparisons=(_comparison(), replace(_comparison(name="hash"), tolerance=None)),
        exclusions=(),
        numerical_verdict="within",
        tolerance_source=ToleranceSource(rule="max_spread", digest="sha256:ee"),
        assumptions=Assumptions(result_latency_ns=ResultLatency(value=200, source="config")),
    )
    fields.update(changes)
    return PreservationCertificate(**fields)


def _dump_both() -> bytes:
    """编码夹具日志与证书，供双进程测试使用。"""
    log = dump_trace_log(TraceLog(source=SOURCE, events=_events()))
    return log + dump_certificate(_certificate())


# --- import surface ---------------------------------------------------------------


@pytest.mark.parametrize("module_path", MODULE_PATHS, ids=lambda path: path.name)
def test_imports_are_stdlib_or_qaiji_only(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    roots = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import at line {node.lineno}"
            roots.append(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            roots += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            assert name not in ("import_module", "__import__"), f"dynamic import {node.lineno}"
    assert roots
    assert {r for r in roots if r not in sys.stdlib_module_names} == {"qaiji"}


# --- events -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: TraceEvent(id="m0", kind="measurement", qubit=0, bit_index=0),
        lambda: TraceEvent(
            id="b:0", kind="branch", conditional_weight=0.1, path_weight=0.1, pruned=False, value=1
        ),
        lambda: TraceEvent(id="x0", kind="measurement", qubit=0, register="s", bit_index=0),
        lambda: TraceEvent(id="m01", kind="measurement", qubit=0, register="s", bit_index=0),
        lambda: _branch("2", 0.1),
        lambda: TraceEvent(id="o:", kind="observable", value=0.1, result_digest="d"),
        lambda: TraceEvent(id="m0", kind="pulse", qubit=0, register="s", bit_index=0),
        lambda: _branch("0", math.nan),
        lambda: _branch("0", math.inf),
        lambda: TraceEvent(id="m0", kind="measurement", qubit=True, register="s", bit_index=0),
        lambda: TraceEvent(id="m0", kind="measurement", qubit=-1, register="s", bit_index=0),
        lambda: TraceEvent(
            id="b:0", kind="branch", conditional_weight=0.1, path_weight=0.1, pruned=1
        ),
    ],
)
def test_event_rejects_invalid_fields(build) -> None:
    with pytest.raises(TraceInputError):
        build()


def test_trace_input_error_is_a_value_error() -> None:
    assert issubclass(TraceInputError, ValueError)
    assert issubclass(TraceInputError, QaijiIRError)


# --- trace log ----------------------------------------------------------------------


def test_trace_log_accepts_canonical_order() -> None:
    log = TraceLog(source=SOURCE, events=_events())
    assert log.schema == "qaiji.t.trace_log/1.0"
    assert [e.id for e in log.events][3:8] == ["b:0", "b:1", "b:01", "b:10", "b:110"]


def test_trace_log_rejects_duplicate_ids() -> None:
    events = _events()
    events.insert(1, _measure("m0", 1))
    with pytest.raises(TraceInputError, match="duplicate"):
        TraceLog(source=SOURCE, events=events)


@pytest.mark.parametrize(
    "order",
    [
        ["m2", "m0"],
        ["b:0", "b:01", "b:1"],
        ["o:z_parity", "o:encoded_population"],
        ["b:0", "m0"],
        ["o:encoded_population", "b:0"],
    ],
)
def test_trace_log_ordering_rejects_noncanonical_order(order: list[str]) -> None:
    by_id = {e.id: e for e in _events()}
    with pytest.raises(TraceInputError, match="order"):
        TraceLog(source=SOURCE, events=[by_id[i] for i in order])


def test_trace_log_rejects_foreign_schema_and_bad_source() -> None:
    with pytest.raises(TraceInputError):
        TraceLog(source=SOURCE, events=(), schema="qaiji.t.trace_log/1.1")
    with pytest.raises(TraceInputError):
        TraceSource(kind="k", digest="", program_ref="p", layer="l0")


# --- codec ---------------------------------------------------------------------


def _bits(value: float) -> bytes:
    return struct.pack(">d", value)


def test_trace_log_round_trip_preserves_every_bit() -> None:
    log = TraceLog(source=SOURCE, events=_events())
    data = dump_trace_log(log)
    restored = load_trace_log(data)
    assert restored == log
    assert dump_trace_log(restored) == data
    weights = [e.path_weight for e in restored.events if e.kind == "branch"]
    assert all(_bits(w) == _bits(-0.0) for w in weights)
    assert b'"3fb999999999999a"' in data  # 0.1 的大端 binary64 十六进制
    canonical = json.dumps(
        json.loads(data), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    assert data == canonical.encode("utf-8")


def test_certificate_round_trip_is_identity() -> None:
    certificate = _certificate()
    data = dump_certificate(certificate)
    assert json.loads(data)["schema"] == "qaiji.t.preservation_certificate/1.0"
    assert load_certificate(data) == certificate
    assert dump_certificate(load_certificate(data)) == data


@pytest.mark.parametrize(
    ("loader", "schema"),
    [
        (load_trace_log, "qaiji.t.trace_log/1.1"),
        (load_trace_log, "qaiji.t.preservation_certificate/1.0"),
        (load_certificate, "qaiji.t.trace_log/1.0"),
        (load_certificate, "qaiji.t.preservation_certificate/2.0"),
    ],
)
def test_load_rejects_unknown_schema(loader, schema: str) -> None:
    source = (
        dump_trace_log(TraceLog(source=SOURCE, events=_events()))
        if loader is load_trace_log
        else dump_certificate(_certificate())
    )
    tree = json.loads(source)
    tree["schema"] = schema
    with pytest.raises(TraceInputError, match="schema"):
        loader(json.dumps(tree).encode("utf-8"))


def test_load_rejects_decimal_floats_and_unknown_keys() -> None:
    tree = json.loads(dump_trace_log(TraceLog(source=SOURCE, events=_events())))
    tree["events"][3]["conditional_weight"] = 0.1
    with pytest.raises(TraceInputError):
        load_trace_log(json.dumps(tree).encode("utf-8"))
    tree = json.loads(dump_certificate(_certificate()))
    tree["comparisons"][0]["note"] = "x"
    with pytest.raises(TraceInputError):
        load_certificate(json.dumps(tree).encode("utf-8"))


def test_two_processes_encode_identical_bytes() -> None:
    code = (
        "import importlib.util as u, sys\n"
        f"s = u.spec_from_file_location('fixture', {str(Path(__file__))!r})\n"
        "m = u.module_from_spec(s); s.loader.exec_module(m)\n"
        "sys.stdout.buffer.write(m._dump_both())\n"
    )
    outputs = [
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, check=True, timeout=120
        ).stdout
        for _ in range(2)
    ]
    assert outputs[0] == outputs[1] == _dump_both()


# --- certificate ------------------------------------------------------------------


def test_exact_exceeded_certificate_round_trip() -> None:
    certificate = _certificate(
        symbolic=SymbolicLevel(
            level=EquivLevel.EXACT, stage="native_lowering", ruleset_version="v1"
        ),
        comparisons=(_comparison("exceeded"), _comparison(name="hash")),
        numerical_verdict="exceeded",
    )
    restored = load_certificate(dump_certificate(certificate))
    assert restored.symbolic.level is EquivLevel.EXACT
    assert restored.numerical_verdict == "exceeded"
    assert restored == certificate


def _verdict_case(comparisons, exclusions, verdict) -> PreservationCertificate:
    return _certificate(
        comparisons=tuple(_comparison(v, name=f"c{i}") for i, v in enumerate(comparisons)),
        exclusions=tuple(Exclusion(layer=layer, dominant_key="01") for layer in exclusions),
        numerical_verdict=verdict,
    )


@pytest.mark.parametrize(
    ("comparisons", "exclusions", "verdict"),
    [
        (("within", "within"), (), "within"),
        (("within", "exceeded"), (), "exceeded"),
        (("within",), ("l1",), "excluded"),
        (("exceeded",), ("l1",), "exceeded"),
        ((), ("l0", "l1"), "excluded"),
        ((), (), "within"),
    ],
)
def test_numerical_verdict_accepts_the_rule(comparisons, exclusions, verdict) -> None:
    assert _verdict_case(comparisons, exclusions, verdict).numerical_verdict == verdict


@pytest.mark.parametrize(
    ("comparisons", "exclusions", "verdict"),
    [
        (("within",), ("l1",), "within"),
        (("within", "exceeded"), (), "within"),
        (("exceeded",), ("l1",), "excluded"),
        (("within",), (), "excluded"),
        (("within",), (), "exceeded"),
        (("within",), (), "unknown"),
    ],
)
def test_numerical_verdict_rejects_inconsistent_value(comparisons, exclusions, verdict) -> None:
    with pytest.raises(TraceInputError, match="verdict"):
        _verdict_case(comparisons, exclusions, verdict)


def test_symbolic_level_accepts_any_equiv_level() -> None:
    # 可判定性由检查器判断，构造器只检查形状。
    level = SymbolicLevel(
        level=EquivLevel.UP_TO_LOCAL, stage="native_lowering", ruleset_version="v1"
    )
    assert level.level is EquivLevel.UP_TO_LOCAL
    with pytest.raises(TraceInputError):
        SymbolicLevel(level="exact", stage="native_lowering", ruleset_version="v1")


@pytest.mark.parametrize(
    "build",
    [
        lambda: ResultLatency(value=200, source="rtl"),
        lambda: ResultLatency(value=-1, source="config"),
        lambda: _comparison("unknown"),
        lambda: replace(_comparison(), kind="same_process"),
        lambda: replace(_comparison(), evidence_refs=(("sha256:aa",),)),
        lambda: replace(_comparison(), evidence_refs=(("sha256:aa", ""),)),
        lambda: replace(_comparison(), evidence_refs=(("", "b:01"),)),
        lambda: _certificate(expected_key="12"),
        lambda: _certificate(program_ref=""),
    ],
)
def test_certificate_rejects_bad_fields(build) -> None:
    with pytest.raises(TraceInputError):
        build()


def test_comparison_accepts_non_event_reference() -> None:
    """引用种类由检查器判定，因此类型必须能携带这种引用。"""
    ref = ("sha256:aa", "assumptions.result_latency_ns")
    comparison = replace(_comparison(), evidence_refs=(ref,))
    certificate = _certificate(comparisons=(comparison,))
    assert load_certificate(dump_certificate(certificate)).comparisons[0].evidence_refs == (ref,)


# --- symbolic level from the native report -----------------------------------------

PASS = CheckResult(status="pass", issues=())


def _report(phases: list[float | None], schedule: CheckResult = PASS) -> NativeValidationReport:
    groups = tuple(
        GroupEvidence(
            source=SourceLocation(gate_index=i, body_offset=None),
            rule_id="r",
            rule=PASS,
            hp=PASS,
            expected_phase_rad=phase,
            max_abs_residual=0.0,
        )
        for i, phase in enumerate(phases)
    )
    return NativeValidationReport(
        source=PASS,
        rules=PASS,
        hp=PASS,
        schedule=schedule,
        groups=groups,
        all_results_ready_ns=None,
    )


def test_equiv_level_of_native_invalid_report_has_no_level() -> None:
    issue = NativeIssue(
        code="result_not_ready", path="$", source=None, operation_index=None, message="late"
    )
    report = _report([0.0], schedule=CheckResult(status="fail", issues=(issue,)))
    assert not report.valid
    assert equiv_level_of_native(report) is None


def test_equiv_level_of_native_zero_or_missing_phase_is_exact() -> None:
    assert equiv_level_of_native(_report([None, 0.0, -0.0, None])) is EquivLevel.EXACT


def test_equiv_level_of_native_nonzero_phase_is_up_to_phase() -> None:
    report = _report([0.0, None, -math.pi / 2])
    assert equiv_level_of_native(report) is EquivLevel.UP_TO_PHASE
