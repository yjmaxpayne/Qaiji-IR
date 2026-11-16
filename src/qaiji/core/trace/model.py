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
    """Raised when a trace value or an encoded document breaks the trace-layer contract."""


# --- field checks -------------------------------------------------------------------


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


# --- trace log ----------------------------------------------------------------------

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
    """One measurement, branch, or observable event of a trace log.

    Example:
        >>> TraceEvent(id="b:01", kind="branch", conditional_weight=0.5,
        ...            path_weight=0.25, pruned=False).id
        'b:01'
    """

    id: str
    """``m<i>`` for a measurement, ``b:<bit key>`` for a branch, ``o:<name>`` for an observable."""
    kind: str
    """``measurement``, ``branch``, or ``observable``."""
    qubit: int | None = None
    """Measured qubit (measurement only)."""
    register: str | None = None
    """Classical register that receives the result (measurement only)."""
    bit_index: int | None = None
    """Bit of the register that receives the result (measurement only)."""
    conditional_weight: float | None = None
    """Probability of the branch given its parent (branch only)."""
    path_weight: float | None = None
    """Probability of the whole path to the branch (branch only)."""
    pruned: bool | None = None
    """True when the simulation dropped the branch (branch only)."""
    value: float | None = None
    """Observable value (observable only)."""
    result_digest: str | None = None
    """Digest of the result the value comes from (observable only)."""

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
    """Identity of the record a trace log comes from; the record format is not parsed."""

    kind: str
    """Format name of the source record."""
    digest: str
    """Hash of the source record."""
    program_ref: str
    """Reference of the program the source record runs."""
    layer: str
    """Layer that produced the source record, such as ``l0`` or ``l1``."""

    def __post_init__(self) -> None:
        for name in ("kind", "digest", "program_ref", "layer"):
            _text(f"source.{name}", getattr(self, name))


@dataclass(frozen=True, kw_only=True)
class TraceLog:
    """Events of one source record in canonical order.

    Measurements come first by id, then branches by (key length, key), then observables
    by name. Ids are unique.
    """

    source: TraceSource
    """Record the events come from."""
    events: tuple[TraceEvent, ...]
    """Events in canonical order."""
    schema: str = TRACE_LOG_SCHEMA
    """Schema literal; only ``qaiji.t.trace_log/1.0`` is accepted."""

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


# --- certificate ----------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SymbolicLevel:
    """Symbolic equivalence level of one lowering stage."""

    level: EquivLevel
    """Any level; the checker accepts only ``EXACT`` and ``UP_TO_PHASE``."""
    stage: str
    """Lowering stage the level belongs to."""
    ruleset_version: str
    """Version of the rule set the stage applied."""

    def __post_init__(self) -> None:
        if not isinstance(self.level, EquivLevel):
            raise TraceInputError(f"symbolic level must be an EquivLevel: {self.level!r}")
        _text("symbolic.stage", self.stage)
        _text("symbolic.ruleset_version", self.ruleset_version)


@dataclass(frozen=True, kw_only=True)
class Comparison:
    """One numerical comparison and the events that support it."""

    name: str
    """Name of the compared quantity."""
    kind: str
    """``same_layer`` or ``cross_layer``."""
    tolerance: float | None
    """Allowed difference; None for a same-layer hash comparison."""
    delta: float
    """Measured difference."""
    verdict: str
    """``within`` or ``exceeded``."""
    evidence_refs: tuple[tuple[str, str], ...]
    """``(record_hash, event_id)`` pairs."""

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
    """A layer whose dominant key differs from the expected key."""

    layer: str
    """Excluded layer."""
    dominant_key: str
    """Dominant key that the layer produced."""

    def __post_init__(self) -> None:
        _text("exclusion.layer", self.layer)
        _bits("exclusion.dominant_key", self.dominant_key)


@dataclass(frozen=True, kw_only=True)
class ToleranceSource:
    """Frozen tolerance file and the rule that picked the values."""

    rule: str
    """Name of the rule that picked the tolerances."""
    digest: str
    """Hash of the frozen tolerance file."""

    def __post_init__(self) -> None:
        _text("tolerance_source.rule", self.rule)
        _text("tolerance_source.digest", self.digest)


@dataclass(frozen=True, kw_only=True)
class ResultLatency:
    """Assumed latency of a measurement result."""

    value: int
    """Latency in ns."""
    source: str
    """``config`` or ``verilator``."""

    def __post_init__(self) -> None:
        _uint("result_latency_ns.value", self.value)
        _choice("result_latency_ns.source", self.source, ("config", "verilator"))


@dataclass(frozen=True, kw_only=True)
class Assumptions:
    """Assumptions recorded with a certificate; no check or reference uses them."""

    result_latency_ns: ResultLatency
    """Assumed result latency."""

    def __post_init__(self) -> None:
        if not isinstance(self.result_latency_ns, ResultLatency):
            raise TraceInputError("assumptions.result_latency_ns must be a ResultLatency")


def numerical_verdict_of(comparisons: Iterable[Comparison], exclusions: Iterable[Exclusion]) -> str:
    """Return the certificate verdict that the comparisons and exclusions imply.

    Args:
        comparisons: Comparisons of the certificate.
        exclusions: Excluded layers of the certificate.

    Returns:
        ``exceeded`` if any comparison exceeded, else ``excluded`` if a layer is excluded,
        else ``within``.
    """
    if any(c.verdict == "exceeded" for c in comparisons):
        return "exceeded"
    return "excluded" if tuple(exclusions) else "within"


@dataclass(frozen=True, kw_only=True)
class PreservationCertificate:
    """Symbolic level and numerical verdict that one program keeps its meaning.

    The symbolic level and the numerical verdict are separate fields; no verdict changes
    the level.
    """

    program_ref: str
    """Reference of the certified program."""
    expected_key: str
    """Ideal dominant key, as the issuer states it."""
    symbolic: SymbolicLevel
    """Symbolic equivalence level of the lowering."""
    comparisons: tuple[Comparison, ...]
    """One entry per compared quantity."""
    exclusions: tuple[Exclusion, ...]
    """Layers whose dominant key differs from ``expected_key``."""
    numerical_verdict: str
    """``within``, ``exceeded``, or ``excluded``; must equal ``numerical_verdict_of``."""
    tolerance_source: ToleranceSource
    """Origin of the tolerances."""
    assumptions: Assumptions
    """Recorded assumptions."""
    schema: str = CERTIFICATE_SCHEMA
    """Schema literal; only ``qaiji.t.preservation_certificate/1.0`` is accepted."""

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
    """Calibrated spread of one compared quantity and the tolerance picked for it."""

    max_abs_delta: float
    """Largest difference seen on the calibration records."""
    tolerance: float
    """Allowed difference."""

    def __post_init__(self) -> None:
        _finite("max_abs_delta", self.max_abs_delta)
        _finite("tolerance", self.tolerance)


@dataclass(frozen=True, kw_only=True)
class ToleranceTable:
    """Frozen tolerance file: one entry per cross-layer comparison name."""

    comparisons: Mapping[str, ToleranceEntry]
    """Entries by comparison name."""
    calibration_records: tuple[str, ...]
    """Hashes of the records that gave the spreads."""
    rule: str = "precision_ladder"
    """Rule that picks a tolerance; only ``precision_ladder`` is accepted."""
    schema: str = TOLERANCES_SCHEMA
    """Schema literal; only ``qaiji.t.tolerances/1.0`` is accepted."""

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
