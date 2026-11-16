# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""T 层文档的规范 JSON 编解码：轨迹日志、保持证书与容差文件。"""

from __future__ import annotations

import json
import struct
from collections.abc import Callable
from typing import Any

from qaiji.core._codec import canonical_json, f64_to_hex
from qaiji.core.semantics import EquivLevel
from qaiji.core.trace.model import (
    _EVENT_FIELDS,
    _EVENT_FLOATS,
    _HEX,
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
)


def _f64_from_hex(name: str, text: Any) -> float:
    if not isinstance(text, str) or not _HEX.fullmatch(text):
        raise TraceInputError(f"{name} must be a 16-digit binary64 hex string, got {text!r}")
    return float(struct.unpack(">d", bytes.fromhex(text))[0])


def _object(
    where: str, tree: Any, required: set[str], optional: frozenset[str] = frozenset()
) -> dict[str, Any]:
    if not isinstance(tree, dict):
        raise TraceInputError(f"{where} must be a JSON object")
    missing, unknown = required - set(tree), set(tree) - required - optional
    if missing or unknown:
        raise TraceInputError(f"{where}: missing keys {sorted(missing)}, unknown {sorted(unknown)}")
    return dict(tree)


def _parse(data: bytes, schema: str) -> Any:
    try:
        tree = json.loads(data)
    except ValueError as exc:
        raise TraceInputError(f"document is not valid JSON: {exc}") from exc
    found = tree.get("schema") if isinstance(tree, dict) else None
    if found != schema:
        raise TraceInputError(f"unknown schema {found!r}; expected {schema!r}")
    return tree


def _decode[T](build: Callable[[], T]) -> T:
    try:
        return build()
    except TraceInputError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise TraceInputError(f"malformed document: {exc}") from exc


def _event_tree(event: TraceEvent) -> dict[str, Any]:
    tree: dict[str, Any] = {"id": event.id, "kind": event.kind}
    for name in _EVENT_FIELDS:
        value = getattr(event, name)
        if value is not None:
            tree[name] = f64_to_hex(value) if name in _EVENT_FLOATS else value
    return tree


def _event_of(tree: Any) -> TraceEvent:
    tree = _object("event", tree, {"id", "kind"}, frozenset(_EVENT_FIELDS))
    fields: dict[str, Any] = {
        k: _f64_from_hex(k, v) if k in _EVENT_FLOATS else v
        for k, v in tree.items()
        if k not in ("id", "kind")
    }
    return TraceEvent(id=tree["id"], kind=tree["kind"], **fields)


def dump_trace_log(log: TraceLog) -> bytes:
    """Encode a trace log as canonical JSON bytes; floats are binary64 hex strings."""
    source = log.source
    return canonical_json(
        {
            "schema": log.schema,
            "source": {
                "kind": source.kind,
                "digest": source.digest,
                "program_ref": source.program_ref,
                "layer": source.layer,
            },
            "events": [_event_tree(event) for event in log.events],
        }
    )


def load_trace_log(data: bytes) -> TraceLog:
    """Decode bytes from ``dump_trace_log``.

    Raises:
        TraceInputError: The schema is unknown, a key is missing or unknown, a float is
            not a hex string, or a value breaks the type contract.
    """
    tree = _object("trace log", _parse(data, TRACE_LOG_SCHEMA), {"schema", "source", "events"})

    def build() -> TraceLog:
        source = _object("source", tree["source"], {"kind", "digest", "program_ref", "layer"})
        if not isinstance(tree["events"], list):
            raise TraceInputError("events must be a JSON array")
        events = tuple(_event_of(event) for event in tree["events"])
        return TraceLog(source=TraceSource(**source), events=events, schema=tree["schema"])

    return _decode(build)


_COMPARISON_KEYS = {"name", "kind", "delta", "verdict", "evidence_refs"}
_CERTIFICATE_KEYS = {
    "schema",
    "program_ref",
    "expected_key",
    "symbolic",
    "comparisons",
    "exclusions",
    "numerical_verdict",
    "tolerance_source",
    "assumptions",
}


def _comparison_tree(comparison: Comparison) -> dict[str, Any]:
    tree: dict[str, Any] = {
        "name": comparison.name,
        "kind": comparison.kind,
        "delta": f64_to_hex(comparison.delta),
        "verdict": comparison.verdict,
        "evidence_refs": [list(ref) for ref in comparison.evidence_refs],
    }
    if comparison.tolerance is not None:
        tree["tolerance"] = f64_to_hex(comparison.tolerance)
    return tree


def _comparison_of(tree: Any) -> Comparison:
    tree = _object("comparison", tree, _COMPARISON_KEYS, frozenset({"tolerance"}))
    tolerance = tree.get("tolerance")
    return Comparison(
        name=tree["name"],
        kind=tree["kind"],
        tolerance=None if tolerance is None else _f64_from_hex("tolerance", tolerance),
        delta=_f64_from_hex("delta", tree["delta"]),
        verdict=tree["verdict"],
        evidence_refs=tree["evidence_refs"],
    )


def dump_certificate(certificate: PreservationCertificate) -> bytes:
    """Encode a preservation certificate as canonical JSON bytes."""
    symbolic = certificate.symbolic
    latency = certificate.assumptions.result_latency_ns
    return canonical_json(
        {
            "schema": certificate.schema,
            "program_ref": certificate.program_ref,
            "expected_key": certificate.expected_key,
            "symbolic": {
                "level": symbolic.level.value,
                "stage": symbolic.stage,
                "ruleset_version": symbolic.ruleset_version,
            },
            "comparisons": [_comparison_tree(c) for c in certificate.comparisons],
            "exclusions": [
                {"layer": e.layer, "dominant_key": e.dominant_key} for e in certificate.exclusions
            ],
            "numerical_verdict": certificate.numerical_verdict,
            "tolerance_source": {
                "rule": certificate.tolerance_source.rule,
                "digest": certificate.tolerance_source.digest,
            },
            "assumptions": {
                "result_latency_ns": {"value": latency.value, "source": latency.source}
            },
        }
    )


def load_certificate(data: bytes) -> PreservationCertificate:
    """Decode bytes from ``dump_certificate``.

    Raises:
        TraceInputError: The schema is unknown, a key is missing or unknown, a float is
            not a hex string, or a value breaks the type or verdict contract.
    """
    tree = _object("certificate", _parse(data, CERTIFICATE_SCHEMA), _CERTIFICATE_KEYS)

    def build() -> PreservationCertificate:
        symbolic = _object("symbolic", tree["symbolic"], {"level", "stage", "ruleset_version"})
        assumptions = _object("assumptions", tree["assumptions"], {"result_latency_ns"})
        latency = _object(
            "result_latency_ns", assumptions["result_latency_ns"], {"value", "source"}
        )
        return PreservationCertificate(
            program_ref=tree["program_ref"],
            expected_key=tree["expected_key"],
            symbolic=SymbolicLevel(
                level=EquivLevel(symbolic["level"]),
                stage=symbolic["stage"],
                ruleset_version=symbolic["ruleset_version"],
            ),
            comparisons=tuple(_comparison_of(c) for c in tree["comparisons"]),
            exclusions=tuple(
                Exclusion(**_object("exclusion", e, {"layer", "dominant_key"}))
                for e in tree["exclusions"]
            ),
            numerical_verdict=tree["numerical_verdict"],
            tolerance_source=ToleranceSource(
                **_object("tolerance_source", tree["tolerance_source"], {"rule", "digest"})
            ),
            assumptions=Assumptions(result_latency_ns=ResultLatency(**latency)),
            schema=tree["schema"],
        )

    return _decode(build)


_LADDER = (1e-10, 1e-6, 1e-3)
_TOLERANCES_KEYS = {"schema", "rule", "comparisons", "calibration_records"}


def dump_tolerances(table: ToleranceTable) -> bytes:
    """Encode a tolerance table as canonical JSON bytes; floats are binary64 hex strings."""
    return canonical_json(
        {
            "schema": table.schema,
            "rule": table.rule,
            "comparisons": {
                name: {
                    "max_abs_delta": f64_to_hex(entry.max_abs_delta),
                    "tolerance": f64_to_hex(entry.tolerance),
                }
                for name, entry in table.comparisons.items()
            },
            "calibration_records": list(table.calibration_records),
        }
    )


def load_tolerances(data: bytes) -> ToleranceTable:
    """Decode bytes from ``dump_tolerances``; the precision ladder is not checked here.

    Raises:
        TraceInputError: The schema or rule is unknown, a key is missing or unknown, a
            float is not a hex string, or a value breaks the type contract.
    """
    tree = _object("tolerances", _parse(data, TOLERANCES_SCHEMA), _TOLERANCES_KEYS)

    def entry(name: str, value: Any) -> ToleranceEntry:
        fields = _object(f"tolerance entry {name!r}", value, {"max_abs_delta", "tolerance"})
        return ToleranceEntry(**{k: _f64_from_hex(k, v) for k, v in fields.items()})

    def build() -> ToleranceTable:
        comparisons, records = tree["comparisons"], tree["calibration_records"]
        if not isinstance(comparisons, dict) or not isinstance(records, list):
            raise TraceInputError("comparisons must be an object; calibration_records a list")
        return ToleranceTable(
            comparisons={name: entry(name, value) for name, value in comparisons.items()},
            calibration_records=tuple(records),
            rule=tree["rule"],
            schema=tree["schema"],
        )

    return _decode(build)
