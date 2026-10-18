# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""P 层不可变数值数组与不透明 JSON 树。"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Self, cast

from .diagnostics import _fail

type _DType = Literal["f64le", "c128le"]
type _JSONValue = None | bool | int | str | _JSONObject | _JSONArray

_ITEMSIZE = {"f64le": 8, "c128le": 16}


def _set(obj: object, name: str, convert: Any) -> None:
    object.__setattr__(obj, name, convert(getattr(obj, name), "/" + name))


def _dtype(value: Any, path: str) -> _DType:
    if type(value) is not str or value not in _ITEMSIZE:
        _fail("DTYPE", path, "Expected dtype f64le or c128le.")
    return cast(_DType, value)


def _shape(value: Any, path: str) -> tuple[int, ...]:
    if isinstance(value, (str, bytes, bytearray, memoryview)) or not isinstance(value, Sequence):
        _fail("SHAPE", path, "Expected a sequence of nonnegative integers.")
    shape: list[int] = []
    for index, item in enumerate(value):
        if type(item) is not int:
            _fail("SHAPE", f"{path}/{index}", "Expected a nonnegative integer.")
        if item < 0:
            _fail("SHAPE", f"{path}/{index}", "Expected a nonnegative integer.")
        shape.append(item)
    return tuple(shape)


def _buffer(value: Any, path: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        _fail("BYTE_LENGTH", path, "Expected bytes, bytearray or memoryview.")
    try:
        return bytes(value)
    except (TypeError, ValueError) as error:
        _fail("BYTE_LENGTH", path, "The buffer cannot be copied.", cause=error)


def _validate_payload(dtype: _DType, shape: tuple[int, ...], data: bytes) -> None:
    expected = math.prod(shape) * _ITEMSIZE[dtype]
    if len(data) != expected:
        _fail(
            "BYTE_LENGTH",
            "/data",
            "The byte length does not match dtype and shape.",
            details={"expected": expected, "actual": len(data)},
        )
    if dtype == "f64le":
        for index, (component,) in enumerate(struct.iter_unpack("<d", data)):
            if not math.isfinite(component):
                _fail(
                    "NONFINITE",
                    f"/data/{index}",
                    "Array components must be finite.",
                )
    else:
        for index, (real, imaginary) in enumerate(struct.iter_unpack("<dd", data)):
            if not math.isfinite(real) or not math.isfinite(imaginary):
                _fail(
                    "NONFINITE",
                    f"/data/{index}",
                    "Array components must be finite.",
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class ArrayData:
    """以 dtype、shape 与 bytes 表达的不可变数组。"""

    dtype: _DType
    shape: tuple[int, ...]
    data: bytes
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "dtype", _dtype)
        _set(self, "shape", _shape)
        _set(self, "data", _buffer)
        _validate_payload(self.dtype, self.shape, self.data)

    @classmethod
    def from_values(
        cls,
        *,
        dtype: _DType,
        shape: Sequence[int],
        values: Iterable[int | float | complex],
    ) -> Self:
        checked_dtype = _dtype(dtype, "/dtype")
        checked_shape = _shape(shape, "/shape")
        if isinstance(values, (str, bytes, bytearray, memoryview, Mapping)) or not isinstance(
            values, Iterable
        ):
            _fail("JSON_TYPE", "/values", "Expected an iterable of numbers.")
        payload = bytearray()
        count = 0
        for index, value in enumerate(values):
            if checked_dtype == "f64le":
                payload += struct.pack("<d", _real_value(value, f"/values/{index}"))
            else:
                payload += struct.pack("<dd", *_complex_value(value, f"/values/{index}"))
            count += 1
        expected = math.prod(checked_shape)
        if count != expected:
            _fail(
                "SHAPE",
                "/values",
                "The number of values does not match shape.",
                details={"expected": expected, "actual": count},
            )
        return cls(dtype=checked_dtype, shape=checked_shape, data=bytes(payload))


def _real_value(value: Any, path: str) -> float:
    if type(value) not in (int, float):
        _fail("NUMBER", path, "Expected a built-in real number.")
    try:
        result = float(value)
    except OverflowError as error:
        _fail("NONFINITE", path, "Number cannot be represented as binary64.", cause=error)
    if not math.isfinite(result):
        _fail("NONFINITE", path, "Expected a finite number.")
    return result


def _complex_value(value: Any, path: str) -> tuple[float, float]:
    if type(value) not in (int, float, complex):
        _fail("NUMBER", path, "Expected a built-in real or complex number.")
    try:
        result = complex(value)
    except OverflowError as error:
        _fail("NONFINITE", path, "Number cannot be represented as binary64.", cause=error)
    if not math.isfinite(result.real) or not math.isfinite(result.imag):
        _fail("NONFINITE", path, "Expected finite components.")
    return (result.real, result.imag)


@dataclass(frozen=True, slots=True)
class _JSONObject:
    items: tuple[tuple[str, _JSONValue], ...]


@dataclass(frozen=True, slots=True)
class _JSONArray:
    items: tuple[_JSONValue, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class FrozenJSON:
    """不可变 JSON 树；普通对象与数组保持不同容器。"""

    value: _JSONValue
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _freeze(self.value, ""))


def _freeze(value: Any, path: str) -> _JSONValue:
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is str:
        _unicode(value, path)
        return value
    if type(value) is float:
        _fail("JSON_TYPE", path, "JSON numbers must be integers.")
    if isinstance(value, Mapping):
        items: list[tuple[str, _JSONValue]] = []
        keys: set[str] = set()
        for key, item in value.items():
            if type(key) is not str:
                _fail("KEY_TYPE", path, "JSON object keys must be strings.")
            _unicode(key, path)
            if key in keys:
                _fail("DUPLICATE", path, "JSON object keys must be unique.")
            keys.add(key)
            items.append((key, _freeze(item, f"{path}/{_escape(key)}")))
        items.sort(key=lambda pair: pair[0])
        return _JSONObject(tuple(items))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        return _JSONArray(
            tuple(_freeze(item, f"{path}/{index}") for index, item in enumerate(value))
        )
    _fail("JSON_TYPE", path, "Expected an immutable JSON value.")


def _unicode(value: str, path: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        _fail("UNICODE", path, "Expected Unicode scalar values.", cause=error)


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")
