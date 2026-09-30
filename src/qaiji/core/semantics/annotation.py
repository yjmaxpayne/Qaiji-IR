# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""附着在电路中某一个操作上的、带位置信息的语义裁决。"""

from dataclasses import dataclass

from qaiji.core.semantics.types import CartanRole, EquivLevel, MorphismType

__all__ = ["SemanticAnnotation"]

SENTINEL_GATE_INDEX = -1
"""游离的单节点探针所用的 gate_index；它永远不属于任何序列。"""


@dataclass(frozen=True, slots=True)
class SemanticAnnotation:
    """一个操作的语义含义，以及它在电路中的位置。

    坐标遵循 INV-NUM 不变量：顶层节点是 ``(index, None)``；Conditional 体内的门是
    ``(父节点 index, offset)``。``body_offset`` 为 ``None`` 和为 ``0`` 是两个不同的
    节点，在序列化传输时绝不可混为一谈。

    Example:
        >>> from qaiji.core.semantics.annotation import SemanticAnnotation
        >>> from qaiji.core.semantics.types import MorphismType
        >>> SemanticAnnotation(gate_index=0, morphism=MorphismType.UNITARY).cartan
        <CartanRole.NONE: 'NONE'>
    """

    gate_index: int
    morphism: MorphismType
    equiv_level: EquivLevel | None = None
    cartan: CartanRole = CartanRole.NONE
    body_offset: int | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """归一化 notes，并拒绝指向不存在节点的坐标。"""
        object.__setattr__(self, "notes", tuple(self.notes))

        if self.gate_index < SENTINEL_GATE_INDEX:
            raise ValueError(f"gate_index must be >= {SENTINEL_GATE_INDEX}, got {self.gate_index}")
        if self.body_offset is not None and self.body_offset < 0:
            raise ValueError(f"body_offset must be non-negative, got {self.body_offset}")
