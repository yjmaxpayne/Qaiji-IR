# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""承载电路摘要及其内容哈希的冻结、JSON 安全的句柄。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

__all__ = ["HandleStatus", "JSONValue", "SemanticIRHandle", "freeze_summary"]

_SCHEMA_VERSION = "qaiji.semantic_ir_handle.v0"


class HandleStatus(StrEnum):
    """句柄摘要载荷的可用性状态。

    只有四个取值，而非上游的五个：qaiji 不存在"不适用"的句柄场景，因此
    ``NOT_APPLICABLE`` 是被有意舍弃的。
    """

    AVAILABLE = "available"
    PLANNED = "planned"
    OMITTED = "omitted"
    FAILED = "failed"


type JSONValue = None | bool | int | float | str | Sequence["JSONValue"] | Mapping[str, "JSONValue"]
"""无需 ``default=`` 钩子即可被 ``json.dumps`` 编码的值树。"""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        for key in value:
            if not isinstance(key, str):
                raise TypeError(f"summary keys must be str, got {key!r} ({type(key).__name__})")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


def freeze_summary(value: Mapping[str, Any]) -> Mapping[str, JSONValue]:
    """递归冻结一个 JSON 形状的映射，得到不可变树。

    每个 ``Mapping`` 变成 ``MappingProxyType``；每个 ``list``/``tuple`` 变成
    ``tuple``。与本实现所借鉴的上游模型不同（上游把嵌套容器重建为新的、仍然可变的
    list），这里的冻结是深度不可变的：真正做到这一点的是 tuple 转换，而不是某种
    共享引用的取巧手法。

    Args:
        value: JSON 形状的映射，原始的或已冻结的均可（幂等）。

    Returns:
        每一层都已冻结的同一棵树。

    Raises:
        TypeError: 映射的键不是 ``str``，或叶子值不属于
            ``None``/``bool``/``int``/``float``/``str``/list/tuple/Mapping。
    """
    return _freeze(value)  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class SemanticIRHandle:
    """下游坍缩阶段消费的唯一对象：摘要、哈希与状态。

    Example:
        >>> from qaiji.core.semantics.handle import SemanticIRHandle
        >>> SemanticIRHandle().status
        <HandleStatus.PLANNED: 'planned'>
    """

    schema_version: str = _SCHEMA_VERSION
    handle_id: str | None = None
    producer: str | None = None
    summary: Mapping[str, JSONValue] = field(default_factory=dict)
    content_hash: str | None = None
    status: HandleStatus = HandleStatus.PLANNED

    def __post_init__(self) -> None:
        """强制校验 schema 版本字面量，并对摘要做深度冻结。"""
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be the frozen literal {_SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )
        object.__setattr__(self, "summary", freeze_summary(self.summary))
