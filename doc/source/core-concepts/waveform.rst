L0 采样波形
===========

L0 WaveformIR 是最接近设备的一层：采样波形、时序网格与通道复用。
脉冲在这一层物化为 DAC 可以播放的样本序列。接口见 :doc:`/api/waveform`。

记录
----

- 通道 ``Channel`` 是一路实值 DAC 输出（``dac_real``）。``ports`` 列出该通道承载的端口。
- 段 ``Segment`` 从 ``time_origin_ns`` 开始，按通道给出 f64le 样本。
  条件段带 ``(condition_id, taken)``，每个条件有两个分支段。
- ``TransformRecord`` 记录生成样本时用过的变换及其参数。
- ``WaveformIR`` 用 ``source_pulse_ref`` 引用生成它的 L1 程序。

规则
----

1. 采样率为整数 Hz。段起点与采样网格对齐：``time_origin_ns · sample_rate_hz`` 是 1e9 的整数倍。
2. 第 k 个样本对应时刻 ``time_origin + k / f_s``。样本是实验室系的实值，不是复 I/Q。
3. 参考采样：包络按中点规则取样。载波相位先用整数按整周约简，再乘 2π。
4. 身份：程序身份为 schema 与规范字节的 SHA-256。每个段、每个通道的样本另有 SHA-256 摘要。

边界
----

- 本包提供单条 ``Play`` 的参考采样，不把整个 L1 程序物化为 ``WaveformIR``。
  后端构造 ``WaveformIR`` 并给出样本。
- 只支持内联样本，不支持外部附件。
- 本包不模拟 DAC 的非理想特性，例如滤波、量化与失真。

相关层：L1（:doc:`pulse`）、P（:doc:`physical`）。层间连接见 :doc:`layer-relations`。
