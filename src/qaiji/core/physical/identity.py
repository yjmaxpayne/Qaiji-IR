# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""P 层规范字节与含 schema 域的内容身份。"""

from __future__ import annotations

import hashlib
import json

from .codec import dump_problem, dump_request
from .diagnostics import CheckBudget
from .model import Problem, Request

_DEFAULT_BUDGET = CheckBudget()


def canonical_problem_bytes(problem: Problem) -> bytes:
    """编码完整问题的规范字节。数组使用内联布局。

    Args:
        problem: 待编码的问题。

    Returns:
        包含 schema 和扩展的 UTF-8 规范 JSON 字节。

    Raises:
        PContractError: 问题不符合交换契约或超出默认交换预算。
    """
    return dump_problem(problem, layout="inline").document


def canonical_request_bytes(request: Request) -> bytes:
    """编码请求的规范字节。身份排除来源。

    Args:
        request: 待编码的请求。

    Returns:
        仅移除 provenance 的内联规范 JSON 字节。

    Raises:
        PContractError: 请求不符合交换契约或超出默认交换预算。
    """
    return _canonical_request_bytes(request, budget=_DEFAULT_BUDGET)


def _canonical_request_bytes(request: Request, *, budget: CheckBudget) -> bytes:
    """按指定交换预算编码请求身份字节。"""
    document = json.loads(dump_request(request, layout="inline", budget=budget).document)
    del document["provenance"]
    return json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def problem_id(problem: Problem) -> str:
    """计算问题的内容身份。摘要包含 schema 域和零分隔字节。

    Args:
        problem: 待计算身份的问题。

    Returns:
        带 sha256: 前缀的小写摘要。

    Raises:
        PContractError: 问题不符合规范编码契约。
    """
    content = canonical_problem_bytes(problem)
    return "sha256:" + hashlib.sha256(problem.schema.encode("utf-8") + b"\0" + content).hexdigest()


def request_id(request: Request) -> str:
    """计算请求的内容身份。摘要包含 schema 域和零分隔字节。

    Args:
        request: 待计算身份的请求。

    Returns:
        带 sha256: 前缀的小写摘要。

    Raises:
        PContractError: 请求不符合规范编码契约。
    """
    return _request_id(request, budget=_DEFAULT_BUDGET)


def _request_id(request: Request, *, budget: CheckBudget) -> str:
    """按指定交换预算计算请求内容身份。"""
    content = _canonical_request_bytes(request, budget=budget)
    return "sha256:" + hashlib.sha256(request.schema.encode("utf-8") + b"\0" + content).hexdigest()
