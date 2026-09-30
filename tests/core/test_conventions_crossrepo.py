# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""基组约定的跨库证伪：用光学适配器 domain 层的冻结事实判定本仓约定。"""

import cmath
import dataclasses
import os
import re
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from pathlib import Path

import pytest
from _crossrepo_criteria import (
    CLAUSES,
    MAX_SNAPSHOT_AGE_DAYS,
    NON_DEGENERATE_THETAS,
    OPTICS_ROOT_ENV,
    Discovery,
    UnsupportedEvidenceError,
    _rz_coupling_at,
    assert_fresh,
    clause_failures,
    discover_optics_repo,
    docstring_problems,
    freshness_problems,
    gate_matrix,
    is_degenerate,
    live_problems,
    mismatch_report,
    r0_application_order,
    r1_sigma_direction,
    r2_sigma_z,
    r3_rz_coupling,
    r3_rz_formula,
    r4_initial_state,
    unpinned_callees,
)
from _optics_snapshot import FACTS, Fact

import qaiji.core.conventions as conventions
from qaiji.constants import DEFAULT_TOLERANCE

pytestmark = pytest.mark.physics

FACT_ID = re.compile(r"XR-[A-Z0-9]+(?:-[A-Z0-9]+)*")
BY_ID = {fact.fact_id: fact for fact in FACTS}


def mutated(fact_id: str, old: str, new: str) -> Fact:
    """返回把 ``old`` 替换为 ``new`` 的事实副本；``old`` 必须恰好出现一次，防止注入空转。"""
    fact = BY_ID[fact_id]
    assert fact.verbatim.count(old) == 1, f"injection anchor not unique in {fact_id}: {old!r}"
    return dataclasses.replace(fact, verbatim=fact.verbatim.replace(old, new))


def test_snapshot_holds_exactly_the_contracted_facts() -> None:
    ids = [fact.fact_id for fact in FACTS]

    assert len(ids) == len(set(ids))
    assert set(ids) == {
        "XR-SP",
        "XR-SM",
        "XR-Z",
        "XR-RZ",
        "XR-ASSEMBLE",
        "XR-SEMPARAM",
        "XR-APPLY-MPS",
        "XR-APPLY-SV",
        "XR-INIT",
        "XR-INIT-PARSE",
    }


@pytest.mark.parametrize("fact", FACTS, ids=lambda fact: fact.fact_id)
def test_fact_fields_are_well_formed(fact: Fact) -> None:
    assert FACT_ID.fullmatch(fact.fact_id)
    assert all((fact.source_path, fact.commit, fact.verbatim.strip(), fact.physical_claim))
    assert fact.lines[0] <= fact.lines[1]
    # 行数与行段不符说明 verbatim 被截断或多抄了行。
    assert len(fact.verbatim.splitlines()) == fact.lines[1] - fact.lines[0] + 1


# 受限求值器：拒收先行。每个白名单分支都配一个拒收兄弟，派生正例放在最后。

SILENT_TRANSFORMS = [
    # 转置、丢虚部、降精度、引入快照外的量：都能让派生出的矩阵悄悄变样。
    pytest.param("XR-RZ", "stack([row0, row1])", "stack([row0, row1], dim=1)", id="stack-dim"),
    pytest.param(
        "XR-RZ",
        "(-1j * theta / 2.0).to(Gate.device)",
        "(-1j * theta / 2.0).to(torch.float64)",
        id="to-float64",
    ),
    pytest.param("XR-Z", "dtype=Gate.dtype", "dtype=torch.float32", id="tensor-float32"),
    pytest.param("XR-Z", "[0.0, -1.0]", "[0.0, -scale]", id="unbound-name"),
]

NEGATIVE_SPACE = [
    pytest.param("XR-Z", "[0.0, -1.0]", "[0.0, True]", id="bool-constant"),
    pytest.param("XR-Z", "[[1.0, 0.0], [0.0, -1.0]]", "[{1.0, 0.0}, [0.0, -1.0]]", id="set"),
    pytest.param("XR-Z", "[[1.0, 0.0], [0.0, -1.0]]", "[{1.0: 0.0}, [0.0, -1.0]]", id="dict"),
    pytest.param("XR-Z", "[0.0, -1.0]", "[0.0, ~1.0]", id="invert"),
    pytest.param("XR-Z", "[0.0, -1.0]", "[0.0, not 1.0]", id="not"),
    pytest.param("XR-RZ", "-1j * theta / 2.0", "-1j * theta**2.0", id="power"),
    pytest.param("XR-RZ", "-1j * theta / 2.0", "-1j * theta % 2.0", id="modulo"),
    pytest.param(
        "XR-Z", "[[1.0, 0.0], [0.0, -1.0]]", "[[1.0, 0.0]] + [[0.0, -1.0]]", id="sequence-add"
    ),
    pytest.param("XR-Z", ", dtype=Gate.dtype", ", 2, dtype=Gate.dtype", id="tensor-extra-arg"),
    pytest.param("XR-RZ", "torch.zeros((), ", "torch.zeros((2,), ", id="zeros-shape"),
    pytest.param(
        "XR-RZ",
        "torch.exp(-1j * theta / 2.0)",
        "torch.exp(-1j * theta / 2.0, out=None)",
        id="exp-keyword",
    ),
    pytest.param("XR-RZ", ".to(Gate.device), z])", ".to(), z])", id="to-empty"),
    pytest.param("XR-RZ", '"theta", theta)', '"theta", theta, 0.5)', id="semparam-extra-arg"),
    pytest.param("XR-RZ", '"theta", theta)', "theta, theta)", id="semparam-name-not-str"),
    pytest.param(
        "XR-RZ", "self._semantic_parameter", "other._semantic_parameter", id="semparam-other"
    ),
    pytest.param("XR-Z", "[[1.0, 0.0], [0.0, -1.0]]", "[[1.0, 0.0]]", id="matrix-shape"),
    pytest.param("XR-RZ", "torch.exp(-1j", "torch.sin(-1j", id="unlisted-function"),
    pytest.param(
        "XR-Z",
        "        self._assemble(matrix)",
        "        self.phase = 1.0\n        self._assemble(matrix)",
        id="other-self-attribute",
    ),
    pytest.param("XR-Z", "self.target_qubits =", "other.target_qubits =", id="other-target"),
    pytest.param(
        "XR-Z",
        "        self._assemble(matrix)",
        "        if True:\n            matrix = matrix\n        self._assemble(matrix)",
        id="if-statement",
    ),
    pytest.param(
        "XR-Z",
        "        self._assemble(matrix)",
        "        for _ in (1,):\n            matrix = matrix\n        self._assemble(matrix)",
        id="for-statement",
    ),
    pytest.param("XR-Z", "self._assemble(matrix)", "result = matrix", id="no-assemble"),
    pytest.param(
        "XR-Z",
        "        self._assemble(matrix)",
        "        self._assemble(matrix)\n        self._assemble(matrix)",
        id="two-assembles",
    ),
    pytest.param(
        "XR-Z",
        "self._assemble(matrix)",
        "self._assemble(matrix, mpo_shape=(2, 2))",
        id="assemble-mpo-shape",
    ),
    pytest.param("XR-Z", "self._assemble(matrix)", "other._assemble(matrix)", id="other-assemble"),
    pytest.param("XR-Z", "class PauliZ(Gate):", "def PauliZ(Gate):", id="no-class"),
    pytest.param(
        "XR-Z",
        '{self.target_qubits[0]}"',
        '{self.target_qubits[0]}"\n\n\nclass Extra:\n    pass',
        id="two-classes",
    ),
    pytest.param("XR-Z", "def __init__(self, q0):", "def __str__(self, q0):", id="no-init"),
    pytest.param(
        "XR-Z",
        "    def __str__(self):",
        "    def _assemble(self, matrix):\n        Gate._assemble(self, matrix.T)\n\n"
        "    def __str__(self):",
        id="class-extra-method",
    ),
    pytest.param("XR-Z", "class PauliZ(Gate):", "class PauliZ(ConjGate):", id="class-base"),
    pytest.param(
        "XR-Z", "class PauliZ(Gate):", "@conjugated\nclass PauliZ(Gate):", id="class-decorator"
    ),
    pytest.param(
        "XR-Z",
        "self.target_qubits = (q0,)",
        "self.target_qubits = self._assemble(matrix)",
        id="target-qubits-expression",
    ),
    pytest.param("XR-Z", "(q0,)", "(self._assemble(matrix),)", id="target-qubits-call-in-tuple"),
]


@pytest.mark.parametrize(("fact_id", "old", "new"), SILENT_TRANSFORMS + NEGATIVE_SPACE)
def test_evaluator_rejects_constructs_outside_the_whitelist(
    fact_id: str, old: str, new: str
) -> None:
    # 必须是这个类型：裸 ValueError / KeyError 说明是意外崩溃，不是求值器的有意拒收。
    with pytest.raises(UnsupportedEvidenceError):
        gate_matrix(mutated(fact_id, old, new), theta=0.7)


def test_evaluator_derives_the_literal_gates() -> None:
    expected = {
        "XR-SP": ((0j, 1 + 0j), (0j, 0j)),
        "XR-SM": ((0j, 0j), (1 + 0j, 0j)),
        "XR-Z": ((1 + 0j, 0j), (0j, -1 + 0j)),
    }
    for fact_id, matrix in expected.items():
        assert conventions._close(gate_matrix(BY_ID[fact_id]), matrix, DEFAULT_TOLERANCE), fact_id


def test_evaluator_derives_rz_from_its_expression() -> None:
    expected = ((cmath.exp(-0.35j), 0j), (0j, cmath.exp(0.35j)))

    derived = gate_matrix(BY_ID["XR-RZ"], theta=0.7)

    assert conventions._close(derived, expected, DEFAULT_TOLERANCE)


def test_every_counterpart_callee_is_pinned_by_a_fact() -> None:
    # 求值器把这些对方方法当作恒等；没有事实钉住它们，这个假设就无人看守。
    assert unpinned_callees(FACTS) == set()
    assert unpinned_callees([f for f in FACTS if f.fact_id != "XR-SEMPARAM"]) == {
        "_semantic_parameter"
    }


# 反证矩阵：每行一个注入，期望为 {判据: 结果种类}；带 ★ 的行是该子句的专属杀手。

type Injection = Callable[[pytest.MonkeyPatch], Mapping[str, Fact]]


@dataclasses.dataclass(frozen=True)
class Row:
    id: str
    injection: Injection
    expected_red: dict[str, str]
    stars: tuple[tuple[str, str], ...] = ()
    fools_self_check: bool = False


def theirs(fact_id: str, old: str, new: str) -> Injection:
    """只改对方事实的副本；本仓约定不动。"""
    return lambda monkeypatch: {**BY_ID, fact_id: mutated(fact_id, old, new)}


def ours(**values: object) -> Injection:
    """只改本仓约定（经 monkeypatch，测试结束自动还原）；对方事实不动。"""

    def inject(monkeypatch: pytest.MonkeyPatch) -> Mapping[str, Fact]:
        for name, value in values.items():
            monkeypatch.setattr(conventions, name, value)
        return BY_ID

    return inject


_ORIGINAL_RZ = conventions._rz


def _rz_with_negated_angle(theta: float) -> tuple[tuple[complex, complex], ...]:
    # 先捕获原函数再包装：晚绑定的 lambda 会在 monkeypatch 后递归调用自己。
    return _ORIGINAL_RZ(-theta)


MISMATCH = "mismatch"
UNSUPPORTED = "unsupported"
FLIPPED_OPTICS = {0: "ground", 1: "excited"}
RZ_ROWS = (
    "row0 = torch.stack([torch.exp(-1j * theta / 2.0).to(Gate.device), z])\n"
    "        row1 = torch.stack([z, torch.exp(1j * theta / 2.0).to(Gate.device)])"
)

MATRIX = [
    Row(
        "D01",
        ours(OPTICS_INDEX_TO_PHYSICAL=FLIPPED_OPTICS),
        {"R1": MISMATCH, "R2": MISMATCH, "R3b": MISMATCH, "R4": MISMATCH},
        stars=(("R2", "attr"), ("R3b", "coupling")),
    ),
    Row(
        # 两张表一起翻：包内 self_check 看不出来，只有跨库判据能抓住。
        "D01-silent",
        ours(OPTICS_INDEX_TO_PHYSICAL=FLIPPED_OPTICS, QASM3_TO_OPTICS_BIT={0: 0, 1: 1}),
        {"R1": MISMATCH, "R2": MISMATCH, "R3b": MISMATCH, "R4": MISMATCH},
        fools_self_check=True,
    ),
    Row("D02", ours(QASM3_INDEX_TO_PHYSICAL={0: "excited", 1: "ground"}), {"R3b": MISMATCH}),
    Row("D03", ours(_rz=_rz_with_negated_angle), {"R3b": MISMATCH}),
    Row(
        "D04",
        theirs("XR-SP", "[[0.0, 1.0], [0.0, 0.0]]", "[[0.0, 0.0], [1.0, 0.0]]"),
        {"R1": MISMATCH, "R2": MISMATCH},
        stars=(("R1", "Sp"), ("R2", "alg")),
    ),
    Row(
        "D04-prime",
        theirs("XR-SM", "[[0.0, 0.0], [1.0, 0.0]]", "[[0.0, 1.0], [0.0, 0.0]]"),
        {"R1": MISMATCH, "R2": MISMATCH},
        stars=(("R1", "Sm"),),
    ),
    Row(
        "D08-prime",
        theirs("XR-INIT-PARSE", "int(c) for c", "1 - int(c) for c"),
        {"R4": MISMATCH},
        stars=(("R4", "parse"),),
    ),
    Row(
        "D08-dprime",
        theirs("XR-INIT", "all ground state", "all excited state"),
        {"R4": MISMATCH},
        stars=(("R4", "claim"),),
    ),
    Row(
        "D05",
        theirs("XR-Z", "[[1.0, 0.0], [0.0, -1.0]]", "[[-1.0, 0.0], [0.0, 1.0]]"),
        {"R2": MISMATCH, "R3a": MISMATCH},
        stars=(("R3a", "formula"),),
    ),
    Row(
        # 用白名单内的写法翻转相位符号；若写成 exp(+1j...) 会被求值器拒收，变成 D13 的复制品。
        "D06",
        theirs(
            "XR-RZ", RZ_ROWS, RZ_ROWS.replace("-1j", "@").replace("1j", "-1j").replace("@", "1j")
        ),
        {"R3a": MISMATCH, "R3b": MISMATCH},
    ),
    Row(
        "D08",
        theirs("XR-INIT", '"1" * num_sites', '"0" * num_sites'),
        {"R4": MISMATCH},
        stars=(("R4", "map"),),
    ),
    Row(
        "D09",
        theirs("XR-APPLY-MPS", '"jx,ixk->ijk"', '"xj,ixk->ijk"'),
        {"R0": MISMATCH},
        stars=(("R0", "mps"),),
    ),
    Row(
        "D09-prime",
        theirs("XR-APPLY-SV", "matmul(matrix, psi_perm)", "matmul(psi_perm, matrix)"),
        {"R0": MISMATCH},
        stars=(("R0", "sv"),),
    ),
    Row(
        "D09-dprime",
        theirs("XR-ASSEMBLE", "mpo = matrix if", "mpo = matrix.T if"),
        {"R0": MISMATCH},
        stars=(("R0", "asm"),),
    ),
    Row(
        "D09-tprime",
        theirs("XR-SEMPARAM", "return tensor", "return -tensor"),
        {"R0": MISMATCH},
        stars=(("R0", "sem"),),
    ),
    Row(
        "D13",
        theirs("XR-RZ", "row0 = torch.stack", "row0 = torch.unknown"),
        {"R3a": UNSUPPORTED, "R3b": UNSUPPORTED},
    ),
]

STARS = [
    pytest.param(rule, clause, row, id=f"{rule}-{clause}")
    for row in MATRIX
    for rule, clause in row.stars
]


@pytest.mark.parametrize(("rule", "clause", "row"), STARS)
def test_exclusive_killer(
    rule: str, clause: str, row: Row, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 恰为 {★ 子句}：若删掉该子句的判断，这一行在该判据上就不再失败。
    facts = row.injection(monkeypatch)

    assert set(clause_failures(rule, facts)) == {clause}


def test_every_clause_has_an_exclusive_killer() -> None:
    # 对 CLAUSES 的真实枚举取等：新增子句而没配杀手、或杀手指向不存在的子句，都会失败。
    killed = {(rule, clause) for row in MATRIX for rule, clause in row.stars}

    assert killed == {(rule, clause) for rule, clauses in CLAUSES.items() for clause in clauses}


OPTICS, QASM3, RZ = "OPTICS_INDEX_TO_PHYSICAL", "QASM3_INDEX_TO_PHYSICAL", "RZ_PHASE_CONVENTION"
CRITERIA = {
    "R0": (r0_application_order, (), "XR-APPLY-MPS"),
    "R1": (r1_sigma_direction, (OPTICS,), "XR-SP"),
    "R2": (r2_sigma_z, (OPTICS,), "XR-Z"),
    "R3a": (r3_rz_formula, (RZ,), "XR-RZ"),
    "R3b": (r3_rz_coupling, (OPTICS, QASM3, RZ), "XR-RZ"),
    "R4": (r4_initial_state, (OPTICS,), "XR-INIT"),
}
"""判据名 → (判据, 它读取的本仓约定, 差异报告里的对方事实)。R0 只判对方一侧的前提。"""


@pytest.mark.parametrize(("rule", "ours", "fact_id"), CRITERIA.values(), ids=CRITERIA)
def test_declared_conventions_survive_cross_repo_falsification(
    rule: Callable[[Mapping[str, Fact]], str | None], ours: tuple[str, ...], fact_id: str
) -> None:
    observed = rule(BY_ID)

    assert observed is None, mismatch_report(
        rule.__name__,
        ", ".join(ours) or "none (adapter-side precondition)",
        {name: getattr(conventions, name) for name in ours},
        BY_ID[fact_id],
        observed,
    )


def test_sample_predicate_flags_every_degenerate_angle() -> None:
    # 0.05 专杀旧阈值 1e-6：它离 0 足够近，RZ 与恒等之差已低于可鉴别的量级。
    for theta in (0.0, 2 * cmath.pi, -2 * cmath.pi, 4 * cmath.pi, 0.05):
        assert is_degenerate(theta), theta


def test_sample_predicate_accepts_the_production_samples() -> None:
    assert not any(is_degenerate(theta) for theta in NON_DEGENERATE_THETAS)


def test_mismatch_report_is_neutral_ascii(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conventions, "OPTICS_INDEX_TO_PHYSICAL", FLIPPED_OPTICS)
    observed = r1_sigma_direction(BY_ID)
    assert observed is not None

    report = mismatch_report(
        "R1", "OPTICS_INDEX_TO_PHYSICAL", FLIPPED_OPTICS, BY_ID["XR-SP"], observed
    )

    assert report.startswith("cross-repo falsification R1 failed")
    assert re.findall(r"^  ([a-z]+) *:", report, re.M) == ["ours", "theirs", "observed", "next"]
    for field in (
        "attribution undecided",
        "XR-SP",
        "raising",
        "d702b677",
        "single_qubit.py:197-222",
    ):
        assert field in report
    assert observed in report
    assert report.isascii()
    assert not {"wrong", "fix"} & set(re.findall(r"[a-z]+", report.lower()))


def test_matrix_holds_exactly_the_planned_rows() -> None:
    ids = [row.id for row in MATRIX]

    assert len(ids) == len(set(ids))
    assert set(ids) == {
        "D01",
        "D01-silent",
        "D02",
        "D03",
        "D04",
        "D04-prime",
        "D05",
        "D06",
        "D08",
        "D08-prime",
        "D08-dprime",
        "D09",
        "D09-prime",
        "D09-dprime",
        "D09-tprime",
        "D13",
    }


def _outcome(rule: str, facts: Mapping[str, Fact]) -> str | None:
    # 只在测试侧把拒收记作 unsupported；其他异常照常抛出，不能被算成「红」。
    try:
        return MISMATCH if CRITERIA[rule][0](facts) is not None else None
    except UnsupportedEvidenceError:
        return UNSUPPORTED


@pytest.mark.parametrize("row", MATRIX, ids=lambda row: row.id)
def test_falsification_matrix(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    facts = row.injection(monkeypatch)

    red = {rule: kind for rule in CRITERIA if (kind := _outcome(rule, facts)) is not None}

    assert red == row.expected_red
    if row.fools_self_check:
        conventions.self_check()


def test_degenerate_samples_hide_a_basis_flip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conventions, "OPTICS_INDEX_TO_PHYSICAL", FLIPPED_OPTICS)

    assert _rz_coupling_at(BY_ID, 0.0) is None
    assert _rz_coupling_at(BY_ID, 2 * cmath.pi) is None
    assert _rz_coupling_at(BY_ID, 0.7) is not None


def test_degenerate_samples_are_rejected_by_the_guard() -> None:
    for criterion in (r3_rz_formula, r3_rz_coupling):
        with pytest.raises(AssertionError, match="cannot expose a basis flip"):
            criterion(BY_ID, (0.0, 2 * cmath.pi))


CONDITION_KILLERS = [
    # 子句内部的每个合取条件各配一个注入：只让这一个条件失败，删掉它，失败集合就会变。
    (
        "asm-to-empty",
        "XR-ASSEMBLE",
        "to(dtype=Gate.dtype, device=Gate.device)",
        "to()",
        "R0",
        {"asm"},
    ),
    (
        "asm-to-float32",
        "XR-ASSEMBLE",
        "to(dtype=Gate.dtype,",
        "to(dtype=torch.float32,",
        "R0",
        {"asm"},
    ),
    ("sem-other-argument", "XR-SEMPARAM", "_as_tensor(value)", "_as_tensor(name)", "R0", {"sem"}),
    ("sem-no-return", "XR-SEMPARAM", "return tensor", "pass", "R0", {"sem"}),
    (
        "sem-rebound",
        "XR-SEMPARAM",
        "        return tensor",
        "        tensor = -tensor\n        return tensor",
        "R0",
        {"sem"},
    ),
    (
        "sem-in-place",
        "XR-SEMPARAM",
        "        return tensor",
        "        tensor.neg_()\n        return tensor",
        "R0",
        {"sem"},
    ),
    ("mps-gate-rank", "XR-APPLY-MPS", "jx,ixk->ijk", "jxy,ixk->ijk", "R0", {"mps"}),
    ("mps-output-index-contracted", "XR-APPLY-MPS", "jx,ixk->ijk", "ix,ixk->iik", "R0", {"mps"}),
    ("mps-input-index-free", "XR-APPLY-MPS", "jx,ixk->ijk", "jy,ixk->ixk", "R0", {"mps"}),
    ("mps-output-order", "XR-APPLY-MPS", "jx,ixk->ijk", "jx,ixk->jik", "R0", {"mps"}),
    (
        "sp-two-targets",
        "XR-SP",
        "[[0.0, 1.0], [0.0, 0.0]]",
        "[[0.0, 1.0], [0.0, 1.0]]",
        "R1",
        {"Sp"},
    ),
    ("z-ground-positive", "XR-Z", "[0.0, -1.0]]", "[0.0, 1.0]]", "R2", {"alg", "attr"}),
    ("z-excited-negative", "XR-Z", "[[1.0, 0.0]", "[[-1.0, 0.0]", "R2", {"alg", "attr"}),
    ("claim-spin-up", "XR-INIT", "all spin down", "all spin up", "R4", {"claim"}),
    ("parse-other-variable", "XR-INIT-PARSE", "int(c) for c", "int(d) for c", "R4", {"parse"}),
    ("parse-filtered", "XR-INIT-PARSE", "in spin_string)", "in spin_string if c)", "R4", {"parse"}),
]


@pytest.mark.parametrize(
    ("fact_id", "old", "new", "rule", "expected"),
    [pytest.param(*case[1:], id=case[0]) for case in CONDITION_KILLERS],
)
def test_clause_condition_killer(
    fact_id: str, old: str, new: str, rule: str, expected: set[str]
) -> None:
    facts = {**BY_ID, fact_id: mutated(fact_id, old, new)}

    assert set(clause_failures(rule, facts)) == expected


# 防腐：G1 保鲜（逐条计龄）与 G2 实时重核（三态发现 + 逐条比对）。

REPO_ROOT = Path(__file__).resolve().parents[2]
# 支持部分刷新：各事实的提取日期可以不同，边界用例按最老 / 最新的那条取。
OLDEST = min(fact.extracted_on for fact in FACTS)
NEWEST = max(fact.extracted_on for fact in FACTS)


def _named(problems: list[str]) -> set[tuple[str, str]]:
    """把问题行解析为 ``(事实 ID, 问题类别)``，按 ID 与类别断言而不按行数。"""
    return {tuple(line.split(": ", 2)[:2]) for line in problems}  # type: ignore[misc]


@pytest.mark.parametrize(
    "today",
    [NEWEST, OLDEST + timedelta(days=MAX_SNAPSHOT_AGE_DAYS)],
    ids=["same-day", "day-180"],
)
def test_freshness_accepts_both_ends_of_the_window(today: date) -> None:

    assert freshness_problems(FACTS, today) == []
    assert_fresh(FACTS, today)


def test_freshness_fails_on_day_181_with_inline_refresh_steps() -> None:
    today = OLDEST + timedelta(days=MAX_SNAPSHOT_AGE_DAYS + 1)

    with pytest.raises(pytest.fail.Exception) as failure:
        assert_fresh(FACTS, today)

    message = str(failure.value)
    assert message.isascii()
    oldest = {fact.fact_id for fact in FACTS if fact.extracted_on == OLDEST}
    assert oldest <= set(FACT_ID.findall(message))
    assert "181 days" in message
    assert "QAIJI-ADD-003 section 4.5" in message
    # CI 读者看不到计划文档，刷新命令必须在消息里且能直接运行。
    assert (
        f"{OPTICS_ROOT_ENV}=... uv run pytest tests/core/test_conventions_crossrepo.py --no-cov -rfEs"
        in message
    )


def test_freshness_fails_on_a_future_extraction_date() -> None:
    today = OLDEST - timedelta(days=1)

    assert _named(freshness_problems(FACTS, today)) == {(fact.fact_id, "future") for fact in FACTS}
    with pytest.raises(pytest.fail.Exception):
        assert_fresh(FACTS, today)


def test_freshness_names_only_the_stale_fact() -> None:
    # 逐条计龄：一条旧事实不能被其余新事实平均掉，新事实也不能被连坐。
    today = OLDEST + timedelta(days=MAX_SNAPSHOT_AGE_DAYS)
    stale = dataclasses.replace(BY_ID["XR-SP"], extracted_on=OLDEST - timedelta(days=1))
    facts = [stale if fact.fact_id == "XR-SP" else fact for fact in FACTS]

    assert _named(freshness_problems(facts, today)) == {("XR-SP", "stale")}


def _optics_checkout(root: Path) -> Path:
    (root / "src" / "quantempo").mkdir(parents=True)
    return root


# (用例名, 变量 未设/空串/无效/有效, 兄弟目录 无/空目录/有效, 期望状态, 期望路径)
DISCOVERY_CASES = [
    ("unset-no-sibling", None, None, Discovery.UNCONFIGURED, "sibling"),
    ("unset-sibling-not-a-checkout", None, "empty", Discovery.UNCONFIGURED, "sibling"),
    ("unset-sibling-checkout", None, "checkout", Discovery.FOUND, "sibling"),
    # 判定顺序：显式配置优先于兄弟目录，配错了不得回退到兄弟目录。
    ("set-invalid-sibling-checkout", "empty", "checkout", Discovery.MISCONFIGURED, "env"),
    ("set-valid-sibling-checkout", "checkout", "checkout", Discovery.FOUND, "env"),
    ("set-valid-no-sibling", "checkout", None, Discovery.FOUND, "env"),
    # 设成空串也是显式配置：大声失败，不当作未设置。
    ("set-blank-sibling-checkout", "blank", "checkout", Discovery.MISCONFIGURED, "blank"),
]


@pytest.mark.parametrize(
    ("env_target", "sibling", "state", "where"),
    [pytest.param(*case[1:], id=case[0]) for case in DISCOVERY_CASES],
)
def test_discovery_state(
    tmp_path: Path, env_target: str | None, sibling: str | None, state: Discovery, where: str
) -> None:
    repo_root = tmp_path / "Qaiji-IR"
    repo_root.mkdir()
    paths = {"sibling": tmp_path / "QuanTempo", "env": tmp_path / "elsewhere", "blank": Path("")}
    for kind, path in ((sibling, paths["sibling"]), (env_target, paths["env"])):
        if kind == "empty":
            path.mkdir()
        elif kind == "checkout":
            _optics_checkout(path)
    configured = {None: None, "blank": ""}.get(env_target, str(paths["env"]))
    env = {} if configured is None else {OPTICS_ROOT_ENV: configured}

    assert discover_optics_repo(env, repo_root) == (state, paths[where])


def _mirror(root: Path, facts: tuple[Fact, ...] = FACTS) -> Path:
    """在 ``root`` 下按事实的源路径写出只含 verbatim 的干净副本。"""
    for fact in facts:
        path = root / fact.source_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(fact.verbatim + "\n\n")
    return root


def test_live_problems_are_empty_on_a_clean_copy(tmp_path: Path) -> None:
    assert live_problems(FACTS, _mirror(tmp_path)) == []


def test_live_problems_report_a_missing_file(tmp_path: Path) -> None:
    root = _mirror(tmp_path)
    source = BY_ID["XR-INIT"].source_path
    (root / source).unlink()
    expected = {(fact.fact_id, "missing") for fact in FACTS if fact.source_path == source}

    assert expected
    assert _named(live_problems(FACTS, root)) == expected


def _verbatim_edit(fact_id: str, old: str, new: str) -> tuple[str, str]:
    verbatim = BY_ID[fact_id].verbatim
    assert verbatim.count(old) == 1, f"injection anchor not unique in {fact_id}: {old!r}"
    return fact_id, verbatim.replace(old, new)


_INIT_PARSE_TAIL = BY_ID["XR-INIT-PARSE"].verbatim.splitlines()[-1]

# (用例名, (事实 ID, 对方源码中替换后的原文), 期望的问题类别)
LIVE_EDITS = [
    ("line-inserted", _verbatim_edit("XR-Z", "(Gate):\n", "(Gate):\n# edited\n"), "drift"),
    # 子串匹配会放过同一行首尾的追加，所以按整行比对。
    ("line-tail", _verbatim_edit("XR-SEMPARAM", "return tensor", "return tensor.conj()"), "drift"),
    (
        "line-commented-out",
        ("XR-APPLY-MPS", "#" + BY_ID["XR-APPLY-MPS"].verbatim),
        "drift",
    ),
    # 块后紧跟更深缩进的行：对方在同一个类 / 语句块里追加了快照之外的代码。
    (
        "class-grown",
        ("XR-SP", BY_ID["XR-SP"].verbatim + "\n\n    def matrix(self):\n        return None"),
        "grown",
    ),
    (
        "block-grown",
        ("XR-INIT-PARSE", BY_ID["XR-INIT-PARSE"].verbatim + "\n" + _INIT_PARSE_TAIL),
        "grown",
    ),
]


@pytest.mark.parametrize(
    ("edit", "kind"), [pytest.param(*case[1:], id=case[0]) for case in LIVE_EDITS]
)
def test_live_problems_report_an_edited_counterpart(
    tmp_path: Path, edit: tuple[str, str], kind: str
) -> None:
    fact_id, edited = edit
    path = _mirror(tmp_path) / BY_ID[fact_id].source_path
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(BY_ID[fact_id].verbatim, edited), encoding="utf-8")

    assert _named(live_problems(FACTS, tmp_path)) == {(fact_id, kind)}


def test_live_problems_report_a_non_unique_verbatim(tmp_path: Path) -> None:
    root = _mirror(tmp_path)
    fact = BY_ID["XR-Z"]
    with (root / fact.source_path).open("a", encoding="utf-8") as handle:
        handle.write(fact.verbatim)

    assert _named(live_problems(FACTS, root)) == {("XR-Z", "not unique")}


def test_snapshot_freshness() -> None:
    assert_fresh(FACTS, date.today())


def test_live_snapshot_matches_counterpart() -> None:
    state, root = discover_optics_repo(os.environ, REPO_ROOT)
    if state is Discovery.UNCONFIGURED:
        pytest.skip(
            f"no optics checkout at {root}; set {OPTICS_ROOT_ENV} to enable the live re-check"
        )
    if state is Discovery.MISCONFIGURED:
        pytest.fail(f"{OPTICS_ROOT_ENV}={root} has no src/quantempo/ directory", pytrace=False)

    problems = live_problems(FACTS, root)
    assert not problems, "\n".join(problems)


# 证伪状态标注：conventions.py 的属性 docstring 必须与快照双向链接（L1–L5）。

CONVENTIONS_SOURCE = Path(conventions.__file__).read_text(encoding="utf-8")


def _rules(problems: list[str]) -> set[str]:
    return {line.split(":", 1)[0] for line in problems}


def test_conventions_docstrings_link_to_snapshot() -> None:
    assert docstring_problems(CONVENTIONS_SOURCE, FACTS, REPO_ROOT) == []


def _source_with(old: str, new: str) -> str:
    assert CONVENTIONS_SOURCE.count(old) == 1, f"injection anchor not unique: {old!r}"
    return CONVENTIONS_SOURCE.replace(old, new)


_OPTICS_DOC_TAIL = '见源码仓库 ``tests/core/_optics_snapshot.py``。\n"""\n\nQASM3_TO_OPTICS_BIT'
_BRIDGE = "QASM3_TO_OPTICS_BIT: Final = {0: 1, 1: 0}\n"
_BRIDGE_BLOCK = CONVENTIONS_SOURCE[
    CONVENTIONS_SOURCE.index(_BRIDGE) : CONVENTIONS_SOURCE.index("RZ_PHASE_CONVENTION: Final")
]

# (用例名, 源码替换前, 替换后, 期望触发的规则集合)；空集合表示该写法不应被 L1 计入。
DOCSTRING_INJECTIONS = [
    ("L1-annassign", "\ntype _Matrix2", "\nNEW_CONST: Final = 1\n\ntype _Matrix2", {"L1"}),
    ("L1-assign", "\ntype _Matrix2", "\nNEW_CONST = 1\n\ntype _Matrix2", {"L1"}),
    # docstring 不再紧跟赋值，就只是一个游离的字符串表达式。
    ("L1-docstring-not-adjacent", _BRIDGE, _BRIDGE + "pass\n", {"L1"}),
    # 带合法 docstring 的第五个常量：只有「集合恰为约定的四个」这一条件能抓住它。
    (
        "L1-extra-documented-constant",
        "\ntype _Matrix2",
        '\nNEW_CONST: Final = 1\n"""新常量。\n\n证伪状态：参照系定义。\n"""\n\ntype _Matrix2',
        {"L1"},
    ),
    ("L1-string-assignment-follows", _BRIDGE, _BRIDGE + '_NOTE = "x"\n', {"L1"}),
    ("L1-number-follows", _BRIDGE, _BRIDGE + "0\n", {"L1"}),
    ("L1-name-follows", _BRIDGE, _BRIDGE + "Final\n", {"L1"}),
    ("L1-contracted-removed", _BRIDGE_BLOCK, "", {"L1"}),
    # 公开名字放在私有名字之后：只看第一个目标或第一个元素就会漏掉它。
    ("L1-chained", "\ntype _Matrix2", "\n_NEW_A = NEW_B = 1\n\ntype _Matrix2", {"L1"}),
    ("L1-tuple", "\ntype _Matrix2", "\n_NEW_A, NEW_B = 1, 2\n\ntype _Matrix2", {"L1"}),
    ("L1-list", "\ntype _Matrix2", "\n[_NEW_A, NEW_B] = 1, 2\n\ntype _Matrix2", {"L1"}),
    # 链式赋值后的 docstring 归属不明，不算任何一个名字的属性 docstring。
    (
        "L1-chained-docstring-ambiguous",
        _BRIDGE,
        "QASM3_TO_OPTICS_BIT = _ALIAS = {0: 1, 1: 0}\n",
        {"L1"},
    ),
    # 私有常量可以有 docstring，但不属于约定，不要求标注证伪状态。
    (
        "L1-private-documented-ignored",
        "\ntype _Matrix2",
        '\n_NEW_CONST = 1\n"""私有说明。"""\n\ntype _Matrix2',
        set(),
    ),
    ("L1-private-ignored", "\ntype _Matrix2", "\n_NEW_CONST = 1\n\ntype _Matrix2", set()),
    ("L1-lowercase-ignored", "\ntype _Matrix2", "\nnew_const = 1\n\ntype _Matrix2", set()),
    (
        "L1-nested-ignored",
        "    try:\n        checks",
        "    NEW_CONST = 1\n    try:\n        checks",
        set(),
    ),
    ("L2-missing", "证伪状态：参照系定义。", "", {"L2"}),
    (
        "L2-duplicate",
        "证伪状态：参照系定义。",
        "证伪状态：参照系定义。证伪状态：参照系定义。",
        {"L2"},
    ),
    ("L2-outside-vocabulary", "证伪状态：参照系定义", "证伪状态：待定", {"L2"}),
    # 删掉全部引用后，这些事实也不再被任何常量引用，L4 必然同时触发。
    (
        "L3-crossrepo-without-facts",
        "XR-SP、XR-SM、XR-Z、XR-ASSEMBLE、XR-SEMPARAM、XR-APPLY-MPS、XR-APPLY-SV、\nXR-INIT、XR-INIT-PARSE，",
        "",
        {"L3", "L4"},
    ),
    (
        "L3-reference-frame-cites-fact",
        "证伪状态：参照系定义。",
        "证伪状态：参照系定义。XR-SP。",
        {"L3"},
    ),
    ("L3-dangling-fact", "XR-INIT-PARSE，", "XR-INIT-PARSE、XR-BOGUS，", {"L3"}),
    (
        "L5-missing-path",
        _OPTICS_DOC_TAIL,
        _OPTICS_DOC_TAIL.replace("_optics_snapshot", "_missing"),
        {"L5"},
    ),
]


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [pytest.param(*case[1:], id=case[0]) for case in DOCSTRING_INJECTIONS],
)
def test_docstring_rule_injection(old: str, new: str, expected: set[str]) -> None:
    problems = docstring_problems(_source_with(old, new), FACTS, REPO_ROOT)

    assert _rules(problems) == expected, problems


def test_docstring_rule_flags_an_orphan_fact() -> None:
    orphan = dataclasses.replace(BY_ID["XR-SP"], fact_id="XR-ORPHAN")

    assert _rules(docstring_problems(CONVENTIONS_SOURCE, (*FACTS, orphan), REPO_ROOT)) == {"L4"}


def test_docstring_rules_each_have_an_injection() -> None:
    covered = set().union(*(case[3] for case in DOCSTRING_INJECTIONS)) | {"L4"}

    assert covered == {"L1", "L2", "L3", "L4", "L5"}
