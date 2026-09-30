# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Capture damaged mutable circuits at the native boundary."""

import importlib
import math
from dataclasses import dataclass

import pytest

from qaiji.core.circuit import PARAM_REQUIREMENTS, Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.native.errors import NativeInputError
from qaiji.core.program import compute_kernel_ref


def capture(circuit):
    module = importlib.import_module("qaiji.core.native.source")
    return module._capture_source(circuit)


def sample():
    circuit = Circuit(2)
    register = ClassicalRegister("c", 2)
    circuit.cregs = [register]
    circuit.gates = [
        Gate(GateType.RX, (0,), (0.5,)),
        Measure(1, ClassicalBit(register, 0)),
        Conditional(register, 1, (Gate(GateType.X, (1,)),)),
    ]
    return circuit


def damage(circuit, path, value):
    obj = circuit
    parts = path.split(".")
    for part in parts[:-1]:
        obj = obj[int(part)] if part.isdecimal() else getattr(obj, part)
    last = parts[-1]
    if last.isdecimal():
        obj[int(last)] = value
    else:
        object.__setattr__(obj, last, value)


BAD = [
    ("num_qubits", True, "source_qubit"),
    ("num_qubits", 0, "source_qubit"),
    ("cregs.0", object(), "source_register"),
    ("cregs.0.name", "bad name", "source_register"),
    ("cregs.0.name", type("Text", (str,), {})("c"), "source_register"),
    ("cregs.0.size", True, "source_register"),
    ("cregs.0.size", 0, "source_register"),
    ("gates.0", "X", "source_node"),
    ("gates.0.gate_type", "RX", "source_node"),
    ("gates.0.qubits", (), "source_arity"),
    ("gates.0.qubits", (0, 1), "source_arity"),
    ("gates.0.qubits.0", True, "source_qubit"),
    ("gates.0.qubits.0", -1, "source_qubit"),
    ("gates.0.qubits.0", 2, "source_qubit"),
    ("gates.0.params", (), "source_parameter"),
    ("gates.1.qubit", True, "source_qubit"),
    ("gates.1.qubit", 2, "source_qubit"),
    ("gates.1.target", object(), "source_reference"),
    ("gates.1.target.index", True, "source_reference"),
    ("gates.1.target.index", -1, "source_reference"),
    ("gates.1.target.index", 2, "source_reference"),
    ("gates.1.target.register", object(), "source_reference"),
    ("gates.1.target.register", ClassicalRegister("other", 2), "source_reference"),
    ("gates.1.target.register", ClassicalRegister("c", 3), "source_reference"),
    ("gates.2.register", object(), "source_reference"),
    ("gates.2.register", ClassicalRegister("other", 2), "source_reference"),
    ("gates.2.register", ClassicalRegister("c", 3), "source_reference"),
    ("gates.2.value", True, "source_condition"),
    ("gates.2.value", -1, "source_condition"),
    ("gates.2.value", 4, "source_condition"),
    ("gates.2.body", ("X",), "source_node"),
    ("gates.2.body", (Measure(0, ClassicalBit(ClassicalRegister("c", 2), 0)),), "source_node"),
    ("gates.2.body", (Conditional(ClassicalRegister("c", 2), 0, ()),), "source_node"),
]
for container in ("gates", "cregs", "gates.0.qubits", "gates.0.params", "gates.2.body"):
    for bad in (set(), iter(()), "", None, {}):
        BAD.append((container, bad, "source_container"))


def error_path(path):
    return "$" + "".join(
        f"[{part}]" if part.isdecimal() else f".{part}" for part in path.split(".")
    )


@pytest.mark.parametrize(
    ("path", "bad", "code"), BAD, ids=[f"{p}-{i}" for i, (p, _, _) in enumerate(BAD)]
)
def test_damaged_mutable_source_matrix(path, bad, code):
    circuit = sample()
    # Mutable containers bypass the old constructor checks.
    object.__setattr__(circuit.gates[0], "qubits", list(circuit.gates[0].qubits))
    damage(circuit, path, bad)
    with pytest.raises(Exception) as caught:
        capture(circuit)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    expected_path = error_path(path)
    if path == "gates.2.body" and code == "source_node":
        expected_path += "[0]"
    assert (caught.value.code, caught.value.path) == (code, expected_path)


def test_damaged_mutable_source_receiver_and_duplicates():
    for source in (None, object(), "circuit"):
        with pytest.raises(Exception) as caught:
            capture(source)
        assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
        assert (caught.value.code, caught.value.path) == ("source_type", "$")
    circuit = sample()
    circuit.cregs.append(ClassicalRegister("c", 1))
    with pytest.raises(Exception) as caught:
        capture(circuit)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == ("source_register", "$.cregs[1].name")
    circuit = sample()
    circuit.gates[0] = Gate(GateType.CX, (0, 1))
    object.__setattr__(circuit.gates[0], "qubits", (0, 0))
    with pytest.raises(Exception) as caught:
        capture(circuit)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == ("source_qubit", "$.gates[0].qubits")


def test_base_subclass_fields_only():
    @dataclass(frozen=True)
    class ExtraGate(Gate):
        ignored: object = None

    circuit = sample()
    original = capture(circuit)
    for cls, obj, _path in [
        (Circuit, circuit, None),
        (ClassicalRegister, circuit.cregs[0], "cregs.0"),
        (Gate, circuit.gates[0], "gates.0"),
        (Measure, circuit.gates[1], "gates.1"),
        (ClassicalBit, circuit.gates[1].target, "gates.1.target"),
        (Conditional, circuit.gates[2], "gates.2"),
    ]:
        child = type("Extra" + cls.__name__, (cls,), {})
        object.__setattr__(obj, "__class__", child)
        object.__setattr__(obj, "extension", object())
    circuit.gates[0] = ExtraGate(GateType.RX, [0], [0.5], object())
    result = capture(circuit)
    assert result == original
    assert type(result.gates[0]) is Gate
    assert type(result.cregs[0]) is ClassicalRegister
    assert type(result.gates[1]) is Measure
    assert type(result.gates[1].target) is ClassicalBit
    assert type(result.gates[2]) is Conditional


ANGLES = [
    (kind, i)
    for kind, count in [
        (GateType.RX, 1),
        (GateType.RY, 1),
        (GateType.RZ, 1),
        (GateType.RX90, 1),
        (GateType.RX180, 1),
        (GateType.U3, 3),
    ]
    for i in range(count)
]


@pytest.mark.parametrize(("kind", "index"), ANGLES)
@pytest.mark.parametrize(
    "angle",
    [
        -math.tau,
        math.tau,
        -0.0,
        0,
        1.0,
        math.nextafter(math.tau, math.inf),
        math.nextafter(-math.tau, -math.inf),
        True,
        float("nan"),
        float("inf"),
        -float("inf"),
        "0",
        10**400,
        type("Real", (float,), {})(0),
        type("Integer", (int,), {})(1),
    ],
)
def test_exact_parameter_domain(kind, index, angle):
    circuit = Circuit(1)
    params = [0.0] * (3 if kind is GateType.U3 else 1)
    gate = Gate(kind, (0,), tuple(params))
    params[index] = angle
    object.__setattr__(gate, "params", params)
    circuit.gates = [gate]
    valid = type(angle) in (int, float) and abs(angle) <= math.tau
    if valid:
        try:
            result = capture(circuit).gates[0].params[index]
        except NativeInputError as error:
            assert error is None, "闭区间内的有限角参数必须接受: " + str(error)
        assert type(result) is type(angle)
        assert float(result).hex() == float(angle).hex()
    else:
        code = (
            "source_angle"
            if type(angle) is float and math.isfinite(angle) and abs(angle) > math.tau
            else "source_parameter"
        )
        with pytest.raises(Exception) as caught:
            capture(circuit)
        assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
        assert (caught.value.code, caught.value.path) == (code, f"$.gates[0].params[{index}]")


def test_kernel_ref_uses_existing_recipe(monkeypatch):
    circuit = Circuit(1)
    reg = ClassicalRegister("c", 1)
    circuit.cregs = [reg]
    circuit.rz(0, 0.5)
    circuit.gates.append(Measure(0, ClassicalBit(reg, 0)))
    assert (
        capture(circuit).source_kernel_ref
        == "sha256:fc6d626b106f4203029114e068bdbb581e92b3f0d03d00294824c57b80606396"
    )
    module = importlib.import_module("qaiji.core.native.source")
    calls = []

    def recorded(captured):
        calls.append(captured)
        circuit.gates.clear()
        return compute_kernel_ref(captured)

    monkeypatch.setattr(module, "compute_kernel_ref", recorded)

    def forbidden(*args):
        pytest.fail("Snapshot rebuilding must assign validated lists once")

    monkeypatch.setattr(Circuit, "add_register", forbidden)
    monkeypatch.setattr(Circuit, "add_measure", forbidden)
    result = capture(circuit)
    assert len(calls) == 1
    assert type(calls[0]) is Circuit
    assert tuple(calls[0].gates) == result.gates
    assert tuple(calls[0].cregs) == result.cregs
    assert result.source_kernel_ref == compute_kernel_ref(calls[0])


def test_source_identity_signed_zero_and_alias():
    refs = []
    for alias in (GateType.CNOT, GateType.CX):
        for angle in (-0.0, 0.0, 0):
            circuit = Circuit(2)
            circuit.gates = [Gate(alias, (0, 1)), Gate(GateType.RX180, (1,), (angle,))]
            result = capture(circuit)
            assert result.gates[0].gate_type is alias
            assert type(result.gates[1].params[0]) is type(angle)
            assert float(result.gates[1].params[0]).hex() == float(angle).hex()
            assert result.source_kernel_ref == compute_kernel_ref(circuit)
            refs.append(result.source_kernel_ref)
    assert len(set(refs)) == 4
    assert refs[1] == refs[2]
    assert refs[4] == refs[5]
    circuit = Circuit(1)
    circuit.rx(0, 1)
    integer = capture(circuit)
    circuit.rx(0, 1.0)
    circuit.gates.pop(0)
    floating = capture(circuit)
    assert integer.source_kernel_ref == floating.source_kernel_ref
    assert type(integer.gates[0].params[0]) is int
    assert type(floating.gates[0].params[0]) is float


def test_fresh_snapshot_each_call():
    circuit = sample()
    first = capture(circuit)
    first_ref = first.source_kernel_ref
    object.__setattr__(circuit.gates[0], "params", [1.0])
    circuit.cregs.append(ClassicalRegister("d", 1))
    second = capture(circuit)
    assert second.source_kernel_ref != first_ref
    assert first.gates[0].params == (0.5,)
    assert len(first.cregs) == 1
    assert type(first.gates) is tuple and type(first.cregs) is tuple
    assert capture(Circuit(1)).gates == ()


def test_fixed_gate_arity_independent_of_mutable_registry(monkeypatch):
    single = {"I", "X", "Y", "Z", "H", "S", "T", "RX", "RY", "RZ", "U3", "RX90", "RX180"}
    counts = {"RX": 1, "RY": 1, "RZ": 1, "RX90": 1, "RX180": 1, "U3": 3}
    expected = single | {"CNOT", "CX", "CZ", "SWAP", "ISWAP", "SQISWAP"}
    assert {kind.value for kind in GateType} == expected
    gates = [
        Gate(kind, (0,) if kind.value in single else (0, 1), (0.0,) * counts.get(kind.value, 0))
        for kind in GateType
    ]
    for kind in GateType:
        monkeypatch.setitem(PARAM_REQUIREMENTS, kind, (9, 9))
    circuit = Circuit(2)
    circuit.gates = gates
    try:
        captured = capture(circuit)
    except NativeInputError as error:
        assert error is None, "固定门签名不得受外部可变注册表影响: " + str(error)
    assert len(captured.gates) == len(expected)
    for gate in gates:
        circuit.gates = [gate]
        object.__setattr__(gate, "qubits", (0, 1) if gate.gate_type.value in single else (0,))
        with pytest.raises(Exception) as caught:
            capture(circuit)
        assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
        assert (caught.value.code, caught.value.path) == ("source_arity", "$.gates[0].qubits")


@pytest.mark.parametrize(
    "path",
    [
        "num_qubits",
        "cregs.0.size",
        "gates.0.qubits.0",
        "gates.0.params.0",
        "gates.1.qubit",
        "gates.1.target.index",
        "gates.2.value",
    ],
)
def test_source_integer_budget(path):
    circuit = sample()
    object.__setattr__(circuit.gates[0], "qubits", [0])
    object.__setattr__(circuit.gates[0], "params", [0.5])
    damage(circuit, path, 10**4096)
    with pytest.raises(Exception) as caught:
        capture(circuit)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == ("range", error_path(path))


def test_source_integer_budget_boundary_and_empty_condition():
    circuit = Circuit(10**4096 - 1)
    result = capture(circuit)
    assert result.num_qubits == 10**4096 - 1
    circuit = sample()
    object.__setattr__(circuit.gates[2], "body", [])
    assert capture(circuit).gates[2].body == ()


@pytest.mark.parametrize(
    "field",
    [
        "num_qubits",
        "cregs.0.size",
        "gates.0.qubits.0",
        "gates.1.qubit",
        "gates.1.target.index",
        "gates.2.value",
    ],
)
@pytest.mark.parametrize("bad", [1.0, "1", None, type("Integer", (int,), {})(1)])
def test_damaged_mutable_source_integer_scalar_types(field, bad):
    circuit = sample()
    object.__setattr__(circuit.gates[0], "qubits", [0])
    damage(circuit, field, bad)
    code = {
        "num_qubits": "source_qubit",
        "cregs.0.size": "source_register",
        "gates.0.qubits.0": "source_qubit",
        "gates.1.qubit": "source_qubit",
        "gates.1.target.index": "source_reference",
        "gates.2.value": "source_condition",
    }[field]
    with pytest.raises(Exception) as caught:
        capture(circuit)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == (code, error_path(field))


@pytest.mark.parametrize("reference", ["gates.1.target.register", "gates.2.register"])
@pytest.mark.parametrize(
    ("field", "bad", "code"),
    [
        ("name", True, "source_reference"),
        ("name", "", "source_reference"),
        ("size", True, "source_reference"),
        ("size", 0, "source_reference"),
        ("size", 10**4096, "range"),
        ("name", type("Text", (str,), {})("c"), "source_reference"),
        ("size", type("Integer", (int,), {})(2), "source_reference"),
    ],
    ids=[
        "name-type",
        "name-empty",
        "size-bool",
        "size-zero",
        "size-budget",
        "name-subclass",
        "size-subclass",
    ],
)
def test_damaged_mutable_source_reference_fields(reference, field, bad, code):
    circuit = sample()
    damage(circuit, reference, ClassicalRegister("c", 2))
    damage(circuit, reference + "." + field, bad)
    with pytest.raises(Exception) as caught:
        capture(circuit)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == (code, error_path(reference + "." + field))


@pytest.mark.parametrize(
    ("field", "bad", "code"),
    [
        ("qubits", set(), "source_container"),
        ("params", iter(()), "source_container"),
        ("qubits", (True,), "source_qubit"),
        ("params", (0,), "source_parameter"),
        ("gate_type", "X", "source_node"),
    ],
)
def test_damaged_mutable_source_body_fields(field, bad, code):
    circuit = sample()
    damage(circuit, "gates.2.body.0." + field, bad)
    with pytest.raises(Exception) as caught:
        capture(circuit)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    path = "$.gates[2].body[0]." + field
    if bad == (True,):
        path += "[0]"
    assert (caught.value.code, caught.value.path) == (code, path)


@pytest.mark.parametrize("sign", [-1, 1])
def test_source_integer_budget_parameter_precedes_conversion(sign):
    circuit = sample()
    object.__setattr__(circuit.gates[0], "params", (sign * 10**4096,))
    with pytest.raises(Exception) as caught:
        capture(circuit)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == ("range", "$.gates[0].params[0]")


def test_kernel_ref_existing_golden_circuits():
    from factories import bell_circuit, feedforward_circuit

    assert (
        capture(bell_circuit()).source_kernel_ref
        == "sha256:afe9bc2fd0c5ae8b243a4a8615bbe457adde36c1753835884557bc2d31e043d1"
    )
    assert (
        capture(feedforward_circuit()).source_kernel_ref
        == "sha256:82687501ff4b7e29c24778be0577d11d4b1a6c194df2f9041158e4fa589eae2d"
    )


def test_fixed_gate_parameter_counts_independent_of_mutable_registry(monkeypatch):
    single = {"I", "X", "Y", "Z", "H", "S", "T", "RX", "RY", "RZ", "U3", "RX90", "RX180"}
    counts = {"RX": 1, "RY": 1, "RZ": 1, "RX90": 1, "RX180": 1, "U3": 3}
    gates = [
        Gate(kind, (0,) if kind.value in single else (0, 1), (0.0,) * counts.get(kind.value, 0))
        for kind in GateType
    ]
    for kind in GateType:
        monkeypatch.setitem(PARAM_REQUIREMENTS, kind, (9, 9))
    for gate in gates:
        circuit = Circuit(2)
        circuit.gates = [gate]
        object.__setattr__(gate, "params", (0.0,) * 9)
        with pytest.raises(Exception) as caught:
            capture(circuit)
        assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
        assert (caught.value.code, caught.value.path) == ("source_parameter", "$.gates[0].params")


def test_fresh_snapshot_copies_every_container_and_freezes_fields():
    from dataclasses import FrozenInstanceError

    circuit = sample()
    qubits, params = [0], [0.5]
    body_qubits, body_params = [1], [0.25]
    body_gate = Gate(GateType.RY, (1,), (0.25,))
    object.__setattr__(body_gate, "qubits", body_qubits)
    object.__setattr__(body_gate, "params", body_params)
    body = [body_gate]
    object.__setattr__(circuit.gates[0], "qubits", qubits)
    object.__setattr__(circuit.gates[0], "params", params)
    object.__setattr__(circuit.gates[2], "body", body)
    result = capture(circuit)
    qubits[0], params[0], body_qubits[0], body_params[0] = 1, 0.75, 0, 0.5
    body.clear()
    circuit.gates.clear()
    circuit.cregs.clear()
    assert result.gates[0].qubits == (0,)
    assert result.gates[0].params == (0.5,)
    assert result.gates[2].body[0].qubits == (1,)
    assert result.gates[2].body[0].params == (0.25,)
    assert len(result.cregs) == 1
    for obj, field, value in [
        (result, "num_qubits", 3),
        (result.gates[0], "params", (1.0,)),
        (result.cregs[0], "size", 3),
        (result.gates[1], "qubit", 0),
        (result.gates[1].target, "index", 1),
        (result.gates[2], "value", 0),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)
