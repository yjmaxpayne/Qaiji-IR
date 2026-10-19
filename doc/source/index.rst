.. image:: _static/logo.png
   :align: center
   :alt: 开济 IR 标识
   :width: 240px

.. include:: ../_includes/badges.rst

开济 IR 文档
==============

开济 IR（Qaiji-IR）面向混合量子与经典计算。
电路前端提供类型化节点和 OpenQASM 3 编解码。
本包还提供 L4 语义授权与 L5 程序描述。
L2 层支持显式配置的原生调度。
程序桥接按 L5 调用关联 L2 测量事件。
P 层提供连续演化的交换契约与分级检查。

本文档只描述由测试守护的公开接口。
本包不执行时间演化、采样或硬件运行时。
脉冲、波形与校准轨迹仍不属于公开接口。
P 层入门见 :doc:`getting-started/physical`。

.. toctree::
   :maxdepth: 2
   :caption: 入门

   getting-started/index

.. toctree::
   :maxdepth: 2
   :caption: 核心概念

   core-concepts/index

.. toctree::
   :maxdepth: 2
   :caption: 开发指南

   development/index

.. toctree::
   :maxdepth: 2
   :caption: 接口参考

   api/index

相关论文
--------

* `arXiv:2609.29305 <https://arxiv.org/abs/2609.29305>`_ （Jun Ye，2026）。

论文的集成验证范围与本包公开接口分别说明，当前包范围以上文为准。
软件引用信息见仓库中的 ``CITATION.cff``。

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
