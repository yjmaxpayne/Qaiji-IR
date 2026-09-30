# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Explicit synthetic timing configuration contracts."""

from dataclasses import fields

import pytest

from _native_fixtures import FIELDS, make
from qaiji.core.native.config import OperationSpec, QubitResource, ScheduleConfig
from qaiji.core.native.errors import NativeInputError


def reject(cls, changes, code, path):
    with pytest.raises(Exception) as caught:
        make(cls, **changes)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == (code, path)


@pytest.mark.parametrize("cls", [QubitResource, OperationSpec, ScheduleConfig])
def test_configuration_field_contract(cls):
    assert {f.name for f in fields(cls)} == set(FIELDS[cls])


@pytest.mark.parametrize(
    "kind,duration", [("I", 0), ("Z", 0), ("RZ", 0), ("RX90", 20), ("CZ", 40), ("MEASURE", 30)]
)
def test_explicit_duration_resource_latency_domains(kind, duration):
    qubits = (0, 1) if kind == "CZ" else (0,)
    try:
        assert (
            make(OperationSpec, kind=kind, qubits=qubits, duration_ns=duration).duration_ns
            == duration
        )
    except NativeInputError as error:
        assert error is None, "非测量零延迟及合法时长必须接受: " + str(error)
    reject(
        OperationSpec,
        dict(kind=kind, qubits=qubits, duration_ns=int(duration == 0)),
        "duration",
        "$.duration_ns",
    )
    if kind == "MEASURE":
        try:
            measured = make(OperationSpec, kind=kind, result_latency_ns=50)
        except NativeInputError as error:
            assert error is None, "测量允许非零结果延迟: " + str(error)
        assert measured.result_latency_ns == 50
    else:
        reject(
            OperationSpec,
            dict(kind=kind, qubits=qubits, duration_ns=duration, result_latency_ns=1),
            "latency",
            "$.result_latency_ns",
        )


def config_values():
    bindings = (make(QubitResource), make(QubitResource, qubit=1, resource="q1"))
    specs = (
        make(
            OperationSpec, kind="CZ", qubits=(1, 0), resources=("q1", "bus", "q0"), duration_ns=40
        ),
    )
    return dict(qubit_resources=bindings, operation_specs=specs, cz_couplings=((0, 1),))


def test_ordered_specs_and_unordered_couplings():
    data = config_values()
    obj = ScheduleConfig(**data)
    assert obj.operation_specs[0].qubits == (1, 0)
    assert obj.operation_specs[0].resources == ("q1", "bus", "q0")
    assert obj.cz_couplings == ((0, 1),)
    cases = [
        ({"cz_couplings": ((1, 0),)}, "coupling", "$.cz_couplings[0]"),
        ({"cz_couplings": ((0, 0),)}, "coupling", "$.cz_couplings[0]"),
        ({"cz_couplings": ((0,),)}, "coupling", "$.cz_couplings[0]"),
        ({"cz_couplings": ((0, 2),)}, "coupling", "$.cz_couplings[0]"),
        ({"cz_couplings": ((0, 1), (0, 1))}, "coupling", "$.cz_couplings[1]"),
        (
            {"qubit_resources": (make(QubitResource), make(QubitResource, resource="other"))},
            "qubit_resources",
            "$.qubit_resources[1].qubit",
        ),
        (
            {"qubit_resources": (make(QubitResource), make(QubitResource, qubit=1))},
            "qubit_resources",
            "$.qubit_resources[1].resource",
        ),
        (
            {"operation_specs": data["operation_specs"] * 2},
            "duplicate_spec",
            "$.operation_specs[1]",
        ),
        (
            {"operation_specs": (make(OperationSpec, qubits=(2,)),)},
            "qubit_resources",
            "$.operation_specs[0].qubits[0]",
        ),
        (
            {"operation_specs": (make(OperationSpec, resources=("bus",)),)},
            "resources",
            "$.operation_specs[0].resources",
        ),
    ]
    for change, code, path in cases:
        with pytest.raises(Exception) as caught:
            ScheduleConfig(**(data | change))
        assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
        assert (caught.value.code, caught.value.path) == (code, path)
    # Missing a coupling is a coverage error for validation, not malformed input.
    assert ScheduleConfig(**(data | {"cz_couplings": ()})).cz_couplings == ()
    reverse = make(
        OperationSpec, kind="CZ", qubits=(0, 1), resources=("q0", "bus", "q1"), duration_ns=41
    )
    both = ScheduleConfig(**(data | {"operation_specs": (*data["operation_specs"], reverse)}))
    assert tuple(s.duration_ns for s in both.operation_specs) == (40, 41)


def test_empty_and_unused_configuration():
    assert make(ScheduleConfig).operation_specs == ()
    unused = make(QubitResource, qubit=100, resource="unused")
    assert make(ScheduleConfig, qubit_resources=(unused,)).qubit_resources == (unused,)
    data = config_values()
    shared = make(OperationSpec, resources=("q0", "bus"))
    assert (
        len(
            ScheduleConfig(
                **(data | {"operation_specs": (*data["operation_specs"], shared)})
            ).operation_specs
        )
        == 2
    )


def test_coupling_each_endpoint():
    for pair in ((1, 2), (0, 2)):
        data = config_values() | {"cz_couplings": (pair,)}
        if pair == (1, 2):
            data["qubit_resources"] = (make(QubitResource, qubit=2, resource="q2"),)
            data["operation_specs"] = ()
        with pytest.raises(Exception) as caught:
            ScheduleConfig(**data)
        assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
        assert (caught.value.code, caught.value.path) == ("coupling", "$.cz_couplings[0]")
