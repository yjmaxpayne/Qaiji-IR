# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""固定完整二叉分支树、事件顺序与旧版本拒绝。"""

import dataclasses
import itertools
import json

import pytest

import qaiji.core.invariants as invariants
from _pulse_fixtures import config, lower_to_l1
from _waveform_fixtures import waveform
from factories import bell_circuit
from qaiji.core.native import lower_to_native
from qaiji.core.waveform import (
    WAVEFORM_SCHEMA,
    Segment,
    WaveformContractError,
    dump_waveform,
    load_waveform,
)


def tree(depth=3):
    assert WAVEFORM_SCHEMA == "qaiji.waveform/0.2", (
        "Waveforms must carry complete branch histories."
    )
    base = waveform()
    segments = []
    for level in range(depth + 1):
        for bits in itertools.product((0, 1), repeat=level):
            id = (
                "segment-1"
                if not bits
                else "segment-" + str(level + 1) + "-branch-" + "".join(map(str, bits))
            )
            segments.append(
                Segment(
                    id=id,
                    time_origin_ns=level * 10,
                    branch=tuple((f"m{i}", bit) for i, bit in enumerate(bits)),
                    samples=base.segments[0].samples,
                )
            )
    return dataclasses.replace(base, segments=tuple(segments))


def test_complete_three_measurement_tree_roundtrips_and_keeps_single_segment_ids():
    built = tree()
    assert len(built.segments) == 15
    assert load_waveform(dump_waveform(built)) == built
    assert [s.id for s in tree(1).segments] == [
        "segment-1",
        "segment-2-branch-0",
        "segment-2-branch-1",
    ]
    assert invariants.check_invariants(dump_waveform(built), layer="L0").ok


@pytest.mark.parametrize(
    "fault", ["parent", "sibling", "subtree", "uneven", "duplicate", "event", "repeat"]
)
def test_each_tree_mutation_reaches_its_target_diagnostic(fault):
    built = tree()
    payload = json.loads(dump_waveform(built))
    segments = payload["segments"]
    if fault == "parent":
        del segments[0]
    elif fault == "sibling":
        segments.pop()
    elif fault == "subtree":
        payload["segments"] = [s for s in segments if not s["branch"] or s["branch"][0]["bit"] == 1]
    elif fault == "uneven":
        payload["segments"] = [
            s
            for s in segments
            if len(s["branch"]) != 3 or [b["bit"] for b in s["branch"][:2]] != [0, 0]
        ]
    elif fault == "duplicate":
        segments.append({**segments[-1], "id": "different-id"})
    elif fault == "event":
        segments[-1]["branch"][-1]["event_id"] = "different-event"
    else:
        segments[-1]["branch"][-1]["event_id"] = "m0"
    expected = "BRANCH_EVENTS" if fault in ("event", "repeat") else "BRANCH"
    with pytest.raises(WaveformContractError) as caught:
        load_waveform(json.dumps(payload).encode())
    (diagnostic,) = caught.value.diagnostics
    assert diagnostic.code == expected
    assert diagnostic.path.endswith("/branch")
    target_message = {
        "parent": "parent prefix",
        "sibling": "sibling",
        "subtree": "sibling",
        "uneven": "both children",
        "duplicate": "unique",
        "event": "same event sequence",
        "repeat": "repeat an event",
    }
    assert target_message[fault] in diagnostic.message
    report = invariants.check_invariants(json.dumps(payload).encode(), layer="L0")
    assert any(r.id == "I-L0.6" and r.verdict == "fail" for r in report.results)


def test_old_waveform_schema_is_rejected_before_field_decoding():
    payload = json.loads(dump_waveform(tree(1)))
    payload["schema"] = "qaiji.waveform/0.1"
    for segment in payload["segments"]:
        branch = segment.pop("branch")
        segment["condition"] = (
            {"id": branch[0]["event_id"], "taken": bool(branch[0]["bit"])} if branch else None
        )
    with pytest.raises(WaveformContractError) as caught:
        load_waveform(json.dumps(payload).encode())
    assert caught.value.diagnostics[0].code == "SCHEMA"


def test_leaf_events_match_acquire_order_for_every_leaf():
    built = tree(2)
    pulse = lower_to_l1(lower_to_native(bell_circuit(), config()))
    assert invariants.check_waveform_events(waveform=built, pulse=pulse).ok
    payload = json.loads(dump_waveform(built))
    for segment in payload["segments"]:
        for pair in segment["branch"]:
            pair["event_id"] = "wrong-" + pair["event_id"]
    candidate = load_waveform(json.dumps(payload).encode())
    assert not invariants.check_waveform_events(waveform=candidate, pulse=pulse).ok
    assert not invariants.check_waveform_events(waveform=tree(1), pulse=pulse).ok


@pytest.mark.parametrize(
    "branch",
    [
        True,
        [True],
        [{"event_id": "m0", "bit": True}],
        [{"event_id": "m0", "bit": 2}],
        [{"event_id": "", "bit": 0}],
    ],
)
def test_branch_field_rejects_non_bit_history(branch):
    payload = json.loads(dump_waveform(tree(0)))
    payload["segments"][0]["branch"] = branch
    with pytest.raises(WaveformContractError) as caught:
        load_waveform(json.dumps(payload).encode())
    if isinstance(branch, list) and branch and isinstance(branch[0], dict):
        assert caught.value.diagnostics[0].code == "BRANCH"
        assert "bit" in caught.value.diagnostics[0].message or not branch[0]["event_id"]
