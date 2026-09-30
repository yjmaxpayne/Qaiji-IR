# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""手写合法候选独立验证精确产生式与局部理想算符两道判据。"""

import ast
import inspect
import math
import random
from dataclasses import replace

import pytest

from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Measure
from qaiji.core.native.matrix import _check_local_matrix
from qaiji.core.native.model import NativeOperation, SourceGroup, SourceLocation
from qaiji.core.native.recognition import _recognize_group
from qaiji.core.native.source import _capture_source

NAMES = (
    "I",
    "X",
    "Y",
    "Z",
    "H",
    "S",
    "T",
    "RX",
    "RY",
    "RZ",
    "U3",
    "RX90",
    "RX180",
    "CNOT",
    "CX",
    "CZ",
    "SWAP",
    "ISWAP",
    "SQISWAP",
)
_rng = random.Random(20260927)
TWO = {"CNOT", "CX", "CZ", "SWAP", "ISWAP", "SQISWAP"}
ANGLE = {"RX", "RY", "RZ", "RX90", "RX180"}
SAMPLES = [
    (0, 1, -1),
    *[tuple(_rng.uniform(-math.tau, math.tau) for _ in range(3)) for _ in range(3)],
    (0.7, 0.2, -0.4),
    (0.0, 0.0, 0.0),
    (-0.0, -0.0, -0.0),
    (math.tau, -math.tau, math.pi),
    (-math.tau, math.tau, -math.pi),
]


def manual(name, qubits=(7, 2), angles=(0.7, 0.2, -0.4), source=None):
    """从规格手写执行序列，完全不调用生成器或认证器构造候选。"""
    source = source or SourceLocation(gate_index=3, body_offset=None)
    a, b = qubits
    p = math.pi

    def rz(q, t):
        return ("RZ", (q,), (t,))

    def pulse(q, t):
        return ("RX90", (q,), (t,))

    h_a = [rz(a, p / 2), pulse(a, 0.0), rz(a, p / 2)]
    h_b = [rz(b, p / 2), pulse(b, 0.0), rz(b, p / 2)]
    cx = [*h_b, ("CZ", (a, b), ()), *h_b]
    rev = [*h_a, ("CZ", (b, a), ()), *h_a]
    t, phi, lam = angles
    exchange_angle = -p / 2 if name == "ISWAP" else -p / 4
    zz = [*cx, rz(b, exchange_angle), *cx]
    table = {
        "I": [("I", (a,), ())],
        "Z": [("Z", (a,), ())],
        "X": [pulse(a, 0.0), pulse(a, 0.0)],
        "Y": [pulse(a, p / 2), pulse(a, p / 2)],
        "H": h_a,
        "S": [rz(a, p / 2)],
        "T": [rz(a, p / 4)],
        "RX": [pulse(a, -p / 2), rz(a, t), pulse(a, p / 2)],
        "RY": [pulse(a, 0.0), rz(a, t), pulse(a, p)],
        "RZ": [rz(a, t)],
        "RX90": [pulse(a, t)],
        "RX180": [pulse(a, t), pulse(a, t)],
        "U3": [rz(a, lam), pulse(a, 0.0), rz(a, t), pulse(a, p), rz(a, phi)],
        "CNOT": cx,
        "CX": cx,
        "CZ": [("CZ", (a, b), ())],
        "SWAP": cx + rev + cx,
        "ISWAP": h_a
        + h_b
        + zz
        + h_a
        + h_b
        + [pulse(a, p), pulse(b, p)]
        + zz
        + [pulse(a, 0.0), pulse(b, 0.0)],
        "SQISWAP": h_a
        + h_b
        + zz
        + h_a
        + h_b
        + [pulse(a, p), pulse(b, p)]
        + zz
        + [pulse(a, 0.0), pulse(b, 0.0)],
        "MEASURE": [("MEASURE", (a,), ())],
    }
    phases = {
        "X": -p / 2,
        "Y": -p / 2,
        "H": -p / 2,
        "S": -p / 4,
        "T": -p / 8,
        "U3": -(phi / 2 + lam / 2),
        "CX": -p,
        "CNOT": -p,
        "SWAP": -3 * p,
        "ISWAP": -6 * p,
        "SQISWAP": -6 * p,
    }
    params = angles if name == "U3" else angles[:1] if name in ANGLE else ()
    node = (
        Measure(a, ClassicalBit(ClassicalRegister("c", 1), 0))
        if name == "MEASURE"
        else Gate(GateType(name), qubits if name in TWO else (a,), params)
    )
    ops = tuple(
        NativeOperation(
            kind=k,
            qubits=q,
            params=v,
            source=source,
            ordinal=i,
            start_ns=i,
            duration_ns=int(k not in {"I", "Z", "RZ"}),
            resources=("drive",),
            condition_id=None,
        )
        for i, (k, q, v) in enumerate(table[name])
    )
    group = SourceGroup(
        source=source,
        rule_id="cz.v0." + name,
        op_start=11,
        op_stop=11 + len(ops),
        phase_rad=phases.get(name, 0.0),
    )
    return node, source, group, ops


def rule(data, operations=None, group=None):
    node, source, original, ops = data
    return _recognize_group(
        node, source, group or original, ops if operations is None else operations
    )


@pytest.mark.parametrize("name", (*NAMES, "MEASURE"))
@pytest.mark.parametrize(
    "mutation",
    [
        "correct",
        "kind",
        "qubits",
        "source",
        "ordinal",
        "delete",
        "append_i",
        "append_rz",
        "rule",
        "phase",
        "group_source",
        "span",
        "body_offset",
        "cz_order",
        "later_slot",
        "precedence",
        "phase_zero",
    ],
)
def test_independent_recipe_rejects_mutants(name, mutation):
    assert set(NAMES) == {g.value for g in GateType}
    data = manual(name)
    node, source, group, ops = data
    assert rule(data).code is None
    expected = "rule_instance"
    bad = ops
    if mutation == "correct":
        assert _check_local_matrix(node, ops).status == (
            "not_applicable" if name == "MEASURE" else "pass"
        )
        return
    if mutation == "kind":
        bad = (
            replace(
                ops[0],
                kind="Z" if ops[0].kind == "I" else "I",
                qubits=(7,),
                params=(),
                duration_ns=0,
            ),
            *ops[1:],
        )
    elif mutation == "qubits":
        bad = (replace(ops[0], qubits=tuple(q + 100 for q in ops[0].qubits)), *ops[1:])
    elif mutation == "body_offset":
        if name == "MEASURE":
            group = replace(group, source=replace(source, body_offset=0))
        else:
            bad = (replace(ops[0], source=replace(source, body_offset=0)), *ops[1:])
    elif mutation == "cz_order":
        if name in TWO:
            index = next(i for i, op in enumerate(ops) if op.kind == "CZ")
            bad = tuple(
                replace(op, qubits=op.qubits[::-1]) if i == index else op
                for i, op in enumerate(ops)
            )
            assert _check_local_matrix(node, bad).status == "pass"
        else:
            bad = (replace(ops[0], qubits=(2,)), *ops[1:])
    elif mutation == "later_slot":
        index = len(ops) - 1
        bad = (*ops[:-1], replace(ops[-1], ordinal=999))
        assert rule(data, bad).operation_index == 11 + index
    elif mutation == "precedence":
        bad = (replace(ops[0], ordinal=999), *ops[1:])
        group = replace(group, rule_id="fake", phase_rad=123.0)
        assert rule(data, bad, group).code == "rule_id"
        assert rule(data, bad, replace(group, rule_id="cz.v0." + name)).code == "rule_instance"
        expected = "rule_id"
    elif mutation == "phase_zero":
        zero_data = manual(name, angles=(0.0, 0.0, 0.0))
        znode, _, zgroup, zops = zero_data
        if zgroup.phase_rad == 0.0:
            changed = math.copysign(0.0, -math.copysign(1.0, zgroup.phase_rad))
            assert rule(zero_data, group=replace(zgroup, phase_rad=changed)).code == "rule_phase"
            assert _check_local_matrix(znode, zops).status == (
                "not_applicable" if name == "MEASURE" else "pass"
            )
        return
    elif mutation == "source":
        bad = (replace(ops[0], source=replace(source, gate_index=4)), *ops[1:])
    elif mutation == "ordinal":
        bad = (replace(ops[0], ordinal=1), *ops[1:])
    elif mutation == "delete":
        bad = ops[:-1]
        if bad:
            group = replace(group, op_stop=11 + len(bad))
    elif mutation.startswith("append"):
        k = "I" if mutation == "append_i" else "RZ"
        bad = (
            *ops,
            replace(
                ops[0],
                kind=k,
                qubits=(7,),
                params=() if k == "I" else (0.0,),
                ordinal=len(ops),
                duration_ns=0,
            ),
        )
        group = replace(group, op_stop=11 + len(bad))
    elif mutation == "rule":
        group = replace(group, rule_id="cz.v0.forged")
        expected = "rule_id"
    elif mutation == "phase":
        group = replace(group, phase_rad=group.phase_rad + math.tau)
        expected = "rule_phase"
    elif mutation == "group_source":
        group = replace(group, source=replace(source, gate_index=4))
    elif mutation == "span":
        group = replace(group, op_stop=group.op_stop + 1)
    result = rule(data, bad, group)
    assert result.code == expected
    if expected in {"rule_id", "rule_phase"}:
        assert result.operation_index is None
    if mutation.startswith("append") or (mutation == "delete" and bad):
        assert result.operation_index == 11 + min(len(ops), len(bad))
    if mutation in {"kind", "qubits", "source", "ordinal"}:
        assert result.operation_index == 11
    assert rule(data).code is None


@pytest.mark.parametrize("name", ["RX90", "RZ"])
@pytest.mark.parametrize(
    "original,changed", [(0.0, -0.0), (-0.0, 0.0), (0.7, math.nextafter(0.7, math.inf))]
)
def test_signed_zero_and_nextafter_are_exact(name, original, changed):
    data = manual(name, angles=(original, 0.0, 0.0))
    node, _, _, ops = data
    assert rule(data).code is None
    altered = (replace(ops[0], params=(changed,)),)
    assert rule(data, altered).code == "rule_instance"
    assert _check_local_matrix(node, altered).status == "pass"
    assert rule(data).code is None


@pytest.mark.parametrize(
    "name", (*NAMES, "common", "independence", "iswap_sign", "sqrt_inverse", "sqrt_branch")
)
@pytest.mark.parametrize("angles", SAMPLES)
def test_hp_rejects_common_generator_recognizer_error(name, angles, monkeypatch):
    if name in {"common", "independence", "iswap_sign", "sqrt_inverse", "sqrt_branch"}:
        common_error_case(name, monkeypatch)
        return
    data = manual(name, angles=angles)
    node, _, _, ops = data
    assert rule(data).code is None
    assert _check_local_matrix(node, ops).status == "pass"
    # 假设两份规则共同误加 Z；直接算符仍须拒收，不能消费共同声称的认证状态。
    wrong = (
        *ops,
        replace(ops[0], kind="Z", qubits=(7,), params=(), duration_ns=0, ordinal=len(ops)),
    )
    result = _check_local_matrix(node, wrong)
    assert result.status == "fail"
    assert result.code == "operator_mismatch"
    assert result.max_abs_residual > 0.1
    assert _check_local_matrix(node, ops).status == "pass"


@pytest.mark.parametrize(
    "case",
    [
        "cx_forward",
        "cx_reverse",
        "u3",
        "outside",
        "measure_in_gate",
        "zero_slot",
        "atol_pass",
        "atol_fail",
        "rtol_pass",
    ],
)
def test_local_operand_order_and_product_direction(case):
    if case in {"zero_slot", "atol_pass", "atol_fail", "rtol_pass"}:
        tolerance_case(case)
        return
    name = "U3" if case == "u3" else "CX"
    data = manual(name, qubits=(1, 0) if case == "cx_reverse" else (0, 1))
    node, _, _, ops = data
    assert _check_local_matrix(node, ops).status == "pass"
    if case == "u3":
        wrong = tuple(replace(op, ordinal=i) for i, op in enumerate(reversed(ops)))
    elif case == "outside":
        wrong = (replace(ops[0], qubits=(99,)), *ops[1:])
    elif case == "measure_in_gate":
        wrong = (replace(ops[0], kind="MEASURE", params=(), duration_ns=1), *ops[1:])
    else:
        wrong = tuple(replace(op, qubits=tuple(1 - q for q in op.qubits)) for op in ops)
    result = _check_local_matrix(node, wrong)
    assert result.code == (
        "operand_domain" if case in {"outside", "measure_in_gate"} else "operator_mismatch"
    )
    assert result.status == "fail"
    assert _check_local_matrix(node, ops).status == "pass"


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("angles", [*SAMPLES, (0.7, math.ulp(0.0), math.ulp(0.0))])
@pytest.mark.parametrize("qubits", [(7, 2), (2, 7)])
def test_independent_expected_phase(name, angles, qubits):
    data = manual(name, angles=angles, qubits=qubits)
    node, _, group, ops = data
    assert rule(data).expected_phase_rad.hex() == group.phase_rad.hex()
    hp = _check_local_matrix(node, ops)
    assert hp.status == "pass"
    assert hp.expected_phase_rad.hex() == group.phase_rad.hex()
    for phase in (
        group.phase_rad + math.tau,
        group.phase_rad + 0.4,
        math.nextafter(group.phase_rad, math.inf),
    ):
        assert rule(data, group=replace(group, phase_rad=phase)).code == "rule_phase"
        assert _check_local_matrix(node, ops) == hp
    assert rule(data).code is None


@pytest.mark.parametrize("case", ["empty", "measure", "wide", "conditional"])
def test_no_exponential_matrix_width(case, monkeypatch):
    from qaiji.core.native import matrix

    original_identity = matrix._identity

    def guarded_identity(size):
        assert size in (2, 4)
        return original_identity(size)

    monkeypatch.setattr(matrix, "_identity", guarded_identity)
    circuit = Circuit(10**6)
    if case == "empty":
        snapshot = _capture_source(circuit)
        assert tuple(_check_local_matrix(node, ()) for node in snapshot.gates) == ()
        return
    data = manual(
        "MEASURE" if case == "measure" else "CX",
        qubits=(999999, 1),
        source=SourceLocation(gate_index=3, body_offset=2 if case == "conditional" else None),
    )
    node, _, _, ops = data
    result = _check_local_matrix(node, ops)
    assert rule(data).code is None
    if case == "measure":
        assert result.status == "not_applicable"
        assert result.expected_phase_rad is None
        assert result.max_abs_residual is None
    else:
        assert result.status == "pass"
        assert result.max_abs_residual < 1e-10


@pytest.mark.parametrize("case", ["id", "phase", "extra", "wrong", "six_pulses"])
def test_recipe_failure_does_not_mask_hp(case):
    if case == "six_pulses":
        data = manual("X")
        node, _, group, ops = data
        wrong = tuple(replace(ops[0], ordinal=i) for i in range(6))
        group = replace(group, op_stop=17, phase_rad=math.pi / 2)
        assert rule(data, wrong, group).code == "rule_instance"
        assert _check_local_matrix(node, wrong).code == "operator_mismatch"
        assert _check_local_matrix(node, ops).status == "pass"
        return
    data = manual("H")
    node, _, group, ops = data
    wrong = ops
    if case == "id":
        group = replace(group, rule_id="cz.v0.X")
    elif case == "phase":
        group = replace(group, phase_rad=0.0)
    else:
        wrong = (*ops, replace(ops[0], kind="I" if case == "extra" else "Z", params=(), ordinal=3))
    assert rule(data, wrong, group).code is not None
    assert _check_local_matrix(node, wrong).status == ("fail" if case == "wrong" else "pass")
    assert rule(data).code is None


def tolerance_case(case):
    data = manual("RZ" if case == "rtol_pass" else "RX", angles=(0.0, 0.0, 0.0))
    node, _, group, ops = data
    assert _check_local_matrix(node, ops).status == "pass"
    if case == "zero_slot":
        wrong = tuple(replace(op, ordinal=i) for i, op in enumerate((ops[0], ops[2])))
        group = replace(group, op_stop=13)
    else:
        angle = {"rtol_pass": 2e-8, "atol_pass": 1e-10, "atol_fail": 4e-10}[case]
        wrong = tuple(replace(op, params=(angle,)) if op.kind == "RZ" else op for op in ops)
    assert rule(data, wrong, group).code == "rule_instance"
    assert _check_local_matrix(node, wrong).status == ("fail" if case == "atol_fail" else "pass")
    assert _check_local_matrix(node, ops).status == "pass"


def common_error_case(case, monkeypatch):
    from qaiji.core.native import matrix, recognition, rules

    if case == "independence":
        for module, forbidden in (
            (recognition, {"rules", "scheduler"}),
            (matrix, {"rules", "recognition", "scheduler"}),
        ):
            tree = ast.parse(inspect.getsource(module))
            imports = set()
            for statement in ast.walk(tree):
                if isinstance(statement, ast.ImportFrom):
                    imports.update((statement.module or "").split("."))
                    imports.update(alias.name for alias in statement.names)
                elif isinstance(statement, ast.Import):
                    for alias in statement.names:
                        imports.update(alias.name.split("."))
                elif isinstance(statement, ast.Call):
                    func = statement.func
                    assert not (isinstance(func, ast.Name) and func.id == "__import__")
                    assert not (isinstance(func, ast.Attribute) and func.attr == "import_module")
            assert not (forbidden | {"importlib"}).intersection(imports)
        return
    data = manual(
        "SQISWAP"
        if case in {"sqrt_branch", "sqrt_inverse"}
        else "ISWAP"
        if case == "iswap_sign"
        else "X"
    )
    node, source, group, ops = data
    assert rule(data).code is None
    assert _check_local_matrix(node, ops).status == "pass"
    if case == "sqrt_branch":
        # Z⊗Z 仅把中间块改为另一平方根；平方仍是同一个 +i iSWAP。
        wrong = (
            *ops,
            *(
                replace(
                    ops[0], kind="Z", qubits=(q,), params=(), duration_ns=0, ordinal=len(ops) + i
                )
                for i, q in enumerate(node.qubits)
            ),
        )
        claimed = replace(group, op_stop=11 + len(wrong))
        assert rule(data, wrong, claimed).code == "rule_instance"
        assert _check_local_matrix(node, wrong).code == "operator_mismatch"
        squared = tuple(replace(op, ordinal=i) for i, op in enumerate((*wrong, *wrong)))
        iswap, _, _, _ = manual("ISWAP")
        assert _check_local_matrix(iswap, squared).status == "pass"
    elif case in {"iswap_sign", "sqrt_inverse"}:
        # 只改实际候选的两个 ZZ 角；参考仍是固定 +i / 正平方根源算符。
        wrong = tuple(
            replace(op, params=(-op.params[0],)) if op.kind == "RZ" and op.params[0] < 0 else op
            for op in ops
        )
        assert _check_local_matrix(node, wrong).code == "operator_mismatch"
    else:
        original_slots, original_gate = rules._gate_slots, recognition._Cursor.gate

        def broken_slots(kind, qubits, params=()):
            return (*original_slots(kind, qubits, params), ("Z", (qubits[0],), ()))

        def broken_recognition(cursor, name, qubits, params):
            original_gate(cursor, name, qubits, params)
            cursor.slot("Z", (qubits[0],))

        with monkeypatch.context() as context:
            context.setattr(rules, "_gate_slots", broken_slots)
            context.setattr(recognition._Cursor, "gate", broken_recognition)
            generated = rules._group(node, source)
            wrong = tuple(
                replace(
                    ops[0],
                    kind=slot.kind,
                    qubits=slot.qubits,
                    params=slot.params,
                    duration_ns=int(slot.kind not in {"I", "Z", "RZ"}),
                    ordinal=slot.ordinal,
                )
                for slot in generated.operations
            )
            claimed = replace(group, op_stop=11 + len(wrong))
            assert rule(data, wrong, claimed).code is None
            assert _check_local_matrix(node, wrong).code == "operator_mismatch"
        assert rule(data, wrong, claimed).code == "rule_instance"
    assert rule(data).code is None
    assert _check_local_matrix(node, ops).status == "pass"
