# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""check_preservation 按 region 判定 UP_TO_LOCAL：入口判定表、结构前提、实例与上限、残差。"""

from __future__ import annotations

import math

import pytest

import qaiji.core.semantics.preservation as preservation
from factories import CORRECTED_TWO_ROUND_CODE, LOOP_WITH_CONDITIONAL
from qaiji.codec import from_qasm3, parse_looped_qasm3
from qaiji.core.circuit import Circuit, GateType
from qaiji.core.loop import BoundedLoop, GateTemplate, LoopedCircuit, LoopIndex, SourceSpan
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
    """平坦解析与循环解析的 region 标识相同，但类型不同，不判定。"""
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
        pytest.param(3, "h q[2];", "h q[2]; cz q[0], q[1];", FAILED, id="cz_on_first_two_of_three"),
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
        pytest.param(2, U, f"{U} {LOCALS} {_zz(9e-11)}", PASSED_LOCAL, id="zz_9e-11"),
        pytest.param(2, U, f"{U} {LOCALS} {_zz(1.1e-10)}", FAILED, id="zz_1.1e-10"),
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

    # 两侧不对称：1 个门对 255 或 256 个门。只数一侧或上限差 1 的实现会放行 257。
    small = _looped(1, "h q[0];")
    for count, expected in ((255, PASSED_EXACT), (256, UNSUPPORTED)):
        large = _looped(1, " ".join(["h q[0];"] * count))
        assert _judge(small, large, "loop:0") == expected, count


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


# --- 循环内条件体的多个实例 -------------------------------------------------


def _loop_conditional(num_qubits: int, start: int, stop: int, body: str, value: int = 1):
    """测量最后一个比特后进入循环（位置 1）；循环体为 ``x``（位置 0）与条件体（位置 1）。

    条件体可用 ``q[i]``，使各次迭代的实例不同。
    """
    last = num_qubits - 1
    text = (
        f"{HEADER}qubit[{num_qubits}] q;\nbit[1] c;\nc[0] = measure q[{last}];\n"
        f"for int i in [{start}:{stop}] {{ x q[{last}]; if (c[0] == {value}) {{ {body} }} }}\n"
    )
    return parse_looped_qasm3(text).circuit


def _h_body(count: int, qubit: int = 0) -> str:
    return " ".join([f"h q[{qubit}];"] * count)


def test_loop_conditional_takes_the_weakest_instance_level() -> None:
    """i = 0 的实例为 Z0·Z0 = I（EXACT），i = 1 的实例为 Z1·Z0（局域）；结果取最弱等级。"""
    original = _loop_conditional(3, 0, 1, "x q[2];")
    transformed = _loop_conditional(3, 0, 1, "x q[2]; z q[i]; z q[0];")
    assert _judge(original, transformed, "loop:1/if:1") == PASSED_LOCAL


def test_loop_conditional_fails_when_a_later_instance_fails() -> None:
    """i = 1 在 CX 控制比特输入侧加 T（局域），i = 2 在目标比特输入侧加 T（失败）。"""
    original = _loop_conditional(3, 1, 2, "cx q[1], q[2];")
    transformed = _loop_conditional(3, 1, 2, "t q[i]; cx q[1], q[2];")
    first_only = _loop_conditional(3, 1, 1, "t q[i]; cx q[1], q[2];")
    assert _judge(_loop_conditional(3, 1, 1, "cx q[1], q[2];"), first_only, "loop:1/if:1") == (
        PASSED_LOCAL
    )
    assert _judge(original, transformed, "loop:1/if:1") == FAILED


def test_loop_conditional_qubit_cap_checks_every_instance() -> None:
    """i = 5 的实例作用 6 个比特，i = 6 的实例作用 7 个比特，超过上限。"""
    six = " ".join(f"h q[{qubit}];" for qubit in range(6))
    assert preservation.MAX_LOCAL_QUBITS == 6
    original = _loop_conditional(8, 5, 6, six)
    transformed = _loop_conditional(8, 5, 6, f"{six} rz(0.3) q[i];")
    assert _judge(original, transformed, "loop:1/if:1") == UNSUPPORTED


def test_failed_instance_outranks_unsupported_instance(monkeypatch) -> None:
    """第 1 个实例的奇异值迭代被替身判为未收敛，第 2 个实例失败；失败优先。"""
    original = _loop_conditional(3, 1, 2, "cx q[1], q[2];")
    transformed = _loop_conditional(3, 1, 2, "t q[i]; cx q[1], q[2];")
    real = preservation._singular_values
    calls = []

    def first_call_unconverged(rows):
        calls.append(rows)
        return None if len(calls) == 1 else real(rows)

    monkeypatch.setattr(preservation, "_singular_values", first_call_unconverged)
    assert _judge(original, transformed, "loop:1/if:1") == FAILED
    assert len(calls) > 1


def test_different_condition_inside_loop_is_unsupported() -> None:
    original = _loop_conditional(2, 0, 1, "h q[0];", value=1)
    transformed = _loop_conditional(2, 0, 1, "h q[0];", value=0)
    assert _judge(original, original, "loop:1/if:1") == PASSED_EXACT
    assert _judge(original, transformed, "loop:1/if:1") == UNSUPPORTED


# --- 条件体的门数上限 -------------------------------------------------------


def test_gate_budget_on_a_top_level_conditional() -> None:
    """顶层条件体只有 1 个实例：128 对 128 个门可判定，128 对 129 个门不判定。"""
    half = preservation.MAX_LOCAL_GATES // 2
    original = _flat_conditional(_h_body(half, qubit=1))
    assert _judge(original, original, "if:1") == PASSED_EXACT
    over = _flat_conditional(_h_body(half + 1, qubit=1))
    assert _judge(original, over, "if:1") == UNSUPPORTED


def test_gate_budget_on_a_loop_conditional_counts_iterations() -> None:
    """2 次迭代：每侧 64 个门合计 256，可判定；64 对 65 个门合计 258，不判定。"""
    quarter = preservation.MAX_LOCAL_GATES // 4
    original = _loop_conditional(2, 0, 1, _h_body(quarter))
    assert _judge(original, original, "loop:1/if:1") == PASSED_EXACT
    over = _loop_conditional(2, 0, 1, _h_body(quarter + 1))
    assert _judge(original, over, "loop:1/if:1") == UNSUPPORTED


def test_over_cap_inputs_build_no_operator(monkeypatch) -> None:
    """超过门数或比特上限的输入在取任何门矩阵之前就判为不判定。"""
    calls = []
    real = preservation.source_operator

    def counting(gate):
        calls.append(gate)
        return real(gate)

    monkeypatch.setattr(preservation, "source_operator", counting)
    seven = range(preservation.MAX_LOCAL_QUBITS + 1)
    wide = " ".join(f"h q[{qubit}];" for qubit in seven)
    cases = [
        (_looped(1, "h q[0];"), _looped(1, _h_body(256)), "loop:0"),
        (_flat_conditional(_h_body(128, 1)), _flat_conditional(_h_body(129, 1)), "if:1"),
        (
            _loop_conditional(2, 0, 1, _h_body(64)),
            _loop_conditional(2, 0, 1, _h_body(65)),
            "loop:1/if:1",
        ),
        (_looped(7, wide), _looped(7, f"{wide} rz(0.3) q[0];"), "loop:0"),
    ]
    for original, transformed, region in cases:
        assert _judge(original, transformed, region) == UNSUPPORTED, region
    assert calls == []


# --- 判定结果的其他字段 -----------------------------------------------------


def test_region_path_leaves_morphism_fields_unset() -> None:
    """按 region 判定不填态射字段；只有 passed 带等级。"""
    cases = [
        ("passed", LOCAL, _looped(2, U), _looped(2, f"{U} {LOCALS}")),
        ("failed", None, _looped(2, U), _looped(2, f"{U} cz q[0], q[1];")),
        ("unsupported", None, _looped(1, "h q[0];", stop=1), _looped(1, "h q[0];", stop=2)),
    ]
    for status, level, original, transformed in cases:
        summary = check_preservation(original, transformed, requested_level=LOCAL, region="loop:0")
        fields = (summary.status, summary.equiv_level)
        morphisms = (summary.original_morphism, summary.lowered_morphism)
        assert (fields, morphisms) == ((status, level), (None, None))


# --- 展开失败 ---------------------------------------------------------------


def test_loop_expansion_failure_is_unsupported() -> None:
    """循环变量下标越界的电路无法展开；按 region 判定返回不判定，不外抛异常。"""
    span = SourceSpan(1, 0, 1, 0)
    body = (GateTemplate(GateType.X, (LoopIndex(),)),)
    circuit = LoopedCircuit(2, (), (BoundedLoop("i", 0, 2, (), body, span),))
    with pytest.raises(ValueError):
        circuit.expand()
    assert [region.id for region in regions_of(circuit)] == ["loop:0"]

    assert _judge(circuit, circuit, "loop:0") == UNSUPPORTED


# --- 等级之间的单调性 -------------------------------------------------------

_X_STRINGS = ((0, 1), (0, 2), (1, 2), (0, 1, 2))


def _x_string(qubits: tuple[int, ...], delta: float) -> str:
    """exp(-i δ X⊗…⊗X)：H 换基，CX 阶梯求奇偶，RZ(2δ)，再逆序还原。"""
    *controls, target = qubits
    basis = " ".join(f"h q[{qubit}];" for qubit in qubits)
    ladder = [f"cx q[{control}], q[{target}];" for control in controls]
    rotation = f"rz({2 * delta!r}) q[{target}];"
    return " ".join([basis, *ladder, rotation, *reversed(ladder), basis])


@pytest.mark.parametrize(
    ("phase", "strongest"),
    [("", PASSED_EXACT), (f"rz({math.tau!r}) q[0];", ("passed", EquivLevel.UP_TO_PHASE))],
    ids=["none", "global_phase"],
)
def test_exact_and_phase_verdicts_never_exceed_the_cut_residual(phase, strongest) -> None:
    """W = exp(-iδ(X0X1 + X0X2 + X1X2 + X0X1X2))，δ 增大时等级不得变强。

    各项对易，每个单比特切分的算符 Schmidt 秩为 2，归一化第二奇异值
    ε = √3·δ·(1 + O(δ²))。EXACT 或 UP_TO_PHASE 须蕴含 ε 不超过残差阈值。
    δ = 0.9e-10 时逐元偏差约 9e-11，ε 约 1.56e-10，须判失败。
    """
    order = [PASSED_EXACT, ("passed", EquivLevel.UP_TO_PHASE), PASSED_LOCAL, FAILED]
    deltas = [0.0, 2e-11, 4e-11, 6e-11, 0.9e-10, 1.2e-10, 1e-9, 1e-6]
    verdicts = []
    for delta in deltas:
        rotation = " ".join(_x_string(qubits, delta) for qubits in _X_STRINGS)
        transformed = _looped(3, f"h q[0]; {rotation} {phase}")
        verdict = _judge(_looped(3, "h q[0];"), transformed, "loop:0")
        verdicts.append(verdict)
        if verdict[1] in FLAT_LEVELS:
            limit = preservation.MAX_LOCAL_RESIDUAL * (1 + 1e-6)
            assert math.sqrt(3) * delta <= limit, (delta, verdict)

    ranks = [order.index(verdict) for verdict in verdicts]
    assert ranks == sorted(ranks), verdicts
    assert (verdicts[0], verdicts[-1]) == (strongest, FAILED)
    assert verdicts[deltas.index(0.9e-10)] == FAILED
