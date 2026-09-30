# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""SemanticAnnotation 的不可变性，以及 INV-NUM 编号不变量。"""

import json
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from qaiji.core.semantics.annotation import SemanticAnnotation
from qaiji.core.semantics.types import CartanRole, EquivLevel, MorphismType


def test_annotation_defaults_describe_an_unclassified_top_level_node() -> None:
    annotation = SemanticAnnotation(gate_index=0, morphism=MorphismType.UNITARY)

    assert annotation.equiv_level is None
    assert annotation.cartan is CartanRole.NONE
    assert annotation.body_offset is None
    assert annotation.notes == ()


def test_annotation_is_frozen_against_post_hoc_relabelling() -> None:
    """分类是一次裁决，而不是一个可变的标签。

    一条事后可被修改的标注，会让消费方把不受支持的态射"洗"成受支持的，而注册表
    自始至终看不到这次改动。
    """
    annotation = SemanticAnnotation(gate_index=0, morphism=MorphismType.UNITARY)

    with pytest.raises(FrozenInstanceError):
        annotation.morphism = MorphismType.IDENTITY  # type: ignore[misc]


def test_annotation_normalizes_notes_into_a_tuple() -> None:
    annotation = SemanticAnnotation(
        gate_index=0, morphism=MorphismType.PHASE, notes=["rz:identity-equivalent"]
    )

    assert annotation.notes == ("rz:identity-equivalent",)


@pytest.mark.parametrize(
    ("gate_index", "body_offset"),
    [(-2, None), (-5, None), (0, -1), (3, -2)],
)
def test_annotation_rejects_out_of_domain_coordinates(
    gate_index: int, body_offset: int | None
) -> None:
    """超出定义域的坐标是构造期错误。

    -1 是唯一有意义的负 gate_index（INV-NUM-6 哨兵值）；比它更小的值、或负的
    body offset，都属于调用方的 bug，必须大声失败，而不是产出一条谁也定位不到的
    标注。
    """
    with pytest.raises(ValueError):
        SemanticAnnotation(
            gate_index=gate_index, morphism=MorphismType.UNITARY, body_offset=body_offset
        )


def test_inv_num_1_top_level_node_carries_no_body_offset() -> None:
    """顶层节点仅凭其下标即可寻址。"""
    annotation = SemanticAnnotation(gate_index=2, morphism=MorphismType.MEASUREMENT)

    assert annotation.gate_index == 2
    assert annotation.body_offset is None


def test_inv_num_2_body_gate_keeps_the_parent_index_and_adds_an_offset() -> None:
    """体内的门相对其所属 Conditional 寻址，而非全局寻址。

    把体内门摊平进顶层下标空间，会与真正占据那些下标的节点相撞。
    """
    annotation = SemanticAnnotation(gate_index=1, morphism=MorphismType.PERMUTATION, body_offset=0)

    assert (annotation.gate_index, annotation.body_offset) == (1, 0)


def test_inv_num_3_coordinates_are_determined_by_position_alone() -> None:
    """同一位置给出同一坐标 —— 标注的身份由位置决定。"""
    first = SemanticAnnotation(gate_index=1, morphism=MorphismType.PERMUTATION, body_offset=0)
    second = SemanticAnnotation(gate_index=1, morphism=MorphismType.PERMUTATION, body_offset=0)

    assert first == second


def test_inv_num_3_dataclass_does_not_police_the_circuit_upper_bound() -> None:
    """上界校验归 annotate_circuit 管，因为只有它知道电路。

    这个 dataclass 没有指向电路的引用；在这里假装校验上界，只会在唯一无法真正检查
    它的那一层制造虚假的安全感。
    """
    annotation = SemanticAnnotation(gate_index=10_000, morphism=MorphismType.UNITARY)

    assert annotation.gate_index == 10_000


def test_inv_num_5_body_offset_none_round_trips_through_json_as_null() -> None:
    """None 必须以 null 的形式挺过序列化，绝不能坍缩成 0。"""
    annotation = SemanticAnnotation(
        gate_index=0, morphism=MorphismType.UNITARY, equiv_level=EquivLevel.EXACT
    )

    payload = json.dumps(asdict(annotation))
    restored = json.loads(payload)

    assert '"body_offset": null' in payload
    assert restored["body_offset"] is None


def test_inv_num_5_null_offset_is_not_the_same_node_as_offset_zero() -> None:
    """null = "Conditional 本身"；0 = "它的第一个体内门"。

    把 null 读成 0 的消费方，会把整个分支的控制语义归到它内部的第一个门头上。下面
    两条标注只在 offset 上不同、其余完全一致，因此只有 None-to-0 的坍缩才能让这条
    断言失败 —— 若拿态射也不同的节点来比，即便发生坍缩断言照样通过，什么也证明不了。
    """
    node_level = SemanticAnnotation(gate_index=1, morphism=MorphismType.CLASSICAL_CTRL)
    same_node_but_first_body_slot = replace(node_level, body_offset=0)

    assert node_level.body_offset is None
    assert same_node_but_first_body_slot.body_offset == 0
    assert node_level != same_node_but_first_body_slot
