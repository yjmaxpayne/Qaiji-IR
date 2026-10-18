# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""P 层不可变数组：缓冲区复制、位模式保留与输入拒绝。"""

from __future__ import annotations

import struct
from dataclasses import FrozenInstanceError

import pytest

from qaiji.core.physical import ArrayData, PContractError


def _f64(*values: float) -> bytes:
    return struct.pack(f"<{len(values)}d", *values)


def _c128(*values: complex) -> bytes:
    payload = bytearray()
    for value in values:
        payload += struct.pack("<dd", value.real, value.imag)
    return bytes(payload)


def _assert_code(error: pytest.ExceptionInfo[PContractError], code: str) -> None:
    assert error.value.diagnostics[0].code == code


def test_p_array_copies_mutable_buffer() -> None:
    shape = [2]
    payload = bytearray(_f64(0.0, -0.0))
    array = ArrayData(dtype="f64le", shape=shape, data=payload)

    assert array.data == _f64(0.0, -0.0)
    assert array.shape == (2,)
    payload[0:8] = _f64(1.0)
    shape[0] = 3
    assert array.data == _f64(0.0, -0.0)
    assert array.shape == (2,)

    backing = bytearray(_f64(2.0))
    view = memoryview(backing)
    copied = ArrayData(dtype="f64le", shape=(1,), data=view)
    backing[0:8] = _f64(3.0)
    assert copied.data == _f64(2.0)
    assert isinstance(copied.data, bytes)

    with pytest.raises(FrozenInstanceError):
        array.data = b""  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        array.shape = (1,)  # type: ignore[misc]


def test_p_array_preserves_binary64_bits() -> None:
    vectors = (
        _f64(0.0),
        _f64(-0.0),
        _f64(1.0),
        _f64(5e-324),
        _f64(1.7976931348623157e308),
    )
    expected = (
        "0000000000000000",
        "8000000000000000",
        "3ff0000000000000",
        "0000000000000001",
        "7fefffffffffffff",
    )
    for payload, bits in zip(vectors, expected, strict=True):
        array = ArrayData(dtype="f64le", shape=(1,), data=payload)
        assert array.data == payload
        assert struct.pack(">d", struct.unpack("<d", array.data)[0]).hex() == bits

    negative_zero = ArrayData.from_values(dtype="f64le", shape=(1,), values=[-0.0])
    assert negative_zero.data == _f64(-0.0)
    assert struct.pack(">d", struct.unpack("<d", negative_zero.data)[0]).hex() == (
        "8000000000000000"
    )

    complex_value = complex(-0.0, 0.0)
    complex_array = ArrayData.from_values(dtype="c128le", shape=(1,), values=[complex_value])
    assert complex_array.data == _c128(complex_value)
    assert complex_array.data[0:8] == struct.pack("<d", -0.0)


def test_p_array_rejects_invalid_components() -> None:
    assert ArrayData(dtype="f64le", shape=(0,), data=b"").shape == (0,)
    assert ArrayData(dtype="f64le", shape=(), data=_f64(0.0)).shape == ()
    assert ArrayData(dtype="c128le", shape=(1,), data=_c128(1 + 2j)).data == _c128(1 + 2j)

    with pytest.raises(PContractError) as invalid_dtype:
        ArrayData(dtype="f32le", shape=(1,), data=b"\x00" * 4)  # type: ignore[arg-type]
    _assert_code(invalid_dtype, "DTYPE")

    with pytest.raises(PContractError) as non_text_dtype:
        ArrayData(dtype=1, shape=(1,), data=b"\x00" * 8)  # type: ignore[arg-type]
    _assert_code(non_text_dtype, "DTYPE")

    with pytest.raises(PContractError) as boolean_shape:
        ArrayData(dtype="f64le", shape=(True,), data=_f64(0.0))  # type: ignore[arg-type]
    _assert_code(boolean_shape, "SHAPE")

    with pytest.raises(PContractError) as negative_shape:
        ArrayData(dtype="f64le", shape=(-1,), data=b"")
    _assert_code(negative_shape, "SHAPE")

    with pytest.raises(PContractError) as text_shape:
        ArrayData(dtype="f64le", shape="1", data=_f64(0.0))  # type: ignore[arg-type]
    _assert_code(text_shape, "SHAPE")

    with pytest.raises(PContractError) as list_data:
        ArrayData(dtype="f64le", shape=(1,), data=[0.0])  # type: ignore[arg-type]
    _assert_code(list_data, "BYTE_LENGTH")

    with pytest.raises(PContractError) as short_data:
        ArrayData(dtype="f64le", shape=(2,), data=_f64(0.0))
    _assert_code(short_data, "BYTE_LENGTH")

    with pytest.raises(PContractError) as long_data:
        ArrayData(dtype="f64le", shape=(1,), data=_f64(0.0, 1.0))
    _assert_code(long_data, "BYTE_LENGTH")

    with pytest.raises(PContractError) as nan_component:
        ArrayData(dtype="f64le", shape=(1,), data=_f64(float("nan")))
    _assert_code(nan_component, "NONFINITE")

    with pytest.raises(PContractError) as infinite_component:
        ArrayData(dtype="f64le", shape=(1,), data=_f64(float("inf")))
    _assert_code(infinite_component, "NONFINITE")

    with pytest.raises(PContractError) as infinite_imaginary:
        ArrayData(dtype="c128le", shape=(1,), data=_c128(complex(0.0, float("-inf"))))
    _assert_code(infinite_imaginary, "NONFINITE")


def test_p_from_values_catches_overflow() -> None:
    assert ArrayData.from_values(dtype="f64le", shape=(2,), values=[1, 2.5]).data == _f64(1.0, 2.5)
    assert ArrayData.from_values(dtype="c128le", shape=(1,), values=[1 + 2j]).data == _c128(1 + 2j)
    assert ArrayData.from_values(dtype="c128le", shape=(1,), values=[3]).data == _c128(3 + 0j)

    with pytest.raises(PContractError) as real_overflow:
        ArrayData.from_values(dtype="f64le", shape=(1,), values=[10**400])
    _assert_code(real_overflow, "NONFINITE")
    assert isinstance(real_overflow.value.__cause__, OverflowError)

    with pytest.raises(PContractError) as complex_overflow:
        ArrayData.from_values(dtype="c128le", shape=(1,), values=[10**400])
    _assert_code(complex_overflow, "NONFINITE")
    assert isinstance(complex_overflow.value.__cause__, OverflowError)

    with pytest.raises(PContractError) as boolean_value:
        ArrayData.from_values(dtype="f64le", shape=(1,), values=[True])
    _assert_code(boolean_value, "NUMBER")

    with pytest.raises(PContractError) as complex_for_real:
        ArrayData.from_values(dtype="f64le", shape=(1,), values=[1 + 0j])
    _assert_code(complex_for_real, "NUMBER")

    with pytest.raises(PContractError) as wrong_count:
        ArrayData.from_values(dtype="f64le", shape=(2,), values=[1.0])
    _assert_code(wrong_count, "SHAPE")

    with pytest.raises(PContractError) as non_finite:
        ArrayData.from_values(dtype="f64le", shape=(1,), values=[float("nan")])
    _assert_code(non_finite, "NONFINITE")

    with pytest.raises(PContractError) as not_iterable:
        ArrayData.from_values(dtype="f64le", shape=(1,), values=1.0)  # type: ignore[arg-type]
    _assert_code(not_iterable, "JSON_TYPE")
