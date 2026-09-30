# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""端到端语义枢轴：QASM3 -> 标注 -> 摘要 -> 哈希 -> 句柄 -> 裁决。

之所以标记为 integration，是因为这里是 semantics 与 codec 唯一相遇的地方；
core/semantics 自身绝不导入 codec 包（I-Q4.1）—— 本测试模块是从两者之外把整条
流水线拼装起来的。
"""

import math

import pytest

from factories import bell_circuit, feedforward_circuit, ghz_circuit
from qaiji.codec.qasm3 import from_qasm3, to_qasm3
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.semantics.handle import HandleStatus, SemanticIRHandle
from qaiji.core.semantics.preservation import check_preservation
from qaiji.core.semantics.registry import annotate_circuit
from qaiji.core.semantics.summary import build_semantic_summary, canonical_summary_hash
from qaiji.core.semantics.types import EquivLevel

pytestmark = pytest.mark.integration

TAU = math.tau


def alias_circuit() -> Circuit:
    """一个唯一的 Sprint-3 别名触发点是 CNOT 的电路。

    三个黄金工厂用的全是 CX，因此 CANONICAL_ALIASES 中唯一的 CNOT->CX 别名条目在
    本测试模块里本来永远不会被触发 —— AC-Q3 的"别名不改变语义"这一主张，需要一个
    真正走到该路径的电路。
    """
    circuit = Circuit(2)
    circuit.add_gate(Gate(GateType.CNOT, (0, 1)))
    return circuit


def _pivot(circuit: Circuit, *, source_language: str | None = None) -> SemanticIRHandle:
    annotations = annotate_circuit(circuit)
    summary = build_semantic_summary(
        circuit=circuit, annotations=annotations, source_language=source_language
    )
    digest = canonical_summary_hash(summary)
    return SemanticIRHandle(
        handle_id=digest,
        producer="qaiji.core.semantics",
        summary=summary,
        content_hash=digest,
        status=HandleStatus.AVAILABLE,
    )


@pytest.mark.parametrize(
    "factory", [bell_circuit, ghz_circuit, feedforward_circuit], ids=("bell", "ghz", "feedforward")
)
def test_golden_circuit_pivot_produces_a_hash_consistent_handle(factory) -> None:
    circuit = from_qasm3(to_qasm3(factory()))

    handle = _pivot(circuit, source_language="openqasm3")

    assert handle.status is HandleStatus.AVAILABLE
    assert handle.handle_id == handle.content_hash
    assert canonical_summary_hash(handle.summary) == handle.content_hash
    assert handle.summary["source_language"] == "openqasm3"
    # 保持性在哈希之后才判定，绝不折进哈希里（ARCH §2.4）。
    assert "preservation" not in handle.summary


def test_alias_canonicalize_passes_exact_but_changes_the_hash() -> None:
    """ARCH §2.2：CNOT/CX 是 UP_TO_PHASE 等价的别名，而不是同一种结构。"""
    circuit = alias_circuit()
    canonical = circuit.canonicalize()

    verdict = check_preservation(circuit, canonical, stage="canonicalize")

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.EXACT
    original_hash = canonical_summary_hash(
        build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))
    )
    canonical_hash = canonical_summary_hash(
        build_semantic_summary(circuit=canonical, annotations=annotate_circuit(canonical))
    )
    assert original_hash != canonical_hash


def test_top_level_rz_tau_canonicalize_is_up_to_phase() -> None:
    circuit = Circuit(1)
    circuit.rz(0, TAU)

    verdict = check_preservation(circuit, circuit.canonicalize(), stage="canonicalize")

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.UP_TO_PHASE


def test_body_rz_tau_canonicalize_is_up_to_phase() -> None:
    register = ClassicalRegister("c", 1)
    circuit = Circuit(2)
    circuit.add_register(register)
    circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
    circuit.add_conditional(Conditional(register, 1, (Gate(GateType.RZ, (1,), (TAU,)),)))

    verdict = check_preservation(circuit, circuit.canonicalize(), stage="canonicalize")

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.UP_TO_PHASE


def test_two_independent_odd_k_folds_aggregate_to_exact() -> None:
    circuit = Circuit(1)
    circuit.rz(0, TAU)
    circuit.rz(0, 3 * TAU)

    verdict = check_preservation(circuit, circuit.canonicalize(), stage="canonicalize")

    assert verdict.status == "passed"
    assert verdict.equiv_level is EquivLevel.EXACT
