# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""不变量登记、物理检查与统一跨层报告的行为契约。"""

from __future__ import annotations

import itertools
import json
from dataclasses import asdict, replace

import pytest

import qaiji.core.invariants as inv
from _pulse_fixtures import config, lower_to_l1
from _waveform_fixtures import waveform
from factories import bell_circuit, feedforward_circuit
from physical_result_factories import carray, result_for, result_request
from qaiji.core.native import lower_to_native
from qaiji.core.physical import CheckBudget, FrozenJSON, ObservationValue, check_request
from qaiji.core.physical.codec import dump_request, dump_result
from qaiji.core.physical.model import State
from qaiji.core.program import (
    ExperimentMetadata,
    ProgramCall,
    ProgramIf,
    ProgramIRV1,
    QuantumInvocation,
    ResultOutput,
)
from qaiji.core.pulse import (
    Acquire,
    Play,
    PortResourceEntry,
    PortResourceMap,
    dump_pulse_program,
    pulse_program_id,
)
from qaiji.core.waveform import Segment, dump_waveform

BELL_HASH = "sha256:afe9bc2fd0c5ae8b243a4a8615bbe457adde36c1753835884557bc2d31e043d1"
CHECKED = (
    "I-L5.4",
    "I-L4.3",
    "I-L2.6",
    "I-L2.7",
    "I-L1.6",
    "I-L1.7",
    "I-L0.5",
    "I-L0.6",
    "I-P.6",
    "I-P.7",
    "I-X.1",
    "I-X.2",
)


def physical_input(**kwargs):
    assert hasattr(inv, "PInvariantInput"), "P checks require an explicit input carrier."
    return inv.PInvariantInput(**kwargs)


def cross(**kwargs):
    assert hasattr(inv, "check_cross_layer"), "Resource and branch checks require a unified report."
    return inv.check_cross_layer(**kwargs)


def bound_records():
    native = lower_to_native(bell_circuit(), config())
    pulse = lower_to_l1(native)
    frames = {f.id: f.port for f in pulse.frames}
    resources = {}
    for item in pulse.instructions:
        if isinstance(item, Play) and item.source is not None:
            resources[frames[item.frame]] = native.operations[item.source].resources
    mapping = PortResourceMap(
        pulse_program_ref=pulse_program_id(pulse),
        entries=tuple(PortResourceEntry(port=p, resources=r) for p, r in sorted(resources.items())),
    )
    events = tuple(i.event_id for i in pulse.instructions if isinstance(i, Acquire))
    base = waveform(source_pulse_ref=pulse_program_id(pulse))
    segments = tuple(
        Segment(
            id=f"s{depth}-" + "".join(map(str, bits)),
            time_origin_ns=depth * 10,
            branch=tuple(zip(events[:depth], bits, strict=True)),
            samples=base.segments[0].samples,
        )
        for depth in range(len(events) + 1)
        for bits in itertools.product((0, 1), repeat=depth)
    )
    return dict(
        schedule=native,
        pulse=pulse,
        port_resources=mapping,
        waveform=replace(base, segments=segments),
    )


def program_input(depth):
    tail = ()
    for _ in range(depth):
        tail = (
            ProgramIf(invocation_index=0, register_name="c", value=0, then_body=tail, else_body=()),
        )
    return inv.ProgramInvariantInput(
        program=ProgramIRV1(
            quantum_invocations=(QuantumInvocation(BELL_HASH),),
            experiment_metadata=ExperimentMetadata(1),
            result_outputs=(ResultOutput(0, "c"),),
            control_flow=(ProgramCall(invocation_index=0), *tail),
        ),
        kernels={BELL_HASH: bell_circuit()},
    )


def conformance_pair(id):
    records = bound_records()
    native, pulse = records["schedule"], records["pulse"]
    layer = id.split("-")[1].split(".")[0]
    if id == "I-L5.4":
        return (
            layer,
            program_input(4),
            program_input(5),
            "/program/control_flow/1/then_body/0/then_body/0/then_body/0/then_body/0",
        )
    if id == "I-L4.3":
        good = inv.L4InvariantInput(circuit=bell_circuit(), recorded_summary_hash=BELL_HASH)
        return (
            layer,
            good,
            replace(good, recorded_summary_hash="sha256:" + "0" * 64),
            "/recorded_summary_hash",
        )
    if id == "I-L2.6":
        good = inv.L2InvariantInput(circuit=bell_circuit(), schedule=native, config=config())
        ops = list(native.operations)
        ops[1] = replace(ops[1], start_ns=ops[1].start_ns + 1)
        return (
            layer,
            good,
            replace(good, schedule=replace(native, operations=tuple(ops))),
            "/schedule/operations/1/start_ns",
        )
    if id == "I-L2.7":
        circuit = feedforward_circuit()
        scheduled = lower_to_native(circuit, config())
        good = inv.L2InvariantInput(circuit=circuit, schedule=scheduled, config=config())
        region = scheduled.conditions[0]
        bad = replace(scheduled, conditions=(replace(region, start_ns=region.start_ns - 1),))
        return layer, good, replace(good, schedule=bad), "/schedule/conditions/0/start_ns"
    if id in ("I-L1.6", "I-L1.7"):
        good = inv.L1InvariantInput(pulse=pulse, schedule=native)
        payload = json.loads(dump_pulse_program(pulse))
        if id == "I-L1.6":
            index = next(i for i, x in enumerate(payload["instructions"]) if x["kind"] == "play")
            payload["instructions"][index]["frame"] = "r0"
            path = f"/pulse/instructions/{index}/frame"
        else:
            indices = [i for i, x in enumerate(payload["instructions"]) if x["kind"] == "acquire"]
            payload["instructions"][indices[1]]["event_id"] = payload["instructions"][indices[0]][
                "event_id"
            ]
            path = f"/pulse/instructions/{indices[1]}/event_id"
        return layer, good, replace(good, pulse=json.dumps(payload).encode()), path
    if id in ("I-L0.5", "I-L0.6"):
        good = waveform(sample_rate_hz=1_500_000_000)
        payload = json.loads(dump_waveform(good))
        if id == "I-L0.5":
            payload["segments"][0]["time_origin_ns"] = 1
            path = "/segments/0/time_origin_ns"
        else:
            payload["segments"].append({**payload["segments"][0], "id": "other"})
            path = "/segments/1/branch"
        return layer, good, json.dumps(payload).encode(), path
    if id in ("I-P.6", "I-P.7"):
        req = result_request()
        good = physical_input(request=req)
        if id == "I-P.6":
            bad_request = replace(
                req,
                problem=replace(
                    req.problem,
                    initial_state=State(kind="ket", frame="lab", data=carray([2, 0], (2,))),
                ),
            )
            return layer, good, replace(good, request=bad_request), "/problem/initial_state/data"
        return (
            layer,
            good,
            replace(good, budget=CheckBudget(max_dense_dimension=1)),
            "/problem/sites",
        )
    if id == "I-X.1":
        bad = {**records, "port_resources": replace(records["port_resources"], entries=())}
        index = next(i for i, x in enumerate(pulse.instructions) if isinstance(x, Play))
        return layer, records, bad, f"/instructions/{index}"
    return layer, records, {**records, "waveform": waveform()}, "/waveform/segments/0/branch"


def run_case(layer, source):
    return cross(**source) if layer == "X" else inv.check_invariants(source, layer=layer)


def test_registry_has_twelve_checked_and_one_convention():
    rows = inv.invariant_registry()
    assert len(rows) == 13
    assert {r.id for r in rows if r.category == "checked"} == set(CHECKED)
    assert [(r.id, r.codes) for r in rows if r.category == "convention"] == [("I-L2.8", ())]


@pytest.mark.parametrize("id", CHECKED)
def test_checked_positive_and_single_violation(id):
    layer, good, bad, path = conformance_pair(id)
    passed = run_case(layer, good)
    assert passed.ok, passed
    assert any(r.id == id and r.verdict == "pass" for r in passed.results)
    assert all(r.id != "I-L2.8" for r in passed.results)
    failed = run_case(layer, bad)
    assert not failed.ok
    assert any(
        (r.id, r.layer, r.path, r.verdict) == (id, layer, path, "fail") for r in failed.results
    ), failed


@pytest.mark.parametrize("wire", [False, True])
def test_physical_request_and_result_inputs(wire):
    req = result_request()
    res = result_for(req)
    source = physical_input(
        request=dump_request(req).document if wire else req,
        result=dump_result(res).document if wire else res,
    )
    report = inv.check_invariants(source, layer="P")
    assert report.ok
    bad = replace(
        res,
        observations=(
            ObservationValue(
                id="state",
                kind="full_state",
                representation="ket",
                data=carray([2, 0] * req.output_times.shape[0], (req.output_times.shape[0], 2)),
            ),
        ),
    )
    source = replace(source, result=dump_result(bad).document if wire else bad)
    report = inv.check_invariants(source, layer="P")
    assert not report.ok
    assert any(
        r.id == "I-P.6"
        and r.path.startswith("/result/observations/")
        and "NORMALIZATION" in r.message
        for r in report.results
    )


@pytest.mark.parametrize("source", [None, b"{}"])
def test_physical_missing_or_invalid_inputs_cannot_pass(source):
    report = inv.check_invariants(physical_input(request=source), layer="P")
    assert not report.ok
    assert all(r.verdict == "fail" for r in report.results)


def test_physical_unknown_and_incomplete_diagnostics_cannot_pass(monkeypatch):
    from qaiji.core.physical import CheckReport, Diagnostic

    good = physical_input(request=result_request())
    assert inv.check_invariants(good, layer="P").ok
    for diagnostics in (
        (
            Diagnostic(
                category="INVALID_REQUEST",
                code="FUTURE",
                path="/x",
                message="future",
                details=FrozenJSON(value={}),
            ),
        ),
        (),
    ):
        monkeypatch.setattr(
            inv,
            "check_request",
            lambda *a, diagnostics=diagnostics, **k: CheckReport(
                level="physical",
                complete=False,
                diagnostics=diagnostics,
                checked=(),
                unchecked=("state",),
            ),
        )
        report = inv.check_invariants(good, layer="P")
        assert not report.ok
        assert all(r.verdict == "fail" for r in report.results)
        assert any(r.id == "UNREGISTERED" for r in report.results)


def test_cross_layer_accepts_bytes_and_refuses_malformed_tree():
    records = bound_records()
    assert cross(**records).ok
    from qaiji.core.pulse import dump_port_resources

    wire = dict(
        schedule=records["schedule"].to_json().encode(),
        pulse=dump_pulse_program(records["pulse"]),
        port_resources=dump_port_resources(records["port_resources"]),
        waveform=dump_waveform(records["waveform"]),
    )
    assert cross(**wire).ok
    payload = json.loads(wire["waveform"])
    payload["segments"].pop()
    report = cross(**{**wire, "waveform": json.dumps(payload).encode()})
    assert not report.ok
    assert all(r.verdict == "fail" for r in report.results)


def test_resource_failure_preserves_mapping_path_and_code():
    records = bound_records()
    mapping = replace(records["port_resources"], pulse_program_ref="sha256:" + "0" * 64)
    report = cross(**{**records, "port_resources": mapping})
    assert not report.ok
    assert any(
        r.id == "I-X.1" and r.path == "/pulse_program_ref" and "RESOURCE_REF" in r.message
        for r in report.results
    )


def test_only_three_budget_defaults_change_and_identity_is_stable():
    expected = dict(
        max_wire_bytes=67108864,
        max_depth=32,
        max_attachment_bytes=16777216,
        max_dense_dimension=128,
        max_numeric_elements=1048576,
        max_rational_ops=8388608,
        max_rational_bits=16384,
    )
    assert asdict(CheckBudget()) == expected
    req = result_request()
    from qaiji.core.physical import request_id

    old = CheckBudget(max_wire_bytes=16777216, max_dense_dimension=64, max_rational_ops=1000000)
    assert request_id(req, budget=old) == request_id(req, budget=CheckBudget())
    assert not check_request(req, level="physical").diagnostics


@pytest.mark.parametrize(
    "fault,code,path",
    [
        ("ref", "RESOURCE_REF", "/pulse_program_ref"),
        ("port", "RESOURCE_PORT", "/entries/0/port"),
        ("missing", "RESOURCE_MISSING", "/instructions/1"),
        ("coverage", "RESOURCE_COVERAGE", "/instructions/1"),
    ],
)
def test_unified_resource_diagnostics_keep_code_category_and_pointer(fault, code, path):
    records = bound_records()
    assert cross(**records).ok
    mapping = records["port_resources"]
    if fault == "ref":
        mapping = replace(mapping, pulse_program_ref="sha256:" + "0" * 64)
    elif fault == "port":
        mapping = replace(mapping, entries=(PortResourceEntry(port="absent", resources=("q0",)),))
    elif fault == "missing":
        mapping = replace(mapping, entries=())
    else:
        entries = list(mapping.entries)
        index = next(i for i, e in enumerate(entries) if e.port == "d0")
        entries[index] = PortResourceEntry(port="d0", resources=("q1",))
        mapping = replace(mapping, entries=tuple(entries))
    report = cross(**{**records, "port_resources": mapping})
    assert not report.ok
    assert any(
        r.id == "I-X.1" and r.path == path and code in r.message and "resources" in r.message
        for r in report.results
    ), report


def test_waveform_event_only_helper_never_certifies_resource_coverage():
    records = bound_records()
    report = inv.check_waveform_events(waveform=records["waveform"], pulse=records["pulse"])
    assert report.ok
    assert {r.id for r in report.results} == {"I-X.2"}


@pytest.mark.parametrize("layer", ["L5", "L4", "L2", "L1", "L0", "P"])
def test_wrong_layer_objects_raise_type_error(layer):
    with pytest.raises(TypeError):
        inv.check_invariants(object(), layer=layer)


@pytest.mark.parametrize("field", ["schedule", "pulse", "port_resources", "waveform"])
def test_cross_layer_wrong_objects_and_invalid_bytes_refuse_certification(field):
    records = bound_records()
    with pytest.raises(TypeError):
        cross(**{**records, field: object()})
    report = cross(**{**records, field: b"{}"})
    assert not report.ok
    assert all(r.verdict == "fail" for r in report.results)


def test_raw_physical_request_object_and_json_bytes_are_supported():
    req = result_request()
    assert inv.check_invariants(req, layer="P").ok
    assert inv.check_invariants(dump_request(req).document, layer="P").ok
