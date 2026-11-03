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
``INVALID_PROGRAM``\ （记录违反 L1 规则）或 ``SCHEDULE_MISMATCH``\ （程序与 L2 调度不一致）。
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

``Port.role`` 取 ``drive``、``readout``、``acquire``、``flux`` 或 ``coupler_flux``。
``Envelope.shape`` 取 ``constant``、``gaussian`` 或 ``drag``。
``ShiftPhase.origin`` 取 ``gate``\ （来自 Z 或 RZ）或 ``correction``\ （来自 CZ）。

自动生成的接口说明
------------------

.. automodule:: qaiji.core.pulse
   :members:
   :undoc-members:
   :show-inheritance:
