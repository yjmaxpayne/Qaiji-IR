核心概念
========

本节说明开济 IR 的架构，以及各层记录的含义和检查边界。
入门示例演示如何调用接口；本节说明这些接口为什么这样划分，以及每项检查能证明什么、
不能证明什么。

本节按下面的顺序组织：

1. :doc:`architecture`：四类关注点、五维语义契约、八层 IR 家族，以及当前包已实现的层。
2. :doc:`conventions`：跨适配层共享的基矢与相位约定。
3. 各主层，自底向上：

   - :doc:`waveform`：L0 采样波形（尚未实现，含设计方向）。
   - :doc:`pulse`：L1 脉冲（尚未实现，含设计方向）。
   - :doc:`native-schedule`：L2 原生调度的输入、时序、认证与消费边界。
   - :doc:`hybrid-control`：L3 条件与经典依赖。
   - :doc:`semantics`：L4 操作分类、等价级别与保持性判决。
   - :doc:`program`：L5 程序记录、内核引用与程序校验。

4. :doc:`physical`：P 侧层的连续演化契约。
5. :doc:`layer-relations`：各层之间的连接，以及每条连接检查什么、不检查什么。

.. toctree::
   :maxdepth: 1

   architecture
   conventions
   waveform
   pulse
   native-schedule
   hybrid-control
   semantics
   program
   physical
   layer-relations
