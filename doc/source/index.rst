.. image:: _static/logo.png
   :align: center
   :alt: 开济 IR 标识
   :width: 240px

.. include:: ../_includes/badges.rst

开济 IR 文档
==============

开济 IR（Qaiji-IR）是面向混合量子—经典计算的跨层中间表示。它以稳定、可验证的
电路级前端为基础：带类型的量子与经典节点、OpenQASM 3 双向编解码器，以及显式的
基矢和旋转相位约定；在此之上提供 L4 语义授权、L5 程序描述、显式配置的 L2 原生调度
与 L5 / L2 测量事件桥接。

本文档只描述由测试守护的公开接口。八层模型中的脉冲、开放系统动力学、校准轨迹
等层不属于这些接口。

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
