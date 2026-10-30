L5 / L2 桥接接口
================

从 ``qaiji.core.program_native`` 显式导入；包根与 ``qaiji.core`` 不导出这些名称。

相关页面：语义边界见 :doc:`/core-concepts/native-schedule`；完整示例见
:doc:`/getting-started/native-schedule`。

``bridge_program_native(program, kernels, bindings)`` 返回 ``ProgramNativeMap``。
``kernels`` 按 ``kernel_ref``\ （内核引用）提供电路；``bindings`` 按从零开始的调用索引提供
``NativeBinding(schedule=..., config=...)``。即便多个调用使用同一电路，每次调用
也必须有绑定并独立认证；没有声明输出的调用也必须认证。

认证顺序与异常
--------------

首先调用原有的 ``validate_program``，其 ``ProgramValidationError`` 保持原样且优先。
随后检查映射与 Python 内置整数键，结构错误可抛 ``NativeInputError``。逐调用收集缺失绑定
或原生调度认证失败后，统一抛出 ``ProgramNativeValidationError``；不会返回部分成功输出。
该异常继承 ``QaijiIRError``，``issues`` 为按调用顺序排列的 ``ProgramNativeIssue`` 元组。

问题项的 ``code`` 为 ``binding_missing``、``native_input`` 或 ``native_invalid``。
``native_input`` 记录底层 ``input_code`` / ``input_path``；``native_invalid``
记录 ``native_report``；不适用的诊断字段为 ``None``。只有所有调用通过后才建立输出映射。
绑定键必须为 Python 内置整数（不接受布尔值）；额外的整数键不参与调用认证。

输出与字段
----------

输出顺序与 ``program.result_outputs`` 一致。``history`` 按对应调度记录的事件顺序
列出该调用中该寄存器的所有测量；``final_bits`` 按位索引升序选择每位最后一次
测量。不同调用中的同名事件（如 ``m0``）通过 ``invocation_index`` 区分。
这些输出都是引用，没有真实采样值；不按 ``shot_count`` 执行采样，也不解析校准/设备引用。

所有记录均不可修改、采用 ``slots``、仅接受关键字参数，且不可哈希；序列保存为元组。

.. list-table:: 公开记录字段（构造时均仅接受关键字参数）
   :header-rows: 1
   :widths: 25 75

   * - 类型
     - 字段
   * - ``FinalBitBinding``
     - ``bit_index``, ``event``
   * - ``InvocationEventRef``
     - ``invocation_index``, ``event_id``
   * - ``NativeBinding``
     - ``schedule``, ``config``
   * - ``OutputMeasurementBinding``
     - ``invocation_index``, ``register_name``, ``history``, ``final_bits``
   * - ``ProgramNativeIssue``
     - ``invocation_index``, ``code``, ``native_report``, ``input_code``, ``input_path``, ``message``
   * - ``ProgramNativeMap``
     - ``outputs``

自动生成的接口说明
------------------

.. automodule:: qaiji.core.program_native
   :members:
   :undoc-members:
   :show-inheritance:
