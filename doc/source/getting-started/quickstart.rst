快速开始
========

本页只用包根接口完成三件事：OpenQASM 3 往返、直接构造电路、得到一个保持性判决。
前置页：:doc:`installation`。

OpenQASM 往返
-------------

下面的示例把 OpenQASM 3 文本解析为电路，再把电路序列化为规范文本。
重新解析规范文本，得到与原电路相等的电路。

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

支持边界
--------

编解码器只接受已登记的 OpenQASM 构件。输入含循环、脉冲语句或未登记的门时，
编解码器抛出 :class:`qaiji.QaijiIRError` 的具体子类，不静默丢弃信息。
序列化输出总是 OpenQASM 3.0；OpenQASM 2.0 输入只作为兼容入口读取。
完整的支持边界见 :doc:`/api/codec`。

保持性判决最小示例
------------------

``qaiji.core.semantics`` 对受支持的逐位置变换给出保持性判决。规则不能确立关系时，
判决为 ``unsupported``。下面的示例对整圈 ``RZ`` 旋转调用
:meth:`~qaiji.Circuit.canonicalize`。规范化把该门折叠为恒等门；判决结果是只保持到
全局相位（``UP_TO_PHASE``），不是算符严格相等（``EXACT``）。

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

相关页面：各层的角色与实现状态见 :doc:`/core-concepts/architecture`；
跨层共享的基矢与相位约定见 :doc:`/core-concepts/conventions`。

下一步：:doc:`native-schedule` 从最接近设备的已实现层 L2 开始，按层自底向上说明各层的接口。
