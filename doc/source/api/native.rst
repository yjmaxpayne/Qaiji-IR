L2 原生调度接口
===============

从 ``qaiji.core.native`` 显式导入。数值范围与不支持域见 :doc:`/native-schedule`，
完整往返示例见 :doc:`/getting-started/native-schedule`。

入口与异常
----------

``lower_to_native(circuit, config)`` 返回已独立认证的 ``NativeScheduleIR``。
``validate_native_schedule(circuit, schedule, config)`` 返回 ``NativeValidationReport``；
语义失败由报告表达，结构或输入类型错误仍可能抛异常。
``qubic_mapping(circuit, schedule, config)`` 重新认证后返回 ``NativeProjection``。
配置始终由调用者提供，没有设备默认值。

``NativeInputError`` 继承 ``ValueError``，含 ``code``、``path``；构造、JSON、
来源或配置的结构错误使用此异常。``NativeValidationError`` 继承
``QaijiIRError``，含 ``report`` 与展平的 ``issues``；生成调度或投影
遇到认证失败时抛出。按输入错误与认证失败分别捕获，也不要将 JSON 解码成功当作认证成功。

报告按 ``source``、``rules``、``hp``、``schedule`` 分层，组证据另见 ``groups``。
``CheckResult.status`` 的取值为 ``pass``、``fail``、``not_run``、
``not_applicable``；仅 ``fail`` 状态包含 ``issues``。
``valid`` 要求来源和时序通过、规则和矩阵层通过或不适用；未运行不算通过。
失败报告的 ``all_results_ready_ns`` 为 ``None``。

记录字段
--------

下列记录均不可修改、采用 ``slots``、仅接受关键字参数，且不可哈希；
列表或元组输入会复制为元组。
``NativeScheduleIR`` 的两个版本字段有默认值，其余字段均显式提供。
``source_kernel_ref`` 使用现有 L5 固定配方的 ``sha256:`` 引用。
``SourceLocation.gate_index`` 为顶层索引，顶层 ``body_offset=None``，条件体为体内索引。
``SourceGroup`` 的 ``[op_start, op_stop)`` 连续覆盖操作，每组的 ``ordinal`` 从零开始。
测量 ``event_id`` 按事件列表顺序为 ``m0``、``m1``……；条件标识为 ``c`` 加顶层索引。
``ConditionRead`` 按寄存器位序关联最新事件。

.. list-table:: 公开记录字段（构造时均仅接受关键字参数）
   :header-rows: 1
   :widths: 25 75

   * - 类型
     - 字段
   * - ``CheckResult``
     - ``status``, ``issues``
   * - ``ConditionRead``
     - ``bit_index``, ``event_id``
   * - ``ConditionRegion``
     - ``condition_id``, ``gate_index``, ``register_name``, ``width``, ``value``, ``reads``, ``op_start``, ``op_stop``, ``start_ns``, ``end_ns``
   * - ``GroupEvidence``
     - ``source``, ``rule_id``, ``rule``, ``hp``, ``expected_phase_rad``, ``max_abs_residual``
   * - ``MeasurementEvent``
     - ``event_id``, ``source``, ``operation_index``, ``qubit``, ``register_name``, ``bit_index``, ``end_ns``, ``ready_ns``
   * - ``NativeIssue``
     - ``code``, ``path``, ``source``, ``operation_index``, ``message``
   * - ``NativeOperation``
     - ``kind``, ``qubits``, ``params``, ``source``, ``ordinal``, ``start_ns``, ``duration_ns``, ``resources``, ``condition_id``
   * - ``NativeProjection``
     - ``source_kernel_ref``, ``operations``, ``conditions``, ``events``, ``end_ns``, ``all_results_ready_ns``
   * - ``NativeScheduleIR``
     - ``source_kernel_ref``, ``num_qubits``, ``registers``, ``operations``, ``groups``, ``events``, ``conditions``, ``end_ns``, ``schema_version``, ``ruleset_version``
   * - ``NativeValidationReport``
     - ``source``, ``rules``, ``hp``, ``schedule``, ``groups``, ``all_results_ready_ns``
   * - ``OperationSpec``
     - ``kind``, ``qubits``, ``duration_ns``, ``resources``, ``result_latency_ns``
   * - ``ProjectedOperation``
     - ``operation_index``, ``operation``, ``labels``, ``event_id``, ``result_ready_ns``
   * - ``QubitResource``
     - ``qubit``, ``resource``
   * - ``RegisterDecl``
     - ``name``, ``size``
   * - ``ScheduleConfig``
     - ``qubit_resources``, ``operation_specs``, ``cz_couplings``
   * - ``SourceGroup``
     - ``source``, ``rule_id``, ``op_start``, ``op_stop``, ``phase_rad``
   * - ``SourceLocation``
     - ``gate_index``, ``body_offset``

``ProjectedOperation.labels`` 为中性消费标签，测量项同时带 ``event_id`` 与
``result_ready_ns``。``NativeProjection.events`` 和 ``conditions`` 保留完整关联。
``NativeScheduleIR.to_json()`` 序列化重新检查的声明字段；
``NativeScheduleIR.from_json(text)`` 恢复完整调度记录，不保存配置、报告或授权令牌。

自动生成的接口说明
------------------

.. automodule:: qaiji.core.native
   :members:
   :undoc-members:
   :show-inheritance:
