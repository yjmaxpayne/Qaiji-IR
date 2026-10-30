L4 操作语义：摘要与保持性判决
==============================

本页演示 L4 的两类接口：为电路生成标注、数据流摘要与内容哈希；对变换给出保持性判决。
这两类接口回答不同的问题。例如，按测量统计分类，``RZ(2*pi)`` 是恒等，
但它的算符比 ``I`` 多一个全局负号。两类问题的定义见 :doc:`/core-concepts/semantics`。
前置页：:doc:`quickstart`。

分类、数据流与内容哈希
----------------------

``annotate_circuit`` 为每个节点和条件体内的每个门生成一条标注，标注记录位置与分类。
``build_semantic_summary`` 输出只含 JSON 值的摘要，内容包括操作结构、测量句柄和
分类计数。相同的输入得到相同的哈希。

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

``SemanticIRHandle`` 会深度冻结摘要。句柄的默认状态是 ``PLANNED``，所以示例显式设置
``AVAILABLE``。内容哈希只标识摘要的内容；它不表示调度已通过认证，也不表示物理结果
已验证。

``build_dataflow_summary`` 按寄存器名把条件连接到测量，不检查门的顺序。
条件位于匹配的测量之前时，也会产生一条边。条件是否读取了已写入的结果、
是否晚于结果就绪时刻，由 L2 原生调度检查，见 :doc:`/core-concepts/native-schedule`。

保持性判决的范围
----------------

``check_preservation`` 逐位置比较变换前后的两个电路。规则 R1–R4 覆盖结构相等、
CNOT 与 CX 别名、同位置的整圈旋转等情形。可判定的级别只有 ``EXACT`` 与
``UP_TO_PHASE``。规则不能确立关系时，判决为 ``unsupported``；不要把 ``unsupported``
当作通过。把一个门展开为多个门、一般的重新排序，都不在逐位置判决的范围内。
判决的步骤与完整规则见 :doc:`/core-concepts/semantics`。

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

这个判决只比较 L4 层的两个电路。它不代替 L2 对展开规则、算符矩阵、资源和时序的认证。

相关页面：完整接口与错误类型见 :doc:`/api/semantics`。

下一步：:doc:`program` 用内核引用把电路接入 L5 程序。
