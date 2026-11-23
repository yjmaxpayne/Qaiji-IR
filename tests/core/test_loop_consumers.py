# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""公开电路消费点收到含循环电路时的处置。"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import pkgutil
import re
from collections.abc import Callable
from typing import Any

import pytest

import qaiji
from qaiji.codec.qasm3 import parse_looped_qasm3, to_qasm3
from qaiji.core.circuit import Circuit
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Measure
from qaiji.core.invariants import (
    L2InvariantInput,
    L4InvariantInput,
    ProgramInvariantInput,
    check_invariants,
)
from qaiji.core.loop import LoopedCircuit
from qaiji.core.native import (
    NativeInputError,
    OperationSpec,
    QubitResource,
    ScheduleConfig,
    lower_to_native,
)
from qaiji.core.native.projection import qubic_mapping
from qaiji.core.native.validation import validate_native_schedule
from qaiji.core.program import (
    ExperimentMetadata,
    ProgramCall,
    ProgramIR,
    ProgramIRV1,
    QuantumInvocation,
    ResultOutput,
    compute_kernel_ref,
    validate_program,
)
from qaiji.core.program_native import NativeBinding, bridge_program_native
from qaiji.core.semantics.dataflow import build_dataflow_summary
from qaiji.core.semantics.preservation import check_preservation
from qaiji.core.semantics.registry import annotate_circuit
from qaiji.core.semantics.summary import build_semantic_summary
from qaiji.exceptions import LoopNotExpandedError, QaijiIRError

LOOPED_SOURCE = """OPENQASM 3.0;
include "stdgates.inc";
qubit[1] q;
bit[1] c;
for int i in [0:1] { c[0] = measure q[0]; }
"""

TWO_ROUND_REPETITION_CODE = """OPENQASM 3.0;
include "stdgates.inc";
qubit[4] q;
for int r in [0:1] {
  bit[2] s;
  h q[3]; cz q[0], q[3]; cz q[3], q[1]; h q[3]; s[0] = measure q[3];
  h q[3]; cz q[1], q[3]; cz q[2], q[3]; h q[3]; s[1] = measure q[3];
}
"""

WELL_FORMED_HASH = "sha256:" + "0" * 64


def looped() -> LoopedCircuit:
    return parse_looped_qasm3(LOOPED_SOURCE).circuit


def flat() -> Circuit:
    circuit = Circuit(1)
    register = ClassicalRegister("c", 1)
    circuit.cregs = [register]
    circuit.gates = [Measure(0, ClassicalBit(register, 0))]
    return circuit


def config() -> ScheduleConfig:
    return ScheduleConfig(
        qubit_resources=(QubitResource(qubit=0, resource="q"),),
        operation_specs=(
            OperationSpec(
                kind="MEASURE",
                qubits=(0,),
                duration_ns=3,
                resources=("q",),
                result_latency_ns=5,
            ),
        ),
        cz_couplings=(),
    )


def program_with_looped_kernel() -> tuple[ProgramIR, dict[str, Any]]:
    """Build a real program whose only invoked kernel resolves to a looped circuit."""
    ref = compute_kernel_ref(flat())
    program = ProgramIR(
        quantum_invocations=(QuantumInvocation(ref),),
        experiment_metadata=ExperimentMetadata(1),
        result_outputs=(ResultOutput(0, "c"),),
    )
    return program, {ref: looped()}


def call_bridge(circuit: LoopedCircuit) -> object:
    program, kernels = program_with_looped_kernel()
    binding = NativeBinding(schedule=lower_to_native(flat(), config()), config=config())
    return bridge_program_native(program, kernels, {0: binding})


# Disposition of every public function that takes a circuit: a returned type or a raised error.
CONSUMERS: dict[str, tuple[Callable[[LoopedCircuit], object], type]] = {
    "qaiji.codec.qasm3.to_qasm3": (to_qasm3, str),
    "qaiji.core.native.api.lower_to_native": (
        lambda c: lower_to_native(c, config()),
        NativeInputError,
    ),
    "qaiji.core.native.projection.qubic_mapping": (
        lambda c: qubic_mapping(c, lower_to_native(flat(), config()), config()),
        NativeInputError,
    ),
    "qaiji.core.native.validation.validate_native_schedule": (
        lambda c: validate_native_schedule(c, lower_to_native(flat(), config()), config()),
        NativeInputError,
    ),
    "qaiji.core.program.validation.compute_kernel_ref": (compute_kernel_ref, LoopNotExpandedError),
    "qaiji.core.program.validation.validate_program": (
        lambda c: validate_program(*program_with_looped_kernel()),
        LoopNotExpandedError,
    ),
    "qaiji.core.program_native.bridge.bridge_program_native": (call_bridge, LoopNotExpandedError),
    "qaiji.core.semantics.dataflow.build_dataflow_summary": (
        build_dataflow_summary,
        LoopNotExpandedError,
    ),
    "qaiji.core.semantics.registry.annotate_circuit": (annotate_circuit, LoopNotExpandedError),
    "qaiji.core.semantics.summary.build_semantic_summary": (
        lambda c: build_semantic_summary(circuit=c, annotations=()),
        LoopNotExpandedError,
    ),
    "qaiji.core.semantics.preservation.check_preservation": (
        lambda c: check_preservation(c, flat()),
        LoopNotExpandedError,
    ),
}

# Public dataclass fields typed with Circuit: the consumer that rejects a looped value,
# or the producer that only ever stores a flat circuit.
CIRCUIT_FIELDS = {
    "qaiji.codec.qasm3.ParsedQasm3.circuit": "flat output of parse_qasm3",
    "qaiji.core.loop.ExpandedCircuit.circuit": "flat output of LoopedCircuit.expand",
    "qaiji.core.invariants.ProgramInvariantInput.kernels": "check_invariants",
    "qaiji.core.invariants.L4InvariantInput.circuit": "check_invariants",
    "qaiji.core.invariants.L2InvariantInput.circuit": "check_invariants",
}

CIRCUIT_TYPE = re.compile(r"\bCircuit\b")
CIRCUIT_PARAMETER_NAMES = {"circuit", "original", "transformed"}


def public_modules() -> list[Any]:
    return [
        importlib.import_module(info.name)
        for info in pkgutil.walk_packages(qaiji.__path__, "qaiji.")
    ]


def takes_circuit(function: Callable[..., object]) -> bool:
    return any(
        CIRCUIT_TYPE.search(str(parameter.annotation)) or parameter.name in CIRCUIT_PARAMETER_NAMES
        for parameter in inspect.signature(function).parameters.values()
    )


@pytest.mark.parametrize("name", sorted(CONSUMERS))
def test_consumer_result_on_looped_circuit(name: str) -> None:
    consume, expected = CONSUMERS[name]

    if issubclass(expected, Exception):
        with pytest.raises(QaijiIRError) as caught:
            consume(looped())
        assert type(caught.value) is expected
        if expected is NativeInputError:
            assert caught.value.code == "source_type"
    else:
        result = consume(looped())
        assert type(result) is expected
        assert "for int i in [0:1]" in str(result)


def invariant_sources(circuit: object) -> dict[str, tuple[object, str]]:
    ref = compute_kernel_ref(flat())
    program = ProgramIRV1(
        quantum_invocations=(QuantumInvocation(ref),),
        experiment_metadata=ExperimentMetadata(1),
        result_outputs=(ResultOutput(0, "c"),),
        control_flow=(ProgramCall(invocation_index=0),),
    )
    schedule = lower_to_native(flat(), config())
    return {
        "L5-kernels": (ProgramInvariantInput(program=program, kernels={ref: circuit}), "L5"),
        "L4-circuit": (
            L4InvariantInput(circuit=circuit, recorded_summary_hash=WELL_FORMED_HASH),  # type: ignore[arg-type]
            "L4",
        ),
        "L4-source": (circuit, "L4"),
        "L2-circuit": (
            L2InvariantInput(circuit=circuit, schedule=schedule, config=config()),  # type: ignore[arg-type]
            "L2",
        ),
    }


@pytest.mark.parametrize("case", ["L5-kernels", "L4-circuit", "L4-source", "L2-circuit"])
def test_check_invariants_rejects_looped_circuit(case: str) -> None:
    source, layer = invariant_sources(looped())[case]

    with pytest.raises(LoopNotExpandedError):
        check_invariants(source, layer=layer)  # type: ignore[arg-type]


@pytest.mark.parametrize("case", ["L5-kernels", "L4-circuit", "L4-source", "L2-circuit"])
def test_check_invariants_keeps_type_error_for_other_inputs(case: str) -> None:
    source, layer = invariant_sources("not a circuit")[case]

    with pytest.raises(TypeError):
        check_invariants(source, layer=layer)  # type: ignore[arg-type]


def test_native_input_error_is_a_qaiji_value_error() -> None:
    assert issubclass(NativeInputError, QaijiIRError)
    assert issubclass(NativeInputError, ValueError)


def test_every_public_circuit_consumer_has_a_disposition() -> None:
    consumers = set()
    for module in public_modules():
        for name in getattr(module, "__all__", ()):
            obj = getattr(module, name, None)
            if inspect.isfunction(obj) and takes_circuit(obj):
                consumers.add(f"{obj.__module__}.{obj.__qualname__}")

    assert consumers == set(CONSUMERS)


def test_every_public_circuit_field_has_a_disposition() -> None:
    circuit_fields = set()
    for module in public_modules():
        if any(part.startswith("_") for part in module.__name__.split(".")):
            continue
        for name, obj in vars(module).items():
            if name.startswith("_") or not dataclasses.is_dataclass(obj):
                continue
            if not inspect.isclass(obj) or obj.__module__ != module.__name__:
                continue
            circuit_fields.update(
                f"{module.__name__}.{name}.{field.name}"
                for field in dataclasses.fields(obj)
                if CIRCUIT_TYPE.search(str(field.type))
            )

    assert circuit_fields == set(CIRCUIT_FIELDS)


def test_expanded_two_round_code_summary_lists_four_measurements() -> None:
    circuit = parse_looped_qasm3(TWO_ROUND_REPETITION_CODE).circuit.expand().circuit

    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))

    handles = [(h["creg_name"], h["creg_index"]) for h in summary["measurement_handles"]]
    assert handles == [("s__0", 0), ("s__0", 1), ("s__1", 0), ("s__1", 1)]
