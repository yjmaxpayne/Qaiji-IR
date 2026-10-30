电路模型接口
============

七个核心类型从包根 ``qaiji`` 或 ``qaiji.core`` 导入；四个门集合常量
（``SINGLE_QUBIT_GATES`` 等）只从 ``qaiji.core`` 导出。

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
