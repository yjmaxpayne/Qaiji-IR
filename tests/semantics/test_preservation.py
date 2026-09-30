# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""check_preservation 的四步裁决流水线：优先级、判定域、R1-R4、汇总。"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from factories import feedforward_circuit
from qaiji.constants import DEFAULT_TOLERANCE
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.semantics import registry
from qaiji.core.semantics.preservation import PreservationSummary, check_preservation
from qaiji.core.semantics.types import CartanRole, EquivLevel, MorphismType
from qaiji.exceptions import UnsupportedEquivLevelError

TAU = math.tau


# --- 构造期不变量 -----------------------------------------------------------


def test_preservation_summary_is_frozen() -> None:
    summary = PreservationSummary()
    with pytest.raises(FrozenInstanceError):
        summary.status = "passed"  # type: ignore[misc]


def test_preservation_summary_has_eight_fields_with_planned_defaults() -> None:
    summary = PreservationSummary()
    assert (
        summary.stage,
        summary.status,
        summary.diagnostic_count,
        summary.failed_gate_indices,
        summary.equiv_level,
        summary.original_morphism,
        summary.lowered_morphism,
        summary.pass_trace_ref,
    ) == ("unspecified_transform", "planned", 0, (), None, None, None, None)


@pytest.mark.parametrize("stage", ["canonicalize", "codec_roundtrip", "unspecified_transform"])
def test_known_stages_are_accepted(stage: str) -> None:
    PreservationSummary(stage=stage)


def test_unknown_stage_raises_value_error() -> None:
    with pytest.raises(ValueError, match="stage"):
        PreservationSummary(stage="post_transpile_pre_pulse")


def test_unknown_status_raises_value_error() -> None:
    with pytest.raises(ValueError, match="status"):
        PreservationSummary(status="skipped")


def test_failed_gate_indices_are_tuple_ized() -> None:
    summary = PreservationSummary(failed_gate_indices=[2, 3])
    assert summary.failed_gate_indices == (2, 3)


# --- 第 0 步：请求域拒绝（AC-Q7 的带类型错误那一半）------------------------


@pytest.mark.parametrize("level", [EquivLevel.UP_TO_LOCAL, EquivLevel.ENTANGLEMENT])
def test_out_of_domain_request_raises_typed_error(level: EquivLevel) -> None:
    circuit = Circuit(1)
    circuit.h(0)

    with pytest.raises(UnsupportedEquivLevelError):
        check_preservation(circuit, circuit, requested_level=level)


# --- 第 1 步：测量湮灭压过其他一切裁决（AC-Q5, I-Q4.5）---------------------


def test_deleting_the_trailing_measurement_is_failed_not_unsupported() -> None:
    """删掉两次测量中的后一次，也会让 len(gates) 不相等 —— 第 2 步会据此判为
    unsupported，但第 1 步必须赢下这场竞争（POC-3 Q8）。
    """
    register = ClassicalRegister("c", 2)
    original = Circuit(2)
    original.add_register(register)
    original.add_measure(Measure(0, ClassicalBit(register, 0)))
    original.add_measure(Measure(1, ClassicalBit(register, 1)))

    transformed = Circuit(2)
    transformed.add_register(register)
    transformed.add_measure(Measure(0, ClassicalBit(register, 0)))

    verdict = check_preservation(original, transformed)

    assert verdict.status == "failed"
    assert verdict.equiv_level is None
    assert verdict.failed_gate_indices == (1,)


def test_deleting_a_middle_measurement_locates_the_mismatch_onward() -> None:
    register = ClassicalRegister("c", 3)
    original = Circuit(3)
    original.add_register(register)
    original.add_measure(Measure(0, ClassicalBit(register, 0)))
    original.add_measure(Measure(1, ClassicalBit(register, 1)))
    original.add_measure(Measure(2, ClassicalBit(register, 2)))

    transformed = Circuit(3)
    transformed.add_register(register)
    transformed.add_measure(Measure(0, ClassicalBit(register, 0)))
    transformed.add_measure(Measure(2, ClassicalBit(register, 2)))

    verdict = check_preservation(original, transformed)

    assert verdict.status == "failed"
    assert verdict.failed_gate_indices == (1, 2)


def test_extra_measurement_in_the_transformed_circuit_is_failed_with_no_indices() -> None:
    """新增一次测量的变换同样判为 failed；此时原电路侧没有可归咎的下标，因此诊断
    集合为空（ARCH §2.3）。
    """
    original = Circuit(1)
    register = ClassicalRegister("c", 1)
    transformed = Circuit(1)
    transformed.add_register(register)
    transformed.add_measure(Measure(0, ClassicalBit(register, 0)))

    verdict = check_preservation(original, transformed)

    assert verdict.status == "failed"
    assert verdict.failed_gate_indices == ()


def test_failed_verdict_still_carries_dominant_morphism_diagnostics() -> None:
    """诊断字段在每条分支上都会输出，failed 分支也不例外。"""
    register = ClassicalRegister("c", 1)
    original = Circuit(1)
    original.add_register(register)
    original.h(0)
    original.add_measure(Measure(0, ClassicalBit(register, 0)))
    transformed = Circuit(1)
    transformed.add_register(register)
    transformed.h(0)

    verdict = check_preservation(original, transformed)

    assert verdict.status == "failed"
    assert verdict.original_morphism is MorphismType.MEASUREMENT
    assert verdict.lowered_morphism is MorphismType.UNITARY


# --- 第 2 步：判定域前置条件（P0-2 回归，unsupported）----------------------


def test_num_qubits_mismatch_is_unsupported() -> None:
    small = Circuit(2)
    small.h(0)
    large = Circuit(5)
    large.h(0)

    verdict = check_preservation(small, large)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == ()
    assert verdict.equiv_level is None


def test_cregs_mismatch_is_unsupported() -> None:
    left = Circuit(1)
    left.add_register(ClassicalRegister("c", 1))
    right = Circuit(1)
    right.add_register(ClassicalRegister("d", 1))

    verdict = check_preservation(left, right)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == ()


def test_gate_count_mismatch_is_unsupported() -> None:
    shorter = Circuit(1)
    shorter.h(0)
    longer = Circuit(1)
    longer.h(0)
    longer.x(0)

    verdict = check_preservation(shorter, longer)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == ()


def test_node_kind_mismatch_locates_the_first_offending_position() -> None:
    register = ClassicalRegister("c", 1)
    original = Circuit(1)
    original.add_register(register)
    original.h(0)
    original.add_measure(Measure(0, ClassicalBit(register, 0)))

    transformed = Circuit(1)
    transformed.add_register(register)
    transformed.add_measure(Measure(0, ClassicalBit(register, 0)))
    transformed.h(0)

    verdict = check_preservation(original, transformed)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == (0,)


# --- 第 3/4 步：R1-R4 比对规则与跨位置汇总 ----------------------------------


def test_r1_structurally_equal_circuit_pair_is_exact() -> None:
    left = Circuit(2)
    left.h(0)
    left.cx(0, 1)
    right = Circuit(2)
    right.h(0)
    right.cx(0, 1)

    verdict = check_preservation(left, right)

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.EXACT


def test_r2_cnot_cx_alias_collapse_is_exact() -> None:
    cnot = Circuit(2)
    cnot.cnot(0, 1)
    cx = Circuit(2)
    cx.cx(0, 1)

    verdict = check_preservation(cnot, cx)

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.EXACT


@pytest.mark.physics
@pytest.mark.parametrize("gate_type", [GateType.RX, GateType.RY, GateType.RZ])
def test_r3_same_axis_rotation_delta_two_pi_is_up_to_phase(gate_type: GateType) -> None:
    left = Circuit(1)
    left.add_gate(Gate(gate_type, (0,), (0.7,)))
    right = Circuit(1)
    right.add_gate(Gate(gate_type, (0,), (0.7 + TAU,)))

    verdict = check_preservation(left, right)

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.UP_TO_PHASE


@pytest.mark.physics
@pytest.mark.parametrize("gate_type", [GateType.RX, GateType.RY, GateType.RZ])
def test_r3_same_axis_rotation_delta_four_pi_is_exact(gate_type: GateType) -> None:
    left = Circuit(1)
    left.add_gate(Gate(gate_type, (0,), (0.7,)))
    right = Circuit(1)
    right.add_gate(Gate(gate_type, (0,), (0.7 + 2 * TAU,)))

    verdict = check_preservation(left, right)

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.EXACT


@pytest.mark.physics
@pytest.mark.parametrize("gate_type", [GateType.RX, GateType.RY, GateType.RZ])
def test_r4_rotation_folds_to_identity_is_up_to_phase_either_direction(
    gate_type: GateType,
) -> None:
    rotated = Circuit(1)
    rotated.add_gate(Gate(gate_type, (0,), (TAU,)))
    identity = Circuit(1)
    identity.add_gate(Gate(GateType.I, (0,)))

    forward = check_preservation(rotated, identity)
    backward = check_preservation(identity, rotated)

    assert forward.status == backward.status == "passed"
    assert forward.equiv_level is backward.equiv_level is EquivLevel.UP_TO_PHASE


def test_cross_position_odd_k_folds_cancel_to_exact() -> None:
    """AC-Q3：不同位置上两次独立的 UP_TO_PHASE 折叠会按奇偶性相消。"""
    circuit = Circuit(1)
    circuit.rz(0, TAU)
    circuit.rz(0, 3 * TAU)

    verdict = check_preservation(circuit, circuit.canonicalize())

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.EXACT


def test_body_r2_alias_collapse_is_exact() -> None:
    """评审指出的零覆盖点：Conditional 体内的 R2。"""
    register = ClassicalRegister("c", 1)
    original = Circuit(2)
    original.add_register(register)
    original.add_measure(Measure(0, ClassicalBit(register, 0)))
    original.add_conditional(Conditional(register, 1, (Gate(GateType.CNOT, (0, 1)),)))

    transformed = Circuit(2)
    transformed.add_register(register)
    transformed.add_measure(Measure(0, ClassicalBit(register, 0)))
    transformed.add_conditional(Conditional(register, 1, (Gate(GateType.CX, (0, 1)),)))

    verdict = check_preservation(original, transformed)

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.EXACT


@pytest.mark.physics
def test_body_r3_rotation_delta_is_up_to_phase() -> None:
    register = ClassicalRegister("c", 1)
    original = Circuit(2)
    original.add_register(register)
    original.add_measure(Measure(0, ClassicalBit(register, 0)))
    original.add_conditional(Conditional(register, 1, (Gate(GateType.RZ, (1,), (0.7,)),)))

    transformed = Circuit(2)
    transformed.add_register(register)
    transformed.add_measure(Measure(0, ClassicalBit(register, 0)))
    transformed.add_conditional(Conditional(register, 1, (Gate(GateType.RZ, (1,), (0.7 + TAU,)),)))

    verdict = check_preservation(original, transformed)

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.UP_TO_PHASE


@pytest.mark.physics
def test_body_r4_rotation_folds_to_identity_is_up_to_phase() -> None:
    register = ClassicalRegister("c", 1)
    original = Circuit(2)
    original.add_register(register)
    original.add_measure(Measure(0, ClassicalBit(register, 0)))
    original.add_conditional(Conditional(register, 1, (Gate(GateType.RZ, (1,), (TAU,)),)))

    transformed = Circuit(2)
    transformed.add_register(register)
    transformed.add_measure(Measure(0, ClassicalBit(register, 0)))
    transformed.add_conditional(Conditional(register, 1, (Gate(GateType.I, (1,)),)))

    verdict = check_preservation(original, transformed)

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.UP_TO_PHASE


# --- 第 3 步越界收集：反向组（I-Q4.6，AC-Q7 前半）--------------------------


def test_h_to_z_swap_is_unsupported() -> None:
    h_circuit = Circuit(1)
    h_circuit.h(0)
    z_circuit = Circuit(1)
    z_circuit.z(0)

    verdict = check_preservation(h_circuit, z_circuit)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == (0,)


def test_u3_parameter_drift_beyond_tolerance_is_unsupported() -> None:
    left = Circuit(1)
    left.u3(0, 0.1, 0.2, 0.3)
    right = Circuit(1)
    right.u3(0, 0.1, 0.2, 0.3 + 100 * DEFAULT_TOLERANCE)

    verdict = check_preservation(left, right)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == (0,)


def test_gate_reorder_is_unsupported() -> None:
    original = Circuit(2)
    original.h(0)
    original.x(1)
    reordered = Circuit(2)
    reordered.x(1)
    reordered.h(0)

    verdict = check_preservation(original, reordered)

    assert verdict.status == "unsupported"
    assert set(verdict.failed_gate_indices) == {0, 1}


def test_unsupported_collects_every_violation_not_just_the_first() -> None:
    """I-Q4.6：收集是穷尽式的，不是遇到第一处违规就短路。"""
    left = Circuit(1)
    left.h(0)
    left.h(0)
    left.h(0)
    right = Circuit(1)
    right.z(0)
    right.h(0)
    right.z(0)

    verdict = check_preservation(left, right)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == (0, 2)


def test_body_violation_is_located_at_the_parent_conditional_index() -> None:
    register = ClassicalRegister("c", 1)
    original = Circuit(2)
    original.add_register(register)
    original.add_measure(Measure(0, ClassicalBit(register, 0)))
    original.add_conditional(Conditional(register, 1, (Gate(GateType.H, (1,)),)))

    transformed = Circuit(2)
    transformed.add_register(register)
    transformed.add_measure(Measure(0, ClassicalBit(register, 0)))
    transformed.add_conditional(Conditional(register, 1, (Gate(GateType.Z, (1,)),)))

    verdict = check_preservation(original, transformed)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == (1,)


def test_measure_retarget_at_the_same_position_is_unsupported() -> None:
    """与第 1 步不同：数量是相等的（1 == 1），因此走的是第 3 步对 Measure 配对的
    相等性检查，而不是测量湮灭那条路径。
    """
    register = ClassicalRegister("c", 2)
    original = Circuit(2)
    original.add_register(register)
    original.add_measure(Measure(0, ClassicalBit(register, 0)))

    transformed = Circuit(2)
    transformed.add_register(register)
    transformed.add_measure(Measure(1, ClassicalBit(register, 0)))

    verdict = check_preservation(original, transformed)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == (0,)


def test_conditional_register_mismatch_with_matching_cregs_is_unsupported() -> None:
    """与 test_conditional_header_mismatch_is_unsupported 不同：那里是单寄存器电路
    的*取值*不同。这里两侧都按相同顺序声明了两个寄存器（因此第 2 步的 cregs 检查
    通过），唯一不同的是 Conditional 指向的那个*寄存器*。
    """
    reg_c = ClassicalRegister("c", 1)
    reg_d = ClassicalRegister("d", 1)
    original = Circuit(2)
    original.add_register(reg_c)
    original.add_register(reg_d)
    original.add_measure(Measure(0, ClassicalBit(reg_c, 0)))
    original.add_conditional(Conditional(reg_c, 1, (Gate(GateType.H, (1,)),)))

    transformed = Circuit(2)
    transformed.add_register(reg_c)
    transformed.add_register(reg_d)
    transformed.add_measure(Measure(0, ClassicalBit(reg_c, 0)))
    transformed.add_conditional(Conditional(reg_d, 1, (Gate(GateType.H, (1,)),)))

    verdict = check_preservation(original, transformed)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == (1,)


def test_conditional_body_length_mismatch_is_unsupported_not_a_crash() -> None:
    """若没有体长度守卫，对体内序列做 zip(..., strict=True) 会抛 ValueError 而不是
    返回裁决 —— check_preservation 必须始终返回一个 PreservationSummary。
    """
    register = ClassicalRegister("c", 1)
    original = Circuit(2)
    original.add_register(register)
    original.add_measure(Measure(0, ClassicalBit(register, 0)))
    original.add_conditional(
        Conditional(register, 1, (Gate(GateType.H, (1,)), Gate(GateType.X, (1,))))
    )

    transformed = Circuit(2)
    transformed.add_register(register)
    transformed.add_measure(Measure(0, ClassicalBit(register, 0)))
    transformed.add_conditional(Conditional(register, 1, (Gate(GateType.H, (1,)),)))

    verdict = check_preservation(original, transformed)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == (1,)


def test_conditional_header_mismatch_is_unsupported() -> None:
    register = ClassicalRegister("c", 1)
    original = Circuit(2)
    original.add_register(register)
    original.add_measure(Measure(0, ClassicalBit(register, 0)))
    original.add_conditional(Conditional(register, 1, (Gate(GateType.H, (1,)),)))

    transformed = Circuit(2)
    transformed.add_register(register)
    transformed.add_measure(Measure(0, ClassicalBit(register, 0)))
    transformed.add_conditional(Conditional(register, 0, (Gate(GateType.H, (1,)),)))

    verdict = check_preservation(original, transformed)

    assert verdict.status == "unsupported"
    assert verdict.failed_gate_indices == (1,)


# --- 仅接受 EXACT 的请求，以及空电路约定 ------------------------------------


def test_exact_request_on_an_odd_k_transform_is_unsupported_but_keeps_the_level() -> None:
    """新语义（§6.6-5）：判定结果为 UP_TO_PHASE，但调用方只接受 EXACT。"""
    circuit = Circuit(1)
    circuit.rz(0, TAU)

    verdict = check_preservation(circuit, circuit.canonicalize(), requested_level=EquivLevel.EXACT)

    assert verdict.status == "unsupported"
    assert verdict.equiv_level is EquivLevel.UP_TO_PHASE
    assert verdict.failed_gate_indices == ()


def test_exact_request_on_an_even_k_transform_still_passes() -> None:
    circuit = Circuit(1)
    circuit.rz(0, TAU)
    circuit.rz(0, TAU)

    verdict = check_preservation(circuit, circuit.canonicalize(), requested_level=EquivLevel.EXACT)

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.EXACT


def test_empty_circuit_pair_with_matching_spaces_is_passed_exact() -> None:
    verdict = check_preservation(Circuit(1), Circuit(1))

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.EXACT


# --- I-Q4.4：cartan 仅供参考，绝不作为裁决输入 ------------------------------


def test_mutating_the_cartan_table_does_not_change_any_verdict_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    circuit = feedforward_circuit()
    baseline = check_preservation(circuit, circuit.canonicalize(), stage="canonicalize")

    monkeypatch.setattr(registry, "_GATE_CARTAN", dict.fromkeys(GateType, CartanRole.MIXED))
    mutated = check_preservation(circuit, circuit.canonicalize(), stage="canonicalize")

    assert mutated == baseline
