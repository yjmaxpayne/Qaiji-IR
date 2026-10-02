# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""分类、摘要与裁决三者共享的冻结语义词汇表。

下面每一个字面量都会进入语义摘要的取值，因而也会进入规范化哈希。枚举值在构造上
与成员名相同：重命名一个成员是一次 schema 变更，而不是一次重构。
"""

from enum import StrEnum

__all__ = [
    "CartanRole",
    "ConditionModel",
    "EquivLevel",
    "MorphismType",
]


class MorphismType(StrEnum):
    """一个操作施加在量子态上的变换种类。"""

    UNITARY = "UNITARY"
    PERMUTATION = "PERMUTATION"
    MEASUREMENT = "MEASUREMENT"
    PHASE = "PHASE"
    IDENTITY = "IDENTITY"
    CLASSICAL_CTRL = "CLASSICAL_CTRL"


class EquivLevel(StrEnum):
    """保持性裁决可以断言的等价强度。

    只有 ``EXACT`` 与 ``UP_TO_PHASE`` 是可判定的；``UP_TO_LOCAL`` 与
    ``ENTANGLEMENT`` 是为后续层预留的词汇，会在判定入口处被拒绝。
    """

    EXACT = "EXACT"
    UP_TO_PHASE = "UP_TO_PHASE"
    UP_TO_LOCAL = "UP_TO_LOCAL"
    ENTANGLEMENT = "ENTANGLEMENT"


class CartanRole(StrEnum):
    """仅供参考的 Cartan 分解角色；绝不作为裁决的输入。"""

    K = "K"
    A = "A"
    MIXED = "MIXED"
    NONE = "NONE"


class ConditionModel(StrEnum):
    """电路的经典条件是如何被求值的。

    ``FPROC_PLACEHOLDER`` 没有任何生产路径 —— 它只是为多条件前馈预留
    位置，而不是声称已经支持。
    """

    REGISTER_ALU = "REGISTER_ALU"
    FPROC_PLACEHOLDER = "FPROC_PLACEHOLDER"
