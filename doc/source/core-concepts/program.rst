L5 程序
=======

L5 ProgramIR 描述一次实验的程序结构：有序的量子调用、实验元数据和结果输出。
程序不嵌入电路，只通过 ``kernel_ref`` 引用电路。本包不执行程序，也不采样。
接口用法见 :doc:`/getting-started/program`，完整接口见 :doc:`/api/program`。

程序记录
--------

.. list-table:: L5 记录
   :header-rows: 1
   :widths: 25 75

   * - 记录
     - 字段与约束
   * - ``ProgramIR``
     - ``schema_version`` 固定为 ``qaiji.program.v0``；``quantum_invocations`` 至少一项；
       ``experiment_metadata``；``result_outputs`` 至少一项，且不得重复。
   * - ``QuantumInvocation``
     - ``kernel_ref``：以 ``sha256:`` 为前缀，后接 64 个小写十六进制字符。
   * - ``ExperimentMetadata``
     - ``shot_count`` 为正整数；``calibration_set_ref`` 与 ``device_profile_ref``
       为非空字符串或 ``None``。
   * - ``ResultOutput``
     - ``invocation_index`` 为非负整数，且不得超出调用列表；``register_name`` 为标识符。

记录在构造时检查上述约束，违反时抛出 ``ValueError``。
``to_json`` 与 ``from_json`` 在程序记录与 JSON 之间往返转换；JSON 中没有电路，读回后仍须提供解析表。

内核引用
--------

``compute_kernel_ref`` 对电路的 L4 规范摘要计算内容哈希，计算前不规范化电路。
因此引用标识电路的结构，不标识等价类：两个判为 ``EXACT`` 的电路可能有不同的引用。
摘要与哈希的定义见 :doc:`semantics`。

.. testcode:: concept-kernel-ref

   from qaiji import Circuit
   from qaiji.core.program import compute_kernel_ref
   from qaiji.core.semantics import (
       annotate_circuit, build_semantic_summary, canonical_summary_hash,
   )

   with_cnot = Circuit(2)
   with_cnot.cnot(0, 1)
   summary = build_semantic_summary(
       circuit=with_cnot, annotations=annotate_circuit(with_cnot),
   )
   assert compute_kernel_ref(with_cnot) == canonical_summary_hash(summary)

   with_cx = Circuit(2)
   with_cx.cx(0, 1)
   assert compute_kernel_ref(with_cnot) != compute_kernel_ref(with_cx)

程序校验
--------

``validate_program(program, kernels)`` 先按调用顺序，再按输出声明顺序收集问题，
并在有问题时抛出 ``ProgramValidationError``，问题列表在该异常的 ``problems`` 属性中。
它检查下列各项：

1. 每个 ``kernel_ref`` 都在解析表中，且按对应电路重新计算得到的引用与它相同。
2. 每个输出寄存器在被引用的电路中恰好声明一次。
3. 输出寄存器的每一位都曾由测量写入。

校验的范围有下列限制：

- 校验的是解析表的内容，不是调用方持有的其他对象；解析表中未被引用的项不检查。
- 由测量写入但未声明为输出的寄存器是合法的。
- 判决是调用时刻的快照。之后修改电路，须重新校验。
- ``shot_count`` 只描述请求；``calibration_set_ref`` 与 ``device_profile_ref`` 只透传，
  本包不验证其内容或存在性。

相关层：L4（:doc:`semantics`）、L2（:doc:`native-schedule`）。层间连接见 :doc:`layer-relations`。
