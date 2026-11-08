# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L5 程序与 L4 电路摘要之间的桥接。"""

from collections.abc import Mapping, Sequence

from qaiji.core import Circuit
from qaiji.core.program.model import ProgramIR
from qaiji.core.program.structured import ProgramCall, ProgramIf, ProgramIRV1
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

    def __init__(self, problems: Sequence[str], *, code: str | None = None, path: str = "") -> None:
        """保存问题并生成逐行汇总消息。

        Args:
            problems: 先调用序、后输出声明序的问题。
        """
        self.code = code
        self.path = path
        self.problems = tuple(problems)
        super().__init__(
            f"ProgramIR failed L4 validation with {len(self.problems)} problem(s):\n"
            + "\n".join(f"- {problem}" for problem in self.problems)
        )


def validate_program(program: ProgramIR | ProgramIRV1, kernels: Mapping[str, Circuit]) -> None:
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
    if isinstance(program, ProgramIRV1):
        _validate_control_flow(program, authenticated)


def _validate_control_flow(program: ProgramIRV1, circuits: Mapping[int, Circuit]) -> None:
    """检查调用绑定与结果必达。深度由不变量入口检查。"""
    order: list[int] = []

    def fail(path: str, message: str) -> None:
        raise ProgramValidationError(
            (f"CONTROL_FLOW {path}: {message}",),
            code="CONTROL_FLOW",
            path=path,
        )

    # 显式栈保留 then、else 顺序，避免深层对象先触发 Python 递归限制。
    tasks: list[tuple[bool, tuple[ProgramCall | ProgramIf, ...], int, set[int], str]] = [
        (False, program.control_flow, 0, set(), "/control_flow")
    ]
    completed: list[set[int]] = []
    while tasks:
        join, nodes, start, available, path = tasks.pop()
        if join:
            no = completed.pop()
            yes = completed.pop()
            tasks.append((False, nodes, start, yes & no, path))
            continue
        for offset in range(start, len(nodes)):
            node = nodes[offset]
            where = f"{path}/{offset}"
            index = node.invocation_index
            if index not in circuits:
                fail(where + "/invocation_index", "Unknown invocation index")
            if isinstance(node, ProgramCall):
                order.append(index)
                available.add(index)
                continue
            if index not in available:
                fail(where + "/invocation_index", "The predicate result is not available")
            circuit = circuits[index]
            registers = [r for r in circuit.cregs if r.name == node.register_name]
            if len(registers) != 1:
                fail(where + "/register_name", "The predicate register must be declared once")
            size = registers[0].size
            written = {
                h.creg_index
                for h in build_dataflow_summary(circuit)["measurement_handles"]
                if h.creg_name == node.register_name
            }
            if written != set(range(size)):
                fail(where + "/register_name", "The predicate register must be fully measured")
            if node.value >= 1 << size:
                fail(where + "/value", "The predicate value exceeds the register width")
            tasks.extend(
                [
                    (True, nodes, offset + 1, set(), path),
                    (False, node.else_body, 0, set(available), where + "/else_body"),
                    (False, node.then_body, 0, set(available), where + "/then_body"),
                ]
            )
            break
        else:
            completed.append(available)
    final = completed[0]
    if order != list(range(len(program.quantum_invocations))):
        fail("/control_flow", "Calls must cover the invocation table once in table order")
    for index, output in enumerate(program.result_outputs):
        if output.invocation_index not in final:
            fail(f"/result_outputs/{index}", "The output is unavailable on some paths")
