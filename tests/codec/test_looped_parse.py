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
    "variable-assignment": (_loop("i = 1;\n  x q[0];"), _UC, "for", ""),
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


@pytest.mark.parametrize("case", EXPANDED)
def test_looped_for_expands_the_closed_range_with_the_loop_value(case):
    """区间含两端，下标代入循环变量的取值；const 边界先求值，展开结果等于手写的平坦程序。"""
    source, flat_body, bounds = EXPANDED[case]
    parsed = _entry()(source)
    (loop,) = _loops(parsed)
    assert (loop.start, loop.stop) == bounds
    assert parsed.circuit.expand().circuit == from_qasm3(H + flat_body)


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
