异常层级
========

所有编解码与约定错误都继承自 :class:`qaiji.QaijiIRError`。调用方可以捕获具体异常以
区分语法错误、范围外构件和门映射缺失，也可以捕获基类统一处理 Qaiji-IR 错误。

程序校验错误 :class:`~qaiji.core.program.ProgramValidationError` 同样继承该基类，
但定义和导出限定在程序子包；其问题汇总契约见 :doc:`program`。

.. autoclass:: qaiji.QaijiIRError
   :show-inheritance:

.. autoclass:: qaiji.Qasm3ParseError
   :show-inheritance:

.. autoclass:: qaiji.Qasm3UnsupportedConstructError
   :show-inheritance:

.. autoclass:: qaiji.Qasm3UnsupportedGateError
   :show-inheritance:

.. autoclass:: qaiji.ConventionViolationError
   :show-inheritance:

.. autoclass:: qaiji.UnsupportedEquivLevelError
   :show-inheritance:
