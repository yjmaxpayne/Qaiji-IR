L4 操作语义接口
===============

从 ``qaiji.core.semantics`` 显式导入；包根与 ``qaiji.core`` 不导出这些名称。

本层为电路操作分类，生成规范摘要与内容哈希，并给出保持性判决。分类与判决是两个
独立的问题：例如，``RZ(2*pi)`` 分类为 ``IDENTITY``\ ，判决为 ``UP_TO_PHASE``\ 。
本层不导入 ``qaiji.codec``、OpenQASM 解析依赖或 ``numpy``，由测试检查这一点。
L4 的保持性判决不认证 L2 的展开、资源或时序；这些由 :doc:`native` 的独立认证处理。

相关页面：分类与判决的定义见 :doc:`/core-concepts/semantics`；分类、摘要与哈希的
可运行示例见 :doc:`/getting-started/semantics`。

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
这些边不证明因果顺序。读前写入与结果就绪时间由 L2 调度认证。

.. autoclass:: qaiji.core.semantics.MeasurementHandle
   :members:

.. autoclass:: qaiji.core.semantics.ClassicalEdge
   :members:

.. autofunction:: qaiji.core.semantics.build_dataflow_summary

规范摘要与内容哈希
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
