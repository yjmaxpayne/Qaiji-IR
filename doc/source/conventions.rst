基矢与相位约定
==============

量子软件栈跨越 OpenQASM、电路 IR 和物理仿真器时，同一个整数索引可能对应不同的存储
顺序。Qaiji-IR 把这条边界写成可导入常量，并用 :func:`qaiji.core.conventions.self_check`
验证它们彼此一致。适配器不应自行推断或复制这些约定。

计算基语义
----------

OpenQASM 一侧采用通常的计算基语义：标签 0 对应基态 :math:`\lvert 0\rangle`，标签 1
对应激发态 :math:`\lvert 1\rangle`。光学适配器的内部索引顺序相反，因此跨边界时必须
应用下面的映射：

.. list-table:: 基矢标签与适配器索引
   :header-rows: 1
   :widths: 25 35 40

   * - OpenQASM 标签
     - 物理含义
     - 光学适配器索引
   * - ``0``
     - ``ground``，即 :math:`\lvert 0\rangle`
     - ``1``
   * - ``1``
     - ``excited``，即 :math:`\lvert 1\rangle`
     - ``0``

对应的权威常量是
:data:`qaiji.core.conventions.QASM3_INDEX_TO_PHYSICAL`、
:data:`qaiji.core.conventions.OPTICS_INDEX_TO_PHYSICAL` 和
:data:`qaiji.core.conventions.QASM3_TO_OPTICS_BIT`。

RZ 相位
-------

Qaiji-IR 采用如下 Z 轴旋转定义：

.. math::

   R_Z(\theta) = \exp\!\left(-\frac{i\theta Z}{2}\right)
               = \begin{pmatrix}
                   e^{-i\theta/2} & 0 \\
                   0 & e^{i\theta/2}
                 \end{pmatrix}.

因此 :math:`R_Z(\pi)=\operatorname{diag}(-i,+i)`，而
:math:`R_Z(2\pi)=-I`。字符串常量
:data:`qaiji.core.conventions.RZ_PHASE_CONVENTION` 保存同一约定，供适配层检查和记录。

运行自检
--------

应用启动或适配器初始化时可以显式运行自检：

.. doctest::

   >>> from qaiji.core.conventions import self_check
   >>> self_check()

自检成功时返回 ``None``；映射缺项、标签冲突或 RZ 符号不一致时抛出
:class:`qaiji.ConventionViolationError`。容差默认取
:data:`qaiji.constants.DEFAULT_TOLERANCE`，即 ``1e-10``。

证伪状态
--------

自检只能证明这些约定彼此一致：如果把光学适配器映射与 OpenQASM 到适配器的翻译表同时翻转，
``self_check`` 依然通过。为此，每个常量的文档字符串都标注了一个证伪状态，取值只有三种：

.. list-table:: 证伪状态词表
   :header-rows: 1
   :widths: 20 55 25

   * - 状态
     - 含义
     - 适用常量
   * - 已跨库证伪
     - 有外部事实能使其失败，且已设判据；文档字符串引用对应的快照事实 ``XR-*``
     - ``OPTICS_INDEX_TO_PHYSICAL``、``RZ_PHASE_CONVENTION``
   * - 参照系定义
     - 本仓定义的比较参照系，语义权威在本仓；外部实现另有解释时出差异报告，不据此改写
     - ``QASM3_INDEX_TO_PHYSICAL``
   * - 推导成立
     - 由其他约定经 ``self_check`` 推出
     - ``QASM3_TO_OPTICS_BIT``

跨库证伪的对象是光学适配器领域层的源码事实：测试把相关源码片段逐字冻结成快照，
再用判据 R0–R4 核对本仓约定。契约范围只覆盖光学适配器的门、电路与原生后端层；
适配器自带的 OpenQASM 加载路径与其他后端不在范围内。

快照带有提取日期，超过 180 天测试就会失败，即使代码没有任何改动。失败消息列出过期的事实与
刷新步骤；刷新方法见 :doc:`development/contributing` 的「跨库证伪测试」一节。
