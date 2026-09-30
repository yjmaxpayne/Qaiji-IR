# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""QASM3 到程序校验的真实闭环，以及本仓不变量的测试映射。

I-Q5.1 → J27 / J28 / J31：确定性 JSON、往返与全新进程字节一致。
I-Q5.2 → M18 / J26：模式版本固定。
I-Q5.3 → V03 / V06–V08：输出唯一声明且每位都被测量写入。
I-Q5.5 → J28 与字段面：程序只持有引用，不嵌入 kernel 主体。
I-Q5.6 → V01 / V02 / V04 / V05：解析与固定配方认证。
I-L5.3 空转：本仓没有 L2 measurement_map，不计分子。
I-L5.4 空转：程序模型无嵌套构造，不计分子。
"""

import pytest

from qaiji.codec import from_qasm3
from qaiji.core.program import (
    ExperimentMetadata,
    ProgramIR,
    ProgramValidationError,
    QuantumInvocation,
    ResultOutput,
    compute_kernel_ref,
    validate_program,
)

pytestmark = pytest.mark.integration

_BELL_QASM3 = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
bit[2] c;
h q[0];
cx q[0], q[1];
c[0] = measure q[0];
c[1] = measure q[1];
"""


def _program(ref: str) -> ProgramIR:
    return ProgramIR(
        quantum_invocations=(QuantumInvocation(ref),),
        experiment_metadata=ExperimentMetadata(1024),
        result_outputs=(ResultOutput(0, "c"),),
    )


def test_qasm3_to_validated_program_closure() -> None:
    """跨 codec、L4 和 L5 真跑，序列化后仍可认证同一电路。"""
    circuit = from_qasm3(_BELL_QASM3)
    ref = compute_kernel_ref(circuit)
    program = _program(ref)
    restored = ProgramIR.from_json(program.to_json())
    assert restored == program
    assert validate_program(restored, {ref: circuit}) is None


def test_qasm3_kernel_edit_after_reference_fails_validation() -> None:
    """旧引用下放入编辑过的解析结果，闭环应拒绝内容漂移。"""
    original = from_qasm3(_BELL_QASM3)
    ref = compute_kernel_ref(original)
    program = ProgramIR.from_json(_program(ref).to_json())
    edited = from_qasm3(_BELL_QASM3.replace("h q[0];", "x q[0];"))
    with pytest.raises(ProgramValidationError) as caught:
        validate_program(program, {ref: edited})
    assert len(caught.value.problems) == 1
    assert "re-hashes to" in caught.value.problems[0]
