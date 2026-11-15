# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""多位寄存器上的 ``if (s[k] == v)``：降级为位级条件，并按原样导出。"""

from __future__ import annotations

import pytest

from qaiji.codec import from_qasm3, to_qasm3
from qaiji.core.classical import Conditional

OUTCOMES = ("00", "01", "10", "11")


def program(width: int, condition: str) -> str:
    measures = "".join(f"s[{bit}] = measure q[{bit}];\n" for bit in range(width))
    return (
        f"OPENQASM 3.0;\nqubit[{width}] q;\nbit[{width}] s;\n{measures}"
        f"if ({condition}) {{ x q[0]; }}\n"
    )


def enters(conditional: Conditional, outcome: str) -> bool:
    """参考谓词。结果串最右一位是 ``s[0]``。"""
    value = int(outcome, 2)
    if conditional.bit_index is None:
        return value == conditional.value
    return (value >> conditional.bit_index) & 1 == conditional.value


@pytest.mark.parametrize(
    ("condition", "entered"),
    [
        ("s[0] == 1", {"01", "11"}),
        ("s[1] == 1", {"10", "11"}),
        ("s[1] == 0", {"00", "01"}),
    ],
)
def test_bit_condition_enters_on_the_indexed_bit(condition, entered):
    conditional = from_qasm3(program(2, condition)).gates[-1]
    assert isinstance(conditional, Conditional)
    assert {outcome for outcome in OUTCOMES if enters(conditional, outcome)} == entered


def test_bit_condition_round_trips_through_qasm3():
    circuit = from_qasm3(program(3, "s[2] == 0"))
    text = to_qasm3(circuit)
    assert "s[2] == 0" in text
    assert from_qasm3(text) == circuit
    assert from_qasm3(text).gates[-1].bit_index == 2
