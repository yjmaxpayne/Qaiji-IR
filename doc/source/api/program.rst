L5 程序接口
===========

从 ``qaiji.core.program`` 显式导入；包根与 ``qaiji.core`` 不导出这些名称。

本模块描述有序的量子调用、实验元数据和结果输出。调用通过 ``kernel_ref`` 引用电路；
``kernel_ref`` 是电路 L4 规范摘要的哈希。校验时，调用方提供解析表；
校验逐个重新计算引用，并核对每个输出寄存器只声明一次、每一位都曾由测量写入。
判决针对调用时刻的解析表内容；电路之后改变时，需要重新校验。

``calibration_set_ref`` 与 ``device_profile_ref`` 是不透明引用，仅用于保存和透传；
本模块不读取它们指向的内容，不检查它们是否存在，它们也不改变校验判决。
本层不执行采样、调度或反馈。

相关页面：程序记录与校验规则见 :doc:`/core-concepts/program`；从 OpenQASM 电路到程序校验的
完整示例见 :doc:`/getting-started/program`；按调用关联原生调度测量事件的示例见
:doc:`/getting-started/native-schedule`。

JSON 契约
---------

``ProgramIR`` 采用冻结数据类，序列保存为元组；输出顺序与重复调用均保留。
写端使用固定格式字段、键排序、紧凑分隔符与 ASCII 转义；读端接受非规范空白
和键顺序，但拒绝未知或缺失字段、任意层重复键、类型错误的值与不合法构造值。
格式版本不匹配会抛出 ``ValueError``。Python 子类的额外字段不属于持久化身份。
JSON 往返只承载程序描述，L4 解析表由调用方另行提供。

模型与版本
----------

.. autodata:: qaiji.core.program.PROGRAM_SCHEMA_VERSION

.. autoclass:: qaiji.core.program.QuantumInvocation
   :members:

.. autoclass:: qaiji.core.program.ExperimentMetadata
   :members:

.. autoclass:: qaiji.core.program.ResultOutput
   :members:

.. autoclass:: qaiji.core.program.ProgramIR
   :members:

引用与校验
----------

问题按调用顺序、再按输出声明顺序汇总；未通过引用认证的调用不再检查输出。
未被引用的表项不参与校验，由测量写入但未声明为结果输出的寄存器合法。
寄存器按名字解析；损坏电路触发的 L4 ``TypeError`` 原样传播。

.. autofunction:: qaiji.core.program.compute_kernel_ref

.. autofunction:: qaiji.core.program.validate_program

专属异常
--------

该异常定义在程序子包，继承 :class:`qaiji.QaijiIRError`，从
``qaiji.core.program`` 导入；包根、``qaiji.core`` 与 ``qaiji.exceptions``
不导出它。``problems`` 为按报告顺序排列的不可修改字符串元组。

.. autoclass:: qaiji.core.program.ProgramValidationError
   :show-inheritance:
   :members:
