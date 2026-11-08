# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""冻结 C.1 字节、C.2 身份与手写 L1 的来源回溯。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from _pulse_fixtures import HEAD, config, play, program, shift
from qaiji.codec import from_qasm3
from qaiji.core.native import NativeScheduleIR, lower_to_native
from qaiji.core.physical import dump_request, dump_result, load_request, load_result, request_id
from qaiji.core.pulse import (
    check_pulse_program,
    dump_port_resources,
    dump_pulse_program,
    load_port_resources,
    load_pulse_program,
    native_schedule_ref,
    port_resources_id,
    pulse_program_id,
)
from qaiji.core.waveform import dump_waveform, load_waveform, waveform_id

DATA = Path(__file__).with_name("data")


def records():
    return {
        "native": (
            lambda b: NativeScheduleIR.from_json(b.decode()),
            lambda r: r.to_json().encode(),
            native_schedule_ref,
        ),
        "pulse": (load_pulse_program, dump_pulse_program, pulse_program_id),
        "resources": (load_port_resources, dump_port_resources, port_resources_id),
        "waveform": (load_waveform, dump_waveform, waveform_id),
        "request": (load_request, lambda r: dump_request(r).document, request_id),
        "result": (load_result, lambda r: dump_result(r).document, None),
    }


@pytest.mark.parametrize("name", ("native", "pulse", "resources", "waveform", "request", "result"))
def test_frozen_schema_roundtrip_and_identity(name):
    metadata = json.loads((DATA / "identities.json").read_bytes())[name]
    content = (DATA / f"{name}.json").read_bytes()
    load, dump, identify = records()[name]
    value = load(content)
    assert dump(value) == content
    assert hashlib.sha256(content).hexdigest() == metadata["wire_sha256"]
    if identify is not None:
        assert identify(value) == metadata["id"]
        document = json.loads(content)
        schema = document.get("schema", document.get("schema_version"))
        if name == "request":
            del document["provenance"]
            content = json.dumps(
                document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
        assert (
            "sha256:" + hashlib.sha256(schema.encode() + b"\0" + content).hexdigest()
            == metadata["id"]
        )


def test_handwritten_l1_sources_trace_to_independent_gate_list():
    circuit = from_qasm3(HEAD + "rz(0.25) q[0]; sx q[1];")
    native = lower_to_native(circuit, config())
    pulse = program(
        (
            shift(frame="d0", at_ns=0, delta_rad=-0.25, source=0),
            play(frame="d1", start_ns=0, duration_ns=40, phase_rad=0, source=1),
        ),
        end_ns=40,
        source_schedule_ref=native_schedule_ref(native),
    )
    check_pulse_program(pulse, native)
    expected = [(0, None, "RZ", (0,), (0.25,)), (1, None, "RX", (1,), (1.5707963267948966,))]
    observed = []
    for instruction in pulse.instructions:
        location = native.operations[instruction.source].source
        gate = circuit.gates[location.gate_index]
        observed.append(
            (
                location.gate_index,
                location.body_offset,
                gate.gate_type.name,
                gate.qubits,
                gate.params,
            )
        )
    assert observed == expected
    changed = replace(
        pulse, instructions=(pulse.instructions[0], replace(pulse.instructions[1], source=0))
    )
    from qaiji.core.pulse import PulseContractError

    with pytest.raises(PulseContractError):
        check_pulse_program(changed, native)


def test_frozen_bytes_reject_schema_type_and_detect_changed_digest():
    load, _, _ = records()["pulse"]
    content = (DATA / "pulse.json").read_bytes()
    load(content)
    payload = json.loads(content)
    payload["end_ns"] = "40"
    from qaiji.core.pulse import PulseContractError

    with pytest.raises(PulseContractError):
        load(json.dumps(payload).encode())
    assert (
        hashlib.sha256(content + b" ").hexdigest()
        != json.loads((DATA / "identities.json").read_bytes())["pulse"]["wire_sha256"]
    )
