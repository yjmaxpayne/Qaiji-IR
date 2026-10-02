# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""验证 ``parse_qasm3`` 的源码旁表：逐门对齐、坐标约定，以及旁表绝不进入语义。"""

from __future__ import annotations

import dataclasses
import inspect
import sys

import openqasm3
import pytest

from qaiji.codec import OperationOrigin, ParsedQasm3, from_qasm3, parse_qasm3, to_qasm3
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import Conditional, Measure
from qaiji.core.semantics import annotate_circuit, build_semantic_summary, canonical_summary_hash
from qaiji.exceptions import QaijiIRError

MIXED = (
    "OPENQASM 3.0;\n"
    'include "stdgates.inc";\n'
    "qubit[3] q;\n"
    "bit[3] c;\n"
    "CX q[0], q[1]; ccx q[0], q[1], q[2];\n"
    "rz(π) q[2];\n"
    "c = measure q;\n"
    "if (c == 1) { x q[1]; h q; }\n"
)
# 与 MIXED 是同一个程序，只有空白、换行与注释不同：两者的语义必须完全一致。
RELAID = (
    'OPENQASM 3.0; include "stdgates.inc";\n'
    "// layout differs only\n"
    "qubit[3] q;   bit[3] c;\n"
    "\n"
    "CX q[0],\n"
    "   q[1];\n"
    "ccx q[0], q[1], q[2]; rz(π) q[2]; c = measure q;\n"
    "if (c == 1) {\n"
    "  x q[1];\n"
    "  h q;\n"
    "}\n"
)


def _source_text(src: str, origin: OperationOrigin) -> str:
    """按闭区间 code point 坐标从源码中切出 origin 指向的文本。"""
    lines = src.split("\n")
    if origin.line == origin.end_line:
        return lines[origin.line - 1][origin.column - 1 : origin.end_column]
    head = lines[origin.line - 1][origin.column - 1 :]
    middle = lines[origin.line : origin.end_line - 1]
    tail = lines[origin.end_line - 1][: origin.end_column]
    return "\n".join([head, *middle, tail])


def _summary_hash(circuit: Circuit) -> str:
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))
    return canonical_summary_hash(summary)


def _kind(operation: object) -> str:
    if isinstance(operation, Measure):
        return "measure"
    if isinstance(operation, Conditional):
        return "if"
    assert isinstance(operation, Gate)
    return "gate"


def test_origins_align_one_to_one_with_gates():
    """消费方按下标把 origin 对回门；展开门、广播、测量与条件各占一位才不会错位。"""
    sources = (
        MIXED,
        "qubit[2] q; h q; cx q[0], q[1];",
        'include "stdgates.inc"; qubit[2] a; qubit[2] b; ch a, b; swap a[0], b[1];',
        "qubit[2] q; bit c; c = measure q[0]; if (c == 1) { cp(0.3) q[0], q[1]; }",
    )
    for src in sources:
        parsed = parse_qasm3(src)
        assert len(parsed.origins) == len(parsed.circuit.gates), src
        for operation, origin in zip(parsed.circuit.gates, parsed.origins, strict=True):
            raw = origin.raw_name if origin.raw_name in ("measure", "if") else "gate"
            assert raw == _kind(operation), (src, origin)
    # 每个源码操作数位置独占一组下标：ccx 展开成 15 个门，它们共享语句却各占一位
    expanded = [o for o in parse_qasm3(MIXED).origins if o.raw_name == "ccx"]
    assert [o.expansion_index for o in expanded] == list(range(15))


def test_conditional_origin_body_aligns_with_body():
    """条件体是门的第二层序列；它的旁表必须与 ``Conditional.body`` 同样逐门对齐。"""
    src = "qubit[2] q; bit c; c = measure q[0]; if (c == 1) { ch q[0], q[1]; h q; }"
    parsed = parse_qasm3(src)
    conditional, origin = parsed.circuit.gates[-1], parsed.origins[-1]
    assert isinstance(conditional, Conditional)
    assert (origin.raw_name, len(origin.body)) == ("if", len(conditional.body))
    assert [(o.raw_name, o.broadcast_index, o.expansion_index) for o in origin.body] == [
        ("ch", 0, 0),
        ("ch", 0, 1),
        ("ch", 0, 2),
        ("h", 0, 0),
        ("h", 1, 0),
    ]
    assert [_source_text(src, o) for o in origin.body] == ["ch q[0], q[1];"] * 3 + ["h q;"] * 2
    # 条件体内的门属于 if 这条顶层语句；只有条件 origin 才带 body
    assert {o.statement_index for o in origin.body} == {origin.statement_index}
    assert all(o.body == () for o in parsed.origins[:-1])


def test_origin_coordinates_are_one_based_inclusive_code_points():
    """坐标与错误消息同一约定（1 起、闭区间），列按 code point 计，EmuPlat 只需减 1。"""
    src = (
        "OPENQASM 3.0;\nqubit[2] q;\nrz(π) q[0]; h q[1];\ncx q[0],\n   q[1];\n"
        "bit c;\nc = measure q[1];\nif (c == 1) {\n x q[1];\n}\n"
    )
    rz, h, cx, measure, condition = parse_qasm3(src).origins
    assert (rz.line, rz.column, rz.end_line, rz.end_column) == (3, 1, 3, 11)
    assert (h.line, h.column, h.end_line, h.end_column) == (3, 13, 3, 19)
    assert (cx.line, cx.column, cx.end_line, cx.end_column) == (4, 1, 5, 8)
    # 测量与条件的 span 覆盖整条语句，而不是其中的操作数、条件表达式或条件体
    assert [_source_text(src, o) for o in (rz, h, cx, measure, condition)] == [
        "rz(π) q[0];",
        "h q[1];",
        "cx q[0],\n   q[1];",
        "c = measure q[1];",
        "if (c == 1) {\n x q[1];\n}",
    ]
    # 标量测量不是广播：广播下标为 0，与被测 qubit 的下标无关
    assert measure.broadcast_index == 0
    rejected = src.replace("h q[1];", "foo q[1];")
    with pytest.raises(QaijiIRError, match=r"^foo at 3:13: "):
        parse_qasm3(rejected)


def test_broadcast_and_expansion_indices_trace_to_statement():
    """两个下标加语句序号能把任一门追回唯一的源码语句、广播位与展开位。"""
    src = 'include "stdgates.inc"; qubit[2] a; qubit[2] b; bit[2] c; h a; ch a, b; c = measure b;'
    parsed = parse_qasm3(src)
    triples = [(o.statement_index, o.broadcast_index, o.expansion_index) for o in parsed.origins]
    # include、两个 qubit 与 bit 声明也占语句序号，因此 h 是第 4 条语句（0 起）
    assert triples == [
        (4, 0, 0),
        (4, 1, 0),
        *((5, i, k) for i in range(2) for k in range(3)),
        (6, 0, 0),
        (6, 1, 0),
    ]
    for gate, origin in zip(parsed.circuit.gates, parsed.origins, strict=True):
        if origin.raw_name == "ch":
            assert set(gate.qubits) <= {origin.broadcast_index, 2 + origin.broadcast_index}
        elif origin.raw_name == "h":
            assert gate.qubits == (origin.broadcast_index,)
        else:
            assert gate.qubit == 2 + origin.broadcast_index


def test_raw_name_preserves_source_spelling():
    """电路只存规范门型，诊断需要的原样拼写只能从 ``raw_name`` 取回。"""
    parsed = parse_qasm3("qubit[2] q; CX q[0], q[1]; Cx q[0], q[1]; H q[0]; h q[1];")
    assert [o.raw_name for o in parsed.origins] == ["CX", "Cx", "H", "h"]
    assert [g.gate_type for g in parsed.circuit.gates] == [
        GateType.CX,
        GateType.CX,
        GateType.H,
        GateType.H,
    ]


def test_declared_version_four_states():
    """版本头原文决定下游的 3.0 专属判定；缺头与注释里的版本头都不能被补成某个值。"""
    cases = {
        "OPENQASM 3.0;\nqubit q;": "3.0",
        "OPENQASM 3;\nqubit q;": "3",
        'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];': "2.0",
        "qubit q;": None,
        "// OPENQASM 3.0;\nqubit q;": None,
        "// OPENQASM 2.0;\nOPENQASM 3;\nqubit q;": "3",
    }
    for src, expected in cases.items():
        parsed = parse_qasm3(src)
        assert parsed.declared_version == expected, src
        assert parsed.version_header_present is (expected is not None), src


def test_parsed_circuit_equals_from_qasm3_circuit():
    """新入口只多给旁表：接受时电路与 ``from_qasm3`` 相同，拒收时异常类与消息逐字相同。"""
    accepted = (MIXED, RELAID, "qubit[2] q; ch q[0], q[1];", "OPENQASM 2.0; qreg q[1]; x q[0];")
    for src in accepted:
        assert parse_qasm3(src).circuit == from_qasm3(src), src
    # 独立构造的期望值：解析结果不能是规范化后的电路（规范化会把 -0.5 折到 [0, 2π)）
    expected = Circuit(1)
    expected.add_gate(Gate(GateType.RZ, (0,), (-0.5,)))
    assert parse_qasm3("qubit q; rz(-0.5) q[0];").circuit.gates == expected.gates

    rejected = (
        "qubit q; foo q;",
        "qubit q; h q",
        "OPENQASM 4.0; qubit q;",
        "",
        "qubit q; rx(" + "(" * 400 + "1" + ")" * 400 + ") q[0];",
    )
    # 只在本测试内压低递归上限，让深嵌套表达式确定地触发递归保护
    original = sys.getrecursionlimit()
    sys.setrecursionlimit(len(inspect.stack(0)) + 200)
    try:
        for src in rejected:
            with pytest.raises(Exception) as from_error:
                from_qasm3(src)
            with pytest.raises(Exception) as parse_error:
                parse_qasm3(src)
            assert (type(parse_error.value), str(parse_error.value)) == (
                type(from_error.value),
                str(from_error.value),
            ), src
            assert isinstance(parse_error.value, QaijiIRError), src
    finally:
        sys.setrecursionlimit(original)


def test_origins_stay_out_of_equality_hash_summary_and_canonical_form():
    """旁表只是外挂元数据：排版不同的同一程序，在相等、摘要哈希与规范形上必须无从区分。"""
    first, second = parse_qasm3(MIXED), parse_qasm3(RELAID)
    assert first.origins != second.origins  # 前提：两份源码的坐标确实不同
    assert first.circuit == second.circuit, "layout leaked into circuit equality"
    assert first.circuit.canonicalize() == second.circuit.canonicalize(), (
        "layout leaked into canonical form"
    )
    assert _summary_hash(first.circuit) == _summary_hash(second.circuit), (
        "layout leaked into summary hash"
    )
    # 电路实例上不挂任何新属性，元数据只活在 ParsedQasm3 里
    assert set(vars(first.circuit)) == set(vars(Circuit(first.circuit.num_qubits)))


def test_to_qasm3_output_ignores_origins():
    """序列化只看电路：排版与原样拼写都不能渗进 ``to_qasm3`` 的输出。"""
    assert to_qasm3(parse_qasm3(MIXED).circuit) == to_qasm3(parse_qasm3(RELAID).circuit)
    upper = to_qasm3(parse_qasm3("qubit[2] q; CX q[0], q[1];").circuit)
    assert upper == to_qasm3(parse_qasm3("qubit[2] q; cx q[0], q[1];").circuit)
    assert "CX" not in upper


def test_parse_qasm3_parses_source_exactly_once(monkeypatch):
    """取版本或旁表不得再解析一遍：每次编译只付一次解析成本。"""
    calls = []
    parse = openqasm3.parse

    def counting(src, *args, **kwargs):
        calls.append(src)
        return parse(src, *args, **kwargs)

    monkeypatch.setattr(openqasm3, "parse", counting)
    for entry in (parse_qasm3, from_qasm3):
        calls.clear()
        entry(MIXED)
        assert calls == [MIXED], entry.__name__
        calls.clear()
        with pytest.raises(QaijiIRError):
            entry("qubit q; foo q;")
        assert len(calls) == 1, entry.__name__


def test_parsed_qasm3_is_frozen_and_unhashable():
    """记录只读；含可变电路故不可哈希，且 ``==`` 连旁表一起比，比较语义要取 ``.circuit``。"""
    first, second = parse_qasm3(MIXED), parse_qasm3(RELAID)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.circuit = second.circuit  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.origins[0].line = 2  # type: ignore[misc]
    with pytest.raises(TypeError, match="unhashable"):
        hash(first)
    assert hash(first.origins[0]) == hash(parse_qasm3(MIXED).origins[0])
    assert first != second and first.circuit == second.circuit
    assert first == parse_qasm3(MIXED)
    # 版本头是否存在由 declared_version 派生，不是可以与之矛盾的独立字段
    assert "version_header_present" not in {f.name for f in dataclasses.fields(ParsedQasm3)}
    assert isinstance(ParsedQasm3.version_header_present, property)
