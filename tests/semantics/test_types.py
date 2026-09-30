# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""语义词汇表契约：成员集合与冻结的字面量取值。"""

import json

import pytest

from qaiji.core.semantics.types import (
    CartanRole,
    ConditionModel,
    EquivLevel,
    MorphismType,
)

MORPHISM_MEMBERS = {
    "UNITARY",
    "PERMUTATION",
    "MEASUREMENT",
    "PHASE",
    "IDENTITY",
    "CLASSICAL_CTRL",
}
EQUIV_LEVEL_MEMBERS = {"EXACT", "UP_TO_PHASE", "UP_TO_LOCAL", "ENTANGLEMENT"}
CARTAN_ROLE_MEMBERS = {"K", "A", "MIXED", "NONE"}
CONDITION_MODEL_MEMBERS = {"REGISTER_ALU", "FPROC_PLACEHOLDER"}

ALL_ENUMS = (MorphismType, EquivLevel, CartanRole, ConditionModel)


@pytest.mark.parametrize(
    ("enum_type", "expected_members"),
    [
        (MorphismType, MORPHISM_MEMBERS),
        (EquivLevel, EQUIV_LEVEL_MEMBERS),
        (CartanRole, CARTAN_ROLE_MEMBERS),
        (ConditionModel, CONDITION_MODEL_MEMBERS),
    ],
)
def test_enum_member_set_is_the_frozen_contract(
    enum_type: type[MorphismType | EquivLevel | CartanRole | ConditionModel],
    expected_members: set[str],
) -> None:
    """增删任一成员都会静默地扩张语义词汇表。"""
    assert {member.name for member in enum_type} == expected_members


@pytest.mark.parametrize("enum_type", ALL_ENUMS)
def test_literal_value_equals_member_name(
    enum_type: type[MorphismType | EquivLevel | CartanRole | ConditionModel],
) -> None:
    """这些字面量会落进摘要的键与规范化哈希。

    取值一旦与成员名脱钩就是一次哈希漂移：同一个电路在不同版本间会产出不同的身份。
    因此重命名成员是一次 schema 变更，绝不是重构。
    """
    for member in enum_type:
        assert member.value == member.name


@pytest.mark.parametrize("enum_type", ALL_ENUMS)
def test_every_member_serializes_as_a_plain_json_string(
    enum_type: type[MorphismType | EquivLevel | CartanRole | ConditionModel],
) -> None:
    """规范化哈希会把它们直接交给 json.dumps，不经任何编码器。"""
    for member in enum_type:
        assert json.dumps(member) == f'"{member.value}"'


def test_partial_equivalence_levels_are_referenceable() -> None:
    """UP_TO_LOCAL / ENTANGLEMENT 在任何判定器出现之前就先作为词汇存在。

    把它们作为*判定请求*来拒绝，是 check_preservation（T3.1）的职责；词汇表本身
    不该假装它们不被支持。
    """
    assert EquivLevel.UP_TO_LOCAL.value == "UP_TO_LOCAL"
    assert EquivLevel.ENTANGLEMENT.value == "ENTANGLEMENT"


def test_fproc_placeholder_is_reserved_without_a_production_path() -> None:
    """QM2 没有任何构造多条件前馈的路径。

    保留该成员是为了让 condition_model 日后可以扩展而无需递增 schema 版本；它不该
    被解读为已支持 FPROC 的声明。
    """
    assert ConditionModel.FPROC_PLACEHOLDER.value == "FPROC_PLACEHOLDER"
