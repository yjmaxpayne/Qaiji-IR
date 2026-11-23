电路模型接口
============

七个核心类型与九个循环类型从包根 ``qaiji`` 或 ``qaiji.core`` 导入；四个门集合常量
（``SINGLE_QUBIT_GATES`` 等）只从 ``qaiji.core`` 导出。``MAX_LOOP_ITERATIONS`` 从
``qaiji.core.loop`` 导入。

``qaiji.core`` 定义电路级 IR 的量子与经典值对象。它是 L5、L4、L2 共用的前端对象模型；
L3 的条件节点 ``Conditional`` 也在本页。节点保持输入顺序；``Gate`` 与经典节点不可变，
``Circuit`` 负责验证寄存器声明、量子比特范围和操作的追加顺序。

相关页面：前端在 IR 家族中的位置见 :doc:`/core-concepts/architecture`；
条件节点的语义见 :doc:`/core-concepts/hybrid-control`；示例见 :doc:`/getting-started/quickstart`。

门模型
------

.. autoclass:: qaiji.GateType
   :members:
   :undoc-members:

.. autoclass:: qaiji.Gate
   :members:

.. autodata:: qaiji.core.circuit.SINGLE_QUBIT_GATES
   :no-value:

.. autodata:: qaiji.core.circuit.TWO_QUBIT_GATES
   :no-value:

.. autodata:: qaiji.core.circuit.PARAM_REQUIREMENTS
   :no-value:

.. autodata:: qaiji.core.circuit.CANONICAL_ALIASES
   :no-value:

电路容器
--------

.. autoclass:: qaiji.Circuit
   :members:

经典节点
--------

.. autoclass:: qaiji.ClassicalRegister
   :members:

.. autoclass:: qaiji.ClassicalBit
   :members:

.. autoclass:: qaiji.Measure
   :members:

.. autoclass:: qaiji.Conditional
   :members:

有界循环
--------

``LoopedCircuit`` 是独立于 ``Circuit`` 的容器，保留有界循环的结构。循环体由模板节点组成，
模板中的比特与位索引可以是循环变量 ``LoopIndex``。``expand`` 按迭代顺序展开全部循环，
返回平坦电路和逐操作的来源。读取 ``gates`` 总是抛出 :class:`qaiji.LoopNotExpandedError`。
``to_json`` 与 ``from_json`` 读写规范 JSON，模式为 ``qaiji.looped_circuit/0.1``。
解析入口见 :doc:`codec`，region 标识见 :doc:`region`。

.. autoclass:: qaiji.LoopedCircuit
   :members:

.. autoclass:: qaiji.BoundedLoop
   :members:

.. autodata:: qaiji.core.loop.MAX_LOOP_ITERATIONS

.. autoclass:: qaiji.LoopIndex
   :members:

.. autoclass:: qaiji.GateTemplate
   :members:

.. autoclass:: qaiji.MeasureTemplate
   :members:

.. autoclass:: qaiji.ConditionalTemplate
   :members:

.. autoclass:: qaiji.SourceSpan
   :members:

.. autoclass:: qaiji.ExpandedCircuit
   :members:

.. autoclass:: qaiji.OperationProvenance
   :members:
