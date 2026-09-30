核心类型
========

``qaiji.core`` 定义电路级中间表示的量子与经典值对象。节点保持输入顺序；
``Gate`` 与经典节点不可变，``Circuit`` 则负责验证寄存器声明、量子比特范围和操作追加顺序。

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
