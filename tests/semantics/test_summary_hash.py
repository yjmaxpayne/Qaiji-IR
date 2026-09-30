# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""规范化语义摘要 schema，及其抗碰撞的内容哈希。"""

import math
from types import MappingProxyType

import pytest

from factories import bell_circuit, feedforward_circuit
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.semantics.registry import annotate_circuit
from qaiji.core.semantics.summary import (
    GATE_COVERAGE_TOTAL,
    SUMMARY_SCHEMA_VERSION,
    build_semantic_summary,
    canonical_summary_hash,
)

EXPECTED_STABLE_KEYS = {
    "summary_schema_version",
    "status_label",
    "num_qubits",
    "cregs",
    "operations",
    "annotation_count",
    "gate_coverage",
    "morphism_counts",
    "equiv_level_counts",
    "cartan_counts",
    "measurement_handles",
    "classical_edges",
    "condition_model",
    "unitary_segment_count",
}


def _hash_of(circuit: Circuit) -> str:
    annotations = annotate_circuit(circuit)
    summary = build_semantic_summary(circuit=circuit, annotations=annotations)
    return canonical_summary_hash(summary)


# --- 碰撞反证（先于正向用例写就，P0-1）--------------------------------------


def test_h_cx_and_y_swap_have_identical_v1_keys_but_different_hash() -> None:
    """P0-1 当初抓到的正是这个回归：v1.0 只计数的键会发生碰撞。

    H 和 Y 都是 UNITARY；CX 和 SWAP 都是 PERMUTATION —— v1.0 纳入哈希的每一个键
    （morphism_counts、annotation_count、gate_coverage）在这两个电路之间都逐字相同，
    但它们结构不同，绝不能共享同一个内容哈希。把两侧都钉死到同一个字面量上（而不是
    仅仅两侧互比），还能证明这些计数不是因为双双退化而空洞地相等。
    """
    h_cx = Circuit(2)
    h_cx.h(0)
    h_cx.cx(0, 1)

    y_swap = Circuit(2)
    y_swap.y(0)
    y_swap.add_gate(Gate(GateType.SWAP, (0, 1)))

    h_cx_annotations = annotate_circuit(h_cx)
    y_swap_annotations = annotate_circuit(y_swap)
    h_cx_summary = build_semantic_summary(circuit=h_cx, annotations=h_cx_annotations)
    y_swap_summary = build_semantic_summary(circuit=y_swap, annotations=y_swap_annotations)

    expected_morphism_counts = {"UNITARY": 1, "PERMUTATION": 1}
    expected_coverage = {"covered": 2, "total_gate_types": GATE_COVERAGE_TOTAL}
    assert h_cx_summary["morphism_counts"] == expected_morphism_counts
    assert y_swap_summary["morphism_counts"] == expected_morphism_counts
    assert h_cx_summary["annotation_count"] == y_swap_summary["annotation_count"] == 2
    assert h_cx_summary["gate_coverage"] == expected_coverage
    assert y_swap_summary["gate_coverage"] == expected_coverage
    assert canonical_summary_hash(h_cx_summary) != canonical_summary_hash(y_swap_summary)


def test_annotation_count_counts_annotations_not_gates() -> None:
    """一个 Conditional 贡献一条节点标注，外加体内每个门各一条。

    只要电路里有 Conditional，annotation_count 与 len(circuit.gates) 就会分道扬镳；
    改用 len(circuit.gates) 来钉断言，等于默默接受了这种混淆。
    """
    circuit = feedforward_circuit()
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))

    assert len(circuit.gates) == 3
    assert summary["annotation_count"] == 4


def test_conditional_value_alone_changes_the_hash() -> None:
    """ADR-203 本就是为修这类碰撞而存在的，这次落在新增的那个键上。

    一份只在门级别区分 cregs/num_qubits/operations、却从不区分分支取值的摘要，会让
    if(c==0) 与 if(c==1) 碰撞 —— 与 P0-1 完全相同的失效模式，只是换了个字段。
    """
    register = ClassicalRegister("c", 1)

    branch_one = Circuit(2)
    branch_one.add_register(register)
    branch_one.add_measure(Measure(0, ClassicalBit(register, 0)))
    branch_one.add_conditional(Conditional(register, 1, (Gate(GateType.X, (1,)),)))

    branch_zero = Circuit(2)
    branch_zero.add_register(register)
    branch_zero.add_measure(Measure(0, ClassicalBit(register, 0)))
    branch_zero.add_conditional(Conditional(register, 0, (Gate(GateType.X, (1,)),)))

    assert _hash_of(branch_one) != _hash_of(branch_zero)


def test_operations_encoding_covers_measure_and_conditional_forms() -> None:
    """ARCH 中 measure/conditional 的 operations schema，否则无处钉死。"""
    circuit = feedforward_circuit()
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))

    assert summary["operations"] == [
        ["gate", "H", [0], []],
        ["measure", 0, "c", 0],
        ["conditional", "c", 1, [["X", [1], []]]],
    ]


def test_measurement_handles_and_classical_edges_are_dicts_with_named_fields() -> None:
    """dataflow.py -> summary.py 这道边界必须保持为 JSON 安全的 dict。

    静默退化成按位置编码（例如 dataclasses.astuple）会改变传输 schema，而没有任何
    测试会察觉。
    """
    circuit = feedforward_circuit()
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))

    assert summary["measurement_handles"] == [
        {
            "measurement_id": "m0",
            "qubit_index": 0,
            "creg_name": "c",
            "creg_index": 0,
            "source": "measure_node",
        }
    ]
    assert summary["classical_edges"] == [
        {"source_handle": "m0", "target": "cond2", "edge_kind": "measurement_to_condition"}
    ]


def test_int_and_equal_float_gate_params_hash_the_same() -> None:
    """repr(param) 必须先强转 float（身份取决于比特层面，而非类型层面）。

    Gate.__post_init__ 只把 params 元组化而不强制转 float，于是手工构造的
    Gate(RZ, (0,), (0,)) 与 Gate(RZ, (0,), (0.0,)) 在 dataclass 意义上相等 —— 它们
    必须哈希到同一个值，而不能因 repr(int) 与 repr(float) 的差异而分叉。
    """
    int_param = Circuit(1)
    int_param.add_gate(Gate(GateType.RZ, (0,), (0,)))
    float_param = Circuit(1)
    float_param.add_gate(Gate(GateType.RZ, (0,), (0.0,)))

    assert _hash_of(int_param) == _hash_of(float_param)


def test_gate_coverage_total_is_pinned_and_tracks_gatetype() -> None:
    """任何一侧发生改动，都必须同时递增 SUMMARY_SCHEMA_VERSION（ARCH §2.5）。"""
    assert GATE_COVERAGE_TOTAL == 19
    assert GATE_COVERAGE_TOTAL == len(GateType)


def test_same_gates_on_different_qubit_counts_produce_different_hash() -> None:
    small = Circuit(2)
    small.h(0)
    large = Circuit(5)
    large.h(0)

    assert _hash_of(small) != _hash_of(large)


def test_cregs_declaration_order_changes_the_hash() -> None:
    """cregs 是判别性键：声明顺序是身份的一部分。"""
    reg_a = ClassicalRegister("a", 1)
    reg_b = ClassicalRegister("b", 1)

    a_then_b = Circuit(1)
    a_then_b.add_register(reg_a)
    a_then_b.add_register(reg_b)
    a_then_b.h(0)

    b_then_a = Circuit(1)
    b_then_a.add_register(reg_b)
    b_then_a.add_register(reg_a)
    b_then_a.h(0)

    assert _hash_of(a_then_b) != _hash_of(b_then_a)


def test_cnot_vs_cx_operations_differ_and_hash_differs() -> None:
    """canonicalize 前后哈希不同是正确的（ARCH §2.2）：

    CNOT 与 CX 是 UP_TO_PHASE 等价的别名，而不是同一种结构。
    """
    cnot = Circuit(2)
    cnot.cnot(0, 1)
    cx = Circuit(2)
    cx.cx(0, 1)

    cnot_annotations = annotate_circuit(cnot)
    cx_annotations = annotate_circuit(cx)
    cnot_summary = build_semantic_summary(circuit=cnot, annotations=cnot_annotations)
    cx_summary = build_semantic_summary(circuit=cx, annotations=cx_annotations)

    assert cnot_summary["operations"] != cx_summary["operations"]
    assert canonical_summary_hash(cnot_summary) != canonical_summary_hash(cx_summary)


# --- 稳定键集合（键漂移必须表现为键名差异，而不是计数差异）-------------------


def test_stable_key_set_is_exactly_the_frozen_fourteen() -> None:
    circuit = bell_circuit()
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))

    assert len(EXPECTED_STABLE_KEYS) == 14
    assert set(summary) == EXPECTED_STABLE_KEYS


def test_optional_keys_are_absent_by_default_and_present_when_given() -> None:
    circuit = Circuit(1)
    circuit.h(0)
    annotations = annotate_circuit(circuit)

    bare = build_semantic_summary(circuit=circuit, annotations=annotations)
    assert "source_language" not in bare
    assert "preservation" not in bare

    decorated = build_semantic_summary(
        circuit=circuit,
        annotations=annotations,
        source_language="openqasm3",
        preservation={"status": "passed"},
    )
    assert decorated["source_language"] == "openqasm3"
    assert decorated["preservation"] == {"status": "passed"}


def test_empty_circuit_emits_empty_containers_and_null_condition_model() -> None:
    circuit = Circuit(1)
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))

    assert summary["cregs"] == []
    assert summary["operations"] == []
    assert summary["annotation_count"] == 0
    assert summary["gate_coverage"] == {"covered": 0, "total_gate_types": GATE_COVERAGE_TOTAL}
    assert summary["morphism_counts"] == {}
    assert summary["equiv_level_counts"] == {}
    assert summary["cartan_counts"] == {}
    assert summary["measurement_handles"] == []
    assert summary["classical_edges"] == []
    assert summary["condition_model"] is None
    assert summary["unitary_segment_count"] == 1


def test_summary_schema_version_is_the_frozen_literal() -> None:
    assert SUMMARY_SCHEMA_VERSION == "qaiji.semantic_summary.v0"

    circuit = Circuit(1)
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))
    assert summary["summary_schema_version"] == "qaiji.semantic_summary.v0"


def test_operations_encoding_rejects_a_node_type_outside_the_domain() -> None:
    """畸形电路必须大声失败，而不是静默丢弃那个出问题的节点。"""
    circuit = Circuit(1)
    circuit.gates.append(object())  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="Cannot encode"):
        build_semantic_summary(circuit=circuit, annotations=())


def test_gate_coverage_counts_distinct_types_including_conditional_body() -> None:
    register = ClassicalRegister("c", 1)
    circuit = Circuit(2)
    circuit.add_register(register)
    circuit.h(0)
    circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
    circuit.add_conditional(Conditional(register, 1, (Gate(GateType.X, (1,)),)))

    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))

    assert summary["gate_coverage"] == {"covered": 2, "total_gate_types": GATE_COVERAGE_TOTAL}


def test_gate_params_are_encoded_as_shortest_round_trip_repr() -> None:
    """在 CPython 中 str(float) 与 repr(float) 一致，因此把它改成裸 `str(param)`
    属于语义等价的变异，不是缺陷 —— 本测试钉死的是"必须是字符串，而不是裸 JSON
    数字"（裸浮点会破坏 ARCH §2.2 承诺的往返免疫性），以及 repr() 对一个没有短
    十进制表示的值所产出的那串精确数字。
    """
    third = 1 / 3
    circuit = Circuit(1)
    circuit.u3(0, 0.1, 0.0, third)

    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))

    assert summary["operations"] == [["gate", "U3", [0], ["0.1", "0.0", repr(third)]]]


# --- canonical_summary_hash 作为独立函数（POC-2）-----------------------------


def test_hash_is_idempotent_for_the_same_summary() -> None:
    circuit = bell_circuit()
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))

    assert canonical_summary_hash(summary) == canonical_summary_hash(summary)


def test_hash_rejects_nan_and_infinite_floats() -> None:
    with pytest.raises(ValueError):
        canonical_summary_hash({"x": math.nan})
    with pytest.raises(ValueError):
        canonical_summary_hash({"x": math.inf})


def test_hash_rejects_non_json_compatible_values() -> None:
    with pytest.raises(TypeError):
        canonical_summary_hash({"x": object()})


def test_frozen_mappingproxy_tree_hashes_identically_to_the_plain_dict() -> None:
    """default=_jsonify（Mapping -> dict）必须让冻结树与普通树给出一致结果。

    AC-Q9 依赖于 canonical_summary_hash(handle.summary) 与冻结前的重算结果相符；
    这里用手工构造的 proxy 树做机制层面的证明（真实 freeze_summary 输出由下方的
    test_freeze_summary_output_hashes_identically_to_the_plain_dict 验证）。
    """
    plain = {"a": 1, "b": {"c": [1, 2, 3], "d": None}}
    frozen = MappingProxyType({"a": 1, "b": MappingProxyType({"c": (1, 2, 3), "d": None})})

    assert canonical_summary_hash(plain) == canonical_summary_hash(frozen)


def test_freeze_summary_output_hashes_identically_to_the_plain_dict() -> None:
    """AC-Q9 的机制，这次针对真实的 freeze_summary（T3.4）验证，而不是手工构造的
    proxy 树。
    """
    from qaiji.core.semantics.handle import freeze_summary

    circuit = feedforward_circuit()
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))

    assert canonical_summary_hash(freeze_summary(summary)) == canonical_summary_hash(summary)
