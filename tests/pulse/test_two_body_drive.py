# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""两体驱动的载频、精确目标与旧角色边界。"""

from dataclasses import replace

import pytest

from _pulse_fixtures import lower_to_l1, rejects, schedule
from qaiji.core.native import NativeScheduleIR
from qaiji.core.pulse import (
    Play,
    Port,
    PortResourceEntry,
    PortResourceMap,
    PulseProgramIR,
    check_port_resources,
    check_pulse_program,
    dump_pulse_program,
    load_pulse_program,
    pulse_program_id,
)


def _two_body(targets: tuple[int, ...] = (0, 1)) -> tuple[NativeScheduleIR, PulseProgramIR]:
    native = schedule("cz q[0], q[1];")
    pulse = lower_to_l1(native)
    pulse = replace(
        pulse,
        ports=tuple(
            Port(id=p.id, role="two_body_drive", targets=targets) if p.id == "f01" else p
            for p in pulse.ports
        ),
        frames=tuple(
            replace(f, frequency_hz=219_825_000) if f.port == "f01" else f for f in pulse.frames
        ),
    )
    return native, pulse


@pytest.mark.parametrize("targets", [(0, 1), (1, 0)])
def test_two_body_cz_accepts_exact_pair_and_nonzero_carrier(targets: tuple[int, ...]) -> None:
    native, pulse = _two_body(targets)
    check_pulse_program(pulse, native)
    check_port_resources(
        native,
        pulse,
        PortResourceMap(
            pulse_program_ref=pulse_program_id(pulse),
            entries=(PortResourceEntry(port="f01", resources=("q0", "q1")),),
        ),
    )
    assert pulse.schema == "qaiji.pulse/0.1"
    assert dump_pulse_program(load_pulse_program(dump_pulse_program(pulse))) == dump_pulse_program(
        pulse
    )


@pytest.mark.parametrize("targets", [(0,), (2,), (0, 2), (0, 1, 2)])
def test_two_body_cz_rejects_inexact_targets(targets: tuple[int, ...]) -> None:
    native, pulse = _two_body(targets)
    index = next(i for i, item in enumerate(pulse.instructions) if isinstance(item, Play))
    rejects("TARGET", f"/instructions/{index}/frame", check_pulse_program, pulse, native)


@pytest.mark.parametrize("body,port", [("sx q[0];", "d0"), ("c[0] = measure q[0];", "r0")])
def test_single_qubit_operations_reject_two_body_role(body: str, port: str) -> None:
    native = schedule(body)
    pulse = lower_to_l1(native)
    pulse = replace(
        pulse,
        ports=tuple(replace(p, role="two_body_drive") if p.id == port else p for p in pulse.ports),
    )
    index = next(i for i, item in enumerate(pulse.instructions) if isinstance(item, Play))
    rejects("TARGET", f"/instructions/{index}/frame", check_pulse_program, pulse, native)


def test_unknown_role_is_rejected_at_decode_boundary() -> None:
    _, pulse = _two_body()
    data = dump_pulse_program(pulse).replace(b"two_body_drive", b"unknown_drive")
    index = next(i for i, p in enumerate(pulse.ports) if p.id == "f01")
    rejects("ROLE", f"/ports/{index}/role", load_pulse_program, data)


@pytest.mark.parametrize("role", ["flux", "coupler_flux"])
def test_legacy_flux_subset_and_zero_carrier_rules_remain(role: str) -> None:
    native = schedule("cz q[0], q[1];")
    pulse = lower_to_l1(native)
    pulse = replace(
        pulse,
        ports=tuple(
            replace(p, role=role, targets=(0,)) if p.id == "f01" else p for p in pulse.ports
        ),
    )
    check_pulse_program(pulse, native)
    index = next(i for i, f in enumerate(pulse.frames) if f.port == "f01")
    rejects(
        "FREQUENCY",
        f"/frames/{index}/frequency_hz",
        lambda: replace(
            pulse,
            frames=tuple(
                replace(f, frequency_hz=1) if f.port == "f01" else f for f in pulse.frames
            ),
        ),
    )
