语义层（L4）
============

``qaiji.core.semantics`` 是 L4 语义授权层：它在同一个 :class:`~qaiji.Circuit` 之上
回答两个正交问题。分类（枚举、标注和注册表）回答"这个操作对测量统计
做了什么"；保持性判决回答"变换后的电路，算符是否仍然（至多
差一个全局相位）等于原来的电路"。两者可以给出不同答案而互不矛盾——例如
``RZ(2*pi)`` 在分类层归为 ``IDENTITY``（测量统计意义上的恒等），在判决层却判为
``UP_TO_PHASE``（算符差一个 ``-1`` 因子）；这是两个独立坐标轴，不是同一个问题
答错了。本层不导入 ``qaiji.codec``、OpenQASM 解析依赖或 ``numpy``，由双门控的
导入纯度测试守护。本仓已有 L2 原生调度，但尚不生成硬件 ISA；L4 的
保持性判决不认证 L2 展开、资源或时序，后者由 :doc:`/api/native` 的独立校验处理。
可运行的分类、摘要与哈希示例见 :doc:`/getting-started/semantics`。

分类枚举与语义标注
------------------

.. autoclass:: qaiji.core.semantics.MorphismType
   :members:
   :undoc-members:

.. autoclass:: qaiji.core.semantics.EquivLevel
   :members:
   :undoc-members:

.. autoclass:: qaiji.core.semantics.CartanRole
   :members:
   :undoc-members:

.. autoclass:: qaiji.core.semantics.ConditionModel
   :members:
   :undoc-members:

.. autoclass:: qaiji.core.semantics.SemanticAnnotation
   :members:

操作分类
--------

.. autofunction:: qaiji.core.semantics.classify_operation

.. autofunction:: qaiji.core.semantics.annotate_circuit

数据流：测量与条件读取
----------------------

这里的边只按寄存器名连接测量与条件，即使条件出现在测量之前也会形成边；
它不证明因果顺序。读前写入与结果就绪时间由 L2 调度校验。

.. autoclass:: qaiji.core.semantics.MeasurementHandle
   :members:

.. autoclass:: qaiji.core.semantics.ClassicalEdge
   :members:

.. autofunction:: qaiji.core.semantics.build_dataflow_summary

摘要与规范身份哈希
------------------

.. autodata:: qaiji.core.semantics.SUMMARY_SCHEMA_VERSION

.. autodata:: qaiji.core.semantics.GATE_COVERAGE_TOTAL

.. autofunction:: qaiji.core.semantics.build_semantic_summary

.. autofunction:: qaiji.core.semantics.canonical_summary_hash

保持性判决与语义句柄
--------------------

.. autoclass:: qaiji.core.semantics.PreservationSummary
   :members:

.. autofunction:: qaiji.core.semantics.check_preservation

.. autoclass:: qaiji.core.semantics.SemanticIRHandle
   :members:

.. autoclass:: qaiji.core.semantics.HandleStatus
   :members:
   :undoc-members:

.. autofunction:: qaiji.core.semantics.freeze_summary

.. autodata:: qaiji.core.semantics.JSONValue
   :no-value:
