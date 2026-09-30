# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""用独立字面槽表检查未排程规则，避免生成器与认证器共享期望。"""

import math
import random

import pytest

from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.native.model import SourceLocation
from qaiji.core.native.rules import _expand_source
from qaiji.core.native.source import _capture_source

GATE_NAMES = (
    "I",
    "X",
    "Y",
    "Z",
    "H",
    "S",
    "T",
    "RX",
    "RY",
    "RZ",
    "U3",
    "RX90",
    "RX180",
    "CNOT",
    "CX",
    "CZ",
    "SWAP",
    "ISWAP",
    "SQISWAP",
)
TWO_QUBIT = {"CNOT", "CX", "CZ", "SWAP", "ISWAP", "SQISWAP"}
ONE_ANGLE = {"RX", "RY", "RZ", "RX90", "RX180"}
_rng = random.Random(20260927)
SAMPLES = [
    (0, 1, -1),
    (0.0, 0.0, 0.0),
    (-0.0, -0.0, -0.0),
    (0.7, 0.2, -0.4),
    (-1.3, 2.1, 0.6),
    (math.tau, math.tau, math.tau),
    (-math.tau, -math.tau, -math.tau),
    *[tuple(_rng.uniform(-math.tau, math.tau) for _ in range(3)) for _ in range(4)],
]


def gate(name, direction=(2, 0), angles=(0.7, 0.2, -0.4)):
    qubits = direction if name in TWO_QUBIT else direction[:1]
    params = angles if name == "U3" else angles[:1] if name in ONE_ANGLE else ()
    return Gate(GateType(name), qubits, params)


def snapshot(nodes):
    circuit = Circuit(3)
    circuit.cregs = [ClassicalRegister("readout", 2)]
    circuit.gates = list(nodes)
    return _capture_source(circuit)


def literal_slots(name, qubits, params):
    """逐槽抄录批准路线；双比特长序列不调用递归展开辅助函数。"""
    a, b = ((*qubits, 0))[:2]
    theta, phi, lam = ((*params, 0.0, 0.0, 0.0))[:3]
    h = math.pi / 2
    angle = -math.pi / 2 if name == "ISWAP" else -math.pi / 4
    table = {
        "I": (("I", (a,), ()),),
        "X": (("RX90", (a,), (0.0,)), ("RX90", (a,), (0.0,))),
        "Y": (("RX90", (a,), (h,)), ("RX90", (a,), (h,))),
        "Z": (("Z", (a,), ()),),
        "H": (("RZ", (a,), (h,)), ("RX90", (a,), (0.0,)), ("RZ", (a,), (h,))),
        "S": (("RZ", (a,), (h,)),),
        "T": (("RZ", (a,), (math.pi / 4,)),),
        "RX": (("RX90", (a,), (-h,)), ("RZ", (a,), (theta,)), ("RX90", (a,), (h,))),
        "RY": (("RX90", (a,), (0.0,)), ("RZ", (a,), (theta,)), ("RX90", (a,), (math.pi,))),
        "RZ": (("RZ", (a,), (theta,)),),
        "U3": (
            ("RZ", (a,), (lam,)),
            ("RX90", (a,), (0.0,)),
            ("RZ", (a,), (theta,)),
            ("RX90", (a,), (math.pi,)),
            ("RZ", (a,), (phi,)),
        ),
        "RX90": (("RX90", (a,), (theta,)),),
        "RX180": (("RX90", (a,), (theta,)), ("RX90", (a,), (theta,))),
        "CZ": (("CZ", (a, b), ()),),
        "CX": (
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("CZ", (a, b), ()),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
        ),
        "CNOT": (
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("CZ", (a, b), ()),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
        ),
        "SWAP": (
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("CZ", (a, b), ()),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("RZ", (a,), (h,)),
            ("RX90", (a,), (0.0,)),
            ("RZ", (a,), (h,)),
            ("CZ", (b, a), ()),
            ("RZ", (a,), (h,)),
            ("RX90", (a,), (0.0,)),
            ("RZ", (a,), (h,)),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("CZ", (a, b), ()),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
        ),
        "exchange": (
            ("RZ", (a,), (h,)),
            ("RX90", (a,), (0.0,)),
            ("RZ", (a,), (h,)),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("CZ", (a, b), ()),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("RZ", (b,), (angle,)),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("CZ", (a, b), ()),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("RZ", (a,), (h,)),
            ("RX90", (a,), (0.0,)),
            ("RZ", (a,), (h,)),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("RX90", (a,), (math.pi,)),
            ("RX90", (b,), (math.pi,)),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("CZ", (a, b), ()),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("RZ", (b,), (angle,)),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("CZ", (a, b), ()),
            ("RZ", (b,), (h,)),
            ("RX90", (b,), (0.0,)),
            ("RZ", (b,), (h,)),
            ("RX90", (a,), (0.0,)),
            ("RX90", (b,), (0.0,)),
        ),
    }
    return table["exchange" if name in ("ISWAP", "SQISWAP") else name]


def assert_slots(group, expected, location, rule_id):
    assert group.source == location
    assert group.rule_id == rule_id
    assert isinstance(group.operations, tuple)
    actual = tuple(
        (op.kind, op.qubits, tuple(p.hex() for p in op.params)) for op in group.operations
    )
    expected_hex = tuple(
        (kind, qubits, tuple(float(p).hex() for p in params)) for kind, qubits, params in expected
    )
    assert actual == expected_hex
    assert tuple(op.ordinal for op in group.operations) == tuple(range(len(expected)))
    assert all(type(op.params) is tuple and type(op.qubits) is tuple for op in group.operations)
    assert all(type(p) is float for op in group.operations for p in op.params)


def test_gate_type_rule_bijection():
    assert {member.value for member in GateType} == set(GATE_NAMES)
    groups = _expand_source(snapshot([gate(name) for name in GATE_NAMES]))
    assert isinstance(groups, tuple)
    assert tuple(group.rule_id for group in groups) == tuple("cz.v0." + name for name in GATE_NAMES)
    assert len(groups) == 19
    measure = Measure(2, ClassicalBit(ClassicalRegister("readout", 2), 1))
    measured = _expand_source(snapshot([measure]))
    assert len(measured) == 1
    assert_slots(
        measured[0],
        (("MEASURE", (2,), ()),),
        SourceLocation(gate_index=0, body_offset=None),
        "cz.v0.MEASURE",
    )


@pytest.mark.parametrize("name", GATE_NAMES)
@pytest.mark.parametrize("direction", [(2, 0), (0, 2)])
@pytest.mark.parametrize("angles", SAMPLES)
def test_approved_native_slots(name, direction, angles):
    node = gate(name, direction, angles)
    groups = _expand_source(snapshot([node]))
    assert len(groups) == 1
    assert_slots(
        groups[0],
        literal_slots(name, node.qubits, node.params),
        SourceLocation(gate_index=0, body_offset=None),
        "cz.v0." + name,
    )


PHASES = {
    "I": "0x0.0p+0",
    "X": "-0x1.921fb54442d18p+0",
    "Y": "-0x1.921fb54442d18p+0",
    "Z": "0x0.0p+0",
    "H": "-0x1.921fb54442d18p+0",
    "S": "-0x1.921fb54442d18p-1",
    "T": "-0x1.921fb54442d18p-2",
    "RX": "0x0.0p+0",
    "RY": "0x0.0p+0",
    "RZ": "0x0.0p+0",
    "U3": "0x1.999999999999ap-4",
    "RX90": "0x0.0p+0",
    "RX180": "0x0.0p+0",
    "CNOT": "-0x1.921fb54442d18p+1",
    "CX": "-0x1.921fb54442d18p+1",
    "CZ": "0x0.0p+0",
    "SWAP": "-0x1.2d97c7f3321d2p+3",
    "ISWAP": "-0x1.2d97c7f3321d2p+4",
    "SQISWAP": "-0x1.2d97c7f3321d2p+4",
}
PHASE_CASES = [(name, (0.7, 0.2, -0.4), value) for name, value in PHASES.items()] + [
    ("MEASURE", (), "0x0.0p+0"),
    ("U3", (0.7, 0.0, 0.0), "-0x0.0p+0"),
    ("U3", (0.7, -0.0, -0.0), "0x0.0p+0"),
    ("U3", (0.7, 5e-324, 5e-324), "-0x0.0p+0"),
    ("U3", (0.7, -5e-324, -5e-324), "0x0.0p+0"),
    ("U3", (0.7, math.tau, math.tau), "-0x1.921fb54442d18p+2"),
    ("U3", (0.7, -math.tau, -math.tau), "0x1.921fb54442d18p+2"),
]


@pytest.mark.parametrize(("name", "angles", "expected"), PHASE_CASES)
def test_phase_expression_hex(name, angles, expected):
    node = (
        Measure(0, ClassicalBit(ClassicalRegister("readout", 2), 0))
        if name == "MEASURE"
        else gate(name, angles=angles)
    )
    nodes = (
        [node]
        if name == "MEASURE"
        else [node, Conditional(ClassicalRegister("readout", 2), 1, (node,))]
    )
    groups = _expand_source(snapshot(nodes))
    assert len(groups) == len(nodes)
    assert tuple(group.phase_rad.hex() for group in groups) == (expected,) * len(nodes)


@pytest.mark.parametrize("name", GATE_NAMES)
@pytest.mark.parametrize("direction", [(2, 0), (0, 2)])
@pytest.mark.parametrize("angles", SAMPLES)
def test_conditional_body_rule_table(name, direction, angles):
    register = ClassicalRegister("readout", 2)
    node = gate(name, direction, angles)
    nodes = [
        gate("I"),
        Conditional(register, 3, ()),
        Conditional(register, 1, (gate("Z"), node)),
        gate("I"),
    ]
    groups = _expand_source(snapshot(nodes))
    assert len(groups) == 4
    assert tuple((group.source.gate_index, group.source.body_offset) for group in groups) == (
        (0, None),
        (2, 0),
        (2, 1),
        (3, None),
    )
    assert_slots(
        groups[2],
        literal_slots(name, node.qubits, node.params),
        SourceLocation(gate_index=2, body_offset=1),
        "cz.v0." + name,
    )
    assert_slots(
        groups[1], (("Z", (2,), ()),), SourceLocation(gate_index=2, body_offset=0), "cz.v0.Z"
    )


@pytest.mark.parametrize("name", ["RX90", "RX180", "ISWAP", "SQISWAP"])
@pytest.mark.parametrize("direction", [(2, 0), (0, 2)])
@pytest.mark.parametrize("angles", SAMPLES)
def test_four_gate_sign_and_branch(name, direction, angles):
    node = gate(name, direction, angles)
    groups = _expand_source(snapshot([node]))
    assert len(groups) == 1
    group = groups[0]
    assert_slots(
        group,
        literal_slots(name, node.qubits, node.params),
        SourceLocation(gate_index=0, body_offset=None),
        "cz.v0." + name,
    )
    if name in ("ISWAP", "SQISWAP"):
        assert len(group.operations) == 46
        assert tuple(i for i, op in enumerate(group.operations) if op.kind == "CZ") == (
            9,
            17,
            32,
            40,
        )
        angle_hex = "-0x1.921fb54442d18p+0" if name == "ISWAP" else "-0x1.921fb54442d18p-1"
        assert tuple(group.operations[i].params[0].hex() for i in (13, 36)) == (
            angle_hex,
            angle_hex,
        )
        assert (
            tuple(group.operations[i].params[0].hex() for i in (27, 28))
            == ("0x1.921fb54442d18p+1",) * 2
        )


def test_no_optimization_of_equivalent_slots():
    names = ("I", "RZ", "RZ", "RX", "RY", "U3", "CX", "CNOT", "I")
    nodes = [
        gate(name, angles=((-0.0,) * 3 if i == 2 else (0.0,) * 3)) for i, name in enumerate(names)
    ]
    groups = _expand_source(snapshot(nodes))
    assert len(groups) == 9
    assert tuple(len(group.operations) for group in groups) == (1, 1, 1, 3, 3, 5, 7, 7, 1)
    for i, (name, node, group) in enumerate(zip(names, nodes, groups, strict=True)):
        assert_slots(
            group,
            literal_slots(name, node.qubits, node.params),
            SourceLocation(gate_index=i, body_offset=None),
            "cz.v0." + name,
        )
    assert groups[6].rule_id != groups[7].rule_id
    assert _expand_source(snapshot([])) == ()
    assert _expand_source(snapshot([Conditional(ClassicalRegister("readout", 2), 0, ())])) == ()


@pytest.mark.parametrize("in_body", [False, True])
def test_generation_uses_captured_source(in_body):
    circuit = Circuit(3)
    node = gate("RX90", angles=(0.7, 0.0, 0.0))
    register = ClassicalRegister("readout", 2)
    circuit.cregs = [register]
    circuit.gates = [Conditional(register, 1, (node,)) if in_body else node]
    captured = _capture_source(circuit)
    original_ref = captured.source_kernel_ref
    initial_groups = _expand_source(captured)
    object.__setattr__(node, "params", (-1.3,))
    if in_body:
        object.__setattr__(circuit.gates[0], "body", (gate("X"),))
    circuit.gates[0] = gate("RX90", angles=(-1.3, 0.0, 0.0))
    circuit.gates.append(gate("X"))
    groups = _expand_source(captured)
    assert len(groups) == 1
    assert_slots(
        groups[0],
        (("RX90", (2,), (0.7,)),),
        SourceLocation(gate_index=0, body_offset=0 if in_body else None),
        "cz.v0.RX90",
    )
    assert groups == initial_groups
    assert captured.source_kernel_ref == original_ref
    assert _capture_source(circuit).source_kernel_ref != original_ref
