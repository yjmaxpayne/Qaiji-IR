# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""``to_qasm3`` 写回循环程序；循环文本的身份经展开后等于手写平坦文本。"""

import pytest

from _fresh_process import run_fresh_process
from qaiji.codec import from_qasm3, parse_looped_qasm3, to_qasm3
from qaiji.core.circuit import Circuit, GateType
from qaiji.core.classical import ClassicalRegister
from qaiji.core.loop import (
    BoundedLoop,
    GateTemplate,
    LoopedCircuit,
    LoopIndex,
    MeasureTemplate,
    SourceSpan,
)
from qaiji.core.program.validation import compute_kernel_ref
from qaiji.core.semantics.registry import annotate_circuit
from qaiji.core.semantics.summary import build_semantic_summary, canonical_summary_hash

HEADER = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[4] q;\n'
ROUND = """h q[3]; cz q[0], q[3]; cz q[3], q[1]; h q[3]; s[0] = measure q[3];
h q[3]; cz q[1], q[3]; cz q[2], q[3]; h q[3]; s[1] = measure q[3];
if (s == 3) { x q[0]; }
if (s == 1) { x q[1]; }
if (s == 2) { x q[2]; }
if (s[1] == 1) { x q[3]; }
"""
INJECTIONS = {"none": "", "x0": "x q[0];\n", "x1": "x q[1];\n", "x2": "x q[2];\n"}


def repetition_loop_text(injection: str, last: int = 1) -> str:
    return f"{HEADER}{injection}for int r in [0:{last}] {{\n  bit[2] s;\n{ROUND}}}\n"


def repetition_flat_text(injection: str, rounds: int = 2) -> str:
    text = HEADER + "".join(f"bit[2] s__{r};\n" for r in range(rounds)) + injection
    for r in range(rounds):
        text += ROUND.replace("s[", f"s__{r}[").replace("(s ==", f"(s__{r} ==")
    return text


def summary_hash(circuit: Circuit) -> str:
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))
    return canonical_summary_hash(summary)


def identity(source: str) -> tuple[Circuit, str, str]:
    circuit = parse_looped_qasm3(source).circuit.expand().circuit
    return circuit, compute_kernel_ref(circuit), summary_hash(circuit)


H = "OPENQASM 3.0;\nqubit[4] q;\n"
ROUND_TRIP_SOURCES = {
    # 起点为 1：写回若从 0 起或右端偏移，再解析后循环节点不等。
    "for-from-one": f"{H}for int i in [1:2] {{ x q[i]; }}\n",
    "index-in-every-slot": (
        f"{H}bit[1] c;\nfor int i in [1:2] {{\n  bit[3] m;\n  rz(0.25) q[i];\n"
        "  m[i] = measure q[i];\n  if (m[i] == 1) { x q[i]; }\n  if (m == 2) { cx q[i], q[0]; }\n}\n"
    ),
    "const-bound": f"{H}const int N = 2;\nfor int i in [1:N] {{ h q[i]; }}\n",
    "operations-around-the-loop": f"{H}x q[0];\nfor int i in [2:3] {{ x q[i]; }}\nh q[1];\n",
    "zero-iterations": f"{H}for int i in [2:1] {{ x q[i]; }}\n",
    "repetition-code-two-rounds": repetition_loop_text("x q[1];\n"),
}


@pytest.mark.parametrize("source", ROUND_TRIP_SOURCES.values(), ids=ROUND_TRIP_SOURCES.keys())
def test_to_qasm3_round_trips_looped_circuits(source: str) -> None:
    circuit = parse_looped_qasm3(source).circuit
    assert any(isinstance(node, BoundedLoop) for node in circuit.operations)

    text = to_qasm3(circuit)

    assert parse_looped_qasm3(text).circuit == circuit
    assert to_qasm3(parse_looped_qasm3(text).circuit) == text


def test_to_qasm3_writes_a_counter_while_as_for() -> None:
    # 条件用 "<" 且起点为 1：写回若保留 while 且把上界原样当作 "<" 的右端，循环少一轮。
    circuit = parse_looped_qasm3(f"{H}int i = 1;\nwhile (i < 3) {{ x q[i]; i += 1; }}\n").circuit

    text = to_qasm3(circuit)

    assert "while" not in text
    assert "for int i in [1:2] {" in text
    assert parse_looped_qasm3(text).circuit == circuit


def test_to_qasm3_qubit_name_avoids_loop_names() -> None:
    body = (GateTemplate(GateType.X, (LoopIndex(),)), MeasureTemplate(LoopIndex(), "q", 0))
    loop = BoundedLoop("q0", 0, 1, (ClassicalRegister("q", 1),), body, SourceSpan(1, 0, 1, 0))
    circuit = LoopedCircuit(2, (), (loop,))

    text = to_qasm3(circuit)

    assert "qubit[2] q1;" in text
    assert parse_looped_qasm3(text).circuit == circuit


# 金标准取自写回循环之前的序列化器输出（浮点格式、位条件、整寄存器条件）。
PLAIN_SOURCE = (
    'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nbit[2] c;\nrz(0.1) q[0];\n'
    "rx(-1.25e-7) q[1];\ncx q[0], q[1];\nc[1] = measure q[1];\nif (c[1] == 1) { x q[0]; }\n"
    "if (c == 2) { rz(3.141592653589793) q[1]; }\n"
)
PLAIN_GOLDEN = (
    'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nbit[2] c;\nrz(0.1) q[0];\n'
    "rx(-1.25e-07) q[1];\ncx q[0], q[1];\nc[1] = measure q[1];\nif (c[1] == 1) {\n  x q[0];\n}\n"
    "if (c == 2) {\n  rz(3.141592653589793) q[1];\n}\n"
)


def test_to_qasm3_plain_circuit_output_is_unchanged() -> None:
    assert to_qasm3(from_qasm3(PLAIN_SOURCE)) == PLAIN_GOLDEN


@pytest.mark.parametrize("injection", INJECTIONS.values(), ids=INJECTIONS.keys())
def test_loop_text_identity_equals_the_flat_text(injection: str) -> None:
    flat = from_qasm3(repetition_flat_text(injection))

    circuit, kernel_ref, digest = identity(repetition_loop_text(injection))

    # 独立 oracle：电路相等。kernel_ref 与 summary_hash 对同一电路取同一 hex，不能单独作证。
    assert [register.name for register in circuit.cregs] == ["s__0", "s__1"]
    assert circuit == flat
    assert kernel_ref == compute_kernel_ref(flat)
    assert digest == summary_hash(flat)


def test_loop_text_identity_is_identical_across_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不同哈希种子暴露随集合顺序或对象 id 变化的身份。"""
    source = repetition_loop_text("x q[2];\n")
    script = (
        "from qaiji.codec import parse_looped_qasm3\n"
        "from qaiji.core.program.validation import compute_kernel_ref\n"
        "from qaiji.core.semantics.registry import annotate_circuit\n"
        "from qaiji.core.semantics.summary import build_semantic_summary, canonical_summary_hash\n"
        f"c = parse_looped_qasm3({source!r}).circuit.expand().circuit\n"
        "s = build_semantic_summary(circuit=c, annotations=annotate_circuit(c))\n"
        "print(compute_kernel_ref(c), canonical_summary_hash(s))\n"
    )
    outputs = []
    for seed in ("1", "2"):
        monkeypatch.setenv("PYTHONHASHSEED", seed)
        outputs.append(run_fresh_process(script).strip())

    _, kernel_ref, digest = identity(source)
    assert outputs == [f"{kernel_ref} {digest}"] * 2


def test_changing_the_loop_text_upper_bound_changes_the_identity() -> None:
    two_rounds, kernel_two, digest_two = identity(repetition_loop_text("x q[0];\n", last=1))
    three_rounds, kernel_three, digest_three = identity(repetition_loop_text("x q[0];\n", last=2))

    assert len(three_rounds.gates) != len(two_rounds.gates)
    assert three_rounds == from_qasm3(repetition_flat_text("x q[0];\n", rounds=3))
    assert kernel_three != kernel_two
    assert digest_three != digest_two
