L0 采样波形接口
===============

从 ``qaiji.core.waveform`` 显式导入。包根与 ``qaiji.core`` 不导出这些名称。
本包只依赖标准库、本包的 ``qaiji.core._codec`` 与 L1 脉冲层。

相关页面：层的角色、规则与边界见 :doc:`/core-concepts/waveform`。L1 输入见 :doc:`pulse`。

入口与异常
----------

``WaveformIR`` 的构造入口检查全部 L0 规则与通道引用，不合法的记录无法构造。
``dump_waveform(waveform)`` 返回规范字节。``load_waveform(data)`` 严格解码字节，
再经构造入口检查全部 L0 规则。``waveform_id(waveform)`` 返回内容身份
``sha256(schema + b"\0" + 规范字节)``。

``sample_digests(waveform)`` 返回每个段、每个通道的样本摘要。键为
``(segment_id, channel_id)``，值为 f64le 样本字节的 SHA-256，小写十六进制，无前缀。

参考采样函数：

- ``sample_count(duration_ns, sample_rate_hz)`` 返回样本数
  N = ``duration_ns · sample_rate_hz / 1e9``。
- ``sample_envelope(envelope, duration_ns, sample_rate_hz)`` 按中点规则对单位幅度包络采样，
  返回 I 与 Q 两个序列。
- ``sample_play(program, play, sample_rate_hz)`` 把一条 L1 ``Play`` 混频为实值实验室系样本。
  第 k 个样本的载波相位为 ``2π·f·t_k·1e-9 + 帧相位``，``t_k = start_ns + k / f_s``。

``WaveformContractError`` 继承 ``QaijiIRError``，携带不可变的 ``WaveformDiagnostic`` 序列。
每条诊断含 ``category``、``code``、``path`` 与 ``message``，``category`` 为 ``INVALID_WAVEFORM``。

记录字段
--------

下列记录均不可修改、采用 ``slots``、仅接受关键字参数，且不可哈希。
采样率为整数 Hz，时间为 ns。``WaveformIR.schema`` 的默认值为 ``WAVEFORM_SCHEMA``\
（``qaiji.waveform/0.1``）。

.. list-table:: 公开记录字段（构造时均仅接受关键字参数）
   :header-rows: 1
   :widths: 25 75

   * - 类型
     - 字段
   * - ``Channel``
     - ``id``, ``kind``, ``ports``
   * - ``Segment``
     - ``id``, ``time_origin_ns``, ``condition``, ``samples``
   * - ``TransformRecord``
     - ``kind``, ``params``
   * - ``WaveformIR``
     - ``source_pulse_ref``, ``sample_rate_hz``, ``channels``, ``segments``, ``transforms``, ``schema``
   * - ``WaveformDiagnostic``
     - ``category``, ``code``, ``path``, ``message``

``Channel.kind`` 取 ``dac_real``。``channels`` 按 ``id`` 唯一且升序。
``Segment.condition`` 为 ``None`` 或 ``(condition_id, taken)``。``taken`` 表示条件寄存器等于
L2 条件的 ``value``。每个条件须有 ``taken`` 为 True 与 False 的两个段。
每个段的 ``samples`` 按通道 ``id`` 升序列出，每项的样本为 f64le ``bytes``。
``time_origin_ns · sample_rate_hz`` 须为 1e9 的整数倍。
``source_pulse_ref`` 填写 ``pulse_program_id`` 的结果。
``TransformRecord.params`` 中的浮点数编码为 ``{"$f64": <十六进制>}``。
以 ``$`` 开头的其他键不合法。嵌套上限为 29 层。

自动生成的接口说明
------------------

.. automodule:: qaiji.core.waveform
   :members:
   :undoc-members:
   :show-inheritance:
