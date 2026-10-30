层间关联
========

本页列出各层之间的连接：每条连接由哪个接口实现，检查什么，不检查什么。
各层自身的语义见对应页面。层的角色与实现状态见 :doc:`architecture`。

当前实现的数据流
----------------

当前实现中，一个程序按下面的顺序经过各层：

1. :func:`qaiji.from_qasm3` 把 OpenQASM 3 源码解析为类型化电路；
   :func:`qaiji.to_qasm3` 输出规范文本。
2. L4 为电路分类并生成规范摘要；L3 的条件依赖作为经典边记录在摘要中。
3. L2 把电路展开为 CZ 基底调度，并独立认证来源、规则、矩阵与时序，
   包括条件是否读取最近一次测量、是否晚于结果就绪时刻。
4. L5 程序通过 ``kernel_ref`` 引用电路；``kernel_ref`` 就是电路 L4 规范摘要的哈希。
5. ``bridge_program_native`` 先校验 L5 程序，再认证每次调用绑定的 L2 调度，
   最后把 L2 测量事件关联到 L5 调用与输出。

P 层不在这条链上：它单独描述连续演化问题，不读取电路或调度。

已实现的连接
------------

.. list-table:: 已实现的层间连接
   :header-rows: 1
   :widths: 16 22 31 31

   * - 连接
     - 接口
     - 检查
     - 不检查
   * - OpenQASM 3 与电路
     - ``from_qasm3``、``to_qasm3``
     - 只接受所支持的语法子集，其余构件以明确的异常拒收；序列化输出规范文本。
     - 外部 OpenQASM 3 工具是否接受该程序；语义判断不以此为判据。
   * - 电路与 L4
     - ``annotate_circuit``、``build_semantic_summary``、``check_preservation``
     - 为每个节点分类；用 R1–R4 判决逐位置变换。
     - 规则域之外的变换（返回 ``unsupported``）；不证明等价。
   * - L4 与 L3
     - ``build_dataflow_summary``
     - 按寄存器名把条件连接到写入该寄存器的全部测量。
     - 测量与条件的先后顺序。
   * - L3 与 L2
     - ``validate_native_schedule``
     - 条件读取的每一位都引用其最近一次测量；条件区域不早于结果就绪时刻。
     - 运行时反馈与真实分支执行。
   * - L4 与 L5
     - ``compute_kernel_ref``、``validate_program``
     - 重新计算每个被引用电路的规范摘要哈希；核对输出寄存器的声明与测量写入。
     - 解析表之外的对象；``calibration_set_ref`` 与 ``device_profile_ref`` 的内容。
   * - L5 与 L2
     - ``bridge_program_native``
     - 先校验 L5，再按调用逐个认证 L2 绑定；输出每次调用的测量事件与每位最后一次测量。
     - 测量比特值、概率与采样结果。
   * - L2 与下层
     - ``qubic_mapping``
     - 重新认证调度后输出中性操作标签。
     - 指令集操作码、DAC 样本与波形；这些属于 L1 与 L0。

约定与 P 层的连接
-----------------

.. list-table:: 约定与侧层的连接
   :header-rows: 1
   :widths: 16 22 31 31

   * - 连接
     - 接口
     - 检查
     - 不检查
   * - 约定与适配层
     - ``qaiji.core.conventions`` 中的常量、``self_check``
     - 基矢映射与 RZ 相位约定彼此一致。
     - 两张映射表同时翻转的情形；这类错误由跨库证伪测试检查，见 :doc:`conventions`。
   * - 约定与 P 层
     - ``Provenance.basis_mapping``
     - 结构检查：每个逻辑比特只映射一次，每个站点也只被映射一次；``zero_label`` 与 ``one_label``
       是该站点上两个不同的基态标签。
     - 标签与 :doc:`conventions` 中常量的对应关系。
   * - P 层与 L5
     - ``Provenance.program_ref``
     - 可选字符串。
     - 是否为有效的 ``kernel_ref``，或是否指向某个 L5 程序。

尚未实现的连接
--------------

- L4 与 P：架构图中的双向虚线。当前没有接口把 L4 语义投影到 P 层问题。
- L1 与 L0：脉冲到采样波形的物化。本包没有这两层的公开接口，见 :doc:`pulse` 与 :doc:`waveform`。
- T 层：执行轨迹、分支决策与保持性证书。本包没有 T 层的公开接口。
  EmuPlat 目前只有通信轨迹记录（例如 ``TraceRecord``）和占位的编译遍轨迹（``PassTrace``），
  没有已执行指令或分支决策的记录，因此 T 层的设计还没有可移植的起点。
- 跨层的保语义证明：每条连接只做上表所列的检查，不组合成端到端的证明。
