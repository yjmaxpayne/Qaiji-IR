# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""一等公民的测量/条件数据流读取，以及声明式的边。"""

import dataclasses

from factories import feedforward_circuit
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.semantics.dataflow import ClassicalEdge, MeasurementHandle, build_dataflow_summary


def test_feedforward_circuit_produces_one_handle_and_one_edge() -> None:
    summary = build_dataflow_summary(feedforward_circuit())

    assert summary["measurement_handles"] == (
        MeasurementHandle(measurement_id="m0", qubit_index=0, creg_name="c", creg_index=0),
    )
    assert summary["classical_edges"] == (ClassicalEdge(source_handle="m0", target="cond2"),)
    assert summary["condition_model"] == "REGISTER_ALU"
    assert summary["unitary_segment_count"] == 2


def test_measurement_id_is_deterministic_across_two_builds() -> None:
    """同一个电路、两次独立构建，必须逐字节一致。

    build_dataflow_summary 会（经由 summary.py）喂给规范化哈希；一套依赖迭代顺序
    或对象身份的编号，会让"regime identity"承诺（AC-Q2）不成立。
    """
    circuit = feedforward_circuit()

    first = build_dataflow_summary(circuit)
    second = build_dataflow_summary(circuit)

    assert first["measurement_handles"] == second["measurement_handles"]
    assert first["classical_edges"] == second["classical_edges"]


def test_conditional_preceding_its_measurement_still_connects() -> None:
    """边表达的是声明式数据流，不是因果证明（ARCH §2.2）。

    调度与因果属于 L2 调度层的议题；即便某个 Conditional 在门序中排在与之匹配的 Measure
    之前，也依然必须产生一条边。
    """
    register = ClassicalRegister("c", 1)
    circuit = Circuit(2)
    circuit.add_register(register)
    circuit.add_conditional(Conditional(register, 1, (Gate(GateType.X, (1,)),)))
    circuit.add_measure(Measure(0, ClassicalBit(register, 0)))

    summary = build_dataflow_summary(circuit)

    assert summary["classical_edges"] == (ClassicalEdge(source_handle="m0", target="cond0"),)


def test_register_level_conditional_connects_every_matching_handle() -> None:
    """寄存器级条件读取的是整个寄存器，而不是某一个比特。"""
    register = ClassicalRegister("c", 2)
    circuit = Circuit(2)
    circuit.add_register(register)
    circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
    circuit.add_measure(Measure(1, ClassicalBit(register, 1)))
    circuit.add_conditional(Conditional(register, 3, (Gate(GateType.X, (0,)),)))

    summary = build_dataflow_summary(circuit)

    assert summary["classical_edges"] == (
        ClassicalEdge(source_handle="m0", target="cond2"),
        ClassicalEdge(source_handle="m1", target="cond2"),
    )


def test_conditional_does_not_connect_to_a_different_register() -> None:
    """creg_name 匹配就是规则的全部；删掉它会导致所有东西都被连起来。"""
    register_a = ClassicalRegister("a", 1)
    register_b = ClassicalRegister("b", 1)
    circuit = Circuit(2)
    circuit.add_register(register_a)
    circuit.add_register(register_b)
    circuit.add_measure(Measure(0, ClassicalBit(register_a, 0)))
    circuit.add_conditional(Conditional(register_b, 1, (Gate(GateType.X, (1,)),)))

    summary = build_dataflow_summary(circuit)

    assert summary["classical_edges"] == ()


def test_conditional_connects_only_the_matching_register_among_several() -> None:
    register_a = ClassicalRegister("a", 1)
    register_b = ClassicalRegister("b", 1)
    circuit = Circuit(2)
    circuit.add_register(register_a)
    circuit.add_register(register_b)
    circuit.add_measure(Measure(0, ClassicalBit(register_a, 0)))
    circuit.add_measure(Measure(1, ClassicalBit(register_b, 0)))
    circuit.add_conditional(Conditional(register_b, 1, (Gate(GateType.X, (0,)),)))

    summary = build_dataflow_summary(circuit)

    assert summary["classical_edges"] == (ClassicalEdge(source_handle="m1", target="cond2"),)


def test_handle_and_edge_literal_defaults_are_pinned() -> None:
    """传输格式的默认值是哈希输入（ARCH 字面量表）。

    把字段值与一个裸字符串字面量相比 —— 而不是与另一个默认构造出来的对象相比 ——
    才能真正抓到漂移的默认值，因为这样两边不会一起漂。
    """
    summary = build_dataflow_summary(feedforward_circuit())

    (handle,) = summary["measurement_handles"]
    assert handle.source == "measure_node"

    (edge,) = summary["classical_edges"]
    assert edge.edge_kind == "measurement_to_condition"


def test_no_measure_yields_a_single_unitary_segment() -> None:
    circuit = Circuit(1)
    circuit.h(0)

    summary = build_dataflow_summary(circuit)

    assert summary["unitary_segment_count"] == 1
    assert summary["measurement_handles"] == ()
    assert summary["classical_edges"] == ()


def test_condition_model_is_explicit_none_without_a_conditional() -> None:
    """该键无条件输出，哪怕根本无话可说。"""
    circuit = Circuit(1)
    circuit.h(0)

    summary = build_dataflow_summary(circuit)

    assert "condition_model" in summary
    assert summary["condition_model"] is None


def test_handle_id_naming_does_not_reappear() -> None:
    """上游的字段名 handle_id 不得回流进来（ARCH P2-3）。

    它会在语义上与 SemanticIRHandle.handle_id 相撞。
    """
    field_names = {field.name for field in dataclasses.fields(MeasurementHandle)}

    assert "handle_id" not in field_names
    assert "measurement_id" in field_names
