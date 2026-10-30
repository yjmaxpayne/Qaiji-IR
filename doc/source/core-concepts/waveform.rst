L0 采样波形
===========

L0 WaveformIR 是最接近设备的一层：采样波形、时序网格与通道复用。
脉冲在这一层物化为 DAC 可以播放的样本序列。

.. note::

   本包尚未实现 L0，也不提供 L0 的公开接口。
   本页“设计方向”一节参照 EmuPlat 中现有的波形层实现，只说明移植的起点。
   其中的类名、字段和单位不是本包的契约，移植时可能改变。

当前边界
--------

本包不生成 DAC 样本或波形。L2 的投影只输出中性操作标签，见 :doc:`native-schedule`。

设计方向（尚未实现）
--------------------

EmuPlat 的波形层以 ``emuplat.ir`` 中的下列结构为核心：

.. list-table:: EmuPlat 波形层的现有结构
   :header-rows: 1
   :widths: 28 72

   * - 结构
     - 内容
   * - ``GeneratedWaveform``
     - 一个脉冲生成的 I/Q 样本，加上采样率（GSps）、NCO 相位、载波频率（Hz）与起始时间（ns）。
       保留末尾 NCO 相位，用于保持相邻脉冲的相位连续。
   * - ``WaveformSnapshot``
     - I/Q 样本与采样率（样本/秒），并标明来源是虚拟还是硬件；支持重采样和按容差比较。
   * - ``ChannelSnapshot``
     - 单个通道的快照：通道名、相位、频率、波形与时间戳。
   * - ``L0DriveSet``
     - 反馈程序的多通道实数驱动：载波（cos 或 sin）、采样率（Hz）、分段与样本哈希。

脉冲到样本的转换由 ``Pulse.waveform(sampling_rate)`` 完成：
先计算基带 I/Q 包络，再按 NCO 相位 :math:`\varphi(t)=\varphi_0+2\pi f t` 做 I/Q 混频。
EmuPlat 的默认采样率为 1 GSps，即每 ns 一个样本。

EmuPlat 的现有实现有下列未决问题，移植时须先决定：

- **采样率单位**：``WaveformSnapshot`` 用样本/秒，``GeneratedWaveform`` 用 GSps，
  ``L0DriveSet`` 用 Hz。本包 L0 须只用一种单位。
- **通道复用**：在 ``emuplat.ir`` 中没有找到把多个脉冲合成到同一通道的记录；
  已找到的多通道记录只出现在反馈程序中。
- **数据类型**：除反馈程序的样本外，数组没有显式的数据类型声明。

相关层：L1（:doc:`pulse`）、P（:doc:`physical`）。层间连接见 :doc:`layer-relations`。
