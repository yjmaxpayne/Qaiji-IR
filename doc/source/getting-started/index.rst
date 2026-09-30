入门
====

安装 Qaiji-IR，完成第一次 OpenQASM 3 往返，并了解常见的安装与解析问题。
基础示例使用包根接口；后续教程依次展示 L4 语义摘要、L5 程序校验和
使用合成配置的 L2 原生调度。

.. toctree::
   :maxdepth: 2
   :caption: 目录

   installation
   quickstart
   semantics
   program
   native-schedule
   troubleshooting

下一步
------

先按 :doc:`installation` 准备环境，再用 :doc:`quickstart` 跑通 OpenQASM 3
往返与语义判决示例，再按 :doc:`semantics`、:doc:`program`、
:doc:`native-schedule` 深入；遇到问题时查阅 :doc:`troubleshooting`。

跑通示例之后，阅读 :doc:`/conventions` 确认物理适配器必须遵守的基矢与相位
约定；完整类型与函数说明见 :doc:`/api/index`。参与开发请参考
:doc:`/development/index`。
