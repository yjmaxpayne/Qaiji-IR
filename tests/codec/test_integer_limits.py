# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""整数字面量超出解释器十进制位数上限时，两个解析入口只接受或抛 typed 错误。"""

import math
import re
import sys

import pytest

from qaiji.codec import from_qasm3, parse_qasm3, to_qasm3
from qaiji.codec import qasm3 as qasm3_module
from qaiji.core.circuit import GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister
from qaiji.exceptions import QaijiIRError, Qasm3ParseError, Qasm3UnsupportedConstructError

# sys.set_int_max_str_digits 允许的最小值：输入随之缩小，判据也不依赖解释器默认的 4300。
_D = 640
DEC_OVER = "1" + "0" * _D
DEC_AT = "9" * _D
# 都不超过位数上限，但都超出 float 范围；未超限的十六进制同样走到参数求值。
HUGE = {"decimal-400": "1" + "0" * 400, "decimal-at-limit": DEC_AT, "hex": "0x" + "f" * 300}
# 十六/二/八进制不受解析期位数上限约束；10**D 是第一个十进制化会失败的值。
NONDECIMAL_OVER = {"hex": hex(10**_D), "binary": bin(10**_D), "octal": oct(10**_D)}
NONDECIMAL_AT = {"hex": hex(10**_D - 1), "binary": bin(10**_D - 1), "octal": oct(10**_D - 1)}
ENTRIES = {"from_qasm3": from_qasm3, "parse_qasm3": parse_qasm3}

_Q1C = "qubit[1] q;\nbit[1] c;\n"
# 每个整数字面量取值点一个模板；{N} 用 str.replace 代入，避免与 QASM 的花括号冲突。
POSITIONS = {
    "qubit-width": "qubit[{N}] q;",
    "bit-width": "qubit q;\nbit[{N}] c;",
    "gate-index": "qubit[2] q;\ncx q[0], q[{N}];",
    "measure-source": _Q1C + "measure q[{N}] -> c[0];",
    "measure-target": _Q1C + "measure q[0] -> c[{N}];",
    "condition-index": _Q1C + "if (c[{N}] == 1) x q[0];",
    "condition-bit-value": _Q1C + "if (c[0] == {N}) x q[0];",
    "condition-register-value": _Q1C + "if (c == {N}) x q[0];",
    "body-index": _Q1C + "if (c[0] == 1) x q[{N}];",
    "parameter": "qubit q;\nrx({N}) q[0];",
}

CONSTRUCTS = {
    "qubit-width": "qubit",
    "bit-width": "classical declaration",
    "gate-index": "cx",
    "measure-source": "measure",
    "measure-target": "measure",
    "condition-index": "if",
    "condition-bit-value": "if",
    "condition-register-value": "if",
    "body-index": "x",
    "parameter": "parameter",
}


@pytest.fixture(autouse=True)
def _digit_limit():
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(_D)
    yield
    sys.set_int_max_str_digits(previous)


def _source(position: str, literal: str) -> str:
    return POSITIONS[position].replace("{N}", literal)


def _native_message(call) -> str:
    """取 Python 自身在同一转换上的报错原文：消息不由本库新造。"""
    with pytest.raises(ValueError) as raised:
        call()
    return str(raised.value)


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("position", POSITIONS)
def test_decimal_literal_over_limit_is_parse_error(entry, position):
    """解析器把超限十进制转成整数时的 ValueError 收口为 Qasm3ParseError，并保留原因。"""
    native = _native_message(lambda: int(DEC_OVER))
    with pytest.raises(Qasm3ParseError) as raised:
        ENTRIES[entry](_source(position, DEC_OVER))
    assert str(raised.value) == f"source at 1:1: {native}"
    assert type(raised.value.__cause__) is ValueError
    assert str(raised.value.__cause__) == native


def test_decimal_literal_at_limit_is_not_a_parse_error(monkeypatch):
    """恰为 D 位的十进制按既有语义处理；遍历阶段的 ValueError 也不被改写成源码级解析错误。"""
    limit = int(DEC_AT)
    assert from_qasm3(_source("qubit-width", DEC_AT)).num_qubits == limit
    assert from_qasm3(_source("bit-width", DEC_AT)).cregs[0].size == limit
    assert from_qasm3(_source("condition-register-value", DEC_AT)).gates[0].value == limit
    with pytest.raises(Qasm3UnsupportedConstructError) as raised:
        from_qasm3(_source("gate-index", DEC_AT))
    assert str(raised.value) == f"cx at 2:1: index {DEC_AT} is outside qubit register 'q' of size 2"

    # 只包裹 openqasm3.parse 这一步：注入的遍历期错误必须原样外泄。
    error = ValueError("injected traversal failure")

    def fail_handler(statement, state):
        raise error

    monkeypatch.setattr(qasm3_module, "_handle_gate", fail_handler)
    with pytest.raises(ValueError) as injected:
        from_qasm3("qubit q; x q[0];")
    assert injected.value is error


def _parameter_error(source: str) -> str:
    with pytest.raises(Qasm3UnsupportedConstructError) as raised:
        from_qasm3(source)
    return str(raised.value)


# 超大整数出现在参数表达式的每种形态里；1/N 下溢为 0.0 被接受，单独钉在下一个测试。
OVERFLOW_FORMS = {
    "literal": "rx({N}) q[0];",
    "negated": "rx(-{N}) q[0];",
    "parenthesised": "rx((({N}))) q[0];",
    "negated-parenthesised": "rx(-(({N}))) q[0];",
    "left-plus": "rx({N} + 1) q[0];",
    "right-plus": "rx(1 + {N}) q[0];",
    "left-minus": "rx({N} - 1) q[0];",
    "right-minus": "rx(1 - {N}) q[0];",
    "left-times": "rx({N} * 1) q[0];",
    "right-times": "rx(1 * {N}) q[0];",
    "left-divide": "rx({N} / 1) q[0];",
    "pi-times": "rx(pi * {N}) q[0];",
    "u3-third": "u3(0, 0, {N}) q[0];",
    "if-body": "if (c[0] == 1) rx({N}) q[0];",
}


@pytest.mark.parametrize("value", HUGE)
@pytest.mark.parametrize("form", OVERFLOW_FORMS)
def test_integer_parameter_overflow_reports_nonfinite(form, value):
    """超出 float 范围的整数与 1e400 同判：走既有的有限性检查，而不是外泄 OverflowError。"""
    source = _Q1C + OVERFLOW_FORMS[form].replace("{N}", HUGE[value])
    gate = "u3" if form == "u3-third" else "rx"
    assert re.fullmatch(
        rf"{gate} at \d+:\d+: Gate parameters must be finite", _parameter_error(source)
    )


@pytest.mark.parametrize("value", HUGE)
def test_reciprocal_of_huge_integer_underflows_to_zero(value):
    circuit = from_qasm3(f"qubit q;\nrx(1 / {HUGE[value]}) q[0];")
    assert circuit.gates[0].gate_type is GateType.RX
    assert circuit.gates[0].params == (0.0,)
    # 溢出取 +inf 而非 -inf：-inf 会下溢成 -0.0，并原样写进 to_qasm3 的输出。
    assert math.copysign(1.0, circuit.gates[0].params[0]) == 1.0


@pytest.mark.parametrize("value", HUGE)
@pytest.mark.parametrize("expression", ["{N} ** 2", "2 ** {N}", "{N} % 2"])
def test_power_and_modulo_of_huge_integer_report_unsupported_operator(expression, value):
    """运算数先求值再查运算符：溢出的运算数不得抢在「不支持的运算符」之前报错。"""
    source = "qubit q;\nrx(" + expression.replace("{N}", HUGE[value]) + ") q[0];"
    assert _parameter_error(source) == "parameter at 2:4: unsupported binary expression"


@pytest.mark.parametrize("value", HUGE)
def test_huge_integer_arithmetic_side_effects_are_pinned(value):
    """inf 替换的全部可见副作用：下溢为有限值的被接受，inf/inf 与 inf-inf 报非有限，1/0.0 报除零。"""
    huge = HUGE[value]
    for expression, expected in (("pi / {N}", 0.0), ("1 / {N} + 1", 1.0)):
        circuit = from_qasm3("qubit q;\nrx(" + expression.replace("{N}", huge) + ") q[0];")
        assert circuit.gates[0].params == (expected,)
    with pytest.raises(Qasm3ParseError) as raised:
        from_qasm3(f"qubit q;\nrx(1 / (1 / {huge})) q[0];")
    assert str(raised.value) == "parameter at 2:4: division by zero"
    for expression in ("{N} - {N}", "{N} / {N}"):
        source = "qubit q;\nrx(" + expression.replace("{N}", huge) + ") q[0];"
        assert _parameter_error(source) == "rx at 2:1: Gate parameters must be finite"


def _location_of(source: str, literal: str) -> tuple[int, int]:
    offset = source.index(literal)
    return source.count("\n", 0, offset) + 1, offset - source.rfind("\n", 0, offset)


def _str_limit_message() -> str:
    return _native_message(lambda: str(10**_D))


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("base", NONDECIMAL_OVER)
@pytest.mark.parametrize("position", POSITIONS)
def test_nondecimal_literal_over_limit_is_parse_error(position, base, entry):
    """非十进制字面量的值无法十进制化时，在读取点拒收，而不是在格式化消息或 to_qasm3 时外泄。"""
    native = _str_limit_message()
    with pytest.raises(Qasm3ParseError) as raised:
        ENTRIES[entry](_source(position, NONDECIMAL_OVER[base]))
    pattern = rf"{CONSTRUCTS[position]} at \d+:\d+: {re.escape(native)}"
    assert re.fullmatch(pattern, str(raised.value))
    assert type(raised.value.__cause__) is ValueError
    assert str(raised.value.__cause__) == native


@pytest.mark.parametrize("base", NONDECIMAL_AT)
def test_nondecimal_literal_below_limit_keeps_existing_behaviour(base):
    """恰能十进制化的值不受新检查影响：每个取值点都保持原有判决与原消息。"""
    literal, value = NONDECIMAL_AT[base], 10**_D - 1
    assert from_qasm3(_source("qubit-width", literal)).num_qubits == value
    assert from_qasm3(_source("condition-register-value", literal)).gates[0].value == value
    register = ClassicalRegister("c", 1)
    core = _native_message(lambda: ClassicalBit(register, value))
    expected = {
        "gate-index": f"cx at 2:1: index {value} is outside qubit register 'q' of size 2",
        "measure-target": f"measure at 3:1: {core}",
        "condition-bit-value": "if at 3:1: bit condition value must be 0 or 1",
        "parameter": "rx at 2:1: Gate parameters must be finite",
    }
    for position, message in expected.items():
        with pytest.raises(Qasm3UnsupportedConstructError) as raised:
            from_qasm3(_source(position, literal))
        assert str(raised.value) == message, position


@pytest.mark.parametrize("entry", ENTRIES)
def test_total_qubit_count_over_limit_is_parse_error(entry):
    """每个宽度都能十进制化、总 qubit 数却不能：to_qasm3 要写出总数，故在越限的那条声明处拒收。"""
    native = _native_message(lambda: str(2 * int(DEC_AT)))
    with pytest.raises(Qasm3ParseError) as raised:
        ENTRIES[entry](f"qubit[{DEC_AT}] a;\nqubit[{DEC_AT}] b;")
    assert str(raised.value) == f"qubit at 2:1: {native}"
    assert type(raised.value.__cause__) is ValueError
    assert str(raised.value.__cause__) == native
    # 同一条声明里，既有的重名检查先于总数检查。
    with pytest.raises(Qasm3UnsupportedConstructError) as duplicate:
        ENTRIES[entry](f"qubit[{DEC_AT}] q;\nqubit[{DEC_AT}] q;")
    assert str(duplicate.value) == "qubit at 2:1: qubit register 'q' is already declared"

    # 经典位按寄存器逐个写出，总数不需要十进制化：同形的 bit 声明仍被接受并往返相等。
    source = "qubit q;\n" + "".join(f"bit[{DEC_AT}] c{i};\n" for i in range(11))
    circuit = ENTRIES[entry](source)
    circuit = getattr(circuit, "circuit", circuit)
    assert sum(register.size for register in circuit.cregs) >= 10**_D
    assert from_qasm3(to_qasm3(circuit)) == circuit


@pytest.mark.parametrize(
    "later",
    [f"qubit[{NONDECIMAL_OVER['hex']}] r;", f"qubit[{DEC_AT}] a;\nqubit[{DEC_AT}] b;"],
    ids=["width-over-limit", "total-over-limit"],
)
def test_prescan_does_not_preempt_earlier_statement_errors(later):
    """预扫描只累计 qubit 总数；越限的声明在按顺序处理到它时才报错，先出错的语句先报。"""
    with pytest.raises(Qasm3UnsupportedConstructError) as raised:
        from_qasm3("qubit[1] q;\ny q[5];\n" + later)
    assert str(raised.value) == "y at 2:1: index 5 is outside qubit register 'q' of size 1"


def _diagnostic_cases() -> dict[str, tuple[str, str, tuple[int, int]]]:
    literal = NONDECIMAL_OVER["hex"]
    cases = {}
    for position in POSITIONS:
        source = "// leading comment\n" + _source(position, literal).replace("\n", "\n  ")
        line, column = _location_of(source, literal)
        # openqasm3 给宽度字面量的 span 从左方括号起；坐标沿用库给出的节点起点，不另行修正。
        if position.endswith("-width"):
            column -= 1
        cases[position] = (source, CONSTRUCTS[position], (line, column))
    # 总 qubit 数没有单个越限字面量：位置取使总数越限的那条声明。
    total = f"qubit[{DEC_AT}] a;\nbit c;\n   qubit[{DEC_AT}] b;\nqubit[1] d;"
    cases["total-qubits"] = (total, "qubit", (3, 4))
    return cases


DIAGNOSTIC_CASES = _diagnostic_cases()


@pytest.mark.parametrize("case", DIAGNOSTIC_CASES)
def test_integer_limit_diagnostics_point_at_the_literal(case):
    """位置取越限字面量本身的起点，而不是所在语句的起点。"""
    source, construct, (line, column) = DIAGNOSTIC_CASES[case]
    with pytest.raises(Qasm3ParseError) as raised:
        from_qasm3(source)
    assert str(raised.value).startswith(f"{construct} at {line}:{column}: ")


# 负空间：进制 × 位数 × 出现位置。资源型的超大广播（如 qubit[10**18] 上的 h）不入。
ADVERSARIAL_VALUES = {
    "decimal-over": DEC_OVER,
    "decimal-at": DEC_AT,
    "decimal-400": "1" + "0" * 400,
    "decimal-small": "2",
    "hex-float-overflow": "0x" + "f" * 300,
    "hex-over": "0x" + "f" * (math.ceil(_D / math.log10(16)) + 130),
    "binary-over": "0b" + "1" * (math.ceil(_D / math.log10(2)) + 200),
    "octal-over": "0o" + "7" * (math.ceil(_D / math.log10(8)) + 130),
    "underscored-over": "1" + "_0" * _D,
    "underscored-half": "1" + "_0" * (_D // 2),
}
_H2 = 'OPENQASM 2.0;\ninclude "qelib1.inc";\n'
ADVERSARIAL_SURFACES = {
    **POSITIONS,
    "qubit-width-then-gate": "qubit[{N}] q;\nx q[0];",
    "total-qubits": "qubit[{N}] a;\nqubit[{N}] b;",
    "qreg-width": _H2 + "qreg q[{N}];\nx q[0];",
    "creg-width": _H2 + "qreg q[1];\ncreg c[{N}];\nmeasure q[0] -> c[0];",
    "single-qubit-index": "qubit[1] q;\nx q[{N}];",
    "parameter-positive": "qubit q;\nrx(+{N}) q[0];",
    **{f"parameter-{form}": _Q1C + text for form, text in OVERFLOW_FORMS.items()},
    "parameter-reciprocal": "qubit q;\nrx(1 / {N}) q[0];",
    "parameter-self-minus": "qubit q;\nrx({N} - {N}) q[0];",
    "parameter-power": "qubit q;\nrx({N} ** 2) q[0];",
    "parameter-exponent": "qubit q;\nrx(2 ** {N}) q[0];",
    "parameter-modulo": "qubit q;\nrx({N} % 2) q[0];",
    "parameter-imaginary": "qubit q;\nrx({N}im) q[0];",
    "const-declaration": "qubit q;\nconst int n = {N};",
    "for-range": "qubit q;\nfor int i in [0:{N}] { x q[0]; }",
    "delay": "qubit q;\ndelay[{N}ns] q[0];",
}
# 修复前曾被接受、随后在 to_qasm3 外泄裸 ValueError 的格。
_FORMER_ESCAPES = {
    (surface, value)
    for surface in (
        "qubit-width",
        "bit-width",
        "qubit-width-then-gate",
        "qreg-width",
        "creg-width",
        "condition-register-value",
    )
    for value in ("hex-over", "binary-over", "octal-over")
}


def _adversarial_source(surface: str, value: str) -> str:
    return ADVERSARIAL_SURFACES[surface].replace("{N}", ADVERSARIAL_VALUES[value])


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("value", ADVERSARIAL_VALUES)
@pytest.mark.parametrize("surface", ADVERSARIAL_SURFACES)
def test_adversarial_inputs_raise_only_qaiji_errors(surface, value, entry):
    """任何 str 输入只有两种结局：接受，或抛 QaijiIRError；其他异常直接让本测试报错。"""
    try:
        ENTRIES[entry](_adversarial_source(surface, value))
    except QaijiIRError:
        pass


@pytest.mark.parametrize("value", ADVERSARIAL_VALUES)
def test_accepted_programs_round_trip_after_integer_checks(value):
    """仍被接受的程序都能写回并原样读回；曾经接受后在 to_qasm3 外泄的格现在于解析时拒收。"""
    accepted = []
    for surface in ADVERSARIAL_SURFACES:
        try:
            circuit = from_qasm3(_adversarial_source(surface, value))
        except QaijiIRError:
            continue
        accepted.append(surface)
        assert from_qasm3(to_qasm3(circuit)) == circuit, surface
    assert not {(surface, value) for surface in accepted} & _FORMER_ESCAPES
    if value in {"decimal-at", "decimal-small", "underscored-half"}:
        assert "qubit-width" in accepted
