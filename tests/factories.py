# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""共享的电路工厂，以一个在整个 tests/ 下唯一的 basename 供导入。

有意不放进 conftest.py：tests/semantics/ 下现在也有一个 conftest.py（全新
进程前置守卫），而 pytest 的裸名模块解析 —— tests/ 下任何地方都没有 __init__.py ——
会让两个同名 "conftest.py" 在 sys.modules 里相撞，对某个 worker 而言后加载的那个
会在该进程余下的时间里赢得 `from conftest import X`（已复现：一旦
tests/semantics/conftest.py 存在且在其后加载，就会打断
tests/codec/test_roundtrip_qasm3.py 里的 `from conftest import ghz_circuit`）。
basename 唯一就不存在这种冲突。
"""

from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure

PROGRAM_V1_PUBLIC_NAMES = frozenset(
    {
        "ProgramCall",
        "ProgramIf",
        "ProgramIRV1",
        "dump_program",
        "load_program",
    }
)
LOOP_PUBLIC_NAMES = frozenset(
    {
        "BoundedLoop",
        "ConditionalTemplate",
        "ExpandedCircuit",
        "GateTemplate",
        "LoopIndex",
        "LoopedCircuit",
        "MeasureTemplate",
        "OperationProvenance",
        "SourceSpan",
    }
)
LOOP_ERROR_PUBLIC_NAMES = frozenset({"LoopNotExpandedError", "LoopedCircuitError"})
LOOPED_CODEC_PUBLIC_NAMES = frozenset({"ParsedLoopedQasm3", "parse_looped_qasm3"})
REGION_PUBLIC_NAMES = frozenset({"Region", "annotate_looped", "regions_of"})

# 两轮重复码：循环前注入一个错误，循环体在两次症状测量后做 4 个条件纠正。
# 注入使循环位于顶层位置 1；循环体内的声明 `bit[2] s;` 不计位置，
# 10 个门与测量节点之后，4 个条件体位于位置 10 至 13。
CORRECTED_TWO_ROUND_CODE = """OPENQASM 3.0;
include "stdgates.inc";
qubit[4] q;
x q[1];
for int r in [0:1] {
  bit[2] s;
  h q[3]; cz q[0], q[3]; cz q[3], q[1]; h q[3]; s[0] = measure q[3];
  h q[3]; cz q[1], q[3]; cz q[2], q[3]; h q[3]; s[1] = measure q[3];
  if (s == 3) { x q[0]; }
  if (s == 1) { x q[1]; }
  if (s == 2) { x q[2]; }
  if (s[1] == 1) { x q[3]; }
}
"""

# 测量之后的循环位于顶层位置 1；循环体内的条件体位于位置 1。
# 用 ``str.format(stop=...)`` 填入循环上界。
LOOP_WITH_CONDITIONAL = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
bit[1] c;
c[0] = measure q[0];
for int i in [0:{stop}] {{ x q[0]; if (c[0] == 1) {{ x q[1]; }} }}
"""


def bell_circuit() -> Circuit:
    """构造一个带测量的两比特 Bell 电路。"""
    register = ClassicalRegister("c", 2)
    circuit = Circuit(2)
    circuit.add_register(register)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
    circuit.add_measure(Measure(1, ClassicalBit(register, 1)))
    return circuit


def ghz_circuit(n: int = 3) -> Circuit:
    """构造一个指定宽度、带测量的 GHZ 电路。"""
    register = ClassicalRegister("c", n)
    circuit = Circuit(n)
    circuit.add_register(register)
    circuit.h(0)
    for target in range(1, n):
        circuit.cx(0, target)
    for qubit in range(n):
        circuit.add_measure(Measure(qubit, ClassicalBit(register, qubit)))
    return circuit


def feedforward_circuit() -> Circuit:
    """构造一次测量，后接一个寄存器级条件节点。"""
    register = ClassicalRegister("c", 1)
    circuit = Circuit(2)
    circuit.add_register(register)
    circuit.h(0)
    circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
    circuit.add_conditional(Conditional(register, 1, (Gate(GateType.X, (1,)),)))
    return circuit
