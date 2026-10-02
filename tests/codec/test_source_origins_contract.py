# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""两个解析入口的契约：拒收逐字相同、互不委托，以及语料与维度矩阵上每个操作都能追回源码。"""

from __future__ import annotations

import ast
import hashlib
import inspect
import itertools
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path

import openqasm3
import pytest
from openqasm3 import ast as qasm_ast
from test_source_origins import _source_text

from qaiji.codec import OperationOrigin, from_qasm3, parse_qasm3
from qaiji.codec import qasm3 as qasm3_module
from qaiji.core.circuit import Gate
from qaiji.core.classical import Measure
from qaiji.exceptions import QaijiIRError, Qasm3ParseError

_HERE = Path(__file__).parent
_CORPUS = _HERE / "data" / "source_origin_corpus.json"
# 嵌套固定为 20 层；递归阈值靠调用方垫高栈深来逼近，而不是靠加深嵌套。
_NESTED = "OPENQASM 3.0; qubit q; rz(" + "(" * 20 + "1" + ")" * 20 + ") q;"

_HEADROOM = 400
_RECURSION_REJECTION = (Qasm3ParseError, "source at 1:1: expression nesting exceeds parser limit")

type Verdict = tuple[type[QaijiIRError] | None, str]


def _verdict(entry: Callable[[str], object], src: str) -> Verdict:
    try:
        entry(src)
    except QaijiIRError as exc:
        return type(exc), str(exc)
    return None, "ok"


def _corpus() -> list[dict[str, str]]:
    programs: list[dict[str, str]] = json.loads(_CORPUS.read_text(encoding="utf-8"))["programs"]
    return programs


def test_parse_and_from_qasm3_reject_identically_on_corpus():
    """新入口不得开辟另一套接受面或拒收面：同一源码两入口的判决（异常类与消息）必须逐字相同。

    源码的生成方式：在运行时用 ``ast`` 扫描本目录全部 ``test_*.py``，取含 ``;`` 的字符串常量
    （f-string 与拼接只收得到其中的字面量片段），并上 ``data/source_origin_corpus.json`` 的
    全部程序；接受与拒收两侧都比较，拒收侧另设数量下限。
    """
    candidates: set[str] = {row["src"] for row in _corpus()}
    for path in sorted(_HERE.glob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and ";" in node.value:
                candidates.add(node.value)
    rejected = 0
    for src in sorted(candidates):
        expected = _verdict(from_qasm3, src)
        assert _verdict(parse_qasm3, src) == expected, src
        rejected += expected[0] is not None
    # 扫描路径或筛选条件写错时拒收侧会接近为空，测试将空转通过
    assert rejected >= 300, rejected


@pytest.fixture
def recursion_headroom() -> Iterator[None]:
    """把递归上限设在当前真实栈深之上 400 帧；pytest 与 xdist 的栈深不同，不能写死绝对值。"""
    original = sys.getrecursionlimit()
    sys.setrecursionlimit(len(inspect.stack(0)) + _HEADROOM)
    try:
        yield
    finally:
        sys.setrecursionlimit(original)
        assert sys.getrecursionlimit() == original


def _at_depth(depth: int, entry: Callable[[str], object]) -> Verdict:
    """在额外 ``depth`` 层栈帧之下调用入口；两个入口经同一 helper 进入，起点深度相同。"""
    if depth == 0:
        return _verdict(entry, _NESTED)
    return _at_depth(depth - 1, entry)


def test_rejection_matches_near_recursion_limit(recursion_headroom):
    """递归上限附近两入口也须同判：任一入口多一层栈帧，阈值处就会一边接受、一边拒收。"""

    def verdicts(depth: int) -> tuple[Verdict, Verdict]:
        return _at_depth(depth, parse_qasm3), _at_depth(depth, from_qasm3)

    # 二分区间是相对栈深的垫栈层数；上界留出余量，保证 helper 自身不会先于入口溢出
    accepted, rejected = 0, _HEADROOM - 50
    assert verdicts(accepted)[0] == (None, "ok")
    assert verdicts(rejected)[0] == _RECURSION_REJECTION
    while rejected - accepted > 1:  # 现场二分 parse_qasm3 首个拒收的垫栈深度
        middle = (accepted + rejected) // 2
        if verdicts(middle)[0] == (None, "ok"):
            accepted = middle
        else:
            rejected = middle
    threshold = rejected
    # 前提：拒收确实来自递归保护，窗口确实跨过阈值
    assert verdicts(threshold)[0] == _RECURSION_REJECTION
    for depth in range(threshold - 2, threshold + 2):
        parse_verdict, from_verdict = verdicts(depth)
        assert parse_verdict == from_verdict, (depth, parse_verdict, from_verdict)


def _direct_calls(function_name: str) -> set[str]:
    """函数自身作用域里按名字直接调用的函数；嵌套的 lambda 与内部函数不算直接调用。"""
    tree = ast.parse(inspect.getsource(qasm3_module))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    names: set[str] = set()
    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Lambda | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
        pending.extend(ast.iter_child_nodes(node))
    return names


def test_entrypoints_call_parse_source_directly():
    """两入口各自直接调用 ``_parse_source``，互不委托；委托会多出栈帧，破坏阈值处的同判。"""
    from_calls, parse_calls = _direct_calls("from_qasm3"), _direct_calls("parse_qasm3")
    assert "_parse_source" in from_calls, sorted(from_calls)
    assert "_parse_source" in parse_calls, sorted(parse_calls)
    assert "parse_qasm3" not in from_calls, "from_qasm3 delegates to parse_qasm3"
    assert "from_qasm3" not in parse_calls, "parse_qasm3 delegates to from_qasm3"


_HEADERS = {"3.0": "OPENQASM 3.0;", "3": "OPENQASM 3;", "2.0": "OPENQASM 2.0;", None: ""}
# 注释里的版本号与所有真实头都不同，一旦被采用就会在每一行上露出来
_COMMENT = "// OPENQASM 3.1;\n"
_KINDS = ("gate", "broadcast", "expanded", "measure", "if", "declaration", "include")


def _expected_origins(
    kind: str, width: int, offset: int
) -> tuple[str, list[tuple[str, int, int]], list[tuple[int, ...]] | None]:
    """返回目标语句、它产出的 (原始门名, 广播下标, 展开下标) 序列与各操作作用的 qubit。"""
    if kind == "gate":
        return f"x q[{width - 1}];", [("x", 0, 0)], [(offset + width - 1,)]
    if kind == "broadcast":
        return "h q;", [("h", i, 0) for i in range(width)], [(offset + i,) for i in range(width)]
    if kind == "expanded":
        # 每个 ch 展开为 3 个门，这一数目来自生产展开表，而不是源码本身
        triples = [("ch", i, k) for i in range(width) for k in range(3)]
        return "ch q, r[0];", triples, None
    if kind == "measure":
        return (
            "c = measure q;",
            [("measure", i, 0) for i in range(width)],
            [(offset + i,) for i in range(width)],
        )
    if kind == "if":
        return "if (c == 1) { x q[0]; }", [("if", 0, 0)], None
    if kind == "declaration":
        return "bit[2] d;", [], None
    return 'include "stdgates.inc";', [], None


def _qubits(operation: object) -> tuple[int, ...]:
    if isinstance(operation, Measure):
        return (operation.qubit,)
    assert isinstance(operation, Gate)
    return operation.qubits


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("version", list(_HEADERS))
def test_origin_matrix_rows(version, kind):
    """版本头 × 语句类 × 广播宽度 × 寄存器偏移 × 跨行/同行 × 注释，每格的 origin 都按构造可知。

    期望坐标由拼接源码时的位置直接算出，不经解析器；``q`` 之前是否有寄存器 ``a`` 决定偏移：
    广播下标始终相对 ``q``，电路里的 qubit 才带偏移。
    """
    for width, offset, multiline, comment in itertools.product(
        (1, 3), (0, 2), (False, True), (False, True)
    ):
        case = (version, kind, width, offset, multiline, comment)
        statement, triples, qubits = _expected_origins(kind, width, offset)
        target = statement.replace(" ", "\n  ", 1) if multiline else statement
        prelude = [f"qubit[{offset}] a;"] if offset else []
        prelude += [f"qubit[{width}] q;", "qubit r;", f"bit[{width}] c;"]
        separator = "\n" if multiline else " "
        head_parts = [part for part in (_HEADERS[version], *prelude) if part]
        head = (_COMMENT if comment else "") + separator.join(head_parts) + separator
        src = head + target + separator + "x q[0];"

        line = head.count("\n") + 1
        column = len(head.rsplit("\n", 1)[-1]) + 1
        tail = target.rsplit("\n", 1)[-1]
        end_column = column + len(tail) - 1 if "\n" not in target else len(tail)
        span = (line, column, line + target.count("\n"), end_column)

        parsed = parse_qasm3(src)
        assert parsed.declared_version == version, case
        index = len(prelude)
        own = [
            (operation, origin)
            for operation, origin in zip(parsed.circuit.gates, parsed.origins, strict=True)
            if origin.statement_index == index
        ]
        assert [(o.raw_name, o.broadcast_index, o.expansion_index) for _, o in own] == triples, case
        assert all(_origin_span(o) == span for _, o in own), case
        if qubits is not None:
            assert [_qubits(operation) for operation, _ in own] == qubits, case
        if kind == "if":
            assert [o.raw_name for o in own[0][1].body] == ["x"], case
        # 不产出操作的声明与 include 也要占语句序号，后继语句才不会错位
        probe = parsed.origins[-1]
        assert (probe.raw_name, probe.statement_index) == ("x", index + 1), case


def _statement_span(statement: qasm_ast.Statement) -> tuple[int, int, int, int]:
    span = statement.span
    assert span is not None
    return (span.start_line, span.start_column + 1, span.end_line, span.end_column + 1)


def _origin_span(origin: OperationOrigin) -> tuple[int, int, int, int]:
    return (origin.line, origin.column, origin.end_line, origin.end_column)


def _assert_traces_to(src: str, statement: object, origin: OperationOrigin) -> None:
    assert isinstance(statement, qasm_ast.Statement)
    assert _origin_span(origin) == _statement_span(statement)
    text = _source_text(src, origin)
    if isinstance(statement, qasm_ast.QuantumGate):
        # 展开出的每个门都要能追回源码里写的那个门名
        assert origin.raw_name == statement.name.name and text.startswith(origin.raw_name)
        assert origin.body == ()
    elif isinstance(statement, qasm_ast.QuantumMeasurementStatement):
        assert origin.raw_name == "measure" and "measure" in text
    else:
        assert isinstance(statement, qasm_ast.BranchingStatement)
        assert origin.raw_name == "if" and text.startswith("if")
        for body_origin in origin.body:
            (gate,) = [
                g for g in statement.if_block if _statement_span(g) == _origin_span(body_origin)
            ]
            _assert_traces_to(src, gate, body_origin)


def test_every_accepted_corpus_operation_has_traceable_origin():
    """真实程序上每个操作（含条件体内的门）都有 origin，且指回原语句与原始门名。

    语料的枚举方式：``data/source_origin_corpus.json`` 收录前端差分核对报告 diff-v1 的
    ``results[].src`` 全部 148 个程序（set ``m1``），以及从 EmuPlat rst 文档抽取、相对 diff-v1
    逐字新增的 41 个程序（set ``doc``）；``id`` 是源码的 SHA256。其中被 ``from_qasm3`` 接受的
    125 + 38 个在此逐个检查，其余由拒收等价测试使用。
    """
    accepted: Counter[str] = Counter()
    for row in _corpus():
        src = row["src"]
        assert hashlib.sha256(src.encode()).hexdigest() == row["id"], row["id"]
        try:
            parsed = parse_qasm3(src)
        except QaijiIRError:
            continue
        accepted[row["set"]] += 1
        statements = openqasm3.parse(src).statements
        for operation, origin in zip(parsed.circuit.gates, parsed.origins, strict=True):
            assert len(origin.body) == len(getattr(operation, "body", ())), row["id"]
            _assert_traces_to(src, statements[origin.statement_index], origin)
    assert accepted == {"m1": 125, "doc": 38}
