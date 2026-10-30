异常层级
========

所有编解码与约定错误都继承自 :class:`qaiji.QaijiIRError`。调用方可以捕获具体异常以
区分语法错误、范围外构件和门映射缺失，也可以捕获基类统一处理 Qaiji-IR 错误。
按现象排查常见错误的方法见 :doc:`/getting-started/troubleshooting`。

下列子包异常也继承该基类，但只从各自的子包导出：

- :class:`~qaiji.core.program.ProgramValidationError`，见 :doc:`program`。
- :class:`~qaiji.core.native.NativeValidationError`，见 :doc:`native`。
- :class:`~qaiji.core.program_native.ProgramNativeValidationError`，见 :doc:`program_native`。
- :class:`~qaiji.core.physical.PContractError`，见 :doc:`physical`。

:class:`~qaiji.core.native.NativeInputError` 继承 ``ValueError``，不继承
:class:`qaiji.QaijiIRError`。``except QaijiIRError`` 不会捕获它。

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
