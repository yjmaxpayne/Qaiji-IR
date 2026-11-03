# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查规则集 v1 的端到端判据：特化模板、条件体无帧改写、三份相位表与版本标记。"""

import cmath
import math
from dataclasses import replace

import pytest

from qaiji.codec import from_qasm3
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.native import (
    NATIVE_RULESET_VERSION,
    NativeInputError,
    NativeScheduleIR,
    OperationSpec,
    QubitResource,
    ScheduleConfig,
    lower_to_native,
    validate_native_schedule,
)
from qaiji.core.native.recognition import _recognize_group
from qaiji.core.native.rules import _expand_source, _NativeSlot
from qaiji.core.native.scheduler import _schedule_source
from qaiji.core.native.source import _capture_source

HEAD = "OPENQASM 3.0;\nqubit[2] q;\nbit[1] c;\n"
HALF_PI = math.pi / 2
ZERO_HEX = (0.0).hex()


def config():
    """两比特合成配置。CZ 两个方向都有规格，因为 `swap` 的反向 CX 需要它。"""
    durations = {"I": 0, "Z": 0, "RZ": 0, "RX90": 40, "MEASURE": 1000}
    specs = [
        OperationSpec(
            kind=kind,
            qubits=(q,),
            duration_ns=duration,
            resources=(f"q{q}",),
            result_latency_ns=200 if kind == "MEASURE" else 0,
        )
        for q in (0, 1)
        for kind, duration in durations.items()
    ]
    specs += [
        OperationSpec(
            kind="CZ", qubits=pair, duration_ns=96, resources=("q0", "q1"), result_latency_ns=0
        )
        for pair in ((0, 1), (1, 0))
    ]
    return ScheduleConfig(
        qubit_resources=tuple(QubitResource(qubit=q, resource=f"q{q}") for q in (0, 1)),
        operation_specs=tuple(specs),
        cz_couplings=((0, 1),),
    )


def unconditional(body):
    return from_qasm3(HEAD + body)


def branch(body):
    return from_qasm3(HEAD + "c[0] = measure q[0];\nif (c[0] == 1) { " + body + " }\n")


def region(schedule):
    """返回条件区间内的原生操作，按调度顺序。"""
    return [op for op in schedule.operations if op.condition_id is not None]


def rx90_count(operations):
    return sum(op.kind == "RX90" for op in operations)


def assert_frame_free(operations):
    """条件区间内不得有 Z，也不得有非零角的 RZ。只允许单槽 RZ(+0.0)。"""
    for op in operations:
        assert op.kind != "Z"
        if op.kind == "RZ":
            assert op.params[0].hex() == ZERO_HEX


def assert_certified(circuit, schedule):
    report = validate_native_schedule(circuit, schedule, config())
    assert (report.source.status, report.rules.status, report.hp.status) == ("pass",) * 3
    return report


def node_circuit(node, conditional):
    """用 GateType 直接构造电路。条件体前放一个测量，供条件读出。"""
    register = ClassicalRegister("c", 1)
    circuit = Circuit(2)
    circuit.cregs = [register]
    measure = Measure(0, ClassicalBit(register, 0))
    circuit.gates = [measure, Conditional(register, 1, (node,))] if conditional else [node]
    return circuit


def scheduled(circuit, groups=None):
    """按给定的组排程，不做认证。手造的组从这里注入。"""
    snapshot = _capture_source(circuit)
    chosen = _expand_source(snapshot) if groups is None else groups
    return _schedule_source(snapshot, config(), chosen)


# 期望值按模板逐槽推导。一个 R(π) 由 2 个 RX90 组成。条件体中每个有帧比特追加 4 个 RX90。
UNCONDITIONAL_RX90 = [
    ("sx q[0];", 1),  # RX(π/2) 特化为 RX90(0)
    ("sxdg q[0];", 1),  # RX(−π/2) 特化为 RX90(π)
    ("u2(0.3, 0.4) q[0];", 1),  # U3(π/2, φ, λ) 的中段为 1 个 RX90
    ("sdg q[0];", 0),  # U3(0, 0, λ) 只剩 RZ
    ("tdg q[0];", 0),
    ("p(0.3) q[0];", 0),
    ("u1(0.3) q[0];", 0),
    ("rx(pi/2) q[0];", 1),
    ("rx(-pi/2) q[0];", 1),
    ("ry(pi/2) q[0];", 1),
    ("ry(-pi/2) q[0];", 1),
    ("cy q[0], q[1];", 2),  # sdg、cx、s 中只有 cx 产生 2 个
    ("cp(0.3) q[0], q[1];", 4),  # 3 个 p 与 2 个 cx 中只有 cx 产生 4 个
    ("x q[0];", 2),
    ("h q[0];", 1),
    ("cx q[0], q[1];", 2),
    ("swap q[0], q[1];", 6),
    ("crz(0.3) q[0], q[1];", 4),
]
CONDITIONAL_RX90 = [
    ("z q[0];", 4),  # 只有尾部
    ("s q[0];", 4),
    ("t q[0];", 4),
    ("rz(0.3) q[0];", 4),
    ("z q[0]; z q[0];", 8),  # 每组的帧从 0.0 起，各带尾部
    ("h q[0];", 5),  # 1 个 RX90 加尾部
    ("x q[0];", 2),  # 没有 RZ 或 Z 槽，不改写
    ("sx q[0];", 1),  # 特化为纯 RX90，不改写
    ("cx q[0], q[1];", 6),  # 目标比特 2 个 RX90 加尾部，控制比特没有帧
    ("swap q[0], q[1];", 14),  # 6 个 RX90 加两个比特各自的尾部
]


@pytest.mark.parametrize(("body", "expected"), UNCONDITIONAL_RX90)
def test_unconditional_rx90_count(body, expected):
    circuit = unconditional(body)
    schedule = lower_to_native(circuit, config())
    assert rx90_count(schedule.operations) == expected
    assert_certified(circuit, schedule)


@pytest.mark.parametrize(("body", "expected"), CONDITIONAL_RX90)
def test_conditional_rx90_count(body, expected):
    circuit = branch(body)
    schedule = lower_to_native(circuit, config())
    assert rx90_count(region(schedule)) == expected
    assert_frame_free(region(schedule))
    assert_certified(circuit, schedule)


def test_zero_u3_keeps_lambda_slot():
    """U3 的三个零角槽都省略时，保留 RZ(λ)，λ 的零符号不变。"""
    node = Gate(GateType.U3, (0,), (0.0, 0.0, -0.0))
    (group,) = _expand_source(_capture_source(node_circuit(node, conditional=False)))
    assert [(s.kind, s.qubits, [p.hex() for p in s.params]) for s in group.operations] == [
        ("RZ", (0,), [(-0.0).hex()])
    ]


def test_subnormal_angle_is_not_zero():
    """零判据按位比较。最小次正规数不是零：RX 用三槽模板，U3 保留该 RZ 槽。"""
    tiny, h = 5e-324, HALF_PI
    cases = [
        (Gate(GateType.RX, (0,), (tiny,)), [("RX90", -h), ("RZ", tiny), ("RX90", h)]),
        (Gate(GateType.U3, (0,), (0.0, tiny, 0.0)), [("RZ", tiny)]),
    ]
    for node, expected in cases:
        circuit = node_circuit(node, conditional=False)
        (group,) = _expand_source(_capture_source(circuit))
        assert [(s.kind, s.params[0].hex()) for s in group.operations] == [
            (kind, angle.hex()) for kind, angle in expected
        ]
        assert_certified(circuit, lower_to_native(circuit, config()))


TWO_QUBIT = {"CNOT", "CX", "CZ", "SWAP", "ISWAP", "SQISWAP"}
ONE_ANGLE = {"RX", "RY", "RZ", "RX90", "RX180"}
ANGLES = [
    (0.0, 0.2, -0.4),
    (-0.0, -0.0, -0.0),
    (HALF_PI, 0.0, 0.7),
    (-HALF_PI, -0.3, 0.0),
    (math.nextafter(HALF_PI, 4.0), 0.2, -0.4),
    (0.7, 0.2, -0.4),
    (math.tau - 1e-12, math.tau, -math.tau),
    (5e-324, 5e-324, -5e-324),
]


def make_gate(name, angles, direction=(0, 1)):
    qubits = direction if name in TWO_QUBIT else direction[:1]
    params = angles if name == "U3" else angles[:1] if name in ONE_ANGLE else ()
    return Gate(GateType(name), qubits, params)


@pytest.mark.parametrize("name", [member.value for member in GateType])
@pytest.mark.parametrize("angles", ANGLES)
@pytest.mark.parametrize("direction", [(0, 1), (1, 0)])
@pytest.mark.parametrize("conditional", [False, True])
def test_every_template_passes_both_checks(name, angles, direction, conditional):
    circuit = node_circuit(make_gate(name, angles, direction), conditional)
    schedule = lower_to_native(circuit, config())
    assert_certified(circuit, schedule)
    if conditional:
        assert_frame_free(region(schedule))


@pytest.mark.parametrize(
    ("theta", "rules"),
    [(HALF_PI, "pass"), (math.nextafter(HALF_PI, 4.0), "fail")],
)
def test_short_template_needs_exact_angle(theta, rules):
    """短模板只在 θ 按位等于 π/2 时成立。θ 多 1 ulp 时矩阵检查仍判绿，识别器须判红。"""
    circuit = node_circuit(Gate(GateType.RX, (0,), (theta,)), conditional=False)
    (group,) = _expand_source(_capture_source(circuit))
    short = (_NativeSlot(kind="RX90", qubits=(0,), params=(0.0,), ordinal=0),)
    schedule = scheduled(circuit, (replace(group, operations=short),))
    report = validate_native_schedule(circuit, schedule, config())
    assert report.hp.status == "pass"
    assert report.rules.status == rules
    if rules == "fail":
        assert report.rules.issues[0].code == "rule_instance"


def diag(a, b):
    return ((complex(a), 0j), (0j, complex(b)))


def product(operations):
    """按 n(+φ) 约定独立求区间乘积。先作用的操作在左乘积的右侧。"""
    total = diag(1, 1)
    for op in operations:
        if op.kind == "RZ":
            local = diag(cmath.exp(-0.5j * op.params[0]), cmath.exp(0.5j * op.params[0]))
        else:
            assert op.kind == "RX90"
            s, phi = math.sqrt(0.5), op.params[0]
            local = ((s + 0j, -1j * s * cmath.exp(-1j * phi)), (-1j * s * cmath.exp(1j * phi), s))
        total = tuple(
            tuple(sum(local[i][k] * total[k][j] for k in range(2)) for j in range(2))
            for i in range(2)
        )
    return total


# 意图门按 OpenQASM 定义手写。δ 满足：区间乘积 = e^{iδ}·意图门。
# z：乘积为 RZ(π) = e^{−iπ/2}·Z。s：RZ(π/2) = e^{−iπ/4}·S。t：RZ(π/4) = e^{−iπ/8}·T。
# sdg：RZ(−π/2) = e^{iπ/4}·Sdg。rz(0.3)：乘积就是 RZ(0.3)，δ = 0。
INTENDED = [
    ("z q[0];", diag(1, -1), -math.pi / 2),
    ("s q[0];", diag(1, 1j), -math.pi / 4),
    ("t q[0];", diag(1, cmath.exp(0.25j * math.pi)), -math.pi / 8),
    ("sdg q[0];", diag(1, -1j), math.pi / 4),
    ("rz(0.3) q[0];", diag(cmath.exp(-0.15j), cmath.exp(0.15j)), 0.0),
]


@pytest.mark.parametrize(("body", "intended", "delta"), INTENDED)
def test_conditional_z_family_is_frame_free(body, intended, delta):
    circuit = branch(body)
    schedule = lower_to_native(circuit, config())
    ops = region(schedule)
    assert_frame_free(ops)
    report = assert_certified(circuit, schedule)
    actual = product(ops)
    factor = cmath.exp(1j * delta)
    for i in range(2):
        for j in range(2):
            assert abs(actual[i][j] - factor * intended[i][j]) <= 1e-10
    group = schedule.groups[-1]
    assert group.source.body_offset == 0
    assert math.isclose(group.phase_rad, delta, abs_tol=1e-15)
    assert math.isclose(report.groups[-1].expected_phase_rad, delta, abs_tol=1e-15)


# 无条件相位来自固定求值式。U3 取角 (0.7, 0.2, −0.4)，相位为 −(0.2/2 + (−0.4)/2)。
PHASE_HEX = {
    "I": "0x0.0p+0",
    "X": "-0x1.921fb54442d18p+0",
    "Y": "-0x1.921fb54442d18p+0",
    "Z": "0x0.0p+0",
    "H": "-0x1.921fb54442d18p+0",
    "S": "-0x1.921fb54442d18p-1",
    "T": "-0x1.921fb54442d18p-2",
    "RX": "0x0.0p+0",
    "RY": "0x0.0p+0",
    "RZ": "0x0.0p+0",
    "U3": "0x1.999999999999ap-4",
    "RX90": "0x0.0p+0",
    "RX180": "0x0.0p+0",
    "CNOT": "-0x1.921fb54442d18p+1",
    "CX": "-0x1.921fb54442d18p+1",
    "CZ": "0x0.0p+0",
    "SWAP": "-0x1.2d97c7f3321d2p+3",
    "ISWAP": "-0x1.2d97c7f3321d2p+4",
    "SQISWAP": "-0x1.2d97c7f3321d2p+4",
}


@pytest.mark.parametrize("name", [member.value for member in GateType])
@pytest.mark.parametrize("conditional", [False, True])
def test_three_phase_tables_agree(name, conditional):
    """生成器、识别器与矩阵检查各有一份相位表。三者按位相等，只有条件体 Z 为 −π/2。"""
    circuit = node_circuit(make_gate(name, (0.7, 0.2, -0.4)), conditional)
    snapshot = _capture_source(circuit)
    schedule = scheduled(circuit)
    report = validate_native_schedule(circuit, schedule, config())
    node = snapshot.gates[-1].body[0] if conditional else snapshot.gates[-1]
    group = schedule.groups[-1]
    ops = schedule.operations[group.op_start : group.op_stop]
    recognized = _recognize_group(node, group.source, group, ops).expected_phase_rad
    expected = "-0x1.921fb54442d18p+0" if conditional and name == "Z" else PHASE_HEX[name]
    assert recognized is not None
    assert group.phase_rad.hex() == expected
    assert recognized.hex() == expected
    assert report.groups[-1].expected_phase_rad.hex() == expected


def test_conditional_cx_tail_on_target():
    """`cx` 的控制比特没有帧。目标比特的净帧为 2π，w = remainder(π, 2π) = π。"""
    schedule = lower_to_native(branch("cx q[0], q[1];"), config())
    ops = region(schedule)
    assert all(op.kind == "CZ" for op in ops if 0 in op.qubits)
    target = [op.params[0].hex() for op in ops if op.kind == "RX90"][-4:]
    assert target == [math.pi.hex()] * 4


def test_moved_tail_fails_matrix_check():
    """`sqiswap` 两个比特的净帧都不是 2π 的整数倍。尾部换到另一比特时，矩阵检查判红。"""
    circuit = node_circuit(make_gate("SQISWAP", ()), conditional=True)
    groups = _expand_source(_capture_source(circuit))
    assert_certified(circuit, scheduled(circuit, groups))
    body = groups[-1]
    q1 = [i for i, slot in enumerate(body.operations) if slot.qubits == (1,)][-4:]
    assert [body.operations[i].params[0] for i in q1[:2]] == [math.pi, math.pi]
    moved = tuple(
        replace(slot, qubits=(0,)) if i in q1 else slot for i, slot in enumerate(body.operations)
    )
    bad = scheduled(circuit, (*groups[:-1], replace(body, operations=moved)))
    assert validate_native_schedule(circuit, bad, config()).hp.status == "fail"


def test_ruleset_version_and_rule_prefix():
    schedule = lower_to_native(branch("sx q[0]; z q[0];"), config())
    assert NATIVE_RULESET_VERSION == "qaiji.cz_basis.v1"
    assert schedule.ruleset_version == NATIVE_RULESET_VERSION
    assert all(group.rule_id.startswith("cz.v1.") for group in schedule.groups)
    old = schedule.to_json().replace(NATIVE_RULESET_VERSION, "qaiji.cz_basis.v0")
    with pytest.raises(NativeInputError) as caught:
        NativeScheduleIR.from_json(old)
    assert caught.value.code == "enum"


def test_rounding_residue_keeps_tail():
    """净帧 −0.3 + (0.1 + 0.2) = 2⁻⁵⁴，不按位为 0，所以保留尾部。w = 2⁻⁵⁵。"""
    schedule = lower_to_native(branch("u3(0, 0.1 + 0.2, -0.3) q[0];"), config())
    ops = region(schedule)
    assert_frame_free(ops)
    assert [op.params[0] for op in ops] == [math.pi, math.pi, 2.0**-55, 2.0**-55]


def test_angle_near_two_pi_passes():
    circuit = branch("rz(6.283185307178586) q[0];")
    schedule = lower_to_native(circuit, config())
    assert_frame_free(region(schedule))
    assert rx90_count(region(schedule)) == 4
    assert_certified(circuit, schedule)


@pytest.mark.parametrize(
    "body",
    [
        "u3(0, 0.5, -0.5) q[0];",
        "u3(0, pi, -pi) q[0];",
        "u3(-0.0, 1.0, -1.0) q[0];",
        "rz(0) q[0];",
        "rx(-0.0) q[0];",
    ],
)
def test_zero_net_frame_lowers_to_identity_slot(body):
    """净帧按位为 0 且没有脉冲时，区间只有 1 槽 RZ(+0.0)。被吸收的 RZ 角可以非零。"""
    circuit = branch(body)
    schedule = lower_to_native(circuit, config())
    assert [(op.kind, op.qubits, [p.hex() for p in op.params]) for op in region(schedule)] == [
        ("RZ", (0,), [ZERO_HEX])
    ]
    assert_certified(circuit, schedule)


def test_first_template_slot_is_not_identity():
    """反例：取无条件模板的第 1 槽 RZ(−0.5)。识别器与矩阵检查都判红。

    本包没有 L1 层。净帧按 L1 的 VZ 规则 RZ(θ) → ShiftPhase(−θ) 在测试内计算。
    """
    circuit = branch("u3(0, 0.5, -0.5) q[0];")
    groups = _expand_source(_capture_source(circuit))
    first = (_NativeSlot(kind="RZ", qubits=(0,), params=(-0.5,), ordinal=0),)
    bad = scheduled(circuit, (*groups[:-1], replace(groups[-1], operations=first)))
    report = validate_native_schedule(circuit, bad, config())
    assert (report.rules.status, report.hp.status) == ("fail", "fail")
    net = sum(-op.params[0] for op in region(bad) if op.kind == "RZ")
    assert abs(math.remainder(net, math.tau)) > 1e-10
