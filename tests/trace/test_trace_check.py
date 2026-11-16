# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Failure codes of the certificate checker: each negative case raises exactly one code."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from qaiji.core.semantics import EquivLevel
from qaiji.core.trace import (
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
    check_certificate,
    dump_certificate,
    dump_tolerances,
    load_certificate,
    load_tolerances,
)

Q0 = "kernel:4f1a9c03"
NONE = "kernel:4f1a9c04"  # differs from Q0 only in the last character
L0 = "sha256:" + "9f2a" * 16
L1 = "sha256:" + "41c7" * 16
L1_COPY = "sha256:" + "e05b" * 16
NONE_L0 = "sha256:" + "b8d3" * 16
NONE_L1 = "sha256:" + "6a90" * 16
POP = "o:encoded_population"

# path weights per branch key; l0 differs from l1 by a few 1e-12 on two keys; the leaf
# weights sum to 0.99 (a pruned remainder)
L1_WEIGHTS = {"0": 0.25, "1": 0.75, "00": 0.125, "01": 0.125, "10": 0.075, "11": 0.665}
L0_WEIGHTS = {**L1_WEIGHTS, "10": 0.075 - 3e-12, "11": 0.665 + 3e-12}
BRANCH_DELTA = max(abs(L0_WEIGHTS[k] - L1_WEIGHTS[k]) for k in L1_WEIGHTS)

# Hand-written 2-site documents: Kronecker order ("1", "0"), dims (3, 2), two time slices.
# The target (site "1" level 1, site "0" level 1) is index 1 * 2 + 1 = 3 of the final slice:
# the ket amplitude there is 0.36+0.48j (population 0.36), the density diagonal is 0.25.
DATA = Path(__file__).parent / "data" / "trace_check"
KET = (DATA / "ket.result.json").read_bytes()
DENSITY = (DATA / "density.result.json").read_bytes()
LEAF_DOCS = {"00": DENSITY, "01": KET, "10": DENSITY, "11": KET}
LEAF_POPS = {"00": 0.25, "01": 0.36, "10": 0.25, "11": 0.36}


def _digest(document: bytes) -> str:
    return "sha256:" + hashlib.sha256(document).hexdigest()


def _definition(target=(("1", 1), ("0", 1)), leaves=None, **changes) -> bytes:
    """Canonical JSON bytes of a basis-population observation over the leaf documents."""
    leaves = LEAF_DOCS if leaves is None else leaves
    tree = {
        "kind": "basis_population",
        "target": [list(pair) for pair in target],
        "tensor_order": ["1", "0"],
        "site_dims": [3, 2],
        "leaves": sorted([key, _digest(document)] for key, document in leaves.items()),
        **changes,
    }
    return json.dumps(tree, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


DEF = _definition()
DOCS = {_digest(document): document for document in (KET, DENSITY, DEF)}


def _population(weights: dict[str, float]) -> float:
    return sum(weights[key] * LEAF_POPS[key] for key in LEAF_POPS)


L1_POP, L0_POP = _population(L1_WEIGHTS), _population(L0_WEIGHTS)


def _log(
    digest: str,
    layer: str,
    weights: dict[str, float],
    pop: float | None = None,
    program_ref: str = Q0,
    definition: bytes = DEF,
):
    parents = {"0": 1.0, "1": 1.0, "00": 0.25, "01": 0.25, "10": 0.75, "11": 0.75}
    events = [
        TraceEvent(id=f"m{i}", kind="measurement", qubit=i, register="s", bit_index=i)
        for i in (0, 1)
    ]
    for key in ("0", "1", "00", "01", "10", "11"):
        events.append(
            TraceEvent(
                id=f"b:{key}",
                kind="branch",
                conditional_weight=weights[key] / parents[key],
                path_weight=weights[key],
                pruned=False,
            )
        )
    value = _population(weights) if pop is None else pop
    events.append(
        TraceEvent(id=POP, kind="observable", value=value, result_digest=_digest(definition))
    )
    source = TraceSource(
        kind="cross_layer_record", digest=digest, program_ref=program_ref, layer=layer
    )
    return TraceLog(source=source, events=tuple(events))


LOG_L0 = _log(L0, "l0", L0_WEIGHTS, L0_POP)
LOG_L1 = _log(L1, "l1", L1_WEIGHTS, L1_POP)


def _table(pop_tolerance: float = 1e-10) -> ToleranceTable:
    return ToleranceTable(
        comparisons={
            "branch_weights": ToleranceEntry(max_abs_delta=4e-12, tolerance=1e-10),
            "encoded_population": ToleranceEntry(max_abs_delta=4e-12, tolerance=pop_tolerance),
        },
        calibration_records=("sha256:" + "c3" * 32, "sha256:" + "57" * 32),
    )


DOC = dump_tolerances(_table())


def _branch_refs(*logs: TraceLog) -> tuple[tuple[str, str], ...]:
    """All branch events of the given logs, listed in reverse (non-canonical) order."""
    refs = [(log.source.digest, e.id) for log in logs for e in log.events if e.kind == "branch"]
    return tuple(reversed(refs))


def _value(log: TraceLog) -> float:
    return next(e.value for e in log.events if e.id == POP)


def _comparisons(l0: TraceLog, l1: TraceLog, pop_tolerance: float = 1e-10):
    d0, d1 = l0.source.digest, l1.source.digest
    return (
        Comparison(
            name="l0_reproducible",
            kind="same_layer",
            tolerance=None,
            delta=0.0,
            verdict="within",
            evidence_refs=((d0, "m0"),),
        ),
        Comparison(
            name="branch_weights",
            kind="cross_layer",
            tolerance=1e-10,
            delta=BRANCH_DELTA,
            verdict="within",
            evidence_refs=_branch_refs(l1, l0),
        ),
        Comparison(
            name="encoded_population",
            kind="cross_layer",
            tolerance=pop_tolerance,
            delta=abs(_value(l0) - _value(l1)),
            verdict="within",
            evidence_refs=((d1, POP), (d0, POP)),
        ),
    )


def _certificate(comparisons=None, document: bytes = DOC, **changes) -> PreservationCertificate:
    fields = dict(
        program_ref=Q0,
        expected_key="11",
        symbolic=SymbolicLevel(
            level=EquivLevel.UP_TO_PHASE, stage="native_lowering", ruleset_version="v1"
        ),
        comparisons=_comparisons(LOG_L0, LOG_L1) if comparisons is None else comparisons,
        exclusions=(),
        numerical_verdict="within",
        tolerance_source=ToleranceSource(rule="precision_ladder", digest=_digest(document)),
        assumptions=Assumptions(result_latency_ns=ResultLatency(value=200, source="config")),
    )
    fields.update(changes)
    return PreservationCertificate(**fields)


def _check(certificate, logs=(LOG_L0, LOG_L1), *, expected_key="11", document=DOC, docs=DOCS):
    return check_certificate(
        certificate,
        logs,
        expected_key=expected_key,
        tolerance_document=document,
        result_documents=docs,
    )


def _with_refs(index: int, refs):
    """Return the fixture comparisons with comparison ``index`` given new evidence refs."""
    items = list(_comparisons(LOG_L0, LOG_L1))
    items[index] = replace(items[index], evidence_refs=tuple(refs))
    return tuple(items)


def _extra_ref(ref):
    population = _comparisons(LOG_L0, LOG_L1)[2]
    return _certificate(_with_refs(2, (*population.evidence_refs, ref)))


# --- consistent certificate ---------------------------------------------------------


def test_consistent_certificate_passes() -> None:
    assert _check(_certificate()) == ()


def test_latency_assumption_does_not_change_the_result() -> None:
    other = Assumptions(result_latency_ns=ResultLatency(value=7, source="verilator"))
    for expected_key in ("11", "10"):
        base = _check(_certificate(), expected_key=expected_key)
        assert _check(_certificate(assumptions=other), expected_key=expected_key) == base


# --- references -----------------------------------------------------------------------


def test_unknown_record_hash_reports_ref_source_missing() -> None:
    assert _check(_extra_ref(("sha256:" + "0d" * 32, POP))) == ("REF_SOURCE_MISSING",)


def test_unknown_event_id_reports_ref_missing() -> None:
    assert _check(_extra_ref((L1, "b:111"))) == ("REF_MISSING",)


def test_reference_to_assumption_field_reports_ref_kind_invalid() -> None:
    certificate = _extra_ref((L1, "assumptions.result_latency_ns"))
    assert _check(load_certificate(dump_certificate(certificate))) == ("REF_KIND_INVALID",)


def test_comparison_without_evidence_reports_evidence_empty() -> None:
    assert _check(_certificate(_with_refs(1, ()))) == ("EVIDENCE_EMPTY",)


# --- pairing and program identity -----------------------------------------------------


def test_pair_from_wrong_layers_reports_input_mismatch() -> None:
    """A cross-layer comparison whose two sides both come from l1."""
    l1_copy = _log(L1_COPY, "l1", L0_WEIGHTS, L0_POP)
    certificate = _certificate(_comparisons(l1_copy, LOG_L1))
    assert _check(certificate, (l1_copy, LOG_L1)) == ("INPUT_MISMATCH",)


@pytest.mark.parametrize("case", ["different_injection", "same_layer_across_layers"])
def test_pair_from_different_injections_reports_input_mismatch(case: str) -> None:
    logs = (LOG_L0, LOG_L1)
    if case == "different_injection":
        other = _log(NONE_L1, "l1", L1_WEIGHTS, L1_POP, program_ref=NONE)
        certificate, logs = _certificate(_comparisons(LOG_L0, other)), (LOG_L0, other)
    else:
        certificate = _certificate(_with_refs(0, ((L0, "m0"), (L1, "m0"))))
    assert "INPUT_MISMATCH" in _check(certificate, logs)


def test_evidence_from_another_injection_reports_program_ref_mismatch() -> None:
    none_l0 = _log(NONE_L0, "l0", L0_WEIGHTS, L0_POP, program_ref=NONE)
    none_l1 = _log(NONE_L1, "l1", L1_WEIGHTS, L1_POP, program_ref=NONE)
    certificate = _certificate(_comparisons(none_l0, none_l1))
    assert _check(certificate, (none_l0, none_l1)) == ("PROGRAM_REF_MISMATCH",)


# --- evidence completeness and comparison set -----------------------------------------


@pytest.mark.parametrize("index", [1, 2], ids=["branch_only_b11", "population_cites_branch"])
def test_partial_or_wrong_kind_evidence_reports_evidence_incomplete(index: int) -> None:
    certificate = _certificate(_with_refs(index, ((L1, "b:11"), (L0, "b:11"))))
    assert _check(certificate) == ("EVIDENCE_INCOMPLETE",)


def test_missing_population_comparison_reports_comparison_set_mismatch() -> None:
    certificate = _certificate(_comparisons(LOG_L0, LOG_L1)[:2])
    assert _check(certificate) == ("COMPARISON_SET_MISMATCH",)


# --- caller inputs --------------------------------------------------------------------


def test_caller_expected_key_differs_reports_expected_key_mismatch() -> None:
    assert _check(_certificate(), expected_key="10") == ("EXPECTED_KEY_MISMATCH",)


@pytest.mark.parametrize("index", [1, 2])
def test_changed_delta_reports_verdict_mismatch(index: int) -> None:
    # Doubling the delta keeps the verdict; only the recomputed delta disagrees.
    items = list(_comparisons(LOG_L0, LOG_L1))
    items[index] = replace(items[index], delta=2 * items[index].delta)
    assert _check(_certificate(tuple(items))) == ("VERDICT_MISMATCH",)


@pytest.mark.parametrize(
    ("delta", "verdict"),
    [(1e-10, "within"), (math.nextafter(1e-10, math.inf), "exceeded")],
)
def test_branch_weight_boundary(delta: float, verdict: str) -> None:
    # The criterion is |delta| <= tolerance: equality is within, one ulp above is exceeded.
    l1 = _log(L1, "l1", {**L1_WEIGHTS, "10": 0.0})
    l0 = _log(L0, "l0", {**L1_WEIGHTS, "10": delta})
    items = list(_comparisons(l0, l1))
    items[1] = replace(items[1], delta=delta, verdict=verdict)
    assert _check(_certificate(tuple(items), numerical_verdict=verdict), (l0, l1)) == ()
    flipped = "exceeded" if verdict == "within" else "within"
    items[1] = replace(items[1], verdict=flipped)
    wrong = _certificate(tuple(items), numerical_verdict=flipped)
    assert "VERDICT_MISMATCH" in _check(wrong, (l0, l1))


def test_added_exclusion_reports_exclusion_mismatch() -> None:
    # Both layers lead with key 11, so no layer may be excluded.
    exclusion = Exclusion(layer="l1", dominant_key="10")
    certificate = _certificate(exclusions=(exclusion,), numerical_verdict="excluded")
    assert _check(certificate) == ("EXCLUSION_MISMATCH",)


@pytest.mark.parametrize("level", [EquivLevel.UP_TO_LOCAL, EquivLevel.ENTANGLEMENT])
def test_undecidable_symbolic_level_reports_symbolic_level_undecidable(level) -> None:
    symbolic = SymbolicLevel(level=level, stage="native_lowering", ruleset_version="v1")
    assert _check(_certificate(symbolic=symbolic)) == ("SYMBOLIC_LEVEL_UNDECIDABLE",)


def _tolerance_case(case: str) -> tuple[PreservationCertificate, bytes]:
    if case == "digest":
        return _certificate(), DOC + b"\n"
    if case == "comparison_value":
        items = list(_comparisons(LOG_L0, LOG_L1))
        items[1] = replace(items[1], tolerance=1e-6)
        return _certificate(tuple(items)), DOC
    if case == "ladder":
        document = dump_tolerances(_table(pop_tolerance=1.0))
        comparisons = _comparisons(LOG_L0, LOG_L1, pop_tolerance=1.0)
        return _certificate(comparisons, document=document), document
    document = json.dumps({"schema": "qaiji.t.tolerances/1.0"}).encode()
    return _certificate(document=document), document


@pytest.mark.parametrize("case", ["digest", "comparison_value", "ladder", "unreadable"])
def test_tolerance_source_mismatch(case: str) -> None:
    certificate, document = _tolerance_case(case)
    assert _check(certificate, document=document) == ("TOLERANCE_SOURCE_MISMATCH",)


# --- observation documents --------------------------------------------------------------


def _without(document: bytes) -> dict[str, bytes]:
    return {key: data for key, data in DOCS.items() if key != _digest(document)}


@pytest.mark.parametrize("docs", [None, _without(DEF), _without(KET)], ids=["none", "def", "leaf"])
def test_missing_documents_report_document_missing(docs) -> None:
    # Without documents the observation is not recomputed, so the check must not pass.
    assert _check(_certificate(), docs=docs) == ("DOCUMENT_MISSING",)


@pytest.mark.parametrize("swap", [(KET, DENSITY), (DEF, _definition(target=(("1", 2),)))])
def test_swapped_document_reports_document_digest_mismatch(swap) -> None:
    document, other = swap
    docs = {**DOCS, _digest(document): other}
    assert _check(_certificate(), docs=docs) == ("DOCUMENT_DIGEST_MISMATCH",)


def test_changed_observation_value_reports_observation_mismatch() -> None:
    # Both values move by 2e-10, so the certificate delta stays consistent and within;
    # only the recompute from the documents finds the change.
    l0 = _log(L0, "l0", L0_WEIGHTS, L0_POP + 2e-10)
    l1 = _log(L1, "l1", L1_WEIGHTS, L1_POP + 2e-10)
    assert _check(_certificate(_comparisons(l0, l1)), (l0, l1)) == ("OBSERVATION_MISMATCH",)


@pytest.mark.parametrize("case", ["unparsable", "tensor_order", "site_dims"])
def test_unusable_document_reports_observation_mismatch(case: str) -> None:
    # Every digest holds; the content does not fit the definition.
    docs = dict(DOCS)
    if case == "unparsable":
        broken = KET[:-3]
        docs[_digest(broken)] = broken
        definition = _definition(leaves={**LEAF_DOCS, "01": broken, "11": broken})
    elif case == "tensor_order":
        definition = _definition(tensor_order=["0", "1"])
    else:
        definition = _definition(site_dims=[2, 2])
    docs[_digest(definition)] = definition
    l0 = _log(L0, "l0", L0_WEIGHTS, definition=definition)
    l1 = _log(L1, "l1", L1_WEIGHTS, definition=definition)
    certificate = _certificate(_comparisons(l0, l1))
    assert _check(certificate, (l0, l1), docs=docs) == ("OBSERVATION_MISMATCH",)


def _density_document(diagonal: dict[int, float]) -> bytes:
    """Return the density fixture with one time slice and the given diagonal (dim 6)."""
    tree = json.loads(DENSITY)
    values = [diagonal.get(i, 0.0) if i == j else 0.0 for i in range(6) for j in range(6)]
    raw = struct.pack("<72d", *(part for v in values for part in (v, 0.0)))
    tree["observations"][0]["data"].update(shape=[1, 6, 6], data=base64.b64encode(raw).decode())
    return json.dumps(tree).encode()


@pytest.mark.parametrize(
    ("delta", "verdict"),
    [(1e-10, "within"), (math.nextafter(1e-10, math.inf), "exceeded")],
)
def test_population_boundary(delta: float, verdict: str) -> None:
    # l1 observes an empty basis state (exactly 0.0); l0 observes about 1e-10 from a
    # dedicated document, and its event value is the boundary value itself.
    zero = _definition(target=(("1", 2), ("0", 1)))
    tiny = _density_document({3: 1e-10 / sum(L0_WEIGHTS[key] for key in LEAF_POPS)})
    small = _definition(leaves=dict.fromkeys(LEAF_POPS, tiny))
    docs = {**DOCS, **{_digest(d): d for d in (zero, tiny, small)}}
    l1 = _log(L1, "l1", L1_WEIGHTS, 0.0, definition=zero)
    l0 = _log(L0, "l0", L0_WEIGHTS, delta, definition=small)
    items = list(_comparisons(l0, l1))
    assert items[2].delta == delta
    items[2] = replace(items[2], verdict=verdict)
    certificate = _certificate(tuple(items), numerical_verdict=verdict)
    assert _check(certificate, (l0, l1), docs=docs) == ()
    flipped = "exceeded" if verdict == "within" else "within"
    items[2] = replace(items[2], verdict=flipped)
    wrong = _certificate(tuple(items), numerical_verdict=flipped)
    assert "VERDICT_MISMATCH" in _check(wrong, (l0, l1), docs=docs)


def test_check_rejects_wrong_input_types() -> None:
    certificate = _certificate()
    with pytest.raises(TraceInputError):
        check_certificate({}, (LOG_L0,), expected_key="11", tolerance_document=DOC)
    with pytest.raises(TraceInputError):
        _check(certificate, docs={_digest(KET): KET.decode()})
    with pytest.raises(TraceInputError):
        _check(certificate, document=DOC.decode())
    with pytest.raises(TraceInputError):
        _check(certificate, logs=(LOG_L0, {}))


# --- tolerance document codec ----------------------------------------------------------


def test_tolerance_document_round_trip() -> None:
    table = _table()
    loaded = load_tolerances(dump_tolerances(table))
    assert loaded == table
    for name, entry in table.comparisons.items():
        for field in ("max_abs_delta", "tolerance"):
            got = getattr(loaded.comparisons[name], field)
            assert struct.pack(">d", got) == struct.pack(">d", getattr(entry, field))
    tree = json.loads(DOC)
    assert DOC == json.dumps(tree, sort_keys=True, separators=(",", ":")).encode()
    assert tree["comparisons"]["branch_weights"]["tolerance"] == struct.pack(">d", 1e-10).hex()
    assert tree["rule"] == "precision_ladder"


def _rewrite(edit) -> bytes:
    tree = json.loads(DOC)
    edit(tree)
    return json.dumps(tree).encode()


@pytest.mark.parametrize(
    "edit",
    [
        lambda t: t.update(schema="qaiji.t.tolerances/1.1"),
        lambda t: t.update(rule="max_spread"),
        lambda t: t["comparisons"]["encoded_population"].update(tolerance=1e-10),
        lambda t: t.update(note="x"),
    ],
    ids=["schema", "rule", "decimal_float", "unknown_key"],
)
def test_load_tolerances_rejects_malformed(edit) -> None:
    with pytest.raises(TraceInputError):
        load_tolerances(_rewrite(edit))
