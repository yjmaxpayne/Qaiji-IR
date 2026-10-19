# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""P 层不可变模型与构造签名。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, cast, overload

from .arrays import ArrayData, FrozenJSON
from .diagnostics import (
    Diagnostic,
    _diagnostics,
    _fail,
    _index,
    _literal,
    _pointer,
    _sequence,
    _set,
    _text,
)

type _Frame = Literal["lab", "rotating"]
type _Representation = Literal["ket", "density", "either"]
type _ActualRepresentation = Literal["ket", "density"]
type _SignalKind = Literal["constant", "zoh"]
type _StateKind = Literal["ket", "density", "product"]
type _ObservationKind = Literal["full_state", "expectation", "partial_trace", "projection"]
type _MethodMode = Literal["fixed", "delegate"]
type _TransformKind = Literal["exact_representation", "numerical_substep"]
type _Basis = Literal["delegated", "allowed_representation"]

_FRAMES = ("lab", "rotating")
_REPRESENTATIONS = ("ket", "density", "either")
_ACTUAL_REPRESENTATIONS = ("ket", "density")
_SIGNAL_KINDS = ("constant", "zoh")
_STATE_KINDS = ("ket", "density", "product")
_OBSERVATION_KINDS = ("full_state", "expectation", "partial_trace", "projection")
_METHOD_MODES = ("fixed", "delegate")
_TRANSFORM_KINDS = ("exact_representation", "numerical_substep")
_DIFFERENCE_BASES = ("delegated", "allowed_representation")


def _optional(convert: Any) -> Any:
    return lambda value, path: None if value is None else convert(value, path)


def _object(value: Any, cls: type[Any], path: str) -> Any:
    if type(value) is not cls:
        _fail("KEY_TYPE", path, f"Expected {cls.__name__}.")
    return value


def _objects(cls: type[Any]) -> Any:
    return lambda value, path: _sequence(value, path, lambda item, at: _object(item, cls, at))


def _texts(value: Any, path: str, *, allow_empty: bool, unique: bool) -> tuple[str, ...]:
    items = _sequence(value, path, _text)
    if not allow_empty and not items:
        _fail("KEYS", path, "Expected at least one entry.")
    if unique and len(set(items)) != len(items):
        _fail("KEYS", path, "Expected unique entries.")
    return items


def _pairs(value: Any, path: str) -> tuple[tuple[str, str], ...]:
    return _sequence(value, path, _pair)


def _pair(value: Any, path: str) -> tuple[str, str]:
    if isinstance(value, (str, bytes, bytearray, memoryview)) or not isinstance(value, Sequence):
        _fail("JSON_TYPE", path, "Expected a two-item sequence.")
    if len(value) != 2:
        _fail("KEYS", path, "Expected exactly two items.")
    return (_text(value[0], f"{path}[0]"), _text(value[1], f"{path}[1]"))


def _boolean_true(value: Any, path: str) -> bool:
    if value is not True:
        _fail("JSON_TYPE", path, "Expected true.")
    return True


def _positive_int(value: Any, path: str) -> int:
    result = _index(value, path)
    if result == 0:
        _fail("INTEGER", path, "Expected a positive integer.")
    return result


def _number(value: Any, path: str) -> float:
    if type(value) not in (int, float):
        _fail("NUMBER", path, "Expected a built-in real number.")
    try:
        result = float(value)
    except OverflowError as error:
        _fail("NONFINITE", path, "Number cannot be represented as binary64.", cause=error)
    if not math.isfinite(result):
        _fail("NONFINITE", path, "Expected a finite number.")
    return result


def _positive_number(value: Any, path: str) -> float:
    result = _number(value, path)
    if not result > 0.0:
        _fail("NUMBER", path, "Expected a positive number.")
    return result


def _nonnegative_number(value: Any, path: str) -> float:
    result = _number(value, path)
    if not result >= 0.0:
        _fail("NUMBER", path, "Expected a nonnegative number.")
    return result


def _complex_number(value: Any, path: str) -> complex:
    if type(value) not in (int, float, complex):
        _fail("NUMBER", path, "Expected a built-in real or complex number.")
    try:
        result = complex(value)
    except OverflowError as error:
        _fail("NONFINITE", path, "Number cannot be represented as binary64.", cause=error)
    if not math.isfinite(result.real) or not math.isfinite(result.imag):
        _fail("NONFINITE", path, "Expected finite components.")
    return result


def _schema(value: Any, expected: str, path: str = "/schema") -> str:
    if type(value) is not str or value != expected:
        _fail("VERSION", path, "Unexpected schema version.")
    return value


def _frame(value: Any, path: str) -> _Frame:
    return cast(_Frame, _literal(value, _FRAMES, path))


def _actual_representation(value: Any, path: str) -> _ActualRepresentation:
    return cast(_ActualRepresentation, _literal(value, _ACTUAL_REPRESENTATIONS, path))


def _array(value: Any, path: str) -> ArrayData:
    return cast(ArrayData, _object(value, ArrayData, path))


def _array_of(value: Any, path: str, dtype: str, ranks: tuple[int, ...]) -> ArrayData:
    array = _array(value, path)
    if array.dtype != dtype:
        _fail("DTYPE", path, f"Expected dtype {dtype}.")
    if len(array.shape) not in ranks:
        _fail("SHAPE", path, "Unexpected array rank.")
    return array


def _vector_f64(value: Any, path: str) -> ArrayData:
    return _array_of(value, path, "f64le", (1,))


def _square_c128(value: Any, path: str) -> ArrayData:
    array = _array_of(value, path, "c128le", (2,))
    if array.shape[0] == 0 or array.shape[0] != array.shape[1]:
        _fail("SHAPE", path, "Expected a nonempty square matrix.")
    return array


def _state_data(kind: str, value: Any, path: str) -> ArrayData:
    if kind == "ket":
        array = _array_of(value, path, "c128le", (1,))
        if array.shape[0] == 0:
            _fail("SHAPE", path, "Expected a nonempty state vector.")
        return array
    return _square_c128(value, path)


def _isometry(value: Any, path: str) -> ArrayData:
    array = _array_of(value, path, "c128le", (2,))
    rows, columns = array.shape
    if rows == 0 or columns == 0 or columns > rows:
        _fail("SHAPE", path, "Expected rows >= columns > 0.")
    return array


def _require_keys(values: Mapping[str, Any], expected: tuple[str, ...], path: str) -> None:
    if set(values) != set(expected):
        _fail("KEYS", path, "Branch fields do not match the declared kind.")


@dataclass(frozen=True, slots=True, kw_only=True)
class Site:
    id: str
    dim: int
    basis: tuple[str, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "id", _text)
        _set(self, "dim", _positive_int)
        _set(self, "basis", lambda value, path: _texts(value, path, allow_empty=True, unique=True))
        if len(self.basis) != self.dim:
            _fail("SITE", "/basis", "The basis length must equal dim.")


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalFactor:
    site: str
    matrix: ArrayData
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "site", _text)
        _set(self, "matrix", _square_c128)


@dataclass(frozen=True, slots=True, kw_only=True)
class OperatorTerm:
    coefficient: complex
    factors: tuple[LocalFactor, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "coefficient", _complex_number)
        _set(self, "factors", _objects(LocalFactor))
        sites = [factor.site for factor in self.factors]
        if len(set(sites)) != len(sites):
            _fail("SITE", "/factors", "A term cannot repeat a site.")


@dataclass(frozen=True, slots=True, kw_only=True)
class OperatorSum:
    unit: str
    terms: tuple[OperatorTerm, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "unit", _text)
        _set(self, "terms", _objects(OperatorTerm))


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class Signal:
    kind: _SignalKind
    unit: str
    value: float | None
    values: ArrayData | None
    __hash__: ClassVar[Any] = None

    @overload
    def __init__(self, *, kind: Literal["constant"], unit: str, value: float) -> None: ...

    @overload
    def __init__(self, *, kind: Literal["zoh"], unit: str, values: ArrayData) -> None: ...

    def __init__(self, **kwargs: Any) -> None:
        kind = kwargs.get("kind")
        if kind == "constant":
            _require_keys(kwargs, ("kind", "unit", "value"), "")
            object.__setattr__(self, "kind", "constant")
            object.__setattr__(self, "unit", _text(kwargs["unit"], "/unit"))
            object.__setattr__(self, "value", _number(kwargs["value"], "/value"))
            object.__setattr__(self, "values", None)
            return
        if kind == "zoh":
            _require_keys(kwargs, ("kind", "unit", "values"), "")
            object.__setattr__(self, "kind", "zoh")
            object.__setattr__(self, "unit", _text(kwargs["unit"], "/unit"))
            object.__setattr__(self, "value", None)
            object.__setattr__(self, "values", _vector_f64(kwargs["values"], "/values"))
            return
        _fail("KEYS", "/kind", "Unknown signal kind.")


@dataclass(frozen=True, slots=True, kw_only=True)
class Drive:
    id: str
    operator: OperatorSum
    signal: Signal
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "id", _text)
        _set(self, "operator", lambda value, path: _object(value, OperatorSum, path))
        _set(self, "signal", lambda value, path: _object(value, Signal, path))


@dataclass(frozen=True, slots=True, kw_only=True)
class Jump:
    id: str
    operator: OperatorSum
    rate: Signal
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "id", _text)
        _set(self, "operator", lambda value, path: _object(value, OperatorSum, path))
        _set(self, "rate", lambda value, path: _object(value, Signal, path))


@dataclass(frozen=True, slots=True, kw_only=True)
class Environment:
    kind: Literal["closed", "markovian"]
    jumps: tuple[Jump, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "kind", lambda value, path: _literal(value, ("closed", "markovian"), path))
        _set(self, "jumps", _objects(Jump))
        if self.kind == "closed" and self.jumps:
            _fail("KEYS", "/jumps", "A closed environment cannot have jumps.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductFactor:
    site: str
    kind: _ActualRepresentation
    data: ArrayData
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "site", _text)
        _set(self, "kind", _actual_representation)
        _set(self, "data", lambda value, path: _state_data(self.kind, value, path))


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class State:
    kind: _StateKind
    frame: _Frame
    data: ArrayData | None
    factors: tuple[ProductFactor, ...] | None
    __hash__: ClassVar[Any] = None

    @overload
    def __init__(self, *, kind: _ActualRepresentation, frame: _Frame, data: ArrayData) -> None: ...

    @overload
    def __init__(
        self, *, kind: Literal["product"], frame: _Frame, factors: Sequence[ProductFactor]
    ) -> None: ...

    def __init__(self, **kwargs: Any) -> None:
        kind = kwargs.get("kind")
        if kind in ("ket", "density"):
            _require_keys(kwargs, ("kind", "frame", "data"), "")
            object.__setattr__(self, "kind", kind)
            object.__setattr__(self, "frame", _frame(kwargs["frame"], "/frame"))
            object.__setattr__(self, "data", _state_data(kind, kwargs["data"], "/data"))
            object.__setattr__(self, "factors", None)
            return
        if kind == "product":
            _require_keys(kwargs, ("kind", "frame", "factors"), "")
            factors = _objects(ProductFactor)(kwargs["factors"], "/factors")
            if not factors:
                _fail("PRODUCT_COVERAGE", "/factors", "Expected at least one factor.")
            sites = [factor.site for factor in factors]
            if len(set(sites)) != len(sites):
                _fail("PRODUCT_COVERAGE", "/factors", "Factors must cover distinct sites.")
            object.__setattr__(self, "kind", "product")
            object.__setattr__(self, "frame", _frame(kwargs["frame"], "/frame"))
            object.__setattr__(self, "data", None)
            object.__setattr__(self, "factors", factors)
            return
        _fail("KEYS", "/kind", "Unknown state kind.")


@dataclass(frozen=True, slots=True, kw_only=True)
class RequiredExtension:
    namespace: str
    version: str
    content_type: str
    required: Literal[True]
    affects_physics: Literal[True]
    payload: FrozenJSON
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "namespace", _text)
        _set(self, "version", _text)
        _set(self, "content_type", _text)
        _set(self, "required", _boolean_true)
        _set(self, "affects_physics", _boolean_true)
        if type(self.payload) is not FrozenJSON:
            _fail("JSON_TYPE", "/payload", "Expected FrozenJSON.")


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotRef:
    id: str
    version: str | None
    digest: str | None
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "id", _text)
        _set(self, "version", _optional(_text))
        _set(self, "digest", _optional(_text))
        if self.version is None and self.digest is None:
            _fail("PROVENANCE", "", "A snapshot needs a version or a digest.")


@dataclass(frozen=True, slots=True, kw_only=True)
class BasisMapping:
    logical_bit: int
    site: str
    zero_label: str
    one_label: str
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "logical_bit", _index)
        _set(self, "site", _text)
        _set(self, "zero_label", _text)
        _set(self, "one_label", _text)


@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance:
    kind: Literal["manual", "device_bound"]
    program_ref: str | None
    binder_version: str | None
    device_snapshot: SnapshotRef | None
    calibration_snapshot: SnapshotRef | None
    basis_mapping: tuple[BasisMapping, ...]
    prior_transforms: tuple[FrozenJSON, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "kind", lambda value, path: _literal(value, ("manual", "device_bound"), path))
        _set(self, "program_ref", _optional(_text))
        _set(self, "binder_version", _optional(_text))
        _set(
            self,
            "device_snapshot",
            _optional(lambda value, path: _object(value, SnapshotRef, path)),
        )
        _set(
            self,
            "calibration_snapshot",
            _optional(lambda value, path: _object(value, SnapshotRef, path)),
        )
        _set(self, "basis_mapping", _objects(BasisMapping))
        _set(self, "prior_transforms", _objects(FrozenJSON))
        if self.kind == "device_bound" and (
            self.device_snapshot is None or self.calibration_snapshot is None
        ):
            _fail("PROVENANCE", "", "A device-bound provenance needs both snapshots.")


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class Observation:
    id: str
    kind: _ObservationKind
    representation: _Representation | None
    operator: OperatorSum | None
    keep_sites: tuple[str, ...] | None
    input_sites: tuple[str, ...] | None
    isometry: ArrayData | None
    __hash__: ClassVar[Any] = None

    @overload
    def __init__(
        self, *, id: str, kind: Literal["full_state"], representation: _Representation
    ) -> None: ...

    @overload
    def __init__(self, *, id: str, kind: Literal["expectation"], operator: OperatorSum) -> None: ...

    @overload
    def __init__(
        self, *, id: str, kind: Literal["partial_trace"], keep_sites: Sequence[str]
    ) -> None: ...

    @overload
    def __init__(
        self,
        *,
        id: str,
        kind: Literal["projection"],
        input_sites: Sequence[str],
        isometry: ArrayData,
    ) -> None: ...

    def __init__(self, **kwargs: Any) -> None:
        kind = kwargs.get("kind")
        values = _observation_fields(kwargs, kind)
        object.__setattr__(self, "id", _text(kwargs["id"], "/id"))
        object.__setattr__(self, "kind", kind)
        for name, value in values.items():
            object.__setattr__(self, name, value)


def _observation_fields(kwargs: Mapping[str, Any], kind: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "representation": None,
        "operator": None,
        "keep_sites": None,
        "input_sites": None,
        "isometry": None,
    }
    if kind == "full_state":
        _require_keys(kwargs, ("id", "kind", "representation"), "")
        values["representation"] = _literal(
            kwargs["representation"], _REPRESENTATIONS, "/representation"
        )
        return values
    if kind == "expectation":
        _require_keys(kwargs, ("id", "kind", "operator"), "")
        values["operator"] = _object(kwargs["operator"], OperatorSum, "/operator")
        return values
    if kind == "partial_trace":
        _require_keys(kwargs, ("id", "kind", "keep_sites"), "")
        values["keep_sites"] = _texts(
            kwargs["keep_sites"], "/keep_sites", allow_empty=False, unique=True
        )
        return values
    if kind == "projection":
        _require_keys(kwargs, ("id", "kind", "input_sites", "isometry"), "")
        values["input_sites"] = _texts(
            kwargs["input_sites"], "/input_sites", allow_empty=False, unique=True
        )
        values["isometry"] = _isometry(kwargs["isometry"], "/isometry")
        return values
    _fail("KEYS", "/kind", "Unknown observation kind.")


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ObservationValue:
    id: str
    kind: _ObservationKind
    representation: _ActualRepresentation | None
    data: ArrayData | None
    keep_sites: tuple[str, ...] | None
    input_sites: tuple[str, ...] | None
    block: ArrayData | None
    leakage: ArrayData | None
    input_trace: ArrayData | None
    trace_error: ArrayData | None
    __hash__: ClassVar[Any] = None

    @overload
    def __init__(
        self,
        *,
        id: str,
        kind: Literal["full_state"],
        representation: _ActualRepresentation,
        data: ArrayData,
    ) -> None: ...

    @overload
    def __init__(self, *, id: str, kind: Literal["expectation"], data: ArrayData) -> None: ...

    @overload
    def __init__(
        self,
        *,
        id: str,
        kind: Literal["partial_trace"],
        keep_sites: Sequence[str],
        data: ArrayData,
    ) -> None: ...

    @overload
    def __init__(
        self,
        *,
        id: str,
        kind: Literal["projection"],
        input_sites: Sequence[str],
        block: ArrayData,
        leakage: ArrayData,
        input_trace: ArrayData,
        trace_error: ArrayData,
    ) -> None: ...

    def __init__(self, **kwargs: Any) -> None:
        kind = kwargs.get("kind")
        values = _observation_value_fields(kwargs, kind)
        object.__setattr__(self, "id", _text(kwargs["id"], "/id"))
        object.__setattr__(self, "kind", kind)
        for name, value in values.items():
            object.__setattr__(self, name, value)


def _observation_value_fields(kwargs: Mapping[str, Any], kind: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "representation": None,
        "data": None,
        "keep_sites": None,
        "input_sites": None,
        "block": None,
        "leakage": None,
        "input_trace": None,
        "trace_error": None,
    }
    if kind == "full_state":
        _require_keys(kwargs, ("id", "kind", "representation", "data"), "")
        values["representation"] = _actual_representation(
            kwargs["representation"], "/representation"
        )
        values["data"] = _array_of(kwargs["data"], "/data", "c128le", (2, 3))
        return values
    if kind == "expectation":
        _require_keys(kwargs, ("id", "kind", "data"), "")
        values["data"] = _array_of(kwargs["data"], "/data", "c128le", (1,))
        return values
    if kind == "partial_trace":
        _require_keys(kwargs, ("id", "kind", "keep_sites", "data"), "")
        values["keep_sites"] = _texts(
            kwargs["keep_sites"], "/keep_sites", allow_empty=False, unique=True
        )
        values["data"] = _array_of(kwargs["data"], "/data", "c128le", (3,))
        return values
    if kind == "projection":
        _require_keys(
            kwargs,
            ("id", "kind", "input_sites", "block", "leakage", "input_trace", "trace_error"),
            "",
        )
        values["input_sites"] = _texts(
            kwargs["input_sites"], "/input_sites", allow_empty=False, unique=True
        )
        values["block"] = _array_of(kwargs["block"], "/block", "c128le", (3,))
        values["leakage"] = _vector_f64(kwargs["leakage"], "/leakage")
        values["input_trace"] = _vector_f64(kwargs["input_trace"], "/input_trace")
        values["trace_error"] = _vector_f64(kwargs["trace_error"], "/trace_error")
        return values
    _fail("KEYS", "/kind", "Unknown observation-value kind.")


@dataclass(frozen=True, slots=True, kw_only=True)
class MethodChoice:
    mode: _MethodMode
    value: str | None
    allowed: tuple[str, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "mode", lambda value, path: _literal(value, _METHOD_MODES, path))
        _set(self, "value", _optional(_text))
        _set(
            self, "allowed", lambda value, path: _texts(value, path, allow_empty=True, unique=True)
        )
        if self.mode == "fixed":
            if self.value is None:
                _fail("METHOD", "/value", "A fixed method needs a value.")
            if self.allowed:
                _fail("METHOD", "/allowed", "A fixed method cannot list alternatives.")
        else:
            if self.value is not None:
                _fail("METHOD", "/value", "A delegated method cannot fix a value.")
            if not self.allowed:
                _fail("METHOD", "/allowed", "A delegated method needs alternatives.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionPolicy:
    method: MethodChoice
    atol: float
    rtol: float
    max_step_ns: float | None
    representation: _Representation
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "method", lambda value, path: _object(value, MethodChoice, path))
        _set(self, "atol", _positive_number)
        _set(self, "rtol", _nonnegative_number)
        _set(self, "max_step_ns", _optional(_positive_number))
        _set(self, "representation", lambda value, path: _literal(value, _REPRESENTATIONS, path))


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyDifference:
    path: str
    requested: FrozenJSON
    actual: FrozenJSON
    basis: _Basis
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "path", _pointer)
        if type(self.requested) is not FrozenJSON:
            _fail("JSON_TYPE", "/requested", "Expected FrozenJSON.")
        if type(self.actual) is not FrozenJSON:
            _fail("JSON_TYPE", "/actual", "Expected FrozenJSON.")
        _set(self, "basis", lambda value, path: _literal(value, _DIFFERENCE_BASES, path))


@dataclass(frozen=True, slots=True, kw_only=True)
class TransformRecord:
    name: str
    kind: _TransformKind
    authorization: FrozenJSON
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "name", _text)
        _set(self, "kind", lambda value, path: _literal(value, _TRANSFORM_KINDS, path))
        if type(self.authorization) is not FrozenJSON:
            _fail("JSON_TYPE", "/authorization", "Expected FrozenJSON.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionReport:
    backend_id: str
    backend_version: str
    actual_policy: FrozenJSON
    policy_differences: tuple[PolicyDifference, ...]
    transforms: tuple[TransformRecord, ...]
    state_representations: FrozenJSON
    validation_level: Literal["transport", "structure", "physical"]
    diagnostics: tuple[Diagnostic, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "backend_id", _text)
        _set(self, "backend_version", _text)
        if type(self.actual_policy) is not FrozenJSON:
            _fail("JSON_TYPE", "/actual_policy", "Expected FrozenJSON.")
        _set(self, "policy_differences", _objects(PolicyDifference))
        _set(self, "transforms", _objects(TransformRecord))
        if type(self.state_representations) is not FrozenJSON:
            _fail("JSON_TYPE", "/state_representations", "Expected FrozenJSON.")
        _set(
            self,
            "validation_level",
            lambda value, path: _literal(value, ("transport", "structure", "physical"), path),
        )
        _set(self, "diagnostics", _diagnostics)


@dataclass(frozen=True, slots=True, kw_only=True)
class Problem:
    sites: tuple[Site, ...]
    tensor_order: tuple[str, ...]
    h0: OperatorSum
    drives: tuple[Drive, ...]
    environment: Environment
    initial_state: State
    signal_edges: ArrayData
    time_unit: Literal["ns"]
    frame: _Frame
    approximations: tuple[str, ...]
    extensions: tuple[RequiredExtension, ...]
    schema: Literal["qaiji.p.problem/1.0"] = "qaiji.p.problem/1.0"
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "sites", _objects(Site))
        if not self.sites:
            _fail("SITE", "/sites", "A problem needs at least one site.")
        _set(
            self,
            "tensor_order",
            lambda value, path: _texts(value, path, allow_empty=False, unique=True),
        )
        _set(self, "h0", lambda value, path: _object(value, OperatorSum, path))
        _set(self, "drives", _objects(Drive))
        _set(self, "environment", lambda value, path: _object(value, Environment, path))
        _set(self, "initial_state", lambda value, path: _object(value, State, path))
        _set(self, "signal_edges", _vector_f64)
        _set(self, "time_unit", lambda value, path: _literal(value, ("ns",), path))
        _set(self, "frame", _frame)
        _set(
            self,
            "approximations",
            lambda value, path: _texts(value, path, allow_empty=True, unique=True),
        )
        _set(self, "extensions", _objects(RequiredExtension))
        _set(self, "schema", lambda value, path: _schema(value, "qaiji.p.problem/1.0", path))


@dataclass(frozen=True, slots=True, kw_only=True)
class Request:
    problem: Problem
    output_times: ArrayData
    observations: tuple[Observation, ...]
    policy: ExecutionPolicy
    provenance: Provenance
    schema: Literal["qaiji.p.request/1.0"] = "qaiji.p.request/1.0"
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "problem", lambda value, path: _object(value, Problem, path))
        _set(self, "output_times", _vector_f64)
        _set(self, "observations", _objects(Observation))
        _set(self, "policy", lambda value, path: _object(value, ExecutionPolicy, path))
        _set(self, "provenance", lambda value, path: _object(value, Provenance, path))
        _set(self, "schema", lambda value, path: _schema(value, "qaiji.p.request/1.0", path))


@dataclass(frozen=True, slots=True, kw_only=True)
class Result:
    request_id: str
    output_times: ArrayData
    tensor_order: tuple[str, ...]
    frame: _Frame
    observations: tuple[ObservationValue, ...]
    report: ExecutionReport
    schema: Literal["qaiji.p.result/1.0"] = "qaiji.p.result/1.0"
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "request_id", _text)
        _set(self, "output_times", _vector_f64)
        _set(
            self,
            "tensor_order",
            lambda value, path: _texts(value, path, allow_empty=False, unique=True),
        )
        _set(self, "frame", _frame)
        _set(self, "observations", _objects(ObservationValue))
        _set(self, "report", lambda value, path: _object(value, ExecutionReport, path))
        _set(self, "schema", lambda value, path: _schema(value, "qaiji.p.result/1.0", path))


@dataclass(frozen=True, slots=True, kw_only=True)
class Requirements:
    profiles: tuple[FrozenJSON, ...]
    dimension: int
    precision: FrozenJSON
    required_extensions: tuple[tuple[str, str], ...]
    output_kinds: tuple[str, ...]
    methods: tuple[str, ...]
    schema: Literal["qaiji.p.requirements/1.0"] = "qaiji.p.requirements/1.0"
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "profiles", _objects(FrozenJSON))
        _set(self, "dimension", _positive_int)
        if type(self.precision) is not FrozenJSON:
            _fail("JSON_TYPE", "/precision", "Expected FrozenJSON.")
        _set(self, "required_extensions", _pairs)
        _set(
            self,
            "output_kinds",
            lambda value, path: _texts(value, path, allow_empty=True, unique=True),
        )
        _set(
            self, "methods", lambda value, path: _texts(value, path, allow_empty=False, unique=True)
        )
        _set(
            self,
            "schema",
            lambda value, path: _schema(value, "qaiji.p.requirements/1.0", path),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Capabilities:
    consumer_id: str
    consumer_version: str
    profiles: tuple[FrozenJSON, ...]
    max_dimension: int
    precision: FrozenJSON
    required_extensions: tuple[tuple[str, str], ...]
    output_kinds: tuple[str, ...]
    methods: tuple[str, ...]
    schema: Literal["qaiji.p.capabilities/1.0"] = "qaiji.p.capabilities/1.0"
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "consumer_id", _text)
        _set(self, "consumer_version", _text)
        _set(self, "profiles", _objects(FrozenJSON))
        _set(self, "max_dimension", _positive_int)
        if type(self.precision) is not FrozenJSON:
            _fail("JSON_TYPE", "/precision", "Expected FrozenJSON.")
        _set(self, "required_extensions", _pairs)
        _set(
            self,
            "output_kinds",
            lambda value, path: _texts(value, path, allow_empty=True, unique=True),
        )
        _set(
            self, "methods", lambda value, path: _texts(value, path, allow_empty=False, unique=True)
        )
        _set(
            self,
            "schema",
            lambda value, path: _schema(value, "qaiji.p.capabilities/1.0", path),
        )
