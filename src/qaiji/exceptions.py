# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Qaiji-IR 各模块共享的异常层级。"""


class QaijiIRError(Exception):
    """所有 Qaiji IR 错误的基类。"""


class Qasm3ParseError(QaijiIRError):
    """QASM3 语法、版本头或参数求值错误。"""


class Qasm3UnsupportedConstructError(QaijiIRError):
    """超出支持范围的 QASM3 语法构造。"""


class Qasm3UnsupportedGateError(Qasm3UnsupportedConstructError):
    """在门注册表或 stdgates 映射中都找不到对应实现的 QASM3 门。"""


class ConventionViolationError(QaijiIRError):
    """约定自检报告的失败。"""


class UnsupportedEquivLevelError(QaijiIRError):
    """在我们无法判定的等价级别上请求了保持性判定。"""
