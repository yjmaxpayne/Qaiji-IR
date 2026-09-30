# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L5 程序与 L4 电路摘要之间的桥接。"""

from collections.abc import Mapping, Sequence

from qaiji.core import Circuit
from qaiji.core.program.model import ProgramIR
from qaiji.core.semantics import (
    annotate_circuit,
    build_dataflow_summary,
    build_semantic_summary,
    canonical_summary_hash,
)
from qaiji.exceptions import QaijiIRError


def compute_kernel_ref(circuit: Circuit) -> str:
    """用单参数固定配方计算引用，不 canonicalize，绑定 qaiji.semantic_summary.v0。

    Args:
        circuit: 待计算引用的 L4 电路。

    Returns:
        带 sha256 前缀的摘要哈希引用。
    """
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))
    return canonical_summary_hash(summary)


class ProgramValidationError(QaijiIRError):
    """携带按判决顺序收集的全部程序问题。"""

    problems: tuple[str, ...]

    def __init__(self, problems: Sequence[str]) -> None:
        """保存问题并生成逐行汇总消息。

        Args:
            problems: 先调用序、后输出声明序的问题。
        """
        self.problems = tuple(problems)
        super().__init__(
            f"ProgramIR failed L4 validation with {len(self.problems)} problem(s):\n"
            + "\n".join(f"- {problem}" for problem in self.problems)
        )


def validate_program(program: ProgramIR, kernels: Mapping[str, Circuit]) -> None:
    """认证调用并核对输出，按调用序、再输出声明序收集问题。

    认证的是解析表内容，而非调用方持有的对象；未被引用的表项不校验。
    被写入但未声明为输出合法，输出按寄存器名解析，继承 L4 的按名语义。
    判决是调用时刻快照，之后修改电路不影响已经返回的结果。
    损坏电路的 TypeError 原样传播，不转为程序问题。

    Args:
        program: 待校验的程序。
        kernels: 引用到 L4 电路的解析表。

    Raises:
        ProgramValidationError: 引用认证或输出寄存器校验失败。
        TypeError: L4 无法分类损坏电路中的节点。
    """
    problems: list[str] = []
    authenticated: dict[int, Circuit] = {}
    for index, invocation in enumerate(program.quantum_invocations):
        ref = invocation.kernel_ref
        if ref not in kernels:
            problems.append(f"invocation {index}: kernel_ref {ref} is not in the kernel table")
            continue
        circuit = kernels[ref]
        actual = compute_kernel_ref(circuit)
        if actual != ref:
            problems.append(f"invocation {index}: kernel re-hashes to {actual}, not {ref}")
            continue
        authenticated[index] = circuit
    for output in program.result_outputs:
        index, name = output.invocation_index, output.register_name
        if index not in authenticated:
            continue
        circuit = authenticated[index]
        registers = [register for register in circuit.cregs if register.name == name]
        prefix = f"output ({index}, {name!r}):"
        if not registers:
            problems.append(f"{prefix} register is not declared by the kernel")
            continue
        if len(registers) > 1:
            problems.append(f"{prefix} register is declared {len(registers)} times by the kernel")
            continue
        handles = build_dataflow_summary(circuit)["measurement_handles"]
        written = {handle.creg_index for handle in handles if handle.creg_name == name}
        missing = sorted(set(range(registers[0].size)) - written)
        if missing:
            problems.append(f"{prefix} bits {missing} are never written by a measurement")
    if problems:
        raise ProgramValidationError(tuple(problems))
