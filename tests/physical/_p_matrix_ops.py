# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""提供测试用通用矩阵运算。"""

from __future__ import annotations

import math
import struct

Matrix = list[list[complex]]


class ConsumerError(ValueError):
    """保存测试消费者的失败类别与细分码。"""

    def __init__(self, category, code, details=None):
        super().__init__(f"{category}: {code}")
        self.category = category
        self.code = code
        self.details = {} if details is None else details


def cvalues(array):
    return [complex(re, im) for re, im in struct.iter_unpack("<dd", array.data)]


def fvalues(array):
    return [value for (value,) in struct.iter_unpack("<d", array.data)]


def zeros(rows, cols=None):
    return [[0j] * (rows if cols is None else cols) for _ in range(rows)]


def eye(n):
    return [[complex(i == j) for j in range(n)] for i in range(n)]


def add(a, b):
    return [[x + y for x, y in zip(ar, br, strict=True)] for ar, br in zip(a, b, strict=True)]


def scale(a, value):
    return [[value * x for x in row] for row in a]


def matmul(a, b):
    columns = list(zip(*b, strict=True))
    return [[sum(x * y for x, y in zip(row, col, strict=True)) for col in columns] for row in a]


def dagger(a):
    return [[x.conjugate() for x in col] for col in zip(*a, strict=True)]


def kron(a, b):
    return [[x * y for x in ar for y in br] for ar in a for br in b]


def outer(ket):
    return [[x * y.conjugate() for y in ket] for x in ket]


def trace(a):
    return sum(a[i][i] for i in range(len(a)))


def flatten(a):
    return [value for row in a for value in row]


def matrix(array):
    values = cvalues(array)
    rows, cols = array.shape
    return [values[i * cols : (i + 1) * cols] for i in range(rows)]


def expm(a):
    """用缩放平方法计算小矩阵指数。"""
    norm = max(sum(abs(x) for x in row) for row in a)
    power = max(0, math.ceil(math.log2(norm / 0.5))) if norm else 0
    reduced = scale(a, 2.0**-power)
    result = eye(len(a))
    term = eye(len(a))
    for order in range(1, 80):
        term = scale(matmul(term, reduced), 1 / order)
        result = add(result, term)
        if max(abs(x) for x in flatten(term)) < 1e-18:
            break
    else:
        raise ConsumerError("SOLVER_FAILURE", "EXPONENTIAL")
    for _ in range(power):
        result = matmul(result, result)
    return result
