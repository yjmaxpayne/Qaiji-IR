# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""门分类分桶、编号入口，以及对定义域之外输入的拒绝。"""

import math

import pytest

from qaiji.core.circuit import TWO_QUBIT_GATES, Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.semantics import registry
from qaiji.core.semantics.registry import annotate_circuit, classify_operation
from qaiji.core.semantics.types import CartanRole, EquivLevel, MorphismType

PARAM_COUNTS = {
    GateType.RX: 1,
    GateType.RY: 1,
    GateType.RZ: 1,
    GateType.U3: 3,
    GateType.RX90: 1,
    GateType.RX180: 1,
}
EXPECTED_MORPHISM = {
    GateType.I: MorphismType.IDENTITY,
    GateType.X: MorphismType.PERMUTATION,
    GateType.CNOT: MorphismType.PERMUTATION,
    GateType.CX: MorphismType.PERMUTATION,
    GateType.SWAP: MorphismType.PERMUTATION,
    GateType.Z: MorphismType.PHASE,
    GateType.S: MorphismType.PHASE,
    GateType.T: MorphismType.PHASE,
    GateType.CZ: MorphismType.PHASE,
    GateType.H: MorphismType.UNITARY,
    GateType.Y: MorphismType.UNITARY,
    GateType.RX: MorphismType.UNITARY,
    GateType.RY: MorphismType.UNITARY,
    GateType.RX90: MorphismType.UNITARY,
    GateType.RX180: MorphismType.UNITARY,
    GateType.U3: MorphismType.UNITARY,
    GateType.ISWAP: MorphismType.UNITARY,
    GateType.SQISWAP: MorphismType.UNITARY,
    GateType.RZ: MorphismType.PHASE,
}
EXPECTED_CARTAN = {
    GateType.I: CartanRole.NONE,
    GateType.X: CartanRole.K,
    GateType.Y: CartanRole.K,
    GateType.Z: CartanRole.K,
    GateType.H: CartanRole.K,
    GateType.S: CartanRole.K,
    GateType.T: CartanRole.K,
    GateType.RX: CartanRole.K,
    GateType.RY: CartanRole.K,
    GateType.RZ: CartanRole.K,
    GateType.U3: CartanRole.K,
    GateType.RX90: CartanRole.K,
    GateType.RX180: CartanRole.K,
    GateType.CNOT: CartanRole.MIXED,
    GateType.CX: CartanRole.MIXED,
    GateType.SWAP: CartanRole.MIXED,
    GateType.CZ: CartanRole.A,
    GateType.ISWAP: CartanRole.A,
    GateType.SQISWAP: CartanRole.A,
}


def build_gate(gate_type: GateType, angle: float = 0.25) -> Gate:
    """构造一个指定类型的、最小的合法门。"""
    qubits = (0, 1) if gate_type in TWO_QUBIT_GATES else (0,)
    params = tuple(angle for _ in range(PARAM_COUNTS.get(gate_type, 0)))
    return Gate(gate_type, qubits, params)


# --- 定义域之外的拒绝（先于正向用例写就）-------------------------------------


def test_unbucketed_gate_type_raises_key_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """没人分类过的门类型必须中止流水线，而不是走默认分桶。

    当未来某个切片新增一个 GateType 时，静默的兜底分桶会把它标成 UNITARY，让一个
    未经验证的操作流进哈希和保持性裁决。大声失败，正是"掌握语义权威"这件事的全部
    意义所在。
    """
    thinned = {
        key: value for key, value in registry._GATE_MORPHISM.items() if key is not GateType.H
    }
    monkeypatch.setattr(registry, "_GATE_MORPHISM", thinned)

    with pytest.raises(KeyError):
        classify_operation(build_gate(GateType.H))


@pytest.mark.parametrize("payload", ["H", 42, None, ("gate",), Circuit(1)])
def test_non_operation_object_raises_type_error(payload: object) -> None:
    """分类只定义在 IR 节点上，不适用于形似的冒牌对象。"""
    with pytest.raises(TypeError):
        classify_operation(payload)  # type: ignore[arg-type]


# --- 门分桶 -----------------------------------------------------------------


def test_classification_tables_cover_every_gate_type() -> None:
    """这些表必须跟踪 GateType 本身，而不是一份手抄的列表。

    本文件里其余测试都以 EXPECTED_MORPHISM 做参数化，而那份表是手工誊抄的 —— 于是
    新增一个 GateType 不会惊动注册表，整个套件照样全绿，直到运行期抛出 KeyError。
    真正把 AC-Q1（"任何合法 Circuit 的每个操作都可判定"）钉在 CI 上的，是与枚举
    本身做比较。
    """
    assert set(registry._GATE_MORPHISM) == set(GateType)
    assert set(registry._GATE_CARTAN) == set(GateType)
    assert set(EXPECTED_MORPHISM) == set(GateType)
    assert set(EXPECTED_CARTAN) == set(GateType)


@pytest.mark.parametrize("gate_type", list(EXPECTED_MORPHISM))
def test_every_gate_type_lands_in_its_declared_bucket(gate_type: GateType) -> None:
    """全部 19 种门类型都可判定 —— AC-Q1 没有例外。"""
    (annotation,) = classify_operation(build_gate(gate_type))

    assert annotation.morphism is EXPECTED_MORPHISM[gate_type]
    assert annotation.cartan is EXPECTED_CARTAN[gate_type]


@pytest.mark.parametrize("gate_type", list(EXPECTED_MORPHISM))
def test_registry_annotations_are_always_exact(gate_type: GateType) -> None:
    """分类本身绝不会削弱等价级别。"""
    (annotation,) = classify_operation(build_gate(gate_type))

    assert annotation.equiv_level is EquivLevel.EXACT


@pytest.mark.physics
@pytest.mark.parametrize("winding", [0, 1, 2, 1_000_000])
def test_rz_at_a_whole_turn_is_classified_as_identity(winding: int) -> None:
    """RZ(2*pi*k) 对任意 k 都是恒等，而不只是 k 属于 {0, 1} 时。

    上游只把 theta 与 0 和 2*pi 这两个字面量作比较；qaiji 借助共享的绕数谓词判定
    一般情形，因此大 k 的旋转不会被误归档成一个它并未施加的相位。
    """
    (annotation,) = classify_operation(Gate(GateType.RZ, (0,), (winding * math.tau,)))

    assert annotation.morphism is MorphismType.IDENTITY
    assert "rz:identity-equivalent" in annotation.notes


@pytest.mark.physics
def test_rz_off_a_whole_turn_stays_a_phase() -> None:
    (annotation,) = classify_operation(Gate(GateType.RZ, (0,), (math.tau + 0.7,)))

    assert annotation.morphism is MorphismType.PHASE
    assert annotation.notes == ()


# --- Measure / Conditional --------------------------------------------------


def test_measure_is_classified_as_a_measurement() -> None:
    register = ClassicalRegister("c", 1)
    (annotation,) = classify_operation(Measure(0, ClassicalBit(register, 0)))

    assert annotation.morphism is MorphismType.MEASUREMENT
    assert annotation.cartan is CartanRole.NONE
    assert annotation.body_offset is None


def test_conditional_emits_a_node_verdict_plus_one_per_body_gate() -> None:
    """分支本身与它执行的内容是两个独立的事实。

    把体内门改写成 CLASSICAL_CTRL，会重复计算控制语义，并抹掉分支触发后实际运行的
    内容。
    """
    register = ClassicalRegister("c", 1)
    conditional = Conditional(register, 1, (Gate(GateType.X, (1,)), Gate(GateType.Z, (0,))))

    node, first_body, second_body = classify_operation(conditional, gate_index=3)

    assert (node.morphism, node.body_offset) == (MorphismType.CLASSICAL_CTRL, None)
    assert (first_body.morphism, first_body.body_offset) == (MorphismType.PERMUTATION, 0)
    assert (second_body.morphism, second_body.body_offset) == (MorphismType.PHASE, 1)
    assert {annotation.gate_index for annotation in (node, first_body, second_body)} == {3}


def test_empty_conditional_body_yields_only_the_node_verdict() -> None:
    register = ClassicalRegister("c", 1)

    annotations = classify_operation(Conditional(register, 1, ()), gate_index=0)

    assert len(annotations) == 1
    assert annotations[0].morphism is MorphismType.CLASSICAL_CTRL


# --- annotate_circuit：权威的编号入口 ---------------------------------------


def test_inv_num_4_conditional_body_annotations_follow_their_node() -> None:
    """顺序由位置决定：先按顶层顺序，体内门紧跟在其分支之后。"""
    register = ClassicalRegister("c", 1)
    circuit = Circuit(2)
    circuit.add_register(register)
    circuit.h(0)
    circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
    circuit.add_conditional(Conditional(register, 1, (Gate(GateType.X, (1,)),)))
    circuit.z(1)

    coordinates = [
        (annotation.gate_index, annotation.body_offset, annotation.morphism)
        for annotation in annotate_circuit(circuit)
    ]

    assert coordinates == [
        (0, None, MorphismType.UNITARY),
        (1, None, MorphismType.MEASUREMENT),
        (2, None, MorphismType.CLASSICAL_CTRL),
        (2, 0, MorphismType.PERMUTATION),
        (3, None, MorphismType.PHASE),
    ]


def test_annotate_circuit_never_emits_the_sentinel_index() -> None:
    """本测试了结的上游欠债：编号是生成出来的，不是事后回填的。

    上游的分类器总是输出 -1，指望每个调用方事后用 replace() 换上真实下标；只要有
    一个调用方忘了，就会静默产出无法寻址的标注。
    """
    register = ClassicalRegister("c", 1)
    circuit = Circuit(2)
    circuit.add_register(register)
    circuit.h(0)
    circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
    circuit.add_conditional(Conditional(register, 1, (Gate(GateType.X, (1,)),)))

    assert all(annotation.gate_index >= 0 for annotation in annotate_circuit(circuit))


def test_annotate_circuit_coordinates_are_unique_within_one_run() -> None:
    register = ClassicalRegister("c", 1)
    circuit = Circuit(2)
    circuit.add_register(register)
    circuit.add_conditional(
        Conditional(register, 1, (Gate(GateType.X, (1,)), Gate(GateType.Z, (1,))))
    )
    circuit.add_conditional(Conditional(register, 0, (Gate(GateType.X, (0,)),)))

    annotations = annotate_circuit(circuit)
    coordinates = [(item.gate_index, item.body_offset) for item in annotations]

    assert len(set(coordinates)) == len(coordinates)


def test_inv_num_6_concatenating_detached_probes_produces_colliding_coordinates() -> None:
    """以实验的形式说明：为什么禁止把 classify_operation 的结果拼接起来。

    每次游离探针都默认取哨兵下标，于是两个真正不同的门经探针返回后共享同一个坐标。
    一旦拼接，就构成一个任何节点都无法寻址的序列 —— 这正是任何序列都必须来自
    annotate_circuit 的原因。
    """
    probes = (
        *classify_operation(build_gate(GateType.H)),
        *classify_operation(build_gate(GateType.Z)),
    )
    coordinates = [(item.gate_index, item.body_offset) for item in probes]

    assert [item.morphism for item in probes] == [
        MorphismType.UNITARY,
        MorphismType.PHASE,
    ]
    assert len(set(coordinates)) < len(coordinates)


def test_annotate_circuit_is_deterministic() -> None:
    circuit = Circuit(2)
    circuit.h(0)
    circuit.cx(0, 1)

    assert annotate_circuit(circuit) == annotate_circuit(circuit)


def test_annotate_circuit_of_an_empty_circuit_is_empty() -> None:
    assert annotate_circuit(Circuit(1)) == ()


# --- I-Q4.4 变异测试 --------------------------------------------------------


def test_cartan_table_is_advisory_and_does_not_steer_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """篡改 Cartan 表只应改变 Cartan 字段，不应撼动其他任何东西。

    Cartan 角色是从上游继承来的参考性元数据。如果某天有裁决开始依赖它们，这次变异
    就会改变某个态射或某个等价级别 —— 而这种依赖，恰恰是 L4 权威绝不能有的。
    """
    circuit = Circuit(2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.rz(0, math.tau)
    baseline = annotate_circuit(circuit)

    monkeypatch.setattr(registry, "_GATE_CARTAN", dict.fromkeys(GateType, CartanRole.MIXED))
    mutated = annotate_circuit(circuit)

    assert [item.morphism for item in mutated] == [item.morphism for item in baseline]
    assert [item.equiv_level for item in mutated] == [item.equiv_level for item in baseline]
    assert [item.notes for item in mutated] == [item.notes for item in baseline]
    assert all(item.cartan is CartanRole.MIXED for item in mutated)
    assert [item.cartan for item in baseline] != [item.cartan for item in mutated]
