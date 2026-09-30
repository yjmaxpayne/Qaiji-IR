快速开始
========

本页假设你已完成 :doc:`installation` 中的安装步骤。

OpenQASM 往返
-------------

下面的示例从 OpenQASM 3 文本构造电路，再将电路序列化为规范化文本。示例使用包根
冻结的公共接口，并由 Sphinx 文档测试在构建流程中执行。

.. doctest::

   >>> from qaiji import from_qasm3, to_qasm3
   >>> source = (
   ...     "OPENQASM 3.0;\n"
   ...     'include "stdgates.inc";\n'
   ...     "qubit[2] q;\n"
   ...     "bit[2] c;\n"
   ...     "h q[0];\n"
   ...     "cx q[0], q[1];\n"
   ...     "c[0] = measure q[0];\n"
   ...     "c[1] = measure q[1];\n"
   ... )
   >>> circuit = from_qasm3(source)
   >>> circuit.num_qubits
   2
   >>> len(circuit)
   4
   >>> emitted = to_qasm3(circuit)
   >>> emitted.startswith("OPENQASM 3.0;\n")
   True
   >>> from_qasm3(emitted) == circuit
   True

直接构造电路
------------

也可以使用 :class:`qaiji.Circuit` 的便捷方法直接构造量子门序列：

.. doctest::

   >>> from qaiji import Circuit, GateType
   >>> bell = Circuit(2)
   >>> bell.h(0)
   >>> bell.cx(0, 1)
   >>> [gate.gate_type for gate in bell.gates]
   [<GateType.H: 'H'>, <GateType.CX: 'CX'>]

切片边界
--------

M-1 前端只接受已经登记的 OpenQASM 构件。遇到循环、脉冲语句或未支持的
门时，编解码器会抛出 :class:`qaiji.QaijiIRError` 的具体子类，不会静默丢弃信息。
序列化输出统一使用 OpenQASM 3.0；OpenQASM 2.0 输入只作为兼容入口读取。

语义判决最小示例
----------------

``qaiji.core.semantics`` 在电路前端之上回答"这次变换是否保持语义"。下面的示例对一个
整圈 ``RZ`` 旋转做 :meth:`~qaiji.Circuit.canonicalize`：门被折叠为恒等门，但判决引擎
判定该变换只保持到全局相位（``UP_TO_PHASE``），而不是算符严格相等（``EXACT``）：

.. doctest::

   >>> import math
   >>> from qaiji import Circuit, GateType
   >>> from qaiji.core.semantics import check_preservation
   >>> circuit = Circuit(1)
   >>> circuit.rz(0, math.tau)
   >>> circuit.gates[0].gate_type
   <GateType.RZ: 'RZ'>
   >>> canonical = circuit.canonicalize()
   >>> canonical.gates[0].gate_type
   <GateType.I: 'I'>
   >>> verdict = check_preservation(circuit, canonical, stage="canonicalize")
   >>> verdict.status
   'passed'
   >>> verdict.equiv_level
   <EquivLevel.UP_TO_PHASE: 'UP_TO_PHASE'>

下一步
------

阅读 :doc:`/conventions`，确认物理适配器必须遵守的基矢和相位约定；完整类型与函数说明见
:doc:`/getting-started/semantics` 和 :doc:`/getting-started/program` 可继续学习
L4 摘要与 L5 程序校验；完整类型与函数说明见 :doc:`/api/index`。
