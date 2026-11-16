# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""T 层值类型：轨迹日志、保持证书、容差表及其构造检查。只依赖标准库与 qaiji。"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from qaiji.core.semantics import EquivLevel
from qaiji.exceptions import QaijiIRError

TRACE_LOG_SCHEMA = "qaiji.t.trace_log/1.0"
CERTIFICATE_SCHEMA = "qaiji.t.preservation_certificate/1.0"
TOLERANCES_SCHEMA = "qaiji.t.tolerances/1.0"
_BITS = re.compile(r"[01]+")
_HEX = re.compile(r"[0-9a-f]{16}")
_DECIDABLE_LEVELS = (EquivLevel.EXACT, EquivLevel.UP_TO_PHASE)


class TraceInputError(QaijiIRError, ValueError):
    """轨迹值或编码文档违反 T 层契约时抛出。"""


# --- 字段检查 -------------------------------------------------------------------


def _text(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise TraceInputError(f"{name} must be a non-empty string, got {value!r}")


def _uint(name: str, value: Any) -> None:
    if type(value) is not int or value < 0:
        raise TraceInputError(f"{name} must be a non-negative int, got {value!r}")


def _finite(name: str, value: Any) -> None:
    if type(value) is not float or not math.isfinite(value):
        raise TraceInputError(f"{name} must be a finite float, got {value!r}")


def _flag(name: str, value: Any) -> None:
    if type(value) is not bool:
        raise TraceInputError(f"{name} must be a bool, got {value!r}")


def _bits(name: str, value: Any) -> None:
    if not isinstance(value, str) or not _BITS.fullmatch(value):
        raise TraceInputError(f"{name} must be a non-empty bit string, got {value!r}")


def _choice(name: str, value: Any, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise TraceInputError(f"{name} must be one of {allowed}, got {value!r}")


def _items(name: str, values: Iterable[Any], item_type: type) -> tuple[Any, ...]:
    items = tuple(values)
    if not all(isinstance(item, item_type) for item in items):
        raise TraceInputError(f"{name} must hold only {item_type.__name__} values")
    return items


# --- 轨迹日志 ----------------------------------------------------------------------

_KINDS: dict[str, tuple[re.Pattern[str], dict[str, Callable[[str, Any], None]]]] = {
    "measurement": (
        re.compile(r"m(0|[1-9][0-9]*)"),
        {"qubit": _uint, "register": _text, "bit_index": _uint},
    ),
    "branch": (
        re.compile(r"b:[01]+"),
        {"conditional_weight": _finite, "path_weight": _finite, "pruned": _flag},
    ),
    "observable": (re.compile(r"o:.+"), {"value": _finite, "result_digest": _text}),
}
_EVENT_FIELDS = (
    "qubit",
    "register",
    "bit_index",
    "conditional_weight",
    "path_weight",
    "pruned",
    "value",
    "result_digest",
)
_EVENT_FLOATS = frozenset({"conditional_weight", "path_weight", "value"})


def _is_event_id(value: Any) -> bool:
    return isinstance(value, str) and any(p.fullmatch(value) for p, _ in _KINDS.values())


@dataclass(frozen=True, kw_only=True)
class TraceEvent:
    """轨迹日志中的一个测量、分支或可观测事件。

    Example:
        >>> TraceEvent(id="b:01", kind="branch", conditional_weight=0.5,
        ...            path_weight=0.25, pruned=False).id
        'b:01'
    """

    id: str
    """测量为 ``m<i>``，分支为 ``b:<bit key>``，可观测量为 ``o:<name>``。"""
    kind: str
    """``measurement``、``branch`` 或 ``observable``。"""
    qubit: int | None = None
    """被测量子比特（仅测量事件）。"""
    register: str | None = None
    """接收结果的经典寄存器（仅测量事件）。"""
    bit_index: int | None = None
    """寄存器中接收结果的位（仅测量事件）。"""
    conditional_weight: float | None = None
    """给定父分支时本分支的概率（仅分支事件）。"""
    path_weight: float | None = None
    """到达本分支的整条路径的概率（仅分支事件）。"""
    pruned: bool | None = None
    """模拟丢弃本分支时为 True（仅分支事件）。"""
    value: float | None = None
    """可观测量的值（仅可观测事件）。"""
    result_digest: str | None = None
    """该值所来自结果的摘要（仅可观测事件）。"""

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise TraceInputError(f"event kind must be one of {tuple(_KINDS)}, got {self.kind!r}")
        pattern, checks = _KINDS[self.kind]
        if not isinstance(self.id, str) or not pattern.fullmatch(self.id):
            raise TraceInputError(f"{self.kind} event id {self.id!r} does not match {pattern}")
        for name in _EVENT_FIELDS:
            value = getattr(self, name)
            if name in checks:
                checks[name](f"{self.id}.{name}", value)
            elif value is not None:
                raise TraceInputError(f"{self.kind} event {self.id} must not set {name}")


def _order_key(event: TraceEvent) -> tuple[int, int, str]:
    if event.kind == "measurement":
        return (0, 0, event.id)
    name = event.id[2:]
    return (1, len(name), name) if event.kind == "branch" else (2, 0, name)


@dataclass(frozen=True, kw_only=True)
class TraceSource:
    """轨迹日志所来自记录的身份；不解析记录格式。"""

    kind: str
    """来源记录的格式名。"""
    digest: str
    """来源记录的哈希。"""
    program_ref: str
    """来源记录所运行程序的引用。"""
    layer: str
    """产生来源记录的层，例如 ``l0`` 或 ``l1``。"""

    def __post_init__(self) -> None:
        for name in ("kind", "digest", "program_ref", "layer"):
            _text(f"source.{name}", getattr(self, name))


@dataclass(frozen=True, kw_only=True)
class TraceLog:
    """一条来源记录的事件，按规范顺序排列。

    测量在前，按 id 排序；其次是分支，按（键长，键）排序；
    最后是可观测量，按名称排序。id 唯一。
    """

    source: TraceSource
    """事件所来自的记录。"""
    events: tuple[TraceEvent, ...]
    """按规范顺序排列的事件。"""
    schema: str = TRACE_LOG_SCHEMA
    """模式字面量；只接受 ``qaiji.t.trace_log/1.0``。"""

    def __post_init__(self) -> None:
        _choice("trace log schema", self.schema, (TRACE_LOG_SCHEMA,))
        if not isinstance(self.source, TraceSource):
            raise TraceInputError("trace log source must be a TraceSource")
        events = _items("trace log events", self.events, TraceEvent)
        object.__setattr__(self, "events", events)
        ids = [event.id for event in events]
        if len(set(ids)) != len(ids):
            raise TraceInputError(f"trace log has duplicate event ids: {ids}")
        keys = [_order_key(event) for event in events]
        if keys != sorted(keys):
            raise TraceInputError(f"trace log events are not in canonical order: {ids}")


# --- 证书 ----------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SymbolicLevel:
    """一个降级阶段的符号等价级别。"""

    level: EquivLevel
    """任一级别；检查器只接受 ``EXACT`` 与 ``UP_TO_PHASE``。"""
    stage: str
    """该级别所属的降级阶段。"""
    ruleset_version: str
    """该阶段所用规则集的版本。"""

    def __post_init__(self) -> None:
        if not isinstance(self.level, EquivLevel):
            raise TraceInputError(f"symbolic level must be an EquivLevel: {self.level!r}")
        _text("symbolic.stage", self.stage)
        _text("symbolic.ruleset_version", self.ruleset_version)


@dataclass(frozen=True, kw_only=True)
class Comparison:
    """一项数值比较及支撑它的事件。"""

    name: str
    """被比较量的名称。"""
    kind: str
    """``same_layer`` 或 ``cross_layer``。"""
    tolerance: float | None
    """允许的差值；同层哈希比较时为 None。"""
    delta: float
    """实测差值。"""
    verdict: str
    """``within`` 或 ``exceeded``。"""
    evidence_refs: tuple[tuple[str, str], ...]
    """``(record_hash, event_id)`` 二元组。"""

    def __post_init__(self) -> None:
        _text("comparison.name", self.name)
        _choice("comparison.kind", self.kind, ("same_layer", "cross_layer"))
        if self.tolerance is not None:
            _finite(f"{self.name}.tolerance", self.tolerance)
        _finite(f"{self.name}.delta", self.delta)
        _choice(f"{self.name}.verdict", self.verdict, ("within", "exceeded"))
        refs = tuple(tuple(ref) for ref in self.evidence_refs)
        for ref in refs:
            if len(ref) != 2:
                raise TraceInputError(f"{self.name} evidence ref {ref!r} is not a hash/event pair")
            _text(f"{self.name} evidence record hash", ref[0])
            _text(f"{self.name} evidence event id", ref[1])
        object.__setattr__(self, "evidence_refs", refs)


@dataclass(frozen=True, kw_only=True)
class Exclusion:
    """主导键与期望键不同的层。"""

    layer: str
    """被排除的层。"""
    dominant_key: str
    """该层产生的主导键。"""

    def __post_init__(self) -> None:
        _text("exclusion.layer", self.layer)
        _bits("exclusion.dominant_key", self.dominant_key)


@dataclass(frozen=True, kw_only=True)
class ToleranceSource:
    """冻结容差文件及选取容差值的规则。"""

    rule: str
    """选取容差的规则名。"""
    digest: str
    """冻结容差文件的哈希。"""

    def __post_init__(self) -> None:
        _text("tolerance_source.rule", self.rule)
        _text("tolerance_source.digest", self.digest)


@dataclass(frozen=True, kw_only=True)
class ResultLatency:
    """测量结果的假定延迟。"""

    value: int
    """延迟，单位 ns。"""
    source: str
    """``config`` 或 ``verilator``。"""

    def __post_init__(self) -> None:
        _uint("result_latency_ns.value", self.value)
        _choice("result_latency_ns.source", self.source, ("config", "verilator"))


@dataclass(frozen=True, kw_only=True)
class Assumptions:
    """随证书记录的假设；检查与引用均不使用。"""

    result_latency_ns: ResultLatency
    """假定的结果延迟。"""

    def __post_init__(self) -> None:
        if not isinstance(self.result_latency_ns, ResultLatency):
            raise TraceInputError("assumptions.result_latency_ns must be a ResultLatency")


def numerical_verdict_of(comparisons: Iterable[Comparison], exclusions: Iterable[Exclusion]) -> str:
    """返回比较项与排除项所蕴含的证书判决。

    Args:
        comparisons: 证书的比较项。
        exclusions: 证书的排除层。

    Returns:
        任一比较超限时返回 ``exceeded``；否则有层被排除时返回 ``excluded``；
        否则返回 ``within``。
    """
    if any(c.verdict == "exceeded" for c in comparisons):
        return "exceeded"
    return "excluded" if tuple(exclusions) else "within"


@dataclass(frozen=True, kw_only=True)
class PreservationCertificate:
    """一个程序保持其含义的符号级别与数值判决。

    符号级别与数值判决是两个独立字段；任何判决都不改变符号级别。
    """

    program_ref: str
    """被认证程序的引用。"""
    expected_key: str
    """理想主导键，由签发方给出。"""
    symbolic: SymbolicLevel
    """降级的符号等价级别。"""
    comparisons: tuple[Comparison, ...]
    """每个被比较量一项。"""
    exclusions: tuple[Exclusion, ...]
    """主导键与 ``expected_key`` 不同的层。"""
    numerical_verdict: str
    """``within``、``exceeded`` 或 ``excluded``；必须等于 ``numerical_verdict_of`` 的结果。"""
    tolerance_source: ToleranceSource
    """容差的来源。"""
    assumptions: Assumptions
    """记录的假设。"""
    schema: str = CERTIFICATE_SCHEMA
    """模式字面量；只接受 ``qaiji.t.preservation_certificate/1.0``。"""

    def __post_init__(self) -> None:
        _choice("certificate schema", self.schema, (CERTIFICATE_SCHEMA,))
        _text("program_ref", self.program_ref)
        _bits("expected_key", self.expected_key)
        if not isinstance(self.symbolic, SymbolicLevel):
            raise TraceInputError("symbolic must be a SymbolicLevel")
        comparisons = _items("comparisons", self.comparisons, Comparison)
        exclusions = _items("exclusions", self.exclusions, Exclusion)
        object.__setattr__(self, "comparisons", comparisons)
        object.__setattr__(self, "exclusions", exclusions)
        expected = numerical_verdict_of(comparisons, exclusions)
        if self.numerical_verdict != expected:
            raise TraceInputError(
                f"numerical verdict {self.numerical_verdict!r} disagrees with the rule: "
                f"{expected!r}"
            )
        if not isinstance(self.tolerance_source, ToleranceSource):
            raise TraceInputError("tolerance_source must be a ToleranceSource")
        if not isinstance(self.assumptions, Assumptions):
            raise TraceInputError("assumptions must be an Assumptions")


@dataclass(frozen=True, kw_only=True)
class ToleranceEntry:
    """一个被比较量的校准离散度及为其选取的容差。"""

    max_abs_delta: float
    """校准记录上观测到的最大差值。"""
    tolerance: float
    """允许的差值。"""

    def __post_init__(self) -> None:
        _finite("max_abs_delta", self.max_abs_delta)
        _finite("tolerance", self.tolerance)


@dataclass(frozen=True, kw_only=True)
class ToleranceTable:
    """冻结容差文件：每个跨层比较名一项。"""

    comparisons: Mapping[str, ToleranceEntry]
    """按比较名索引的条目。"""
    calibration_records: tuple[str, ...]
    """给出离散度的记录的哈希。"""
    rule: str = "precision_ladder"
    """选取容差的规则；只接受 ``precision_ladder``。"""
    schema: str = TOLERANCES_SCHEMA
    """模式字面量；只接受 ``qaiji.t.tolerances/1.0``。"""

    def __post_init__(self) -> None:
        _choice("tolerances schema", self.schema, (TOLERANCES_SCHEMA,))
        _choice("tolerances rule", self.rule, ("precision_ladder",))
        if not isinstance(self.comparisons, Mapping):
            raise TraceInputError("tolerance comparisons must be a mapping")
        comparisons = dict(self.comparisons)
        for name, entry in comparisons.items():
            _text("tolerance comparison name", name)
            if not isinstance(entry, ToleranceEntry):
                raise TraceInputError(f"tolerance entry {name!r} must be a ToleranceEntry")
        records = _items("calibration_records", self.calibration_records, str)
        for record in records:
            _text("calibration record", record)
        object.__setattr__(self, "comparisons", comparisons)
        object.__setattr__(self, "calibration_records", records)
