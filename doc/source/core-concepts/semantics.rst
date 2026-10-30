L4 操作语义
===========

L4 SemanticIR 记录操作结构，并对一组有限的等价规则给出判决。
它回答两个不同的问题：一个操作属于哪类变换；一次变换是否保持算符关系。
L3 的条件依赖也记录在 L4 摘要中，条件本身的语义见 :doc:`hybrid-control`。
接口用法见 :doc:`/getting-started/semantics`，完整接口见 :doc:`/api/semantics`。

L4 记录
-------

.. list-table:: L4 核心记录
   :header-rows: 1
   :widths: 22 78

   * - 记录
     - 字段与含义
   * - 标注
     - ``gate_index``、``body_offset``、``morphism``、``equiv_level``、``cartan``、
       ``notes``。``gate_index`` 指向顶层节点；``body_offset`` 指向条件体内的门。
       条件节点和它体内的门各有一条标注。
   * - 测量句柄
     - ``measurement_id``、``qubit_index``、``creg_name``、``creg_index``、``source``。
       句柄保留寄存器名和位索引。
   * - 经典边
     - ``source_handle``、``target``、``edge_kind``。声明一条从测量到条件的依赖。
   * - 保持性判决
     - ``stage``、``status``、``diagnostic_count``、``failed_gate_indices``、
       ``equiv_level``、``original_morphism``、``lowered_morphism``、``pass_trace_ref``。
   * - L4 摘要
     - 模式版本 ``qaiji.semantic_summary.v0``；含 ``num_qubits``、``cregs``、有序的
       ``operations``、各类计数、测量句柄、经典边和 ``condition_model``。

操作分类
--------

每个操作得到一个 ``MorphismType`` 标签。标签只有一个，但对应的数学类别可以重叠：
置换门和相位门同时也是酉操作。

.. list-table:: 分类注册表
   :header-rows: 1
   :widths: 25 75

   * - 标签
     - 操作
   * - ``IDENTITY``
     - I；角度在数值上为 :math:`2\pi k` 的 RZ（含 :math:`k=0`）。
   * - ``PERMUTATION``
     - X、CNOT、CX、SWAP。
   * - ``PHASE``
     - Z、S、T、CZ；角度不是整圈的 RZ。
   * - ``UNITARY``
     - H、Y、RX、RY、RX90、RX180、U3、ISWAP、SQISWAP。
   * - ``MEASUREMENT``
     - 测量节点（:class:`qaiji.Measure`）。
   * - ``CLASSICAL_CTRL``
     - 条件节点（:class:`qaiji.Conditional`）；体内的门按各自类别另行标注。

整圈判定使用绝对容差 :data:`qaiji.constants.DEFAULT_TOLERANCE`，即 ``1e-10``。
Cartan 角色（``K``、``A``、``MIXED``、``NONE``）只是优化提示，不作为等价判决的输入。

分类与判决是两条独立的轴。分类描述操作对测量统计的作用；判决描述算符是否相等。
例如 :math:`R_Z(2\pi)=-I`：它的分类是 ``IDENTITY``，但它与 I 只在相差全局相位的
意义下相等。

等价级别
--------

.. list-table:: 等价级别
   :header-rows: 1
   :widths: 22 78

   * - 级别
     - 含义
   * - ``EXACT``
     - 酉操作严格相等，即 :math:`U=V`。
   * - ``UP_TO_PHASE``
     - 酉操作相差一个全局相位，即 :math:`U=e^{i\phi}V`。
   * - ``UP_TO_LOCAL``、``ENTANGLEMENT``
     - 为后续层预留的词汇。判决入口拒绝这两个级别，
       并抛出 :class:`qaiji.UnsupportedEquivLevelError`。

对于测量，相等是指：对每个经典结果标签，对应的量子操作相等。

保持性判决
----------

``check_preservation`` 按下面的顺序判决，先命中的步骤决定结果：

1. 两个电路的顶层测量数量不同时，返回 ``failed``。
   ``failed_gate_indices`` 列出从第一个不匹配处开始的原电路测量位置。
2. 量子比特数、经典寄存器、节点数量或逐位置的节点种类不同时，返回 ``unsupported``。
3. 逐位置比对每一对节点：

   - 每一对门必须作用于相同的量子比特，并命中下表中的一条规则。
   - 每一对测量节点的量子比特和目标位必须相同。
   - 每一对条件节点的寄存器、比较值和体长度必须相同；体内的门按下表逐个比对，
     并计入相位。

   任何一对不满足上述条件时，返回 ``unsupported``，并列出所有不满足的位置。
4. 汇总各对门的全局相位。相位为 1 时级别为 ``EXACT``，为 :math:`-1` 时为
   ``UP_TO_PHASE``。级别为 ``UP_TO_PHASE`` 而调用方要求 ``EXACT`` 时，返回
   ``unsupported``；其他情况返回 ``passed``。

.. list-table:: 逐位置规则
   :header-rows: 1
   :widths: 10 50 40

   * - 规则
     - 条件
     - 相位贡献
   * - R1
     - 两个门结构相等。
     - 无。
   * - R2
     - CNOT 与 CX 互为别名，且作用比特相同。
     - 无。
   * - R3
     - 同一种旋转门（RX、RY 或 RZ）、同一比特，角度差为 :math:`2\pi k`。
     - :math:`k` 为奇数时贡献 :math:`-1`。
   * - R4
     - 一侧是角度为 :math:`2\pi k` 的 RX、RY 或 RZ，另一侧是同一比特上的 I。
     - :math:`k` 为奇数时贡献 :math:`-1`。

三个判决状态的含义不同：

- ``passed``：规则确立了返回的等价级别。
- ``failed``：测量数量不同，可以确定变换改变了测量记录。
- ``unsupported``：规则无法确立两者的关系。它既不证明等价，也不证明不等价，
  不得当作通过处理。

``PreservationSummary`` 的状态词表还包含 ``warning`` 与 ``planned``，
但 ``check_preservation`` 不返回这两个值。

一般的门融合和重排序不在规则域内。下面的示例中，合法的旋转融合返回 ``unsupported``；
丢失测量返回 ``failed``；对 :math:`R_Z(2\pi)\to I` 要求 ``EXACT`` 也返回 ``unsupported``。

.. testcode:: concept-verdicts

   import math
   from qaiji import Circuit, UnsupportedEquivLevelError, from_qasm3
   from qaiji.core.semantics import EquivLevel, check_preservation

   fused_from = Circuit(1)
   fused_from.rx(0, 0.2)
   fused_from.rx(0, 0.3)
   fused_to = Circuit(1)
   fused_to.rx(0, 0.5)
   assert check_preservation(fused_from, fused_to).status == "unsupported"

   header = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[1] q;\nbit[1] c;\nh q[0];\n'
   measured = from_qasm3(header + "c[0] = measure q[0];\n")
   verdict = check_preservation(measured, from_qasm3(header))
   assert verdict.status == "failed"
   assert verdict.failed_gate_indices == (1,)

   full_turn = Circuit(1)
   full_turn.rz(0, math.tau)
   identity = full_turn.canonicalize()
   assert check_preservation(full_turn, identity).equiv_level is EquivLevel.UP_TO_PHASE
   strict = check_preservation(full_turn, identity, requested_level=EquivLevel.EXACT)
   assert strict.status == "unsupported"

   try:
       check_preservation(full_turn, identity, requested_level=EquivLevel.UP_TO_LOCAL)
   except UnsupportedEquivLevelError:
       pass
   else:
       raise AssertionError("UP_TO_LOCAL 必须被拒绝")

摘要与内容哈希
--------------

``build_semantic_summary`` 输出 JSON 安全的摘要，``canonical_summary_hash`` 对其规范
JSON 计算 SHA-256。哈希标识记录的结构，不标识等价类：两个被判为 ``EXACT`` 的电路
仍可能有不同的哈希。

.. testcode:: concept-hash

   from qaiji import Circuit
   from qaiji.core.semantics import (
       EquivLevel, annotate_circuit, build_semantic_summary,
       canonical_summary_hash, check_preservation,
   )

   def summary_hash(circuit):
       summary = build_semantic_summary(
           circuit=circuit, annotations=annotate_circuit(circuit),
       )
       return canonical_summary_hash(summary)

   with_cnot = Circuit(2)
   with_cnot.cnot(0, 1)
   with_cx = Circuit(2)
   with_cx.cx(0, 1)
   assert check_preservation(with_cnot, with_cx).equiv_level is EquivLevel.EXACT
   assert summary_hash(with_cnot) != summary_hash(with_cx)


相关层：L3（:doc:`hybrid-control`）、L5（:doc:`program`）。层间连接见 :doc:`layer-relations`。
