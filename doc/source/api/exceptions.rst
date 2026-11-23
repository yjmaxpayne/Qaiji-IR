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
- :class:`~qaiji.core.pulse.PulseContractError`，见 :doc:`pulse`。
- :class:`~qaiji.core.waveform.WaveformContractError`，见 :doc:`waveform`。
- :class:`~qaiji.core.native.NativeInputError`，见 :doc:`native`。它同时继承 ``ValueError``，
  所以 ``except QaijiIRError`` 与 ``except ValueError`` 都捕获它。

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

两个循环异常从包根 ``qaiji`` 导入。在未展开的 :class:`qaiji.LoopedCircuit` 上读取平坦
操作序列时抛出 ``LoopNotExpandedError``。读取 ``gates``、调用 ``check_invariants``，以及不带
``region`` 调用 ``check_preservation`` 都属于这种情况。循环容器、循环 JSON 或循环电路的写出
不合法时抛出 ``LoopedCircuitError``，它同时继承 ``ValueError``。

.. autoclass:: qaiji.LoopNotExpandedError
   :show-inheritance:

.. autoclass:: qaiji.LoopedCircuitError
   :show-inheritance:
