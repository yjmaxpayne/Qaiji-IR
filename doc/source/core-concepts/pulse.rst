L1 脉冲
=======

L1 PulseIR 描述原生操作降级后的控制脉冲：脉冲、frame、port 与读出。

.. note::

   本包尚未实现 L1，也不提供 L1 的公开接口。
   本页“设计方向”一节参照 EmuPlat 中现有的脉冲层实现，只说明移植的起点。
   其中的类名、字段和单位不是本包的契约，移植时可能改变。

当前边界
--------

L2 投影函数 ``qubic_mapping`` 提供本包当前最底层的输出。它只输出中性操作标签
（``PULSE``、``PULSE_READOUT`` 等），不生成脉冲参数、指令集操作码或波形。
选择脉冲形状、时长与频率，目前由后端完成。

设计方向（尚未实现）
--------------------

EmuPlat 的脉冲层以 ``emuplat.ir`` 中的下列结构为核心：

.. list-table:: EmuPlat 脉冲层的现有结构
   :header-rows: 1
   :widths: 28 72

   * - 结构
     - 内容
   * - ``Pulse``
     - 一个绝对定时的脉冲：``start`` 与 ``duration``\ （整数 ns）、``amplitude``
       （无量纲，范围 [-1, 1]）、``frequency``\ （整数 Hz）、``relative_phase``\ （rad）、
       ``shape``、``channel``、``type`` 与 ``qubit``。
   * - 脉冲子类
     - ``DrivePulse``、``ReadoutPulse``、``FluxPulse``、``CouplerFluxPulse``。
   * - ``PulseType``
     - 驱动、读出、磁通、耦合器磁通、等待与虚拟 Z。
   * - ``PulseShape``
     - 包络形状，例如 ``Rectangular``、``Gaussian``、``Drag``；按采样率计算 I/Q 包络。
   * - ``PulseSequence``
     - 绝对定时脉冲的平铺列表；按比特累计虚拟 Z 相位，并检查脉冲重叠。
   * - ``SymbolicPulse``
     - 与 ``Pulse`` 平行的符号形式：幅度与相位可以是符号表达式，解析后得到具体脉冲。
   * - ``NativePulse``
     - 从校准数据（runcard）构造原生门对应的脉冲；这是 L2 到 L1 的降级入口。

EmuPlat 的现有实现与本层的角色描述有下列差异，移植前须先决定如何处理这些差异：

- **frame 与 port**：EmuPlat 没有独立的 frame 或 port 对象。相位在脉冲上计算，
  通道只是字符串，由 runcard 映射到仪器。
- **操作**：EmuPlat 没有 play、delay、shift-phase、acquire 这类操作记录。
  延时由 ``start`` 隐含，相位变化由 ``relative_phase`` 或虚拟 Z 表示。
- **读出**：只有读出脉冲，没有采集窗口对象；读出窗口只出现在反馈程序中。
- **单位**：EmuPlat 用整数 Hz 表示频率，幅度范围为 [-1, 1]。
  P 层用 rad/ns 表示角频率（见 :doc:`physical`）。本包 L1 的单位尚未确定。

相关层：L0（:doc:`waveform`）、L2（:doc:`native-schedule`）。层间连接见 :doc:`layer-relations`。
