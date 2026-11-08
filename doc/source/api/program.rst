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

权威控制树
----------

``ProgramIR`` 保持 ``qaiji.program.v0`` 的构造与字节契约。
``ProgramIRV1`` 使用独立的 ``qaiji.program.v1``。
v1 保存 ``control_flow``，节点为 ``ProgramCall`` 或 ``ProgramIf``。
调用节点引用 ``quantum_invocations`` 的下标。
条件节点读取先前调用的测量寄存器。
条件值使用低位在前的整数约定。
每个调用须在树中出现一次。深度优先顺序须与调用表一致。
条件读取的结果须在所有到达路径上可用。
最终输出也须在全部路径上可用。
分支内部的结果可以供该分支读取。

``validate_program`` 检查两种程序版本。
它报告控制结构问题，诊断码为 ``CONTROL_FLOW``。
不变量检查器单独检查 v1 的条件深度。
根深度为 0。每层 ``ProgramIf`` 增加 1。
深度 4 通过。深度 5 报 ``DEPTH``。
v0 缺少权威控制树，不能认证该深度不变量。
原生桥接接受 v1 的无条件调用序列。
原生桥接以 ``CONTROL_FLOW_UNSUPPORTED`` 拒绝条件 v1。

.. autoclass:: qaiji.core.program.ProgramCall
   :members:

.. autoclass:: qaiji.core.program.ProgramIf
   :members:

.. autoclass:: qaiji.core.program.ProgramIRV1
   :members:

.. autofunction:: qaiji.core.program.dump_program

.. autofunction:: qaiji.core.program.load_program

不变量输入绑定
--------------

``qaiji.core.invariants`` 提供稳定 ID、诊断绑定与 JSON Pointer。
当前检查入口支持 L5、L4、L2、L1 与 L0。
层对象缺少上下文时，检查器返回失败报告。
对象类型与层不符时，检查器抛出 ``TypeError``。
未登记的诊断产生 ``UNREGISTERED`` 失败。
现有检查器在首错后停止时，后续项不得报告通过。

L5 使用 ``ProgramInvariantInput(program, kernels)``。
L4 使用 ``L4InvariantInput(circuit, recorded_summary_hash)``。
L4 摘要须来自冻结输入或先前记录。
L4 检查不得从当前电路生成比较右值。
L2 使用 ``L2InvariantInput(circuit, schedule, config)``。
L1 使用 ``L1InvariantInput(pulse, schedule)``。
L0 接受 ``WaveformIR`` 或 waveform JSON 字节。
``check_waveform_events`` 逐叶比较 L0 与 L1 的事件顺序。

上述载体只接受关键字参数。
载体不改变既有 L1 字节或内容身份。
载体不从外部文件或注册表解析缺失输入。

.. autofunction:: qaiji.core.invariants.invariant_registry

.. autofunction:: qaiji.core.invariants.check_invariants

.. autofunction:: qaiji.core.invariants.check_waveform_events
