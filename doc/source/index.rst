.. image:: _static/logo.png
   :align: center
   :alt: 开济 IR 标识
   :width: 240px

.. include:: ../_includes/badges.rst

开济 IR 文档
==============

开济 IR（Qaiji-IR）是一组用于混合量子—经典编译的中间表示（IR）。
它把从程序结构到设备信号的编译过程划分为八层 IR，并用本包自己的规则和检查器判断语义。
OpenQASM 3 只作为前端适配器，不作为语义判据。
各层的角色与实现状态见 :doc:`core-concepts/architecture`。

本包提供的功能
--------------

.. list-table:: 当前公开接口
   :header-rows: 1
   :widths: 22 78

   * - 部分
     - 功能
   * - 电路前端
     - 类型化电路，以及 OpenQASM 3 文本与电路之间的双向转换。
   * - L5 程序
     - 程序记录、内核引用与程序校验。
   * - L4 操作语义
     - 操作分类、规范摘要与内容哈希，以及逐位置变换的保持性判决。
   * - L3 混合控制
     - 只有条件节点及其测量依赖。
   * - L2 原生调度
     - 显式配置的 CZ 基底调度与独立认证，以及把 L2 测量事件关联到 L5 调用的桥接。
   * - P 动力学
     - 连续演化的交换契约与分级检查。

本文档只描述由测试守护的公开接口。

本包不提供的功能
----------------

- 本包不执行时间演化、采样或硬件运行。
- L1 脉冲、L0 采样波形与 T 执行轨迹层没有公开接口。
- 每条层间连接只做各自的检查，不组合成跨层的保语义证明。

阅读路径
--------

.. list-table:: 按目的选择阅读顺序
   :header-rows: 1
   :widths: 30 70

   * - 目的
     - 阅读顺序
   * - 调用接口
     - :doc:`getting-started/installation` → :doc:`getting-started/quickstart`
       → :doc:`getting-started/index` 中的其他页面。
   * - 理解设计边界，或编写适配器与后端
     - :doc:`core-concepts/architecture` → :doc:`core-concepts/conventions`
       → :doc:`core-concepts/layer-relations` → :doc:`api/index`。
   * - 参与本仓库的开发
     - :doc:`development/code-map` → :doc:`development/contributing`。

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
   :caption: 接口参考

   api/index

.. toctree::
   :maxdepth: 2
   :caption: 开发指南

   development/index

相关论文
--------

* `arXiv:2609.29305 <https://arxiv.org/abs/2609.29305>`_ （Jun Ye，2026）。

论文报告的集成验证范围大于本包公开接口覆盖的范围；本包的范围以本页上文为准。
软件引用信息见仓库中的 ``CITATION.cff``。

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
