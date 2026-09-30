# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""OpenQASM 声明与序列化的接受契约。"""

# 本文件的来源核对报告：.plan/matrix/diff-v1.json（schema qaiji.qm6.diff.v1）。
# 报告 ID（文件 SHA256）：115acd9634159fe8f0187ef3c84a6e333ad3f12a3e397730ba164c75a547bab2
# EmuPlat HEAD：ff6bfc8f1b59e1e60f91de7996bf5434c06ea597；双方 openqasm3 1.0.1。
# 下列程序 ID 是报告 results[].id 的唯一前缀；首现位置相对于该 EmuPlat 检出树。
# 关联样例说明语义来源，不表示参数化输入逐字来自语料；原有期望值及其构造方式不变。
# 补充重放：tmp/qm6-impl/T10b/golden-replay.json，含全部58例输入和两侧规范形式。
# 条件候选只核对数量、值、展开门名和宽度；不证明候选未携带的寄存器名/目标/参数。
# 展开规范化共用生产展开表，物理正确性由独立物理测试负责。

import pytest

from qaiji.codec.qasm3 import from_qasm3, to_qasm3
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.exceptions import QaijiIRError


# 来源核对：声明/测量关联样例；去头、改版本和改寄存器名是手写派生，非逐字快照。
# diff-v1 程序 26594a7df50cc16b（A），首现 tests/compiler/test_frontend_source_span.py:10。
@pytest.mark.parametrize(
    ("header", "source"),
    [
        (
            "OPENQASM 2.0;",
            'include "qelib1.inc"; qreg a[2]; creg c[2]; h a[0]; cx a[0], a[1]; measure a[1] -> c[0];',
        ),
        (
            "OPENQASM 3.0;",
            'include "stdgates.inc"; qubit[2] a; bit[2] c; h a[0]; cx a[0], a[1]; c[0] = measure a[1];',
        ),
        ("OPENQASM 2.5;", "qreg a[1]; x a[0];"),
        ("OPENQASM 3.1;", "qubit a; x a[0];"),
    ],
)
def test_header_optional_programs_match_explicit_headers(header, source):
    try:
        actual = from_qasm3(source)
        explicit = from_qasm3(header + " " + source)
    except QaijiIRError as exc:
        raise AssertionError("headerless program was rejected") from exc
    assert actual == explicit, "headerless program changed circuit"


# 来源核对：多寄存器偏移关联样例；下列不对称下标和条件体是手写派生。
# diff-v1 程序 682ffadbe3c9f7a8（A），首现 tests/quantum/qasm/test_parser.py:287。
@pytest.mark.parametrize(
    "declarations",
    [
        "qubit a; qubit[3] b; qubit[2] d; bit[2] c;",
        "creg c[2]; qreg a[1]; qreg b[3]; qreg d[2];",
    ],
)
def test_qubit_registers_flatten_in_declaration_order(declarations):
    source = (
        'OPENQASM 3.0; include "stdgates.inc"; '
        + declarations
        + " x b[1]; cx a[0], d[0]; c[1] = measure b[0]; if (c == 1) { h d[0]; cx b[2], a[0]; }"
    )
    c = ClassicalRegister("c", 2)
    expected = Circuit(6)
    expected.add_register(c)
    expected.add_gate(Gate(GateType.X, (2,)))
    expected.add_gate(Gate(GateType.CX, (0, 4)))
    expected.add_measure(Measure(1, ClassicalBit(c, 1)))
    expected.add_conditional(Conditional(c, 1, (Gate(GateType.H, (4,)), Gate(GateType.CX, (3, 0)))))
    try:
        actual = from_qasm3(source)
    except QaijiIRError as exc:
        raise AssertionError("multiple register program was rejected") from exc
    assert actual == expected, "register flattening changed ordered operations"
    assert from_qasm3(to_qasm3(actual)) == expected, "flattened program roundtrip changed"


# 来源核对：命名避让是 qaiji 序列化契约，真实语料无对应首现位置；非 EmuPlat 快照。
@pytest.mark.parametrize(
    ("names", "expected_name"),
    [
        (("q",), "q0"),
        (("q", "q0"), "q1"),
        (("q", "q0", "q1"), "q2"),
        (("q", "q1"), "q0"),
        (("q", "q0", "q2"), "q1"),
    ],
    ids=["q-taken", "q0-taken", "q1-taken", "first-hole", "later-hole"],
)
def test_to_qasm3_avoids_classical_register_names(names, expected_name):
    circuit = Circuit(2)
    registers = [ClassicalRegister(name, 1) for name in names]
    for register in registers:
        circuit.add_register(register)
    circuit.add_gate(Gate(GateType.H, (0,)))
    circuit.add_measure(Measure(0, ClassicalBit(registers[0], 0)))
    circuit.add_conditional(Conditional(registers[0], 1, (Gate(GateType.X, (1,)),)))
    try:
        source = to_qasm3(circuit)
        second_source = to_qasm3(circuit)
    except QaijiIRError as exc:
        raise AssertionError("register naming serialization was rejected") from exc
    assert f"qubit[2] {expected_name};\n" in source, "quantum register candidate selection changed"
    assert source == second_source, "quantum register selection is nondeterministic"
    try:
        restored = from_qasm3(source)
    except QaijiIRError as exc:
        raise AssertionError("register naming roundtrip was rejected") from exc
    assert restored == circuit, "register naming roundtrip changed circuit"


# 来源核对：bell 输入逐字命中；三份输出均源自 qaiji 原始序列化器，不源自 EmuPlat 输出。
# diff-v1 程序 52b456fd583d44c1（A），首现 tests/compiler/test_frontend_version_mismatch.py:20。
# 原始输出：tmp/qm6-impl/T3/codec/origin.json 的 goldens；feedforward/c-and-q0 无逐字语料首现。
@pytest.mark.parametrize(
    ("name", "golden"),
    [
        (
            "bell",
            'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nbit[2] c;\nh q[0];\ncx q[0], q[1];\nc[0] = measure q[0];\nc[1] = measure q[1];\n',
        ),
        (
            "feedforward",
            'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nbit[1] c;\nh q[0];\nc[0] = measure q[0];\nif (c == 1) {\n  x q[1];\n}\n',
        ),
        (
            "c-and-q0",
            'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nbit[1] c;\nbit[1] q0;\nh q[0];\nc[0] = measure q[0];\nif (q0 == 1) {\n  x q[1];\n}\n',
        ),
    ],
    ids=["bell", "feedforward", "c-and-q0"],
)
def test_to_qasm3_output_is_unchanged_when_q_is_free(name, golden):
    from factories import bell_circuit, feedforward_circuit

    if name == "bell":
        circuit = bell_circuit()
    elif name == "feedforward":
        circuit = feedforward_circuit()
    else:
        circuit = Circuit(2)
        c, q0 = ClassicalRegister("c", 1), ClassicalRegister("q0", 1)
        circuit.add_register(c)
        circuit.add_register(q0)
        circuit.add_gate(Gate(GateType.H, (0,)))
        circuit.add_measure(Measure(0, ClassicalBit(c, 0)))
        circuit.add_conditional(Conditional(q0, 1, (Gate(GateType.X, (1,)),)))
    try:
        source = to_qasm3(circuit)
    except QaijiIRError as exc:
        raise AssertionError("unoccupied quantum register serialization was rejected") from exc
    assert source == golden, "unoccupied quantum register output changed"


# 来源核对：x b 的有序广播关联样例；门名、宽度、固定端点及条件体是手写派生。
# diff-v1 程序 8bf5afd5d32bd603（A），首现 tests/quantum/qasm/test_parser.py:519。
@pytest.mark.parametrize(
    ("operation", "gate_type", "qubits"),
    [
        ("h a;", "H", [(0,), (1,), (2,)]),
        ("cx a, b;", "CX", [(0, 3), (1, 4), (2, 5)]),
        ("cx a[1], b;", "CX", [(1, 3), (1, 4), (1, 5)]),
        ("cx a, b[1];", "CX", [(0, 4), (1, 4), (2, 4)]),
    ],
    ids=["single-register", "two-registers", "fixed-control", "fixed-target"],
)
@pytest.mark.parametrize("conditional", [False, True])
def test_gate_broadcast_orders_applications_by_index(operation, gate_type, qubits, conditional):
    expected = Circuit(6)
    c = ClassicalRegister("c", 1)
    expected.add_register(c)
    gates = tuple(Gate(GateType[gate_type], tuple(qs)) for qs in qubits)
    if conditional:
        operation = "if (c == 1) { " + operation + " }"
        expected.add_conditional(Conditional(c, 1, gates))
    else:
        for gate in gates:
            expected.add_gate(gate)
    try:
        actual = from_qasm3("qubit[3] a; qubit[3] b; bit c; " + operation)
    except QaijiIRError as exc:
        raise AssertionError("gate broadcast was rejected") from exc
    assert actual == expected, "gate broadcast ordered applications changed"
    assert from_qasm3(to_qasm3(actual)) == expected


# 来源核对：整寄存器测量关联样例；前缀偏移、宽度和赋值写法是手写派生。
# diff-v1 程序 26594a7df50cc16b（A），首现 tests/compiler/test_frontend_source_span.py:10。
@pytest.mark.parametrize(
    "operation", ["c = measure q;", "measure q -> c;"], ids=["assignment", "arrow"]
)
def test_measurement_broadcast_pairs_by_index(operation):
    c = ClassicalRegister("c", 3)
    expected = Circuit(5)
    expected.add_register(c)
    for qubit, bit in [(2, 0), (3, 1), (4, 2)]:
        expected.add_measure(Measure(qubit, ClassicalBit(c, bit)))
    try:
        actual = from_qasm3("qubit[2] prefix; qubit[3] q; bit[3] c; " + operation)
    except QaijiIRError as exc:
        raise AssertionError("measurement broadcast was rejected") from exc
    assert actual == expected, "measurement broadcast ordered pairs changed"
    assert from_qasm3(to_qasm3(actual)) == expected


# 来源核对：p/sx/crx/cry/crz 关联样例，不代表全部19门均在语料；其余由补充重放核对。
# diff-v1 程序 015c19d7ba90940a（A），首现 tests/quantum/qasm/test_parser.py:207。
@pytest.mark.parametrize(
    "name",
    [
        "p",
        "u1",
        "u2",
        "u",
        "sdg",
        "tdg",
        "sx",
        "sxdg",
        "cy",
        "ch",
        "crx",
        "cry",
        "crz",
        "cp",
        "cu1",
        "cu",
        "cu3",
        "ccx",
        "cswap",
    ],
)
def test_standard_gate_names_expand_through_frontend(name):
    from qaiji.codec._stdgates import _EXPANSIONS

    spec = _EXPANSIONS[name]
    params = (0.25, -0.5, 0.75, -1.0)[: spec.n_params]
    args = "(" + ",".join(map(str, params)) + ")" if params else ""
    operands = ",".join(f"q[{i}]" for i in range(spec.arity))
    expected = Circuit(spec.arity)
    for gate in spec.build(tuple(range(spec.arity)), params):
        expected.add_gate(gate)
    try:
        actual = from_qasm3(f"qubit[{spec.arity}] q; {name}{args} {operands};")
    except QaijiIRError as exc:
        raise AssertionError("standard gate expansion was rejected") from exc
    assert actual == expected, "standard gate expansion ordered sequence changed"
    assert from_qasm3(to_qasm3(actual)) == expected


# 来源核对：小写 sx 关联样例；cu3 为手写探针。SX/U/CX 被 EmuPlat 拒收，不标为等价快照。
# diff-v1 程序 2525996694d55515（A），首现 tests/compiler/fixtures/qasm/q3_stdgates_unmapped_sx.qasm:1。
@pytest.mark.parametrize(
    ("operation", "golden"),
    [
        ("SX q[0];", [("RX", (0,), (1.5707963267948966,))]),
        ("U(0.25,-0.5,0.75) q[0];", [("U3", (0,), (0.25, -0.5, 0.75))]),
        ("CX q[0],q[1];", [("CX", (0, 1), ())]),
        ("sx q[0];", [("RX", (0,), (1.5707963267948966,))]),
        (
            "cu3(0.25,-0.5,0.75) q[0],q[1];",
            [
                ("U3", (1,), (0.0, 0.0, 0.625)),
                ("CX", (0, 1), ()),
                ("U3", (1,), (-0.125, 0.0, -0.125)),
                ("CX", (0, 1), ()),
                ("U3", (1,), (0.125, -0.5, 0.0)),
            ],
        ),
    ],
    ids=["SX", "U", "CX", "literal-sx", "literal-cu3"],
)
def test_uppercase_gate_names_follow_lowercasing(operation, golden):
    expected = Circuit(2)
    for name, qubits, params in golden:
        expected.add_gate(Gate(GateType[name], qubits, params))
    try:
        actual = from_qasm3("qubit[2] q; " + operation)
    except QaijiIRError as exc:
        raise AssertionError("uppercase or golden expansion was rejected") from exc
    assert actual == expected, "literal expansion ordered sequence changed"


# 来源核对：cy 有序展开关联样例；整寄存器广播、cp 和条件组合由补充重放核对。
# diff-v1 程序 b9e68c0849f77286（A），首现 tests/quantum/qasm/test_parser.py:173。
@pytest.mark.parametrize("name", ["cy", "cp"])
@pytest.mark.parametrize("conditional", [False, True])
def test_broadcast_happens_before_expansion(name, conditional):
    c = ClassicalRegister("c", 1)
    expected = Circuit(4)
    expected.add_register(c)
    gates = []
    for control, target in [(0, 2), (1, 3)]:
        if name == "cy":
            gates.extend(
                [
                    Gate(GateType.U3, (target,), (0.0, 0.0, -1.5707963267948966)),
                    Gate(GateType.CX, (control, target)),
                    Gate(GateType.S, (target,)),
                ]
            )
        else:
            gates.extend(
                [
                    Gate(GateType.U3, (control,), (0.0, 0.0, 0.375)),
                    Gate(GateType.CX, (control, target)),
                    Gate(GateType.U3, (target,), (0.0, 0.0, -0.375)),
                    Gate(GateType.CX, (control, target)),
                    Gate(GateType.U3, (target,), (0.0, 0.0, 0.375)),
                ]
            )
    operation = name + ("(0.75)" if name == "cp" else "") + " a, b;"
    if conditional:
        operation = "if (c == 1) { " + operation + " }"
        expected.add_conditional(Conditional(c, 1, tuple(gates)))
    else:
        for gate in gates:
            expected.add_gate(gate)
    try:
        actual = from_qasm3("qubit[2] a; qubit[2] b; bit c; " + operation)
    except QaijiIRError as exc:
        raise AssertionError("broadcast expansion was rejected") from exc
    assert actual == expected, "broadcast expansion ordered blocks changed"
    assert from_qasm3(to_qasm3(actual)) == expected


# 来源核对：单位 bit 反馈关联样例；寄存器名和值的参数化是手写派生，候选不含目标信息。
# diff-v1 程序 f81832c6de6a3119（A-feedback），首现 examples/00_quickstart/active_reset_feedback.py:51。
@pytest.mark.parametrize("name", ["c", "d"])
@pytest.mark.parametrize("value", [0, 1])
def test_single_bit_register_condition_lowers_to_register_conditional(name, value):
    c, d = ClassicalRegister("c", 1), ClassicalRegister("d", 1)
    expected = Circuit(1)
    expected.add_register(c)
    expected.add_register(d)
    register = c if name == "c" else d
    expected.add_conditional(Conditional(register, value, (Gate(GateType.X, (0,)),)))
    try:
        actual = from_qasm3(f"qubit q; bit c; bit d; if ({name}[0] == {value}) {{ x q[0]; }}")
    except QaijiIRError as exc:
        raise AssertionError("single-bit condition was rejected") from exc
    assert actual == expected, "single-bit condition register or value changed"
    assert actual.gates[0].register == register
    assert actual.gates[0].value == value
    assert from_qasm3(to_qasm3(actual)) == expected


# 来源核对：无测量的单位 bit 条件关联样例；多门、广播和展开组合是 qaiji 超集契约。
# diff-v1 程序 946dfbe6b1d8ac4f（C-superset），首现 tests/compiler/test_semantic_annotation_seam.py:97。
@pytest.mark.parametrize("value", [0, 1])
def test_bit_condition_body_allows_broadcast_and_expansion(value):
    register = ClassicalRegister("c", 1)
    expected = Circuit(4)
    expected.add_register(register)
    golden = [
        ("H", (0,), ()),
        ("H", (1,), ()),
        ("U3", (2,), (0.0, 0.0, -1.5707963267948966)),
        ("CX", (0, 2), ()),
        ("S", (2,), ()),
        ("U3", (3,), (0.0, 0.0, -1.5707963267948966)),
        ("CX", (1, 3), ()),
        ("S", (3,), ()),
        ("X", (3,), ()),
    ]
    gates = tuple(Gate(GateType[name], qubits, params) for name, qubits, params in golden)
    expected.add_conditional(Conditional(register, value, gates))
    try:
        actual = from_qasm3(
            f"qubit[2] a; qubit[2] b; bit c; if (c[0] == {value}) {{ h a; cy a, b; x b[1]; }}"
        )
    except QaijiIRError as exc:
        raise AssertionError("single-bit conditional broadcast expansion was rejected") from exc
    assert actual == expected, "conditional broadcast expansion order changed"
    assert from_qasm3(to_qasm3(actual)) == expected


@pytest.mark.parametrize(
    "golden_family",
    [
        "test_header_optional_programs_match_explicit_headers",
        "test_qubit_registers_flatten_in_declaration_order",
        "test_to_qasm3_avoids_classical_register_names",
        "test_to_qasm3_output_is_unchanged_when_q_is_free",
        "test_gate_broadcast_orders_applications_by_index",
        "test_measurement_broadcast_pairs_by_index",
        "test_standard_gate_names_expand_through_frontend",
        "test_uppercase_gate_names_follow_lowercasing",
        "test_broadcast_happens_before_expansion",
        "test_single_bit_register_condition_lowers_to_register_conditional",
        "test_bit_condition_body_allows_broadcast_and_expansion",
    ],
)
def test_m1_programs_round_trip_through_to_qasm3(golden_family, monkeypatch):
    """重放每个接受 golden 的全部参数，并在编解码边界检查 Circuit 精确相等。"""
    from itertools import product

    parse, serialize = from_qasm3, to_qasm3
    checked = []

    def round_trip_parse(source):
        circuit = parse(source)
        assert parse(serialize(circuit)) == circuit, "M-1 parsed circuit roundtrip changed"
        checked.append(source)
        return circuit

    def round_trip_serialize(circuit):
        source = serialize(circuit)
        assert parse(source) == circuit, "M-1 serialized circuit roundtrip changed"
        checked.append(source)
        return source

    monkeypatch.setitem(globals(), "from_qasm3", round_trip_parse)
    monkeypatch.setitem(globals(), "to_qasm3", round_trip_serialize)
    golden = globals()[golden_family]
    parameter_groups = []
    for mark in golden.pytestmark:
        assert mark.name == "parametrize", "golden acquired a non-parameter mark"
        names, values = mark.args
        if isinstance(names, str):
            names = (names,)
        parameter_groups.append(
            [
                dict(zip(names, (value,) if len(names) == 1 else value, strict=True))
                for value in values
            ]
        )
    for combination in product(*parameter_groups):
        kwargs = {key: value for group in combination for key, value in group.items()}
        before = len(checked)
        golden(**kwargs)
        assert len(checked) > before, "golden did not exercise a codec boundary"
