# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""``parse_looped_qasm3`` 的接受面与拒收面；两个严格入口的接受面保持不变。"""

import inspect
import tracemalloc

import pytest

from qaiji.codec import from_qasm3, parse_qasm3
from qaiji.codec import qasm3 as qasm3_module
from qaiji.core import loop as loop_module
from qaiji.core.loop import BoundedLoop
from qaiji.exceptions import (
    QaijiIRError,
    Qasm3UnsupportedConstructError,
    Qasm3UnsupportedGateError,
)

H = "OPENQASM 3.0;\nqubit[4] q;\nbit[2] c;\n"
STRICT_ENTRIES = {"from_qasm3": from_qasm3, "parse_qasm3": parse_qasm3}


def _entry():
    # 按名导入：新入口缺失时只有调用它的用例失败，严格入口的用例照常运行。
    from qaiji.codec import parse_looped_qasm3

    return parse_looped_qasm3


def _loop(body: str, head: str = "for int i in [0:1]") -> str:
    return f"{H}{head} {{\n  {body}\n}}\n"


def _while(
    body: str = "x q[i];",
    head: str = "int i = 1;\nwhile (i <= 3)",
    step: str = "i += 1;",
    tail: str = "",
) -> str:
    return f"{H}{head} {{\n  {body}\n  {step}\n}}\n{tail}"


def _loops(parsed) -> list[BoundedLoop]:
    return [node for node in parsed.circuit.operations if isinstance(node, BoundedLoop)]


_UC = Qasm3UnsupportedConstructError
_BIG = "1" + "0" * 400

# (源码, 确切异常类型, construct, 消息片段)。片段为空时只断言类型与前缀。
REJECTED = {
    "above-iteration-limit": (_loop("x q[0];", "for int i in [0:1024]"), _UC, "for", "1024"),
    "huge-bound": (_loop("x q[0];", f"for int i in [0:{_BIG}]"), _UC, "for", ""),
    "literal-index-in-empty-loop": (
        _loop("x q[9];", "for int i in [1:0]"),
        _UC,
        "x",
        "index 9 is outside",
    ),
    "index-out-of-range-on-last-iteration": (
        _loop("x q[i];", "for int i in [1:4]"),
        _UC,
        "x",
        "index 4 is outside",
    ),
    "duplicate-qubit-in-iteration": (_loop("cx q[i], q[1];"), _UC, "cx", "unique"),
    "outer-register-name": (_loop("bit[2] c;\n  c[0] = measure q[i];"), _UC, "for", ""),
    "break-in-body": (_loop("break;"), _UC, "for", ""),
    "continue-in-body": (_loop("continue;"), _UC, "for", ""),
    "reset-in-body": (_loop("reset q[i];"), _UC, "for", ""),
    "barrier-in-body": (_loop("barrier q[i];"), _UC, "for", ""),
    "delay-in-body": (_loop("delay[10ns] q[i];"), _UC, "for", ""),
    "switch-in-body": (_loop("switch (c) { case 0 { x q[i]; } }"), _UC, "for", ""),
    "const-in-body": (_loop("const int m = 1;\n  x q[i];"), _UC, "for", ""),
    "offset-index": (_loop("x q[i+1];"), _UC, "for", ""),
    "variable-as-parameter": (_loop("rz(i) q[0];"), _UC, "for", ""),
    "variable-in-condition": (_loop("if (i == 0) { x q[0]; }"), _UC, "for", ""),
    "variable-assignment": (
        _loop("i = 1;\n  x q[0];"),
        _UC,
        "for",
        "is not allowed in a loop body",
    ),
    "uint-variable": (_loop("x q[i];", "for uint i in [0:1]"), _UC, "for", ""),
    "sized-int-variable": (_loop("x q[i];", "for int[8] i in [0:1]"), _UC, "for", ""),
    "stepped-range": (_loop("x q[i];", "for int i in [0:2:3]"), _UC, "for", ""),
    "discrete-set": (_loop("x q[i];", "for int i in {0, 2}"), _UC, "for", ""),
    "register-iterable": (_loop("x q[0];", "for int i in c"), _UC, "for", ""),
    "undeclared-bound": (_loop("x q[i];", "for int i in [0:k]"), _UC, "for", ""),
    "register-bound": (_loop("x q[i];", "for int i in [0:c]"), _UC, "for", ""),
    "measured-bit-bound": (_loop("x q[i];", "for int i in [0:c[0]]"), _UC, "for", ""),
    "nested-loop": (_loop("for int j in [0:1] { x q[j]; }"), _UC, "for", ""),
    "loop-in-if-body": (
        H + "if (c[0] == 1) {\n  for int i in [0:1] { x q[i]; }\n}\n",
        _UC,
        "for",
        "",
    ),
    "two-quantum-registers": (
        H + "qubit[2] r;\nfor int i in [0:1] {\n  x q[i];\n}\n",
        _UC,
        "for",
        "",
    ),
    "uint-const": (
        H + "const uint N = 2;\nfor int i in [0:N-1] { x q[i]; }\n",
        _UC,
        "const",
        "",
    ),
    "sized-int-const": (
        H + "const int[8] N = 2;\nfor int i in [0:N-1] { x q[i]; }\n",
        _UC,
        "const",
        "",
    ),
    "unused-const": (H + "const int n = 1;\nfor int i in [0:1] { x q[i]; }\n", _UC, "const", ""),
    "const-qubit-width": (
        "OPENQASM 3.0;\nconst int N = 4;\nqubit[N] q;\nbit[2] c;\n"
        "for int i in [0:N-1] { x q[i]; }\n",
        _UC,
        "qubit",
        "integer literal",
    ),
    "const-division": (
        H + "const int N = 4 / 2;\nfor int i in [0:N-1] { x q[i]; }\n",
        _UC,
        "const",
        "",
    ),
    "gate-modifier-in-body": (
        _loop("ctrl @ x q[0], q[1];"),
        Qasm3UnsupportedGateError,
        "x",
        "modifiers",
    ),
    "loop-variable-shadows-declared-name": (
        _loop("x q[0];", "for int c in [0:1]"),
        _UC,
        "for",
        "",
    ),
    "expanded-register-collides-with-declared-name": (
        H + "bit[1] s__1;\nfor int i in [0:1] {\n  bit[1] s;\n  s[0] = measure q[i];\n}\n",
        _UC,
        "for",
        "",
    ),
    "while-equality-condition": (_while(head="int i = 0;\nwhile (c[0] == 1)"), _UC, "while", ""),
    "while-greater-than-condition": (_while(head="int i = 1;\nwhile (i > 0)"), _UC, "while", ""),
    "while-condition-on-register-bit": (
        _while(head="int i = 1;\nwhile (c[0] < 2)"),
        _UC,
        "while",
        "",
    ),
    "while-decrement-step": (_while(step="i -= 1;"), _UC, "while", ""),
    "while-plain-assignment-step": (_while(step="i = i + 1;"), _UC, "while", ""),
    "while-step-of-two": (_while(step="i += 2;"), _UC, "while", ""),
    "while-missing-step": (_while(step=""), _UC, "while", ""),
    "while-step-not-last": (_while(body="i += 1;", step="x q[0];"), _UC, "while", ""),
    "while-without-counter-declaration": (_while(head="while (i <= 3)"), _UC, "while", ""),
    "while-counter-used-twice": (
        _while(tail="while (i <= 3) {\n  x q[i];\n  i += 1;\n}\n"),
        _UC,
        "while",
        "",
    ),
    "while-sized-counter": (_while(head="int[8] i = 1;\nwhile (i <= 3)"), _UC, "int", ""),
    "while-uninitialized-counter": (_while(head="int i;\nwhile (i <= 3)"), _UC, "int", ""),
    "while-counter-shadows-declared-name": (
        _while(body="x q[c];", head="int c = 1;\nwhile (c <= 3)", step="c += 1;"),
        _UC,
        "int",
        "",
    ),
    "while-counter-followed-by-gate": (
        _while(head="int i = 1;\nx q[0];\nwhile (i <= 3)"),
        _UC,
        "int",
        "",
    ),
    "while-counter-at-end": (H + "x q[0];\nint i = 1;\n", _UC, "int", ""),
    "while-second-step": (_while(body="x q[i];\n  i += 1;"), _UC, "while", ""),
    "while-measure-into-counter": (_while(body="i = measure q[0];"), _UC, "while", ""),
    "while-counter-read-after-loop": (_while(tail="x q[i];\n"), _UC, "x", ""),
    "while-reset-in-body": (_while(body="reset q[i];"), _UC, "while", ""),
    "while-above-iteration-limit": (
        _while(body="x q[0];", head="int i = 0;\nwhile (i <= 1024)"),
        _UC,
        "while",
        "1024",
    ),
    # 循环变量名与计数器名在循环后保留：写回把顶层声明提到循环之前，同名声明无法写回。
    "register-named-like-an-earlier-loop-variable": (
        _loop("x q[i];", "for int i in [0:0]") + "bit[1] i;\n",
        _UC,
        "for",
        "name 'i' is already used by a loop",
    ),
    "register-named-like-an-earlier-counter": (
        _while(head="int i = 0;\nwhile (i < 1)", tail="bit[1] i;\n"),
        _UC,
        "for",
        "name 'i' is already used by a loop",
    ),
    "const-named-like-an-earlier-loop-variable": (
        _loop("x q[i];", "for int i in [0:0]")
        + "const int i = 1;\nfor int j in [0:i] { x q[j]; }\n",
        _UC,
        "const",
        "has a declared, gate or constant name",
    ),
    "const-named-like-a-constant": (
        H + "const int pi = 1;\nfor int i in [0:pi] { x q[i]; }\n",
        _UC,
        "const",
        "has a declared, gate or constant name",
    ),
    "const-named-like-a-gate": (
        H + "const int x = 1;\nfor int i in [0:x] { h q[i]; }\n",
        _UC,
        "const",
        "has a declared, gate or constant name",
    ),
    "upper-case-loop-variable-named-like-a-gate": (
        _loop("X q[0];", "for int X in [0:0]"),
        _UC,
        "for",
        "has a declared, gate or constant name",
    ),
    "if-body-index-out-of-range": (
        _loop("if (c[0] == 1) { x q[9]; }"),
        _UC,
        "if",
        "index 9 is outside",
    ),
    "if-body-index-out-of-range-in-empty-loop": (
        _loop("if (c[0] == 1) { x q[9]; }", "for int i in [1:0]"),
        _UC,
        "if",
        "index 9 is outside",
    ),
}

# (源码, 等价的平坦正文, 循环节点的 (start, stop))。
EXPANDED = {
    "literal-bounds": (
        _loop("x q[i];", "for int i in [1:3]"),
        "x q[1];\nx q[2];\nx q[3];\n",
        (1, 3),
    ),
    "const-bounds": (
        H + "const int N = 2;\nfor int i in [0:N-1] {\n  x q[i];\n}\n",
        "x q[0];\nx q[1];\n",
        (0, 1),
    ),
    "const-expression-bounds": (
        H + "const int N = 2;\nconst int M = N * 2 - 1;\nfor int i in [-1 + N:M] {\n  x q[i];\n}\n",
        "x q[1];\nx q[2];\nx q[3];\n",
        (1, 3),
    ),
}

# (计数器 while 源码, 等价的 for 源码, 等价的平坦正文, 循环节点的 (start, stop))。
WHILE_EXPANDED = {
    "less-or-equal": (
        _while(),
        _loop("x q[i];", "for int i in [1:3]"),
        "x q[1];\nx q[2];\nx q[3];\n",
        (1, 3),
    ),
    "less-than": (
        _while(head="int i = 1;\nwhile (i < 3)"),
        _loop("x q[i];", "for int i in [1:2]"),
        "x q[1];\nx q[2];\n",
        (1, 2),
    ),
    "const-bound-with-register": (
        H + "const int N = 3;\nint i = 1;\n"
        "while (i < N) {\n  bit[1] s;\n  s[0] = measure q[i];\n  i += 1;\n}\n",
        H + "const int N = 3;\nfor int i in [1:N-1] {\n  bit[1] s;\n  s[0] = measure q[i];\n}\n",
        "bit[1] s__0;\ns__0[0] = measure q[1];\nbit[1] s__1;\ns__1[0] = measure q[2];\n",
        (1, 2),
    ),
}

# 迭代 n 次的循环；循环体不依赖 i，所以去掉上限后 n 次都能实例化。
LIMIT_LOOPS = {
    "for": lambda n: _loop("x q[0];", f"for int i in [0:{n - 1}]"),
    "while": lambda n: _while(body="x q[0];", head=f"int i = 0;\nwhile (i < {n})"),
}

EMPTY_RANGE = _loop("x q[i];", "for int i in [1:0]")
AT_LIMIT = _loop("x q[0];", "for int i in [0:1023]")
HUGE_RANGE = _loop("x q[0];", "for int i in [0:9999999]")
UNBRACED = H + "for int i in [1:3] x q[i];\n"
MEASURE_ARROW = _loop("measure q[i] -> c[i];")
MEASURE_ASSIGNMENT = _loop("c[i] = measure q[i];")
FRESH_REGISTERS = _loop("bit[1] s;\n  s[0] = measure q[i];")
CLASSICAL_INDEX = _loop("c[i] = measure q[0];")
FLAT_TWO_REGISTERS = (
    "OPENQASM 3.0;\nqubit[2] a;\nqubit[1] b;\nbit[2] c;\n"
    "h a[0];\ncx a[0], b[0];\nc[0] = measure a[0];\nif (c[0] == 1) { x b[0]; }\n"
)

LOOPED_SAMPLES = {
    **{name: case[0] for name, case in REJECTED.items()},
    **{name: case[0] for name, case in EXPANDED.items()},
    **{f"while-{name}": case[0] for name, case in WHILE_EXPANDED.items()},
    "empty-range": EMPTY_RANGE,
    "at-limit": AT_LIMIT,
    "huge-range": HUGE_RANGE,
    "unbraced": UNBRACED,
    "measure-arrow": MEASURE_ARROW,
    "measure-assignment": MEASURE_ASSIGNMENT,
    "fresh-registers": FRESH_REGISTERS,
    "classical-index": CLASSICAL_INDEX,
}


@pytest.mark.parametrize("case", REJECTED)
def test_looped_entry_rejects_outside_the_subset(case):
    """子集外的写法抛确切类型的错误，消息前缀指向拦截它的守卫，移除守卫会改变前缀。"""
    source, error_type, construct, fragment = REJECTED[case]
    with pytest.raises(QaijiIRError) as raised:
        _entry()(source)
    error = raised.value
    assert type(error) is error_type
    assert str(error).startswith(f"{construct} at ")
    assert fragment in str(error)


def test_looped_entry_accepts_two_loops_with_the_same_variable():
    """循环变量名在循环后保留，但不算已声明名称：之后的循环可以再用同一个变量名。"""
    parsed = _entry()(H + "for int i in [0:1] { x q[i]; }\nfor int i in [2:3] { x q[i]; }\n")
    assert [(loop.variable, loop.start, loop.stop) for loop in _loops(parsed)] == [
        ("i", 0, 1),
        ("i", 2, 3),
    ]


@pytest.mark.parametrize("case", EXPANDED)
def test_looped_for_expands_the_closed_range_with_the_loop_value(case):
    """区间含两端，下标代入循环变量的取值；const 边界先求值，展开结果等于手写的平坦程序。"""
    source, flat_body, bounds = EXPANDED[case]
    parsed = _entry()(source)
    (loop,) = _loops(parsed)
    assert (loop.start, loop.stop) == bounds
    assert parsed.circuit.expand().circuit == from_qasm3(H + flat_body)


@pytest.mark.parametrize("case", WHILE_EXPANDED)
def test_looped_counter_while_equals_the_equivalent_for(case):
    """计数器 while 的起点取声明的初值，``<`` 不含右端、``<=`` 含右端，与等价的 for 得同一个循环节点。"""
    source, for_source, flat_body, bounds = WHILE_EXPANDED[case]
    parsed = _entry()(source)
    (loop,) = _loops(parsed)
    assert (loop.start, loop.stop) == bounds
    assert parsed.circuit == _entry()(for_source).circuit
    assert parsed.circuit.expand().circuit == from_qasm3(H + flat_body)


@pytest.mark.parametrize("kind", LIMIT_LOOPS)
def test_looped_iteration_limit_follows_the_parser_constant(kind, monkeypatch):
    """上限比较读解析器模块的上限常量：常量改为 4 时 5 次迭代拒收，4 次迭代接受。"""
    monkeypatch.setattr(qasm3_module, "MAX_LOOP_ITERATIONS", 4)
    with pytest.raises(QaijiIRError) as raised:
        _entry()(LIMIT_LOOPS[kind](5))
    assert type(raised.value) is Qasm3UnsupportedConstructError
    assert str(raised.value).startswith(f"{kind} at ")
    parsed = _entry()(LIMIT_LOOPS[kind](4))
    assert len(parsed.circuit.expand().circuit.gates) == 4


def test_looped_empty_range_has_no_operations():
    """上界小于下界时迭代 0 次，展开后没有任何操作。"""
    parsed = _entry()(EMPTY_RANGE)
    (loop,) = _loops(parsed)
    assert (loop.start, loop.stop, loop.values) == (1, 0, ())
    expanded = parsed.circuit.expand().circuit
    assert len(expanded.gates) == 0
    assert expanded == from_qasm3(H)


def test_looped_iteration_limit_admits_exactly_the_core_limit():
    """迭代数恰为 1024 时接受，上限比较含等号。"""
    parsed = _entry()(AT_LIMIT)
    (loop,) = _loops(parsed)
    assert len(loop.values) == 1024
    assert len(parsed.circuit.expand().circuit.gates) == 1024


def test_looped_parser_uses_the_core_iteration_limit():
    """解析器引用核心的上限常量本身，不另写一个字面量。"""
    assert qasm3_module.MAX_LOOP_ITERATIONS is loop_module.MAX_LOOP_ITERATIONS


def test_looped_huge_range_is_rejected_before_instantiation():
    """一千万次迭代的区间由边界算出迭代数后拒收，解析期间的内存峰值低于 8 MiB。"""
    entry = _entry()
    with pytest.raises(Qasm3UnsupportedConstructError):
        entry(HUGE_RANGE)
    tracemalloc.start()
    try:
        with pytest.raises(Qasm3UnsupportedConstructError) as raised:
            entry(HUGE_RANGE)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert str(raised.value).startswith("for at ")
    assert peak < 8 * 1024 * 1024


def test_looped_body_without_braces_equals_the_braced_body():
    """无花括号的单句循环体与带花括号的写法得到同一电路。"""
    entry = _entry()
    unbraced = entry(UNBRACED).circuit
    braced = entry(_loop("x q[i];", "for int i in [1:3]")).circuit
    assert unbraced == braced
    assert unbraced.expand().circuit == from_qasm3(H + "x q[1];\nx q[2];\nx q[3];\n")


def test_looped_measure_arrow_and_assignment_forms_are_equal():
    """循环体内两种测量写法都被接受，并且结果相同。"""
    entry = _entry()
    arrow = entry(MEASURE_ARROW).circuit.expand().circuit
    assignment = entry(MEASURE_ASSIGNMENT).circuit.expand().circuit
    assert arrow == assignment
    assert arrow == from_qasm3(H + "c[0] = measure q[0];\nc[1] = measure q[1];\n")


def test_looped_body_registers_are_fresh_per_iteration():
    """循环体声明的寄存器在第 k 轮展开为 s__k，两轮的测量写入不同的寄存器。"""
    expanded = _entry()(FRESH_REGISTERS).circuit.expand().circuit
    assert [register.name for register in expanded.cregs] == ["c", "s__0", "s__1"]
    flat = H + "bit[1] s__0;\nbit[1] s__1;\ns__0[0] = measure q[0];\ns__1[0] = measure q[1];\n"
    assert expanded == from_qasm3(flat)


def test_looped_loop_variable_indexes_classical_bits():
    """循环变量也可作经典下标，各轮写入不同的比特。"""
    expanded = _entry()(CLASSICAL_INDEX).circuit.expand().circuit
    assert expanded == from_qasm3(H + "c[0] = measure q[0];\nc[1] = measure q[0];\n")


def test_looped_entry_without_loops_matches_the_strict_entry():
    """不含循环的程序走同一段代码：多个量子寄存器照常接受，结果与严格入口相同。"""
    parsed = _entry()(FLAT_TWO_REGISTERS)
    assert parsed.declared_version == "3.0"
    assert _loops(parsed) == []
    assert parsed.circuit.expand().circuit == from_qasm3(FLAT_TWO_REGISTERS)


def test_looped_entry_calls_the_shared_parser_at_strict_stack_depth(monkeypatch):
    """三个入口都直接调用共享解析函数，栈深相同；只有新入口传入打开循环语法的参数。"""
    entry = _entry()
    real = qasm3_module._parse_source
    calls = []

    def recording(src, **options):
        calls.append((len(inspect.stack(0)), options))
        return real(src, **options)

    monkeypatch.setattr(qasm3_module, "_parse_source", recording)
    from_qasm3(FLAT_TWO_REGISTERS)
    parse_qasm3(FLAT_TWO_REGISTERS)
    entry(FLAT_TWO_REGISTERS)
    depths = [depth for depth, _ in calls]
    options = [option for _, option in calls]
    assert len(calls) == 3
    assert depths[0] == depths[1] == depths[2]
    assert options[0] == options[1]
    assert options[2] != options[0]


@pytest.mark.parametrize("sample", LOOPED_SAMPLES)
@pytest.mark.parametrize("entry", STRICT_ENTRIES)
def test_strict_entries_reject_looped_sources(entry, sample):
    """两个严格入口对任何含循环或 const 的程序仍然拒收。"""
    with pytest.raises(QaijiIRError):
        STRICT_ENTRIES[entry](LOOPED_SAMPLES[sample])
