# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Explicit immutable timing and resource configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from .model import (
    _duration,
    _fail,
    _kind,
    _objects,
    _operands,
    _qubits,
    _resources,
    _sequence,
    _set,
    _text,
    _uint,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class QubitResource:
    qubit: int
    resource: str
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "qubit", _uint)
        _set(self, "resource", _text)


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationSpec:
    kind: str
    qubits: tuple[int, ...]
    duration_ns: int
    resources: tuple[str, ...]
    result_latency_ns: int
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "kind", _kind)
        _set(self, "qubits", _qubits)
        _set(self, "duration_ns", _uint)
        _set(self, "resources", _resources)
        _set(self, "result_latency_ns", _uint)
        _operands(self.kind, self.qubits)
        _duration(self.kind, self.duration_ns)
        if self.kind != "MEASURE" and self.result_latency_ns != 0:
            _fail("latency", "$.result_latency_ns", "Only measurement has result latency.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScheduleConfig:
    qubit_resources: tuple[QubitResource, ...]
    operation_specs: tuple[OperationSpec, ...]
    cz_couplings: tuple[tuple[int, int], ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "qubit_resources", _objects(QubitResource))
        _set(self, "operation_specs", _objects(OperationSpec))
        _set(self, "cz_couplings", lambda v, p: _sequence(v, p, _qubits))

        bindings: dict[int, str] = {}
        resources: set[str] = set()
        for i, binding in enumerate(self.qubit_resources):
            if binding.qubit in bindings:
                _fail(
                    "qubit_resources", f"$.qubit_resources[{i}].qubit", "Duplicate qubit binding."
                )
            if binding.resource in resources:
                _fail(
                    "qubit_resources",
                    f"$.qubit_resources[{i}].resource",
                    "Exclusive resources must be unique.",
                )
            bindings[binding.qubit] = binding.resource
            resources.add(binding.resource)
        specs: set[tuple[str, tuple[int, ...]]] = set()
        for i, spec in enumerate(self.operation_specs):
            path = f"$.operation_specs[{i}]"
            key = (spec.kind, spec.qubits)
            if key in specs:
                _fail("duplicate_spec", path, "Duplicate ordered operation specification.")
            specs.add(key)
            for j, qubit in enumerate(spec.qubits):
                if qubit not in bindings:
                    _fail(
                        "qubit_resources", f"{path}.qubits[{j}]", "Qubit has no exclusive resource."
                    )
                if bindings[qubit] not in spec.resources:
                    _fail("resources", path + ".resources", "Missing exclusive qubit resource.")
        couplings: set[tuple[int, int]] = set()
        for i, coupling in enumerate(self.cz_couplings):
            path = f"$.cz_couplings[{i}]"
            if len(coupling) != 2:
                _fail("coupling", path, "Coupling requires two endpoints.")
            if coupling[0] >= coupling[1]:
                _fail("coupling", path, "Coupling endpoints must be ascending.")
            if coupling[0] not in bindings or coupling[1] not in bindings:
                _fail("coupling", path, "Coupling endpoints must have exclusive resources.")
            if coupling in couplings:
                _fail("coupling", path, "Duplicate coupling.")
            couplings.add(coupling)
