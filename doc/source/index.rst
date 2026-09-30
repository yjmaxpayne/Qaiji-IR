.. image:: _static/logo.png
   :align: center
   :alt: 开济 IR 标识
   :width: 240px

.. include:: ../_includes/badges.rst

开济 IR 文档
==============

开济 IR（Qaiji-IR）是面向混合量子—经典计算的跨层中间表示。当前发布的 Slice A
聚焦稳定、可验证的电路级前端：它提供带类型的量子与经典节点、OpenQASM 3 双向
编解码器，以及显式的基矢和旋转相位约定。当前还提供 L4 语义授权、L5 程序描述、
显式配置的 L2 原生调度与 L5 / L2 测量事件桥接。

本套文档只描述仓库中已经交付并由测试守护的能力。脉冲、开放系统动力学、校准轨迹
等后续层仍属于项目路线图，不构成当前接口承诺。

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

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
