L3 混合控制
===========

L3 HybridControlIR 描述量子操作与经典控制之间的依赖：分支、循环、条件与反馈边。
当前包只实现其中最小的一部分：条件节点及其测量依赖。
每个条件节点只比较一个经典寄存器与一个整数。

条件节点
--------

条件节点（:class:`qaiji.Conditional`）比较整个经典寄存器与一个整数，条件体只含门。
OpenQASM 3 编解码器按下面的方式处理条件：

- 解析接受整寄存器相等 ``c == 1``。
- 寄存器宽度为 1 时，解析也接受位索引形式 ``c[0] == 1``，比较值只能是 0 或 1。
  多位寄存器上的位条件被拒收。
- ``else`` 分支、非相等比较和非字面量比较值被拒收。
- 序列化总是输出整寄存器相等，所以 ``c[0] == 1`` 往返后变为 ``c == 1``。

每个顶层测量按出现顺序产生一个句柄（``m0``、``m1`` 等）。每个条件节点连接到写入
同一寄存器的全部测量句柄，边的目标写作 ``cond`` 加该条件的顶层位置，例如 ``cond2``。
经典边只是声明的依赖，不证明因果顺序：
``build_dataflow_summary`` 不检查门序，条件位于匹配测量之前时仍产生一条边。
条件是否读取了最近一次测量、是否晚于结果就绪时刻，由 L2 认证，见 :doc:`native-schedule`。

依赖记录（测量句柄与经典边）属于 L4 摘要，字段定义见 :doc:`semantics`。

示例
----

下面的单比特主动重置电路有四条标注：初始门、测量、条件节点、条件体内的门。

.. testcode:: concept-reset

   from qaiji import from_qasm3, to_qasm3
   from qaiji.core.semantics import (
       MorphismType, annotate_circuit, build_dataflow_summary,
   )

   reset = from_qasm3("""OPENQASM 3.0;
   include "stdgates.inc";
   qubit[1] q;
   bit[1] c;
   x q[0];
   c[0] = measure q[0];
   if (c[0] == 1) { x q[0]; }
   """)
   labels = [(a.gate_index, a.body_offset, a.morphism) for a in annotate_circuit(reset)]
   assert labels == [
       (0, None, MorphismType.PERMUTATION),
       (1, None, MorphismType.MEASUREMENT),
       (2, None, MorphismType.CLASSICAL_CTRL),
       (2, 0, MorphismType.PERMUTATION),
   ]
   edge = build_dataflow_summary(reset)["classical_edges"][0]
   assert (edge.source_handle, edge.target) == ("m0", "cond2")
   assert "if (c == 1)" in to_qasm3(reset)

条件模型 ``REGISTER_ALU`` 是当前唯一有生产路径的取值。``FPROC_PLACEHOLDER`` 只为
多条件前馈预留位置，不表示已经支持。一般谓词、嵌套条件、条件内测量、循环与
控制流图均不在当前范围内。

设计方向（尚未实现）
--------------------

分支、循环与一般谓词尚未实现。EmuPlat 中现有的反馈降级可以作为移植的起点；
下面的名称不是本包的契约，移植时可能改变。

- EmuPlat 把每条经典边降级为一对指令 ``ALU_FPROC_I`` 与 ``JUMP_FPROC_I``，
  这一降级只在条件模型为 ``REGISTER_ALU`` 时执行。比较运算固定为 ``EQ``，比较值固定为 1。
- 降级结果 ``LoweredFeedbackProgram`` 只支持一次测量和至多一个条件区域，
  并记录结果就绪延迟 ``tau_ns``。
- VPPU 指令集的 ALU 运算有 ``ID0``、``ADD``、``SUB``、``EQ``、``LE``、``GE``、``ID1``、``ZERO``，
  没有不等、小于或大于。扩展谓词时，须用这些运算组合，或扩展指令集。
- 在 EmuPlat 的编译器 IR 中没有找到循环或多位寄存器谓词。

相关层：L2（:doc:`native-schedule`）、L4（:doc:`semantics`）。层间连接见 :doc:`layer-relations`。
