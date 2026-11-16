# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""T 层：保持证书检查器，独立重算证书中的每条结论。"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from qaiji.core.trace.codec import _LADDER, load_tolerances
from qaiji.core.trace.model import (
    _DECIDABLE_LEVELS,
    Comparison,
    Exclusion,
    PreservationCertificate,
    TraceEvent,
    TraceInputError,
    TraceLog,
    _bits,
    _is_event_id,
    _items,
    numerical_verdict_of,
)

# --- certificate check ----------------------------------------------------------------

_FAILURE_CODES = (
    "REF_SOURCE_MISSING",
    "REF_MISSING",
    "REF_KIND_INVALID",
    "EVIDENCE_EMPTY",
    "INPUT_MISMATCH",
    "VERDICT_MISMATCH",
    "EXCLUSION_MISMATCH",
    "SYMBOLIC_LEVEL_UNDECIDABLE",
    "EXPECTED_KEY_MISMATCH",
    "TOLERANCE_SOURCE_MISMATCH",
    "PROGRAM_REF_MISMATCH",
    "EVIDENCE_INCOMPLETE",
    "COMPARISON_SET_MISMATCH",
    "DOCUMENT_MISSING",
    "DOCUMENT_DIGEST_MISMATCH",
    "OBSERVATION_MISMATCH",
)


def _required_evidence(name: str, sides: Iterable[TraceLog]) -> set[tuple[str, str]]:
    """Return the references a cross-layer comparison must cite on its two sides."""
    if name == "branch_weights":
        return {(s.source.digest, e.id) for s in sides for e in s.events if e.kind == "branch"}
    return {(s.source.digest, f"o:{name}") for s in sides}


def _comparison_codes(
    comparison: Comparison,
    logs: Mapping[str, TraceLog],
    program_ref: str,
    verdicts: dict[str, str],
) -> set[str]:
    """Return the reference, pairing, evidence, and verdict codes of one comparison.

    The recomputed verdict goes into ``verdicts`` by comparison name.
    """
    if not comparison.evidence_refs:
        return {"EVIDENCE_EMPTY"}
    codes: set[str] = set()
    cited: set[tuple[str, str]] = set()
    for digest, event_id in comparison.evidence_refs:
        if not _is_event_id(event_id):
            codes.add("REF_KIND_INVALID")
        elif digest not in logs:
            codes.add("REF_SOURCE_MISSING")
        elif event_id not in {event.id for event in logs[digest].events}:
            codes.add("REF_MISSING")
        else:
            cited.add((digest, event_id))
    sides = [logs[digest] for digest in sorted({digest for digest, _ in cited})]
    if not sides:
        return codes
    if any(side.source.program_ref != program_ref for side in sides):
        codes.add("PROGRAM_REF_MISMATCH")
    layers = 1 if comparison.kind == "same_layer" else 2
    programs = {side.source.program_ref for side in sides}
    if len(programs) != 1 or len({side.source.layer for side in sides}) != layers:
        codes.add("INPUT_MISMATCH")
    if comparison.kind == "cross_layer" and cited != _required_evidence(comparison.name, sides):
        codes.add("EVIDENCE_INCOMPLETE")
    if "INPUT_MISMATCH" in codes:
        return codes
    delta = _recomputed_delta(comparison, sides)
    if delta is None:
        return codes | {"VERDICT_MISMATCH"}
    verdicts[comparison.name] = _verdict_of(comparison, delta)
    if delta != comparison.delta or verdicts[comparison.name] != comparison.verdict:
        codes.add("VERDICT_MISMATCH")
    return codes


def _exclusion_codes(
    certificate: PreservationCertificate, logs: Mapping[str, TraceLog], verdicts: dict[str, str]
) -> set[str]:
    """Return ``EXCLUSION_MISMATCH`` if the recomputed exclusions or verdict disagree."""
    cited = {d for c in certificate.comparisons for d, e in c.evidence_refs if d in logs}
    keys = {(logs[d].source.layer, _dominant_key(logs[d])) for d in cited}
    excluded = {(lay, k) for lay, k in keys if k is not None and k != certificate.expected_key}
    stated = {(e.layer, e.dominant_key) for e in certificate.exclusions}
    rows = [replace(c, verdict=verdicts.get(c.name, c.verdict)) for c in certificate.comparisons]
    verdict = numerical_verdict_of(
        rows, [Exclusion(layer=lay, dominant_key=k) for lay, k in excluded]
    )
    if excluded != stated or verdict != certificate.numerical_verdict:
        return {"EXCLUSION_MISMATCH"}
    return set()


def _recomputed_delta(comparison: Comparison, sides: list[TraceLog]) -> float | None:
    """Return the delta of a comparison from its two sides; None if it cannot be computed."""
    if comparison.kind == "same_layer":
        return 0.0 if len(sides) == 1 else 1.0
    if len(sides) != 2:
        return None
    if comparison.name == "branch_weights":
        weights = [
            {e.id: e.path_weight or 0.0 for e in s.events if e.kind == "branch"} for s in sides
        ]
        keys = set(weights[0]) | set(weights[1])
        return max(
            (abs(weights[0].get(k, 0.0) - weights[1].get(k, 0.0)) for k in keys), default=0.0
        )
    values = [
        next((e.value for e in s.events if e.id == f"o:{comparison.name}"), None) for s in sides
    ]
    if values[0] is None or values[1] is None:
        return None
    return abs(values[0] - values[1])


def _verdict_of(comparison: Comparison, delta: float) -> str:
    """Return ``within`` if ``|delta| <= tolerance``; a same-layer comparison needs delta 0."""
    if comparison.tolerance is None:
        return "within" if delta == 0.0 else "exceeded"
    return "within" if abs(delta) <= comparison.tolerance else "exceeded"


def _dominant_key(log: TraceLog) -> str | None:
    """Return the leaf branch key with the largest path weight; None without branches."""
    keys = {e.id[2:]: e.path_weight or 0.0 for e in log.events if e.kind == "branch"}
    leaves = [k for k in keys if not any(o != k and o.startswith(k) for o in keys)]
    return max(leaves, key=lambda k: (keys[k], k), default=None)


_OBSERVATION_TOLERANCE = 1e-10
_DOCUMENT_ERRORS = (ValueError, KeyError, TypeError, IndexError, struct.error)


def _fetch(digest: str, documents: Mapping[str, bytes]) -> bytes | str:
    """Return the document under ``digest``; a failure code if it is absent or altered."""
    data = documents.get(digest)
    if data is None:
        return "DOCUMENT_MISSING"
    if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        return "DOCUMENT_DIGEST_MISMATCH"
    return data


def _population(definition: Mapping[str, Any], document: bytes) -> float:
    """Return the final-state population of the definition's target in one result document.

    Raises:
        ValueError: The document does not fit the definition (order, dimension, layout).
    """
    result = json.loads(document)
    order, dims = list(definition["tensor_order"]), list(definition["site_dims"])
    if result["tensor_order"] != order or len(dims) != len(order):
        raise ValueError("tensor_order differs from the result document")
    (state,) = [o for o in result["observations"] if o["kind"] == "full_state"]
    array, dim = state["data"], math.prod(dims)
    density = {"ket": False, "density": True}[state["representation"]]
    shape = array["shape"]
    if array["dtype"] != "c128le" or shape[1:] != [dim] * (1 + density) or shape[0] < 1:
        raise ValueError("site_dims do not give the final-state dimension")
    raw = base64.b64decode(array["data"], validate=True)
    values = struct.unpack(f"<{2 * math.prod(shape)}d", raw)
    position = {label: n for n, label in enumerate(order)}
    wanted = {position[label]: level for label, level in definition["target"]}
    if any(not 0 <= level < dims[n] for n, level in wanted.items()):
        raise ValueError("target level is outside its site")
    offset, total = (shape[0] - 1) * dim ** (1 + density), 0.0
    for index in range(dim):
        digits, rest = [], index
        for size in reversed(dims):
            digits.append(rest % size)
            rest //= size
        if all(digits[len(dims) - 1 - n] == level for n, level in wanted.items()):
            k = 2 * (offset + (index * dim + index if density else index))
            total += values[k] if density else values[k] ** 2 + values[k + 1] ** 2
    return total


def _observation_codes(
    event: TraceEvent, log: TraceLog, documents: Mapping[str, bytes] | None
) -> set[str]:
    """Return the document and observation codes of one observable event.

    The definition comes first, then the leaf documents; each is hashed before it is parsed.
    """
    if documents is None:
        return {"DOCUMENT_MISSING"}
    definition = _fetch(event.result_digest or "", documents)
    if isinstance(definition, str):
        return {definition}
    try:
        tree = json.loads(definition)
        leaves = {key: _fetch(digest, documents) for key, digest in tree["leaves"]}
    except _DOCUMENT_ERRORS:
        return {"OBSERVATION_MISMATCH"}
    codes = {data for data in leaves.values() if isinstance(data, str)}
    if codes:
        return codes
    found = {key: data for key, data in leaves.items() if isinstance(data, bytes)}
    # A leaf without a branch event or without a path weight is an observation mismatch.
    weights = {
        e.id[2:]: e.path_weight
        for e in log.events
        if e.kind == "branch" and e.path_weight is not None
    }
    if not set(found) <= set(weights):
        return {"OBSERVATION_MISMATCH"}
    try:
        value = math.fsum(weights[k] * _population(tree, data) for k, data in found.items())
    except _DOCUMENT_ERRORS:
        return {"OBSERVATION_MISMATCH"}
    if abs(value - (event.value or 0.0)) > _OBSERVATION_TOLERANCE:
        return {"OBSERVATION_MISMATCH"}
    return set()


def _tolerance_codes(certificate: PreservationCertificate, document: bytes) -> set[str]:
    """Return the tolerance-file and comparison-set codes; the hash is checked before parsing."""
    digest = "sha256:" + hashlib.sha256(document).hexdigest()
    if digest != certificate.tolerance_source.digest:
        return {"TOLERANCE_SOURCE_MISMATCH"}
    try:
        table = load_tolerances(document)
    except TraceInputError:
        return {"TOLERANCE_SOURCE_MISMATCH"}
    codes: set[str] = set()
    cross = {c.name: c for c in certificate.comparisons if c.kind == "cross_layer"}
    if set(cross) != set(table.comparisons):
        codes.add("COMPARISON_SET_MISMATCH")
    for name, entry in table.comparisons.items():
        level = next((t for t in _LADDER if t >= entry.max_abs_delta), None)
        stated = cross.get(name)
        if entry.tolerance != level or (stated is not None and stated.tolerance != entry.tolerance):
            codes.add("TOLERANCE_SOURCE_MISMATCH")
    return codes


def check_certificate(
    certificate: PreservationCertificate,
    trace_logs: Iterable[TraceLog],
    *,
    expected_key: str,
    tolerance_document: bytes,
    result_documents: Mapping[str, bytes] | None = None,
) -> tuple[str, ...]:
    """Check a certificate against its trace logs, the ideal key, and the tolerance file.

    A reference is checked for its kind, then its record, then its event; a bad
    reference does not enter the later checks.

    Args:
        certificate: Certificate to check.
        trace_logs: Trace logs that the references cite, found by ``source.digest``.
        expected_key: Ideal dominant key, as the caller computes it.
        tolerance_document: Bytes of the frozen tolerance file.
        result_documents: Observation definitions and leaf result documents, by
            ``sha256:<hex>`` digest. Each cited observable event is recomputed from them.

    Returns:
        Failure codes without duplicates, in a fixed order; empty when the certificate holds.

    Raises:
        TraceInputError: An argument has the wrong type.
    """
    if not isinstance(certificate, PreservationCertificate):
        raise TraceInputError("certificate must be a PreservationCertificate")
    logs = {log.source.digest: log for log in _items("trace_logs", trace_logs, TraceLog)}
    _bits("expected_key", expected_key)
    if not isinstance(tolerance_document, bytes):
        raise TraceInputError("tolerance_document must be bytes")
    if result_documents is not None and (
        not isinstance(result_documents, Mapping)
        or not all(isinstance(data, bytes) for data in result_documents.values())
    ):
        raise TraceInputError("result_documents must map digests to bytes")
    codes: set[str] = set()
    verdicts: dict[str, str] = {}
    observed = {
        (log.source.digest, e.id): (log, e)
        for log in logs.values()
        for e in log.events
        if e.kind == "observable"
    }
    for comparison in certificate.comparisons:
        codes |= _comparison_codes(comparison, logs, certificate.program_ref, verdicts)
        for ref in comparison.evidence_refs:
            if ref in observed:
                codes |= _observation_codes(observed[ref][1], observed[ref][0], result_documents)
    codes |= _exclusion_codes(certificate, logs, verdicts)
    if certificate.symbolic.level not in _DECIDABLE_LEVELS:
        codes.add("SYMBOLIC_LEVEL_UNDECIDABLE")
    if certificate.expected_key != expected_key:
        codes.add("EXPECTED_KEY_MISMATCH")
    codes |= _tolerance_codes(certificate, tolerance_document)
    return tuple(code for code in _FAILURE_CODES if code in codes)
