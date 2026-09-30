# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Output order, complete histories and invocation isolation."""

from dataclasses import replace

import pytest

import qaiji.core.program_native.bridge as bridge_module
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Measure
from qaiji.core.native import lower_to_native
from qaiji.core.program import (
    ProgramValidationError,
    QuantumInvocation,
    ResultOutput,
    compute_kernel_ref,
)
from qaiji.core.program_native import (
    NativeBinding,
    ProgramNativeValidationError,
    bridge_program_native,
)

from .test_authentication import fixture, inner


def output_fixture():
    program, kernels, bindings = fixture()
    circuit = next(iter(kernels.values()))
    c = ClassicalRegister("c", 2)
    d = ClassicalRegister("d", 1)
    circuit.cregs = [c, d]
    circuit.gates = [
        Measure(0, ClassicalBit(reg, bit)) for reg, bit in [(c, 1), (d, 0), (c, 0), (c, 1), (d, 0)]
    ]
    ref = compute_kernel_ref(circuit)
    program = replace(
        program,
        quantum_invocations=(QuantumInvocation(ref), QuantumInvocation(ref)),
        result_outputs=(
            ResultOutput(1, "d"),
            ResultOutput(0, "c"),
            ResultOutput(1, "c"),
            ResultOutput(0, "d"),
        ),
    )
    binding = NativeBinding(
        schedule=lower_to_native(circuit, bindings[0].config), config=bindings[0].config
    )
    return program, {ref: circuit}, {0: binding, 1: binding}


def tuples(result):
    return tuple(
        (
            o.invocation_index,
            o.register_name,
            tuple((e.invocation_index, e.event_id) for e in o.history),
            tuple((b.bit_index, b.event.invocation_index, b.event.event_id) for b in o.final_bits),
        )
        for o in result.outputs
    )


def test_declared_output_order():
    program, kernels, bindings = output_fixture()
    result = bridge_program_native(program, kernels, bindings)
    assert [(o.invocation_index, o.register_name) for o in result.outputs] == [
        (1, "d"),
        (0, "c"),
        (1, "c"),
        (0, "d"),
    ]


def test_history_and_final_bit_order():
    program, kernels, bindings = output_fixture()
    result = bridge_program_native(program, kernels, bindings)
    assert tuples(result) == (
        (1, "d", ((1, "m1"), (1, "m4")), ((0, 1, "m4"),)),
        (0, "c", ((0, "m0"), (0, "m2"), (0, "m3")), ((0, 0, "m2"), (1, 0, "m3"))),
        (1, "c", ((1, "m0"), (1, "m2"), (1, "m3")), ((0, 1, "m2"), (1, 1, "m3"))),
        (0, "d", ((0, "m1"), (0, "m4")), ((0, 0, "m4"),)),
    )


def test_two_invocation_two_register_isolation():
    program, kernels, bindings = output_fixture()
    # A distinct second source reverses writes; its event ids now have different meaning.
    import copy

    circuit = copy.deepcopy(next(iter(kernels.values())))
    circuit.gates.reverse()
    ref = compute_kernel_ref(circuit)
    kernels[ref] = circuit
    program = replace(
        program, quantum_invocations=(program.quantum_invocations[0], QuantumInvocation(ref))
    )
    bindings[1] = NativeBinding(
        schedule=lower_to_native(circuit, bindings[0].config), config=bindings[0].config
    )
    assert tuples(bridge_program_native(program, kernels, bindings)) == (
        (1, "d", ((1, "m0"), (1, "m3")), ((0, 1, "m3"),)),
        (0, "c", ((0, "m0"), (0, "m2"), (0, "m3")), ((0, 0, "m2"), (1, 0, "m3"))),
        (1, "c", ((1, "m1"), (1, "m2"), (1, "m4")), ((0, 1, "m2"), (1, 1, "m4"))),
        (0, "d", ((0, "m1"), (0, "m4")), ((0, 0, "m4"),)),
    )


def test_unexported_measurements_still_authenticated():
    program, kernels, bindings = output_fixture()
    program = replace(program, result_outputs=(ResultOutput(0, "c"),))
    schedule = bindings[0].schedule
    events = list(schedule.events)
    events[1] = replace(events[1], ready_ns=99)
    bindings[0] = replace(bindings[0], schedule=replace(schedule, events=events))
    with pytest.raises(ProgramNativeValidationError) as caught:
        bridge_program_native(program, kernels, bindings)
    (issue,) = caught.value.issues
    assert (issue.invocation_index, issue.code) == (0, "native_invalid")
    assert inner(issue.native_report) == (
        ("measurement_events", "$.events[1].ready_ns", schedule.events[1].source, 1),
    )


def test_no_measure_cannot_supply_output():
    program, kernels, bindings = fixture(1)
    circuit = next(iter(kernels.values()))
    circuit.gates = []
    ref = compute_kernel_ref(circuit)
    program = replace(program, quantum_invocations=(QuantumInvocation(ref),))
    with pytest.raises(ProgramValidationError) as caught:
        bridge_program_native(program, {ref: circuit}, bindings)
    assert caught.value.problems == (
        "output (0, 'c'): bits [0] are never written by a measurement",
    )


def test_projection_consumes_authenticated_copy(monkeypatch):
    program, kernels, bindings = output_fixture()
    original = bridge_module._validate_snapshot

    def change(snapshot, schedule, config):
        report = original(snapshot, schedule, config)
        # Alter external binding only after the authentication has consumed its snapshot.
        object.__setattr__(bindings[0].schedule, "events", ())
        return report

    # Independent bindings prevent a second invocation from encountering the tampered input.
    program = replace(
        program,
        quantum_invocations=(program.quantum_invocations[0],),
        result_outputs=(ResultOutput(0, "c"), ResultOutput(0, "d")),
    )
    monkeypatch.setattr(bridge_module, "_validate_snapshot", change)
    error = None
    result = None
    try:
        result = bridge_program_native(program, kernels, {0: bindings[0]})
    except Exception as caught:
        error = caught
    assert error is None, f"Authenticated copy must remain consumable: {error!r}"
    assert tuples(result) == (
        (0, "c", ((0, "m0"), (0, "m2"), (0, "m3")), ((0, 0, "m2"), (1, 0, "m3"))),
        (0, "d", ((0, "m1"), (0, "m4")), ((0, 0, "m4"),)),
    )


def test_output_index_visits_events_once_without_register_scan():
    program, _, bindings = output_fixture()
    accesses = {"registers": 0, "events": 0, "operations": 0}

    class ObservedSchedule:
        @property
        def registers(self):
            accesses["registers"] += 1
            return bindings[0].schedule.registers

        @property
        def events(self):
            accesses["events"] += 1
            return bindings[0].schedule.events

        @property
        def operations(self):
            accesses["operations"] += 1
            return bindings[0].schedule.operations

    # Only the already-authenticated B2 consumer is measured, not inherited B0/ref work.
    result = bridge_module._map_outputs(program, {0: ObservedSchedule(), 1: ObservedSchedule()})
    assert accesses == {"registers": 0, "events": 2, "operations": 0}
    assert tuples(result) == (
        (1, "d", ((1, "m1"), (1, "m4")), ((0, 1, "m4"),)),
        (0, "c", ((0, "m0"), (0, "m2"), (0, "m3")), ((0, 0, "m2"), (1, 0, "m3"))),
        (1, "c", ((1, "m0"), (1, "m2"), (1, "m3")), ((0, 1, "m2"), (1, 1, "m3"))),
        (0, "d", ((0, "m1"), (0, "m4")), ((0, 0, "m4"),)),
    )
