# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Certificate checker: conflicting logs, tolerance provenance and same-layer coverage."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_trace_check import (
    DOC,
    L0,
    L0_POP,
    L0_WEIGHTS,
    L1,
    L1_POP,
    L1_WEIGHTS,
    LOG_L0,
    LOG_L1,
    NONE,
    NONE_L0,
    _certificate,
    _check,
    _comparisons,
    _log,
)

from qaiji.core.trace import Comparison, TraceLog, dump_trace_log, load_tolerances
from qaiji.core.trace.check import _FAILURE_CODES

L0_RERUN = "sha256:" + "d1e7" * 16
NONE_L0_RERUN = "sha256:" + "37ac" * 16

# a second l0 run of the same program whose record differs from LOG_L0
LOG_L0_RERUN = _log(L0_RERUN, "l0", L0_WEIGHTS, L0_POP)
LOG_NONE_L0 = _log(NONE_L0, "l0", L0_WEIGHTS, L0_POP, program_ref=NONE)
LOG_NONE_L0_RERUN = _log(NONE_L0_RERUN, "l0", L0_WEIGHTS, L0_POP, program_ref=NONE)


def _same_layer(*digests: str, name: str = "l0_reproducible", **changes) -> Comparison:
    """A same-layer comparison citing event ``m0`` of each given record."""
    fields = dict(
        name=name,
        kind="same_layer",
        tolerance=None,
        delta=0.0,
        verdict="within",
        evidence_refs=tuple((digest, "m0") for digest in digests),
    )
    fields.update(changes)
    return Comparison(**fields)


def _cross() -> tuple[Comparison, ...]:
    """The fixture cross-layer comparisons, without the same-layer one."""
    return _comparisons(LOG_L0, LOG_L1)[1:]


def _group(log: TraceLog) -> tuple[str, str]:
    return log.source.layer, log.source.program_ref


# --- logs that share a digest -----------------------------------------------------------


def _relabelled(log: TraceLog) -> TraceLog:
    """Same digest, different bytes: only the unreferenced ``m1`` register changes."""
    events = tuple(replace(e, register="c") if e.id == "m1" else e for e in log.events)
    return replace(log, events=events)


@pytest.mark.parametrize("order", ["copy_last", "copy_first"])
def test_same_digest_with_different_bytes_reports_trace_log_conflict(order: str) -> None:
    copy = _relabelled(LOG_L0)
    assert copy.source.digest == LOG_L0.source.digest
    assert dump_trace_log(copy) != dump_trace_log(LOG_L0)
    # each version on its own passes, so only the conflict can block
    assert _check(_certificate(), (copy, LOG_L1)) == ()
    assert _check(_certificate(), (LOG_L0, LOG_L1)) == ()
    logs = (LOG_L0, copy, LOG_L1) if order == "copy_last" else (copy, LOG_L0, LOG_L1)
    assert _check(_certificate(), logs) == ("TRACE_LOG_CONFLICT",)


def test_identical_duplicate_logs_pass() -> None:
    duplicate = _log(L0, "l0", L0_WEIGHTS, L0_POP)
    assert duplicate is not LOG_L0
    assert dump_trace_log(duplicate) == dump_trace_log(LOG_L0)
    assert _check(_certificate(), (LOG_L0, duplicate, LOG_L1)) == ()


# --- tolerance provenance -----------------------------------------------------------------


def test_tolerance_rule_differs_from_table_reports_tolerance_source_mismatch() -> None:
    certificate = _certificate()
    assert load_tolerances(DOC).rule == certificate.tolerance_source.rule
    assert _check(certificate) == ()
    source = replace(certificate.tolerance_source, rule="manual")
    assert source.digest == certificate.tolerance_source.digest
    assert _check(replace(certificate, tolerance_source=source)) == ("TOLERANCE_SOURCE_MISMATCH",)


def _stated_tolerance(case: str) -> tuple[Comparison, tuple[TraceLog, ...]]:
    """A same-layer comparison that states a tolerance, and the logs it cites."""
    if case == "two_digests":
        same = _same_layer(L0, L0_RERUN, tolerance=1.0, delta=1.0)
        return same, (LOG_L0, LOG_L0_RERUN, LOG_L1)
    tolerance = 1e-6 if case == "one_digest" else 0.0
    return _same_layer(L0, tolerance=tolerance), (LOG_L0, LOG_L1)


@pytest.mark.parametrize("case", ["two_digests", "one_digest", "zero_tolerance"])
def test_same_layer_tolerance_reports_same_layer_tolerance_present(case: str) -> None:
    same, logs = _stated_tolerance(case)
    assert same.tolerance is not None
    assert case == "two_digests" or same.delta == 0.0
    # without the tolerance (and with the verdict it then implies) the certificate passes
    verdict = "exceeded" if case == "two_digests" else "within"
    bare = replace(same, tolerance=None, verdict=verdict)
    assert _check(_certificate((bare, *_cross()), numerical_verdict=verdict), logs) == ()
    certificate = _certificate((same, *_cross()))
    assert _check(certificate, logs) == ("SAME_LAYER_TOLERANCE_PRESENT",)


# --- same-layer coverage ------------------------------------------------------------------


def test_certificate_without_same_layer_comparison_reports_comparison_set_mismatch() -> None:
    certificate = _certificate(_cross())
    assert all(c.kind == "cross_layer" for c in certificate.comparisons)
    # the cross-layer set matches the tolerance table, so that check cannot raise the code
    assert {c.name for c in certificate.comparisons} == set(load_tolerances(DOC).comparisons)
    assert _check(certificate) == ("COMPARISON_SET_MISMATCH",)


def test_uncited_same_layer_log_reports_evidence_incomplete() -> None:
    assert _group(LOG_L0_RERUN) == _group(LOG_L0)
    assert L0_RERUN != L0
    assert _check(_certificate()) == ()
    assert _check(_certificate(), (LOG_L0, LOG_L0_RERUN, LOG_L1)) == ("EVIDENCE_INCOMPLETE",)


@pytest.mark.parametrize("case", ["other_layer", "other_program"])
def test_logs_outside_the_cited_group_are_not_counted(case: str) -> None:
    certificate = _certificate()
    assert {d for d, _ in certificate.comparisons[0].evidence_refs} == {L0}
    if case == "other_layer":
        logs = (LOG_L0, LOG_L1)  # the l1 record is not cited by the same-layer comparison
        assert _group(LOG_L1)[0] != _group(LOG_L0)[0]
    else:
        logs = (LOG_L0, LOG_NONE_L0, LOG_L1)  # same layer, another program
        assert _group(LOG_NONE_L0) == ("l0", NONE) != _group(LOG_L0)
    assert _check(certificate, logs) == ()


def test_uncovered_repeated_group_reports_evidence_incomplete() -> None:
    """Two distinct l0 runs need a covering comparison even if only l1 is compared."""
    l1_copy = _log(L1, "l1", L1_WEIGHTS, L1_POP)
    assert dump_trace_log(l1_copy) == dump_trace_log(LOG_L1)
    assert _group(LOG_L0_RERUN) == _group(LOG_L0) and L0_RERUN != L0
    certificate = _certificate((_same_layer(L1, name="l1_reproducible"), *_cross()))
    # without the second l0 run the certificate passes
    assert _check(certificate, (LOG_L0, LOG_L1, l1_copy)) == ()
    logs = (LOG_L0, LOG_L0_RERUN, LOG_L1, l1_copy)
    assert _check(certificate, logs) == ("EVIDENCE_INCOMPLETE",)


@pytest.mark.parametrize("case", ["one_digest", "two_digests"])
def test_same_layer_evidence_from_another_program_is_rejected(case: str) -> None:
    """Reproducibility shown for another program does not certify this one."""
    if case == "one_digest":
        same = _same_layer(NONE_L0)
        logs = (LOG_L0, LOG_NONE_L0, LOG_NONE_L0, LOG_L1)
    else:
        same = _same_layer(NONE_L0, NONE_L0_RERUN)
        logs = (LOG_L0, LOG_NONE_L0, LOG_NONE_L0_RERUN, LOG_L1)
    cited = {digest for digest, _ in same.evidence_refs}
    assert {log.source.program_ref for log in logs if log.source.digest in cited} == {NONE}
    codes = _check(_certificate((same, *_cross())), logs)
    if case == "one_digest":
        assert codes == ("PROGRAM_REF_MISMATCH",)
    else:
        assert "PROGRAM_REF_MISMATCH" in codes


def test_repeated_identical_logs_need_a_covering_comparison() -> None:
    """A group counts the logs passed in, so two identical l1 copies need a comparison."""
    l1_copy = _log(L1, "l1", L1_WEIGHTS, L1_POP)
    assert dump_trace_log(l1_copy) == dump_trace_log(LOG_L1)
    certificate = _certificate()
    assert all(c.kind == "cross_layer" for c in certificate.comparisons[1:])
    assert _check(certificate, (LOG_L0, LOG_L1)) == ()
    assert _check(certificate, (LOG_L0, LOG_L1, l1_copy)) == ("EVIDENCE_INCOMPLETE",)


@pytest.mark.parametrize("case", ["distinct_runs", "identical_runs"])
def test_missing_same_layer_comparison_and_uncovered_group_report_both_codes(case: str) -> None:
    second = LOG_L0_RERUN if case == "distinct_runs" else _log(L0, "l0", L0_WEIGHTS, L0_POP)
    assert _group(second) == _group(LOG_L0)
    certificate = _certificate(_cross())
    assert _check(certificate) == ("COMPARISON_SET_MISMATCH",)
    codes = _check(certificate, (LOG_L0, second, LOG_L1))
    assert codes == ("EVIDENCE_INCOMPLETE", "COMPARISON_SET_MISMATCH")


def test_group_split_across_comparisons_reports_evidence_incomplete() -> None:
    """Each comparison cites one l0 run, so no comparison relates the two runs."""
    logs = (LOG_L0, LOG_L0_RERUN, LOG_L1)
    # one comparison over both runs covers the group
    joint = _same_layer(L0, L0_RERUN, delta=1.0, verdict="exceeded")
    assert _check(_certificate((joint, *_cross()), numerical_verdict="exceeded"), logs) == ()
    split = (_same_layer(L0), _same_layer(L0_RERUN, name="l0_rerun_reproducible"))
    certificate = _certificate((*split, *_cross()))
    assert _check(certificate, logs) == ("EVIDENCE_INCOMPLETE",)


# --- failure code order -------------------------------------------------------------------

RELEASED_CODES = (
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


def test_failure_codes_keep_the_released_order() -> None:
    """New codes go after the released ones, so callers that sort by position still work."""
    assert _FAILURE_CODES[:16] == RELEASED_CODES
    assert _FAILURE_CODES[16:] == ("TRACE_LOG_CONFLICT", "SAME_LAYER_TOLERANCE_PRESENT")
