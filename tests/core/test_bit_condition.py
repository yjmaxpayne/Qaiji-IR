# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""位级条件 ``Conditional.bit_index``：校验、归一、摘要、等价与依赖边。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from _pulse_fixtures import config
from factories import bell_circuit, feedforward_circuit
from qaiji.codec import from_qasm3, to_qasm3
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.native.api import lower_to_native
from qaiji.core.native.jsonio import from_json, to_json
from qaiji.core.native.source import _capture_source
from qaiji.core.semantics.dataflow import build_dataflow_summary
from qaiji.core.semantics.preservation import check_preservation
from qaiji.core.semantics.registry import annotate_circuit
from qaiji.core.semantics.summary import build_semantic_summary, canonical_summary_hash

BODY = (Gate(GateType.X, (0,)),)
ROOT = Path(__file__).resolve().parents[2]


def measured(width: int, *conditionals: tuple[int, int | None]) -> Circuit:
    """测量 ``width`` 位寄存器 ``s`` 的全部比特，再追加给定的 ``(value, bit_index)`` 条件。"""
    register = ClassicalRegister("s", width)
    circuit = Circuit(width)
    circuit.add_register(register)
    for bit in range(width):
        circuit.add_measure(Measure(bit, ClassicalBit(register, bit)))
    for value, bit_index in conditionals:
        circuit.add_conditional(Conditional(register, value, BODY, bit_index=bit_index))
    return circuit


def summary_hash(circuit: Circuit) -> str:
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))
    return canonical_summary_hash(summary)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.parametrize(("width", "bit_index"), [(3, 3), (2, 2), (1, 1), (3, -1)])
def test_bit_index_outside_register_is_rejected(width, bit_index):
    with pytest.raises(ValueError, match="bit index"):
        Conditional(ClassicalRegister("s", width), 1, BODY, bit_index=bit_index)


@pytest.mark.parametrize("value", [2, 3])
def test_bit_condition_value_must_be_a_single_bit(value):
    # 宽 3 寄存器上 value=2、3 本可放进寄存器；位级条件只允许 0 或 1。
    with pytest.raises(ValueError, match="0 or 1"):
        Conditional(ClassicalRegister("s", 3), value, BODY, bit_index=1)


def test_single_bit_register_normalizes_bit_zero_to_whole_register():
    register = ClassicalRegister("c", 1)
    indexed = Conditional(register, 1, BODY, bit_index=0)
    assert indexed.bit_index is None
    assert indexed == Conditional(register, 1, BODY)


def test_multi_bit_register_keeps_bit_zero():
    register = ClassicalRegister("s", 2)
    assert Conditional(register, 1, BODY, bit_index=0).bit_index == 0
    assert Conditional(register, 1, BODY, bit_index=0) != Conditional(register, 1, BODY)


def test_summary_hash_distinguishes_bit_conditions():
    hashes = {summary_hash(measured(3, c)) for c in [(1, 1), (1, 2), (1, None), (0, 2)]}
    assert len(hashes) == 4


# 改动前（基于 bd5e227）冻结的存量身份。位级条件的引入不得改变它们。
LEGACY_QASM = {
    "bit1_index": "OPENQASM 3.0;\nqubit[2] q;\nbit[1] c;\nh q[0];\n"
    "c[0] = measure q[0];\nif (c[0] == 1) { x q[1]; }\n",
    "bit2_whole": "OPENQASM 3.0;\nqubit[3] q;\nbit[2] s;\nh q[0];\nh q[1];\n"
    "s[0] = measure q[0];\ns[1] = measure q[1];\nif (s == 2) { x q[2]; }\n",
    "bit3_whole": "OPENQASM 3.0;\nqubit[3] q;\nbit[3] r;\n"
    "r[0] = measure q[0];\nr[1] = measure q[1];\nr[2] = measure q[2];\n"
    "if (r == 5) { x q[0]; }\n",
}
LEGACY_SUMMARY = {
    "bit1_index": "82687501ff4b7e29c24778be0577d11d4b1a6c194df2f9041158e4fa589eae2d",
    "bit2_whole": "324973fb0d2b0ba782c42d18480fecfe0647e613f2b322cecb78fde857946562",
    "bit3_whole": "429aa05923528a434ade605427b8281f8b642a825a7a4d3a034434379e66f5a5",
}
LEGACY_QASM3_SHA = {
    "bit1_index": "627c72edda8db89944600bb3c0bc50d5a6b98ef140309d9bb7dfa2ca71c89eb2",
    "bit2_whole": "0efc8f16b70623c4afa9c383423d30e14308673c8ba222cfe0d1f25771f5011f",
    "bit3_whole": "f300a9c56259404aba634744be2a62e9ef5e604d800aef048875b0e4836e2a38",
}


def test_legacy_identity_is_frozen():
    for name, text in LEGACY_QASM.items():
        circuit = from_qasm3(text)
        assert summary_hash(circuit) == "sha256:" + LEGACY_SUMMARY[name], name
        assert sha(to_qasm3(circuit)) == LEGACY_QASM3_SHA[name], name
    assert summary_hash(feedforward_circuit()) == "sha256:" + LEGACY_SUMMARY["bit1_index"]
    assert summary_hash(bell_circuit()).startswith("sha256:afe9bc2f")
    native = lower_to_native(from_qasm3(LEGACY_QASM["bit1_index"]), config())
    assert sha(to_json(native)) == (
        "e34225e817fe573f26c3c22a29ce5eb053995de165f16da2bb50d1463c2aaa30"
    )
    conformance = (ROOT / "tests/conformance/data/native.json").read_text()
    assert sha(to_json(from_json(conformance))) == (
        "a45099faad7889965adb9dfba64b229dff8c0f87e73322463b9ede8ffbb055a6"
    )


def test_node_equality_and_canonicalize_keep_bit_index():
    left, right = measured(3, (1, 1)), measured(3, (1, 2))
    assert left != right
    assert left.canonicalize().gates[-1].bit_index == 1
    assert right.canonicalize() == right


def test_preservation_flags_changed_bit_index():
    summary = check_preservation(measured(2, (1, 0)), measured(2, (1, 1)))
    # 逐位置违例按既有约定汇总为 unsupported，并列出违例位置。
    assert summary.status == "unsupported"
    assert summary.failed_gate_indices == (2,)
    assert check_preservation(measured(2, (1, 1)), measured(2, (1, 1))).status == "passed"


def test_dataflow_links_only_the_tested_bit():
    dataflow = build_dataflow_summary(measured(3, (0, 2), (1, None)))
    edges = {(edge.source_handle, edge.target) for edge in dataflow["classical_edges"]}
    whole = {(f"m{bit}", "cond4") for bit in range(3)}
    assert edges == {("m2", "cond3")} | whole


def test_source_snapshot_keeps_bit_index():
    assert _capture_source(measured(3, (0, 1))).gates[-1].bit_index == 1
