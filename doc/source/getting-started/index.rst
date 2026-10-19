入门
====

本节说明安装方法与 OpenQASM 3 往返。
基础示例使用包根接口。
后续教程介绍 L4 摘要与 L5 程序检查。
L2 教程使用合成配置说明原生调度。
P 层教程说明连续演化的交换契约。

.. toctree::
   :maxdepth: 2
   :caption: 目录

   installation
   quickstart
   semantics
   program
   native-schedule
   physical
   troubleshooting

下一步
------

先按 :doc:`installation` 准备环境，再用 :doc:`quickstart` 跑通 OpenQASM 3
往返与语义判决示例，再按 :doc:`semantics`、:doc:`program`、
:doc:`native-schedule` 深入；遇到问题时查阅 :doc:`troubleshooting`。
连续演化的单位与检查边界见 :doc:`physical`。

跑通示例之后，阅读 :doc:`/conventions` 确认物理适配器必须遵守的基矢与相位
约定；完整类型与函数说明见 :doc:`/api/index`。参与开发请参考
:doc:`/development/index`。
