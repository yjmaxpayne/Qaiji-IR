L1 脉冲接口
===========

从 ``qaiji.core.pulse`` 显式导入。包根与 ``qaiji.core`` 不导出这些名称。
本包只依赖标准库、``qaiji.exceptions``、``qaiji.core._codec`` 与 L2 原生调度层 ``qaiji.core.native``。

相关页面：层的角色、规则与边界见 :doc:`/core-concepts/pulse`。L2 输入见 :doc:`native`。
L0 采样见 :doc:`waveform`。

入口与异常
----------

``PulseProgramIR`` 的构造入口检查全部 L1 不变量，不合法的记录无法构造。
``check_pulse_program(program, schedule)`` 检查 L1 程序与生成它的 L2 调度一致：
引用、时间、来源、目标帧、覆盖与测量。检查项的完整列表见自动生成的接口说明。

``dump_pulse_program(program)`` 返回规范字节。``load_pulse_program(data)`` 严格解码字节，
再经构造入口检查全部不变量。``pulse_program_id(program)`` 返回内容身份
``sha256(schema + b"\0" + 规范字节)``。``native_schedule_ref(schedule)`` 返回 L2 调度的引用
``sha256(schema_version + b"\0" + to_json() 字节)``，用于填写 ``source_schedule_ref``。
两者都返回带 ``sha256:`` 前缀的小写十六进制摘要。

``frame_phase(program, play)`` 返回 ``play`` 的帧相位：帧初相、同一帧上
``at_ns <= play.start_ns`` 的全部 ``ShiftPhase`` 增量与 ``play.phase_rad`` 之和，单位 rad，不取模。
``carrier_phase(program, play, t_ns)`` 返回绝对时刻 ``t_ns`` 的载波相位
``2π·f·t·1e-9 + 帧相位``。``phases_equal(a, b)`` 按 2π 取模比较两个相位，
容差为 ``PHASE_ATOL``\ （1e-10）。

``PulseContractError`` 继承 ``QaijiIRError``，携带不可变的 ``PulseDiagnostic`` 序列。
每条诊断含 ``category``、``code``、``path`` 与 ``message``。``category`` 为
``INVALID_PROGRAM``\ （记录违反 L1 规则）、``SCHEDULE_MISMATCH``\ （程序与 L2 调度不一致）
或 ``resources``\ （独立端口资源映射不一致）。
文本字段须为非空字符串，且只含 Unicode 标量值。孤立代理项的诊断码为 ``UNICODE``。

记录字段
--------

下列记录均不可修改、采用 ``slots``、仅接受关键字参数，且不可哈希。
时间为整数 ns，频率为整数 Hz，相位为 rad，幅度为无量纲值，范围 [-1, 1]。
``PulseProgramIR.schema`` 的默认值为 ``PULSE_SCHEMA``\ （``qaiji.pulse/0.1``）。

.. list-table:: 公开记录字段（构造时均仅接受关键字参数）
   :header-rows: 1
   :widths: 25 75

   * - 类型
     - 字段
   * - ``Port``
     - ``id``, ``role``, ``targets``
   * - ``Frame``
     - ``id``, ``port``, ``frequency_hz``, ``phase_rad``
   * - ``Envelope``
     - ``shape``, ``rel_sigma``, ``beta_ns``
   * - ``Play``
     - ``frame``, ``start_ns``, ``duration_ns``, ``envelope``, ``amplitude``, ``phase_rad``, ``condition_id``, ``source``
   * - ``ShiftPhase``
     - ``frame``, ``at_ns``, ``delta_rad``, ``origin``, ``condition_id``, ``source``
   * - ``Acquire``
     - ``port``, ``start_ns``, ``duration_ns``, ``event_id``, ``condition_id``
   * - ``PulseProgramIR``
     - ``source_schedule_ref``, ``ports``, ``frames``, ``instructions``, ``conditions``, ``end_ns``, ``schema``
   * - ``PulseDiagnostic``
     - ``category``, ``code``, ``path``, ``message``

``Port.role`` 取 ``drive``、``readout``、``acquire``、``flux``、``coupler_flux`` 或 ``two_body_drive``。
``two_body_drive`` 允许非零帧载频。只有 CZ 的 Play 接受该角色。
其 ``targets`` 必须恰为 CZ 的两个比特，顺序不限。
``flux`` 与 ``coupler_flux`` 保留目标子集规则，帧载频必须为零。
``Envelope.shape`` 取 ``constant``、``gaussian`` 或 ``drag``。
``ShiftPhase.origin`` 取 ``gate``\ （来自 Z 或 RZ）或 ``correction``\ （来自 CZ）。

独立端口资源映射
----------------

``PortResourceEntry(port, resources)`` 与 ``PortResourceMap(pulse_program_ref, entries, schema)``
均只接受关键字参数。记录不可修改，采用 ``slots``，不可哈希。
``resources`` 必须非空、唯一且按升序排列。``entries`` 必须按端口名升序排列，端口不得重复。
``entries`` 可以为空。映射通过 ``pulse_program_ref`` 绑定 L1 内容身份，不向 L1 增加字段。
映射 schema 为 ``PORT_RESOURCES_SCHEMA``\ （``qaiji.port_resources/0.1``）。

``dump_port_resources(mapping)`` 编码规范 UTF-8 JSON 字节。
``load_port_resources(data)`` 严格解码，拒绝重复键、未知字段与错误版本。
``port_resources_id(mapping)`` 返回 ``sha256(schema + b"\0" + 规范字节)`` 的带前缀摘要。

``check_port_resources(schedule, pulse, mapping)`` 检查每条带 ``source`` 的 Play。
端口映射的资源必须是该 Play 来源 L2 操作资源的子集。
检查器逐条检查共用同一端口的 Play。
Acquire、ShiftPhase 与无来源 Play 不参与覆盖检查。
检查器验证 L2 调度引用和来源下标。其余一致性由 ``check_pulse_program`` 检查。

映射错误抛出 ``PulseContractError``，类别为 ``resources``：

.. list-table:: 资源映射诊断
   :header-rows: 1

   * - 码
     - 条件与路径
   * - ``RESOURCE_REF``
     - L1 引用错配。路径为 ``/pulse_program_ref``。
   * - ``RESOURCE_PORT``
     - 未知端口。路径为 ``/entries/<i>/port``。
   * - ``RESOURCE_MISSING``
     - Play 端口缺少映射。路径为 ``/instructions/<i>``。
   * - ``RESOURCE_COVERAGE``
     - 映射资源超出来源资源。路径为 ``/instructions/<i>``，消息包含 Play 下标。

自动生成的接口说明
------------------

.. automodule:: qaiji.core.pulse
   :members:
   :undoc-members:
   :show-inheritance:
