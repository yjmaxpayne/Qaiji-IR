入门
====

本节用可执行的示例说明如何调用各层的接口。所有示例都在文档构建时执行。
接口为什么这样划分、每项检查能证明什么，见每页对应的概念页。

.. list-table:: 入门各页
   :header-rows: 1
   :widths: 22 12 44 22

   * - 页面
     - 层
     - 读完后能做的事
     - 概念页
   * - :doc:`installation`
     - —
     - 安装本包，并确认可以导入。
     - —
   * - :doc:`quickstart`
     - 前端、L4
     - 完成 OpenQASM 3 往返，直接构造电路，并得到一个保持性判决。
     - :doc:`/core-concepts/architecture`
   * - :doc:`native-schedule`
     - L2、L5 / L2
     - 用合成配置生成并认证原生调度，再把测量事件关联到 L5 输出。
     - :doc:`/core-concepts/native-schedule`
   * - :doc:`semantics`
     - L4
     - 生成标注、数据流摘要与内容哈希，并确定保持性判决的适用范围。
     - :doc:`/core-concepts/semantics`
   * - :doc:`program`
     - L5
     - 构造程序记录，计算内核引用，并校验程序。
     - :doc:`/core-concepts/program`
   * - :doc:`physical`
     - P
     - 构造并检查连续演化问题，再交换该记录。
     - :doc:`/core-concepts/physical`
   * - :doc:`troubleshooting`
     - 全部
     - 按现象定位常见错误。
     - —

页面顺序与 :doc:`/core-concepts/index` 一致：安装与快速开始之后，按层自底向上排列，
然后是 P 侧层。L0 采样波形、L1 脉冲与 T 执行轨迹层没有公开接口，所以没有入门页。
L3 只有条件节点及其测量依赖，没有单独的入门页：条件的依赖边见 :doc:`semantics`，
条件的读前写入与结果就绪检查见 :doc:`native-schedule`。

.. toctree::
   :maxdepth: 2
   :caption: 目录

   installation
   quickstart
   native-schedule
   semantics
   program
   physical
   troubleshooting

跑通示例之后，接口的完整签名见 :doc:`/api/index`。参与开发见 :doc:`/development/index`。
