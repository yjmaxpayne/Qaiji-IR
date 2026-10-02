L4 语义摘要与保持性
===================

L4 给电路操作分类，生成可重复计算的内容引用，并对受支持的逐位置变换给出
保持性判决。这些是不同的问题：``RZ(2*pi)`` 在测量统计分类中是恒等，
算符却比 ``I`` 多一个全局负号。下面的示例均在文档测试中执行。

分类、数据流与内容引用
----------------------

``annotate_circuit`` 为节点分配位置；``build_semantic_summary`` 输出包含
操作结构、测量句柄和分类计数的 JSON 安全摘要。相同输入可得到相同哈希。

.. testcode:: semantics

   from qaiji import from_qasm3
   from qaiji.core.semantics import (
       HandleStatus, SemanticIRHandle, annotate_circuit,
       build_dataflow_summary, build_semantic_summary, canonical_summary_hash,
   )

   circuit = from_qasm3("""OPENQASM 3.0;
   include "stdgates.inc";
   qubit[1] q;
   bit[1] c;
   h q[0];
   c[0] = measure q[0];
   """)
   annotations = annotate_circuit(circuit)
   dataflow = build_dataflow_summary(circuit)
   assert len(annotations) == 2
   assert dataflow["measurement_handles"][0].measurement_id == "m0"
   assert dataflow["unitary_segment_count"] == 2

   summary = build_semantic_summary(circuit=circuit, annotations=annotations)
   digest = canonical_summary_hash(summary)
   assert digest.startswith("sha256:")
   assert digest == canonical_summary_hash(summary)
   handle = SemanticIRHandle(
       summary=summary, content_hash=digest, status=HandleStatus.AVAILABLE,
   )
   assert canonical_summary_hash(handle.summary) == handle.content_hash

``SemanticIRHandle`` 会深度冻结摘要；默认状态是 ``PLANNED``，因此示例显式设置
``AVAILABLE``。内容哈希只标识摘要内容，不代表调度已获认证或物理结果已验证。
``build_dataflow_summary`` 的条件边按寄存器名连接测量与条件，不检查门序；
条件可以先于匹配的测量而仍产生一条边。读前写入与结果就绪由 L2 原生调度
检查，见 :doc:`/native-schedule`。

保持性判决的范围
----------------

``check_preservation`` 支持结构相等、CNOT/CX 别名和同位置整圈旋转等 R1–R4
情形。``EXACT`` 与 ``UP_TO_PHASE`` 是可判定级别；无法证明的变换会返回
``unsupported``，不能将其当成通过。一个门展开成多个门或一般重排序不属于
这个逐位置判决域。:doc:`/api/semantics` 给出完整接口与错误类型。

.. testcode:: preservation

   import math
   from qaiji import Circuit
   from qaiji.core.semantics import EquivLevel, MorphismType, check_preservation, classify_operation

   original = Circuit(1)
   original.rz(0, math.tau)
   canonical = original.canonicalize()
   assert classify_operation(original.gates[0])[0].morphism is MorphismType.IDENTITY
   verdict = check_preservation(original, canonical, stage="canonicalize")
   assert verdict.status == "passed"
   assert verdict.equiv_level is EquivLevel.UP_TO_PHASE

此判决比较的是 L4 输入与变换后电路，不代替 L2 的规则、算符矩阵、资源和时序认证。
