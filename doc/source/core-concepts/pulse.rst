L1 脉冲
=======

L1 PulseIR 描述原生操作降级后的控制脉冲：脉冲、frame、port 与读出。
接口见 :doc:`/api/pulse`。

记录
----

- 端口 ``Port`` 声明角色（驱动、读出、采集、磁通或耦合器磁通）与所属比特。
- 帧 ``Frame`` 绑定一个端口，带整数 Hz 频率与程序时间 0 的初相。磁通类端口的帧频率为 0。
- 指令有 3 种，都使用绝对时间（整数 ns）：

  - ``Play`` 在一个帧上播放一个带包络的脉冲。
  - ``ShiftPhase`` 在某一时刻改变一个帧的相位。
  - ``Acquire`` 在一个端口上采集一个测量事件。

- 带 ``condition_id`` 的指令属于程序的一个条件区间。
- ``PulseProgramIR`` 用 ``source_schedule_ref`` 引用生成它的 L2 调度。

规则
----

1. 帧相位：``Play`` 的帧相位等于帧初相、同一帧上不晚于它的全部 ``ShiftPhase`` 增量与它自身相位之和。
   同一时刻的 ``ShiftPhase`` 先于 ``Play`` 生效。
2. 载波相位：绝对时刻 t 的载波相位为 ``2π·f·t·1e-9`` 加帧相位。
3. 两个相位按 2π 取模比较，容差为 1e-10 rad。
4. 与 L2 一致：``check_pulse_program`` 检查程序的引用、时间、来源、目标帧、覆盖与测量是否与 L2 调度一致。
5. 身份：程序身份为 schema 与规范字节的 SHA-256。

边界
----

- 本包定义 L1 记录并检查它们，不实现 L2 到 L1 的降级。后端（例如 EmuPlat）按设备校准构造 L1 程序，
  再调用 ``check_pulse_program``。
- 本包不选择脉冲形状、时长、幅度或频率。
- 包络只有 ``constant``、``gaussian`` 与 ``drag`` 三种。

相关层：L0（:doc:`waveform`）、L2（:doc:`native-schedule`）。层间连接见 :doc:`layer-relations`。
