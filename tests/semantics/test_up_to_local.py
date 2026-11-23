# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""check_preservation 按 region 判定 UP_TO_LOCAL：入口判定表、结构前提、实例与上限、残差。"""

from __future__ import annotations

import math

import pytest

import qaiji.core.semantics.preservation as preservation
from factories import CORRECTED_TWO_ROUND_CODE, LOOP_WITH_CONDITIONAL
from qaiji.codec import from_qasm3, parse_looped_qasm3
from qaiji.core.circuit import Circuit
from qaiji.core.semantics.preservation import check_preservation
from qaiji.core.semantics.region import regions_of
from qaiji.core.semantics.types import EquivLevel
from qaiji.exceptions import LoopNotExpandedError, UnsupportedEquivLevelError

LOCAL = EquivLevel.UP_TO_LOCAL
FLAT_LEVELS = [EquivLevel.EXACT, EquivLevel.UP_TO_PHASE]
HEADER = 'OPENQASM 3.0;\ninclude "stdgates.inc";\n'

# 酉 U 与局域门；局域门取非对角的一般单比特门。
U = "h q[0]; cz q[0], q[1]; rx(0.3) q[1];"
LOCALS = "u3(0.4, 0.1, 0.7) q[0]; u3(1.1, 0.2, 0.9) q[1];"
CX = "cx q[0], q[1];"
FOUR = "h q[0]; cz q[0], q[1]; cz q[1], q[2]; cz q[2], q[3]; rx(0.2) q[3];"
FOUR_LOCAL = " ".join(f"u3({0.3 + qubit!r}, 0.2, 0.5) q[{qubit}];" for qubit in range(4))


def _zz(delta: float) -> str:
    """exp(-i delta Z⊗Z)，写成 CX、RZ(2 delta)、CX。"""
    return f"cx q[0], q[1]; rz({2 * delta!r}) q[1]; cx q[0], q[1];"


def _looped(num_qubits: int, body: str, *, stop: int = 0, before: str = "", after: str = ""):
    """一个循环位于 ``before`` 之后；``stop = 0`` 时迭代 1 次，``stop = -1`` 时迭代 0 次。"""
    text = f"{HEADER}qubit[{num_qubits}] q;\n{before}for int i in [0:{stop}] {{ {body} }}\n{after}"
    return parse_looped_qasm3(text).circuit


def _conditional_text(body: str, value: int = 1) -> str:
    """顶层条件体位于位置 1（前面是 1 个测量）。"""
    return (
        f"{HEADER}qubit[2] q;\nbit[1] c;\nc[0] = measure q[0];\nif (c[0] == {value}) {{ {body} }}\n"
    )


def _flat_conditional(body: str, value: int = 1) -> Circuit:
    return from_qasm3(_conditional_text(body, value))


def _judge(original, transformed, region, level=LOCAL):
    """返回 (status, equiv_level)；只有 passed 带等级。"""
    summary = check_preservation(original, transformed, requested_level=level, region=region)
    return summary.status, summary.equiv_level if summary.status == "passed" else None


PASSED_LOCAL = ("passed", LOCAL)
PASSED_EXACT = ("passed", EquivLevel.EXACT)
FAILED = ("failed", None)
UNSUPPORTED = ("unsupported", None)


def _flat_pair():
    return _flat_conditional("h q[1];"), _flat_conditional("h q[1];"), "if:1"


def _looped_pair():
    return _looped(1, "h q[0];"), _looped(1, "h q[0];"), "loop:0"


# --- 入口判定表 -------------------------------------------------------------


@pytest.mark.parametrize("make_pair", [_flat_pair, _looped_pair], ids=["flat", "looped"])
@pytest.mark.parametrize("with_region", [False, True], ids=["no_region", "region"])
def test_entanglement_raises_for_any_region_and_input(make_pair, with_region) -> None:
    """ENTANGLEMENT 在任何 region 与输入下都抛错，先于循环输入的拒绝。"""
    original, transformed, region = make_pair()
    kwargs = {"region": region} if with_region else {}

    with pytest.raises(UnsupportedEquivLevelError):
        check_preservation(original, transformed, requested_level=EquivLevel.ENTANGLEMENT, **kwargs)


@pytest.mark.parametrize("level", FLAT_LEVELS)
@pytest.mark.parametrize("explicit_none", [False, True], ids=["omitted", "explicit_none"])
def test_flat_levels_without_region_keep_the_existing_pipeline(level, explicit_none) -> None:
    """无 region 时两个平坦电路走现有流水线，结果不变。"""
    circuit = Circuit(2)
    circuit.h(0)
    circuit.cz(0, 1)
    kwargs = {"region": None} if explicit_none else {}

    summary = check_preservation(circuit, circuit, requested_level=level, **kwargs)

    assert (summary.status, summary.equiv_level) == PASSED_EXACT


@pytest.mark.parametrize("level", FLAT_LEVELS)
@pytest.mark.parametrize("looped_side", ["original", "transformed"])
def test_flat_levels_without_region_reject_looped_input(level, looped_side) -> None:
    """无 region 时循环输入仍须先展开。"""
    looped = _looped(1, "h q[0];")
    flat = Circuit(1)
    flat.h(0)
    pair = (looped, flat) if looped_side == "original" else (flat, looped)

    with pytest.raises(LoopNotExpandedError):
        check_preservation(*pair, requested_level=level)


@pytest.mark.parametrize("level", FLAT_LEVELS)
@pytest.mark.parametrize("make_pair", [_flat_pair, _looped_pair], ids=["flat", "looped"])
def test_flat_levels_with_region_are_unsupported(level, make_pair) -> None:
    """EXACT 与 UP_TO_PHASE 不按 region 判定；循环输入也不抛展开错误。"""
    original, transformed, region = make_pair()
    assert _judge(original, transformed, region, level) == UNSUPPORTED


@pytest.mark.parametrize("make_pair", [_flat_pair, _looped_pair], ids=["flat", "looped"])
def test_local_level_without_region_is_unsupported(make_pair) -> None:
    """UP_TO_LOCAL 不给 region 时不判定，循环输入也不抛展开错误。"""
    original, transformed, _ = make_pair()
    assert _judge(original, transformed, None) == UNSUPPORTED


@pytest.mark.parametrize("flat_side", ["original", "transformed"])
def test_local_level_with_mixed_input_types_is_unsupported(flat_side) -> None:
    """同一文本的平坦解析与循环解析结构相同，但类型不同，不判定。"""
    flat = _flat_conditional("h q[1];")
    looped = parse_looped_qasm3(_conditional_text("h q[1]; t q[1];")).circuit
    assert [r.id for r in regions_of(flat)] == [r.id for r in regions_of(looped)] == ["if:1"]
    pair = (flat, looped) if flat_side == "original" else (looped, flat)

    assert _judge(*pair, "if:1") == UNSUPPORTED


def test_local_limits_are_public_constants() -> None:
    assert preservation.MAX_LOCAL_QUBITS == 6
    assert preservation.MAX_LOCAL_GATES == 256
    assert preservation.MAX_LOCAL_RESIDUAL == 1e-10


# --- 单次迭代循环体上的残差判定 --------------------------------------------


@pytest.mark.parametrize(
    ("num_qubits", "before", "after", "expected"),
    [
        pytest.param(2, U, f"{U} rz(0.7) q[0];", PASSED_LOCAL, id="rz_output"),
        pytest.param(2, U, f"{U} {LOCALS}", PASSED_LOCAL, id="general_local"),
        pytest.param(2, CX, f"t q[0]; {CX}", PASSED_LOCAL, id="t_on_control_input"),
        pytest.param(4, FOUR, f"{FOUR} {FOUR_LOCAL}", PASSED_LOCAL, id="four_qubit_local"),
        pytest.param(2, U, f"{U} cz q[0], q[1];", FAILED, id="extra_cz"),
        pytest.param(3, "h q[0];", "h q[0]; cz q[1], q[2];", FAILED, id="cz_on_two_of_three"),
        pytest.param(2, CX, f"t q[1]; {CX}", FAILED, id="t_on_target_input"),
        pytest.param(2, U, U, PASSED_EXACT, id="same_body"),
        pytest.param(
            2,
            U,
            f"{U} rz({math.tau!r}) q[0];",
            ("passed", EquivLevel.UP_TO_PHASE),
            id="global_phase",
        ),
        pytest.param(2, U, f"{U} {LOCALS} {_zz(1e-11)}", PASSED_LOCAL, id="zz_1e-11"),
        pytest.param(2, U, f"{U} {LOCALS} {_zz(1e-9)}", FAILED, id="zz_1e-9"),
    ],
)
def test_local_verdicts_on_a_single_iteration_body(num_qubits, before, after, expected) -> None:
    """单向判定 W = U_after·U_before†，逐个单比特切分查局域性。

    目标比特输入侧的 T 只能在两侧各补局域门时吸收，单向判定须判失败；
    多出的 CZ 幅值与单位阵相同；3 比特的 I⊗CZ 在比特 0 的切分上可分；
    δ = 1e-9 的保真度损失只有 δ² 量级。
    """
    original = _looped(num_qubits, before)
    transformed = _looped(num_qubits, after)
    assert len(original.operations[0].values) == 1

    assert _judge(original, transformed, "loop:0") == expected


def test_local_level_on_flat_top_level_conditional() -> None:
    """顶层条件体只有 1 个实例；平坦电路也能按 region 判定。"""
    original = _flat_conditional("h q[1]; cz q[0], q[1];")
    transformed = _flat_conditional("h q[1]; cz q[0], q[1]; t q[0];")
    assert _judge(original, transformed, "if:1") == PASSED_LOCAL


# --- 结构前提 ---------------------------------------------------------------


def _two_round_code(text: str = CORRECTED_TWO_ROUND_CODE):
    return parse_looped_qasm3(text).circuit


def _two_round_code_with_extra_z():
    """第 2 个条件体（循环体位置 11）多 1 个 Z；其余节点不变。"""
    text = CORRECTED_TWO_ROUND_CODE.replace(
        "if (s == 1) { x q[1]; }", "if (s == 1) { x q[1]; z q[1]; }"
    )
    assert text != CORRECTED_TWO_ROUND_CODE
    return _two_round_code(text)


def test_two_round_code_loop_body_is_unsupported() -> None:
    """循环体含测量与条件节点，两侧相同也不判定。"""
    circuit = _two_round_code()
    assert _judge(circuit, circuit, "loop:1") == UNSUPPORTED


def test_two_round_code_conditional_body_is_decidable() -> None:
    """目标是第 2 个条件体，标识与 regions_of 下标不同。"""
    original = _two_round_code()
    transformed = _two_round_code_with_extra_z()
    ids = [region.id for region in regions_of(original)]
    assert ids.index("loop:1/if:11") == 2

    assert _judge(original, transformed, "loop:1/if:11") == PASSED_LOCAL


def test_difference_outside_the_target_region_is_unsupported() -> None:
    """差异在位置 11 的条件体内，目标是位置 10 的条件体。"""
    original = _two_round_code()
    transformed = _two_round_code_with_extra_z()
    assert _judge(original, transformed, "loop:1/if:10") == UNSUPPORTED


def test_loop_body_with_conditional_is_unsupported() -> None:
    """循环体只含条件节点、不含测量，也不判定。"""
    circuit = parse_looped_qasm3(LOOP_WITH_CONDITIONAL.format(stop=1)).circuit
    assert _judge(circuit, circuit, "loop:1") == UNSUPPORTED


def test_shifted_region_identifier_is_unsupported() -> None:
    """循环在两侧的位置不同，同一标识不指向同一节点。"""
    original = _looped(2, U, before="h q[1];\n")
    transformed = _looped(2, f"{U} t q[0];", after="h q[1];\n")
    assert _judge(original, transformed, "loop:1") == UNSUPPORTED
    assert _judge(original, transformed, "loop:0") == UNSUPPORTED


def test_missing_target_region_is_unsupported() -> None:
    original = _looped(2, U)
    transformed = _looped(2, f"{U} t q[0];")
    assert _judge(original, transformed, "loop:5") == UNSUPPORTED


def test_different_condition_is_unsupported() -> None:
    original = _flat_conditional("h q[1];", value=1)
    transformed = _flat_conditional("h q[1];", value=0)
    assert _judge(original, transformed, "if:1") == UNSUPPORTED


def test_different_loop_bounds_are_unsupported() -> None:
    """H 迭代 2 次与 3 次的合成只差局域门 H；边界不同仍须不判定。"""
    original = _looped(1, "h q[0];", stop=1)
    transformed = _looped(1, "h q[0];", stop=2)
    assert _judge(original, transformed, "loop:0") == UNSUPPORTED


def test_different_qubit_count_is_unsupported() -> None:
    assert _judge(_looped(2, "h q[0];"), _looped(3, "h q[0];"), "loop:0") == UNSUPPORTED


# --- 实例 -------------------------------------------------------------------


def test_loop_body_fails_only_after_composing_iterations() -> None:
    """每次迭代后多 1 个目标比特 T：单次迭代局域，2 次迭代的合成不局域。"""
    after = f"{CX} t q[1];"
    single = _judge(_looped(2, CX), _looped(2, after), "loop:0")
    double = _judge(_looped(2, CX, stop=1), _looped(2, after, stop=1), "loop:0")
    assert (single, double) == (PASSED_LOCAL, FAILED)


def test_target_region_is_judged_alone_when_an_entangler_follows() -> None:
    """region 后跟 CX；整个电路的 W 不局域，目标 region 的 W 局域。"""
    original = _looped(2, "h q[0];", after=f"{CX}\n")
    transformed = _looped(2, "h q[0]; t q[1];", after=f"{CX}\n")
    assert _judge(original, transformed, "loop:0") == PASSED_LOCAL


def _loop_with_conditional(stop: int, body: str = "x q[1];"):
    text = LOOP_WITH_CONDITIONAL.format(stop=stop)
    replaced = text.replace("{ x q[1]; }", f"{{ {body} }}")
    assert "x q[0];" in replaced and f"{{ {body} }}" in replaced
    return parse_looped_qasm3(replaced).circuit


def test_conditional_inside_loop_pairs_each_iteration() -> None:
    original = _loop_with_conditional(2)
    transformed = _loop_with_conditional(2, "x q[1]; t q[1];")
    assert len(original.operations[1].values) == 3
    assert _judge(original, transformed, "loop:1/if:1") == PASSED_LOCAL


def test_conditional_inside_zero_iteration_loop_is_unsupported() -> None:
    original = _loop_with_conditional(-1)
    transformed = _loop_with_conditional(-1, "x q[1]; t q[1];")
    assert original.operations[1].values == ()
    assert _judge(original, transformed, "loop:1/if:1") == UNSUPPORTED


def test_zero_iteration_loop_body_is_exact() -> None:
    """0 次迭代的合成是单位阵：两侧体不同也报 EXACT。"""
    original = _looped(2, "x q[0];", stop=-1)
    transformed = _looped(2, CX, stop=-1)
    assert original.operations[0].values == ()
    assert _judge(original, transformed, "loop:0") == PASSED_EXACT


def test_empty_body_loop_is_exact() -> None:
    circuit = _looped(1, "bit[1] s;", stop=1)
    assert circuit.operations[0].body == ()
    assert _judge(circuit, circuit, "loop:0") == PASSED_EXACT


# --- 上限 -------------------------------------------------------------------


def test_gate_budget_counts_iterations_on_both_sides() -> None:
    """门数 = 迭代数 × 体门数，两侧合计；上限本身仍可判定。"""
    iterations = preservation.MAX_LOCAL_GATES // 2
    at_limit = _looped(1, "h q[0];", stop=iterations - 1)
    over_limit = _looped(1, "h q[0];", stop=iterations)
    assert len(over_limit.operations[0].values) * 2 > preservation.MAX_LOCAL_GATES

    assert _judge(at_limit, at_limit, "loop:0") == PASSED_EXACT
    assert _judge(over_limit, over_limit, "loop:0") == UNSUPPORTED


def test_qubit_budget_is_inclusive() -> None:
    """作用比特并集等于上限时判定，多 1 个比特时不判定。"""

    def pair(num_qubits):
        qubits = range(num_qubits)
        before = " ".join(f"h q[{qubit}];" for qubit in qubits)
        after = before + " " + " ".join(f"rz(0.3) q[{qubit}];" for qubit in qubits)
        return _looped(num_qubits, before), _looped(num_qubits, after)

    limit = preservation.MAX_LOCAL_QUBITS
    assert _judge(*pair(limit), "loop:0") == PASSED_LOCAL
    assert _judge(*pair(limit + 1), "loop:0") == UNSUPPORTED


def test_gate_without_matrix_definition_is_unsupported(monkeypatch) -> None:
    """现有门类型都有矩阵定义；替身让 T 门没有定义，判定须不判定而不是抛错。"""
    original_operator = preservation.source_operator

    def without_t(gate):
        if gate.gate_type.value == "T":
            raise ValueError("Unknown source gate kind.")
        return original_operator(gate)

    monkeypatch.setattr(preservation, "source_operator", without_t)
    original = _looped(2, U)
    transformed = _looped(2, f"{U} t q[0];")

    assert _judge(original, transformed, "loop:0") == UNSUPPORTED


def test_unconverged_singular_values_are_unsupported(monkeypatch) -> None:
    """奇异值迭代未收敛时残差未知，判定须不判定，而不是给出等级。"""
    original = _looped(2, U)
    transformed = _looped(2, f"{U} {LOCALS}")
    assert _judge(original, transformed, "loop:0") == PASSED_LOCAL

    monkeypatch.setattr(preservation, "_JACOBI_MAX_SWEEPS", 0)
    assert _judge(original, transformed, "loop:0") == UNSUPPORTED
