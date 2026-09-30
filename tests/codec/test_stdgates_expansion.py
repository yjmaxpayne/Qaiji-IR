# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""以独立规范参考验证标准门展开的相位、比特序和可序列化性。"""

from __future__ import annotations

import ast
import cmath
import dataclasses
import importlib
import math
import random
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from qaiji.codec.qasm3 import _GATE_REGISTRY, from_qasm3, to_qasm3
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.native.matrix import _embed as qaiji_embed
from qaiji.core.native.matrix import _source_operator

pytestmark = pytest.mark.physics
ATOL = 1e-10
PI = math.pi

# 规范声明独立于被测表，新增或删除规则不能同步改变参考范围。
SHAPES = {
    "p": (1, 1),
    "u1": (1, 1),
    "u2": (1, 2),
    "u": (1, 3),
    "sdg": (1, 0),
    "tdg": (1, 0),
    "sx": (1, 0),
    "sxdg": (1, 0),
    "cy": (2, 0),
    "ch": (2, 0),
    "crx": (2, 1),
    "cry": (2, 1),
    "crz": (2, 1),
    "cp": (2, 1),
    "cu1": (2, 1),
    "cu": (2, 4),
    "cu3": (2, 3),
    "ccx": (3, 0),
    "cswap": (3, 0),
}
PAIRS = (
    ("p", "R3", "EXACT"),
    ("u1", "R3", "EXACT"),
    ("u1", "R2", "UP_TO_PHASE"),
    ("u2", "R3", "UP_TO_PHASE"),
    ("u2", "R2", "UP_TO_PHASE"),
    ("u", "R2", "UP_TO_PHASE"),
    ("sdg", "R3", "EXACT"),
    ("sdg", "R2", "UP_TO_PHASE"),
    ("tdg", "R3", "EXACT"),
    ("tdg", "R2", "UP_TO_PHASE"),
    ("sx", "R3", "UP_TO_PHASE"),
    ("sxdg", "R3", "UP_TO_PHASE"),
    ("cy", "R3", "EXACT"),
    ("cy", "R2", "EXACT"),
    ("ch", "R3", "EXACT"),
    ("ch", "R2", "UP_TO_PHASE"),
    ("crx", "R3", "EXACT"),
    ("cry", "R3", "EXACT"),
    ("crz", "R3", "EXACT"),
    ("crz", "R2", "EXACT"),
    ("cp", "R3", "EXACT"),
    ("cu1", "R2", "UP_TO_PHASE"),
    ("cu", "R3", "EXACT"),
    ("cu3", "R2", "EXACT"),
    ("ccx", "R3", "EXACT"),
    ("ccx", "R2", "UP_TO_PHASE"),
    ("cswap", "R3", "EXACT"),
)


def eye(d):
    return [[complex(i == j) for j in range(d)] for i in range(d)]


def mm(a, b):
    return [
        [sum(a[i][k] * b[k][j] for k in range(len(b))) for j in range(len(b[0]))]
        for i in range(len(a))
    ]


def dag(a):
    return [[a[j][i].conjugate() for j in range(len(a))] for i in range(len(a[0]))]


def sc(c, a):
    return [[c * x for x in row] for row in a]


def diag(*v):
    return [[complex(v[i]) if i == j else 0j for j in range(len(v))] for i in range(len(v))]


def maxdiff(a, b):
    return max(abs(x - y) for ra, rb in zip(a, b, strict=True) for x, y in zip(ra, rb, strict=True))


def gph(x):
    return cmath.exp(1j * x)


def ctrl(g):
    """将第一个操作数作为控制位，即局部最高位。"""
    n = len(g)
    result = eye(2 * n)
    for i in range(n):
        for j in range(n):
            result[n + i][n + j] = g[i][j]
    return result


def embed(mat, qubits, n):
    """独立嵌入任意局部门；全局零号比特和局部首操作数均为高位。"""
    k, d = len(qubits), 2**n
    full = [[0j] * d for _ in range(d)]
    for col in range(d):
        bits = [(col >> (n - 1 - i)) & 1 for i in range(n)]
        sub_in = sum(bits[q] << (k - 1 - j) for j, q in enumerate(qubits))
        for sub_out in range(2**k):
            new_bits = list(bits)
            for j, q in enumerate(qubits):
                new_bits[q] = (sub_out >> (k - 1 - j)) & 1
            row = sum(b << (n - 1 - i) for i, b in enumerate(new_bits))
            full[row][col] += mat[sub_out][sub_in]
    return full


def seq(ops, n):
    """按程序顺序左乘，得到最后一门至第一门的矩阵积。"""
    result = eye(2**n)
    for mat, qubits in ops:
        result = mm(embed(mat, qubits, n), result)
    return result


def level(ref, got):
    """按最大模元素求唯一全局因子，使用绝对容差且不使用相对容差。"""
    i, j = max(
        ((i, j) for i in range(len(ref)) for j in range(len(ref))),
        key=lambda ij: abs(ref[ij[0]][ij[1]]),
    )
    phase = got[i][j] / ref[i][j]
    if abs(abs(phase) - 1) > ATOL or maxdiff(got, sc(phase, ref)) > ATOL:
        return None
    return "EXACT" if abs(phase - 1) <= ATOL else "UP_TO_PHASE"


def principal_sqrt(z):
    """在 (−π, π] 上取主值；只吸收负实轴处浮点舍入的虚部。"""
    angle = cmath.phase(z)
    if z.real < 0 and abs(z.imag) <= 1e-14 * abs(z):
        angle = PI
    return math.sqrt(abs(z)) * cmath.exp(0.5j * angle)


def sqrtm2(mat):
    """用 Sylvester 公式求具有不同特征值的二阶矩阵主平方根。"""
    (a, b), (c, d) = mat
    trace, det = a + d, a * d - b * c
    discriminant = cmath.sqrt(trace * trace - 4 * det)
    l1, l2 = (trace + discriminant) / 2, (trace - discriminant) / 2
    s1, s2 = principal_sqrt(l1), principal_sqrt(l2)
    a_l2, a_l1 = [[a - l2, b], [c, d - l2]], [[a - l1, b], [c, d - l1]]
    return [[(s1 * a_l2[i][j] - s2 * a_l1[i][j]) / (l1 - l2) for j in range(2)] for i in range(2)]


# OpenQASM 3 stdgates.inc 的参考只调用上述复数代数。
def u_oq3(t, p, lam):  # OpenQASM 3 的内置 U 定义。
    e = cmath.exp(1j * t)
    return sc(
        0.5,
        [
            [1 + e, -1j * cmath.exp(1j * lam) * (1 - e)],
            [1j * cmath.exp(1j * p) * (1 - e), cmath.exp(1j * (p + lam)) * (1 + e)],
        ],
    )


def build_r3():
    x3 = sc(gph(-PI / 2), u_oq3(PI, 0, PI))
    y3 = sc(gph(-PI / 2), u_oq3(PI, PI / 2, PI / 2))
    h3 = sc(gph(-PI / 4), u_oq3(PI / 2, 0, PI))

    def p3(lam):
        return ctrl([[gph(lam)]])

    z3 = p3(PI)
    s3 = sqrtm2(z3)

    def rx3(t):
        return sc(gph(-t / 2), u_oq3(t, -PI / 2, PI / 2))

    def ry3(t):
        return sc(gph(-t / 2), u_oq3(t, 0, 0))

    def rz3(lam):
        return sc(gph(-lam / 2), u_oq3(0, 0, lam))

    swap = diag(1, 1, 1, 1)
    swap[1][1] = swap[2][2] = 0j
    swap[1][2] = swap[2][1] = 1 + 0j
    return {
        "p": (1, 1, lambda lam: p3(lam)),
        "sdg": (1, 0, lambda: dag(sqrtm2(z3))),
        "tdg": (1, 0, lambda: dag(sqrtm2(s3))),
        "sx": (1, 0, lambda: sqrtm2(x3)),
        "sxdg": (1, 0, lambda: dag(sqrtm2(x3))),
        "u1": (1, 1, lambda lam: u_oq3(0, 0, lam)),
        "u2": (1, 2, lambda p, lam: sc(gph(-(p + lam + PI / 2) / 2), u_oq3(PI / 2, p, lam))),
        "cy": (2, 0, lambda: ctrl(y3)),
        "cp": (2, 1, lambda lam: ctrl(p3(lam))),
        "crx": (2, 1, lambda t: ctrl(rx3(t))),
        "cry": (2, 1, lambda t: ctrl(ry3(t))),
        "crz": (2, 1, lambda t: ctrl(rz3(t))),
        "ch": (2, 0, lambda: ctrl(h3)),
        "ccx": (3, 0, lambda: ctrl(ctrl(x3))),
        "cswap": (3, 0, lambda: ctrl(swap)),
        "cu": (
            2,
            4,
            lambda t, p, lam, g: seq([(p3(g - t / 2), (0,)), (ctrl(u_oq3(t, p, lam)), (0, 1))], 2),
        ),
    }


# 官方 OpenQASM 2 qelib1.inc 的逐行参考。
def rz_(a):
    return diag(cmath.exp(-0.5j * a), cmath.exp(0.5j * a))


def ry_(a):
    c, s = math.cos(a / 2), math.sin(a / 2)
    return [[complex(c), complex(-s)], [complex(s), complex(c)]]


def u_oq2(t, p, lam):  # OpenQASM 2 内置 U = Rz(phi) Ry(theta) Rz(lambda)。
    return mm(mm(rz_(p), ry_(t)), rz_(lam))


def build_r2():
    def u1(lam):
        return u_oq2(0, 0, lam)

    cx = ctrl([[0j, 1 + 0j], [1 + 0j, 0j]])
    h2 = u_oq2(PI / 2, 0, PI)
    s2, sdg2, t2, tdg2 = u1(PI / 2), u1(-PI / 2), u1(PI / 4), u1(-PI / 4)
    x2 = u_oq2(PI, 0, PI)

    def ccx2():
        a, b, c = 0, 1, 2
        return seq(
            [
                (h2, (c,)),
                (cx, (b, c)),
                (tdg2, (c,)),
                (cx, (a, c)),
                (t2, (c,)),
                (cx, (b, c)),
                (tdg2, (c,)),
                (cx, (a, c)),
                (t2, (b,)),
                (t2, (c,)),
                (h2, (c,)),
                (cx, (a, b)),
                (t2, (a,)),
                (tdg2, (b,)),
                (cx, (a, b)),
            ],
            3,
        )

    return {
        "sdg": (1, 0, lambda: sdg2),
        "tdg": (1, 0, lambda: tdg2),
        "u1": (1, 1, u1),
        "u2": (1, 2, lambda p, lam: u_oq2(PI / 2, p, lam)),
        "cy": (2, 0, lambda: seq([(sdg2, (1,)), (cx, (0, 1)), (s2, (1,))], 2)),
        "ch": (
            2,
            0,
            lambda: seq(
                [
                    (h2, (1,)),
                    (sdg2, (1,)),
                    (cx, (0, 1)),
                    (h2, (1,)),
                    (t2, (1,)),
                    (cx, (0, 1)),
                    (t2, (1,)),
                    (h2, (1,)),
                    (s2, (1,)),
                    (x2, (1,)),
                    (s2, (0,)),
                ],
                2,
            ),
        ),
        "ccx": (3, 0, ccx2),
        "crz": (
            2,
            1,
            lambda lam: seq(
                [(u1(lam / 2), (1,)), (cx, (0, 1)), (u1(-lam / 2), (1,)), (cx, (0, 1))], 2
            ),
        ),
        "cu1": (
            2,
            1,
            lambda lam: seq(
                [
                    (u1(lam / 2), (0,)),
                    (cx, (0, 1)),
                    (u1(-lam / 2), (1,)),
                    (cx, (0, 1)),
                    (u1(lam / 2), (1,)),
                ],
                2,
            ),
        ),
        "cu3": (
            2,
            3,
            lambda t, p, lam: seq(
                [
                    (u1((lam - p) / 2), (1,)),
                    (cx, (0, 1)),
                    (u_oq2(-t / 2, 0, -(p + lam) / 2), (1,)),
                    (cx, (0, 1)),
                    (u_oq2(t / 2, p, 0), (1,)),
                ],
                2,
            ),
        ),
        # u 采用 OpenQASM 2 内置 U；官方 qelib1 未另行定义此别名。
        "u": (1, 3, lambda t, p, lam: u_oq2(t, p, lam)),
    }


R3, R2 = build_r3(), build_r2()


def anchors(n_params):
    """每个参数位置都覆盖两个固定锚点，随后覆盖固定种子的非退化输入。"""
    if not n_params:
        return ((),)
    fixed = (PI / 5, -PI / 3, 0.7, 2.3)
    values = [tuple(fixed[(i + shift) % 4] for i in range(n_params)) for shift in range(4)]
    rng = random.Random(20260928)
    for _ in range(8):
        row = []
        while len(row) < n_params:
            value = rng.uniform(-4 * PI, 4 * PI)
            if abs(value / (PI / 2) - round(value / (PI / 2))) > 0.05 and value not in row:
                row.append(value)
        values.append(tuple(row))
    return tuple(values)


def expansions():
    # 延迟导入让参考自证在尚无实现时也能执行。
    return importlib.import_module("qaiji.codec._stdgates")._EXPANSIONS


def gates_unitary(gates, n):
    return seq([(_source_operator(gate), gate.qubits) for gate in gates], n)


def equivalent_swap_reason(first, second):
    if set(first.qubits).isdisjoint(second.qubits):
        return "作用于不相交比特"
    for diagonal, cx in ((first, second), (second, first)):
        if cx.gate_type == GateType.CX and diagonal.qubits == (cx.qubits[0],):
            mat = _source_operator(diagonal)
            if abs(mat[0][1]) <= ATOL and abs(mat[1][0]) <= ATOL:
                return "控制位上的对角门与 CX 可交换"
    if first.gate_type == second.gate_type == GateType.CX and first.qubits[1] == second.qubits[1]:
        return "同一目标位、不同控制位的 CX 可交换"
    return None


def test_reference_primitives_pin_conventions():
    cx_literal = (
        (1, 0, 0, 0),
        (0, 1, 0, 0),
        (0, 0, 0, 1),
        (0, 0, 1, 0),
    )
    cx = _source_operator(Gate(GateType.CX, (0, 1)))
    assert maxdiff(cx, cx_literal) == 0
    assert maxdiff(embed(cx, (0, 1), 2), cx_literal) == 0
    cx_2_to_0 = (
        (1, 0, 0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 1, 0, 0),
        (0, 0, 1, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0, 0, 1),
        (0, 0, 0, 0, 1, 0, 0, 0),
        (0, 1, 0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0, 1, 0),
        (0, 0, 0, 1, 0, 0, 0, 0),
    )
    assert maxdiff(embed(cx, (2, 0), 3), cx_2_to_0) == 0
    assert maxdiff(embed(cx, (0, 2), 3), cx_2_to_0) == 1
    for position in (0, 1):
        rz = rz_(PI / 5)
        assert maxdiff(embed(rz, (position,), 2), qaiji_embed(rz, position)) == 0
    assert maxdiff(rz_(PI / 5), diag(gph(-PI / 10), gph(PI / 10))) == 0
    assert abs(principal_sqrt(complex(-1, -0.0)) - 1j) <= ATOL
    assert abs(principal_sqrt(gph(-PI + 1e-6)) - gph((-PI + 1e-6) / 2)) <= ATOL
    x_literal = [[0, 1], [1, 0]]
    sx_literal = [[(1 + 1j) / 2, (1 - 1j) / 2], [(1 - 1j) / 2, (1 + 1j) / 2]]
    for theta, lam in ((PI, PI), (-PI, PI), (PI, -PI)):
        source = sc(gph(-PI / 2), u_oq3(theta, 0, lam))
        root = sqrtm2(source)
        assert maxdiff(source, x_literal) <= ATOL
        assert maxdiff(root, sx_literal) <= ATOL
        assert maxdiff(mm(root, root), source) <= ATOL
        # 同源的伴随也是 X 的平方根，但与主值根有可观测差别。
        other_root = dag(root)
        assert maxdiff(mm(other_root, other_root), source) <= ATOL
        assert level(root, other_root) is None
    z = diag(1, -1)
    s = sqrtm2(z)
    assert maxdiff(mm(s, s), z) <= ATOL
    assert maxdiff(mm(sqrtm2(s), sqrtm2(s)), s) <= ATOL


def test_phase_alignment_judges_global_versus_relative_phase():
    # 非对称且非实的矩阵让实数、迹或子空间分开对齐的错误无处隐藏。
    reference = ctrl(u_oq3(PI / 5, -PI / 3, 0.7))
    assert level(reference, reference) == "EXACT"
    assert level(reference, sc(gph(0.37), reference)) == "UP_TO_PHASE"
    relative = [row[:] for row in reference]
    for i in (2, 3):
        relative[i] = [gph(0.37) * value for value in relative[i]]
    assert level(reference, relative) is None
    assert level(reference, sc(2, reference)) is None
    damaged = [row[:] for row in reference]
    damaged[0][1] = 0.1j
    assert level(reference, damaged) is None


@pytest.mark.parametrize(
    ("name", "reference", "declared"), PAIRS, ids=[f"{name}-{ref}" for name, ref, _ in PAIRS]
)
def test_expansion_matches_reference_at_declared_level(name, reference, declared):
    arity, n_params, build_reference = (R3 if reference == "R3" else R2)[name]
    for params in anchors(n_params):
        gates = expansions()[name].build(tuple(range(arity)), params)
        assert level(build_reference(*params), gates_unitary(gates, arity)) == declared, params


@pytest.mark.parametrize("name", SHAPES)
def test_expansion_tampering_is_detected(name):
    arity, n_params, reference = R3.get(name) or R2[name]
    params = anchors(n_params)[0]
    ref = reference(*params)
    build = expansions()[name].build
    base = build(tuple(range(arity)), params)
    for i, gate in enumerate(base):
        for j in range(len(gate.params)):
            changed = list(gate.params)
            changed[j] += 1e-7
            mutant = list(base)
            mutant[i] = Gate(gate.gate_type, gate.qubits, tuple(changed))
            assert level(ref, gates_unitary(mutant, arity)) is None, ("angle", i, j)
        if len(gate.qubits) == 2:
            mutant = list(base)
            mutant[i] = Gate(gate.gate_type, gate.qubits[::-1], gate.params)
            assert level(ref, gates_unitary(mutant, arity)) is None, ("operands", i)
        assert level(ref, gates_unitary(base[:i] + base[i + 1 :], arity)) is None, ("delete", i)
    for j in range(n_params):
        changed = tuple(-value if i == j else value for i, value in enumerate(params))
        assert level(ref, gates_unitary(build(tuple(range(arity)), changed), arity)) is None, (
            "sign",
            j,
        )
    if n_params:
        inverted = build(tuple(range(arity)), tuple(-value for value in params))
        assert level(ref, gates_unitary(inverted, arity)) is None, "all signs"
    for i in range(len(base) - 1):
        first, second = base[i : i + 2]
        left = embed(_source_operator(first), first.qubits, arity)
        right = embed(_source_operator(second), second.qubits, arity)
        mutant = list(base)
        mutant[i : i + 2] = second, first
        if maxdiff(mm(left, right), mm(right, left)) <= ATOL:
            assert equivalent_swap_reason(first, second) is not None, ("equivalent", i)
            assert level(gates_unitary(base, arity), gates_unitary(mutant, arity)) == "EXACT"
        else:
            assert level(ref, gates_unitary(mutant, arity)) is None, ("order", i)


def test_cu3_follows_official_qelib1():
    for params in anchors(3):
        official = R2["cu3"][2](*params)
        got = gates_unitary(expansions()["cu3"].build((0, 1), params), 2)
        theta, phi, lam = params
        # Qiskit 读法为 ctrl@U3conv；独立构造，不能借用被测 cu 实现。
        qiskit = ctrl(sc(gph(-theta / 2), u_oq3(theta, phi, lam)))
        assert level(official, got) == "EXACT"
        assert level(official, qiskit) is None


def test_anchors_avoid_blind_angles():
    assert len(PAIRS) == 27
    assert {(name, ref) for name, ref, _ in PAIRS} == (
        {(name, "R3") for name in R3} | {(name, "R2") for name in R2}
    )
    for n_params in range(1, 5):
        samples = anchors(n_params)
        assert samples == anchors(n_params)
        for position in range(n_params):
            column = {sample[position] for sample in samples}
            assert {PI / 5, -PI / 3} <= column
        for sample in samples:
            assert len(set(sample)) == n_params
            for value in sample:
                assert value != 0
                assert abs(value / (PI / 2) - round(value / (PI / 2))) > 0.05


def test_expansion_table_shape_is_literal():
    table = expansions()
    assert isinstance(table, Mapping)
    assert {name: (entry.arity, entry.n_params) for name, entry in table.items()} == SHAPES
    assert len(table) == 19
    for name, entry in table.items():
        assert entry.name == name
        assert [field.name for field in dataclasses.fields(entry)] == [
            "name",
            "arity",
            "n_params",
            "build",
        ]
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.name = "changed"
        result = entry.build(tuple(range(entry.arity)), anchors(entry.n_params)[0])
        assert isinstance(result, tuple)
        if entry.arity == 1:
            assert len(result) == 1


def test_expansion_names_are_disjoint_from_registry():
    assert not expansions().keys() & _GATE_REGISTRY.keys()


def test_expansion_targets_are_registered_gate_types():
    registered = {spec.gate_type for spec in _GATE_REGISTRY.values()}
    for name, (arity, n_params) in SHAPES.items():
        # 非连续、逆序操作数同时守护 builder 没有偷偷使用 0、1、2。
        qubits = (4, 1, 3)[:arity]
        for params in anchors(n_params):
            gates = expansions()[name].build(qubits, params)
            assert all(gate.gate_type in registered for gate in gates)
            assert all(set(gate.qubits) <= set(qubits) for gate in gates)
            contiguous = expansions()[name].build(tuple(range(arity)), params)
            relabeled = tuple(
                Gate(gate.gate_type, tuple(qubits[q] for q in gate.qubits), gate.params)
                for gate in contiguous
            )
            assert gates == relabeled
            circuit = Circuit(5)
            for gate in gates:
                circuit.add_gate(gate)
            assert from_qasm3(to_qasm3(circuit)).gates == circuit.gates


def test_expansion_module_imports_only_stdlib_and_qaiji():
    module = importlib.import_module("qaiji.codec._stdgates")
    tree = ast.parse(Path(module.__file__).read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            roots.add(node.module.split(".")[0])
    assert roots <= sys.stdlib_module_names | {"qaiji"}
    assert "numpy" not in sys.modules
