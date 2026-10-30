代码地图
========

本页说明每一层的源码在哪个目录、测试在哪个目录，以及参与开发时先读哪些文件。
开发环境、必跑检查与提交规范见 :doc:`contributing`。

源码与测试的对应
----------------

下表「源码」「测试」两列中的路径都相对于仓库根目录。每个子包的 ``__init__.py`` 用 ``__all__`` 列出该子包的
公开名称；先读它，再读入口函数所在的文件。

.. list-table:: 层、源码与测试
   :header-rows: 1
   :widths: 16 30 24 30

   * - 层
     - 源码
     - 测试
     - 入口函数所在的文件
   * - 包根
     - ``src/qaiji/__init__.py``、``exceptions.py``、``constants.py``
     - ``tests/test_public_api.py``、``tests/test_distribution.py``
     - ``__init__.py``：包根冻结导出
   * - 前端：电路模型
     - ``src/qaiji/core/circuit.py``、``classical.py``
     - ``tests/core/``
     - ``circuit.py``：``Circuit``、``Gate``、``GateType``
   * - 前端：编解码器
     - ``src/qaiji/codec/``
     - ``tests/codec/``
     - ``qasm3.py``：``from_qasm3``、``parse_qasm3``、``to_qasm3``
   * - 约定
     - ``src/qaiji/core/conventions.py``
     - ``tests/core/test_conventions*.py``
     - ``conventions.py``：权威常量与 ``self_check``
   * - L2
     - ``src/qaiji/core/native/``
     - ``tests/native/``
     - ``api.py``：``lower_to_native``；``validation.py``：``validate_native_schedule``；
       ``projection.py``：``qubic_mapping``
   * - L4
     - ``src/qaiji/core/semantics/``
     - ``tests/semantics/``
     - ``registry.py``：``annotate_circuit``；``dataflow.py``；``summary.py``；
       ``preservation.py``：``check_preservation``
   * - L5
     - ``src/qaiji/core/program/``
     - ``tests/program/``
     - ``validation.py``：``compute_kernel_ref``、``validate_program``
   * - L5 / L2
     - ``src/qaiji/core/program_native/``
     - ``tests/program_native/``
     - ``bridge.py``：``bridge_program_native``
   * - P
     - ``src/qaiji/core/physical/``
     - ``tests/physical/``
     - ``model.py``：记录类型；``validation.py``：``check_problem``；
       ``results.py``：``check_result``；``capabilities.py``：``match_capabilities``

L3 没有独立的子包：条件节点在 ``core/classical.py`` 中定义，依赖边由 L4 的 ``dataflow.py``
生成，读前写入与结果就绪由 L2 的 ``validation.py`` 检查。L1、L0 与 T 层没有源码。

测试共用的电路工厂在 ``tests/factories.py`` 中。``tests/conftest.py`` 在运行任何测试之前
执行约定自检 ``self_check``\ ；自检失败时，每个测试都在准备阶段报错。

入手顺序
--------

1. 读 :doc:`/core-concepts/architecture` 与 :doc:`/core-concepts/layer-relations`，
   确定要改动的层，以及该层与相邻层之间的连接检查什么、不检查什么。
2. 读 ``src/qaiji/__init__.py`` 与 ``tests/test_public_api.py``，确认包根的冻结导出。
   改动包根导出就是改动公开契约。
3. 读目标层的测试目录，再读入口函数所在的文件。测试记录了该层的契约。
4. 按 :doc:`contributing` 的「测试与 TDD」一节，先写失败的测试，再改实现。
5. 改动公开接口时，同步更新对应的概念页、入门页与接口页；
   入门页的示例由 ``make -C doc doctest`` 执行。

改动公开契约之前
----------------

下列改动影响下游适配器，须先确认范围：

- 改动 OpenQASM 3 文本往返的格式契约：提升 ``IR_SCHEMA_VERSION``，并在 ``CHANGELOG.md``
  中记录，见 :doc:`/api/constants`。
- 改动基矢或相位约定：跨库证伪测试必须仍然有效，见 :doc:`contributing` 的「跨库证伪测试」一节
  与 :doc:`/core-concepts/conventions`。
- 新增层级或扩大公开接口：先在议题或设计文档中对齐范围，见 :doc:`contributing` 的「范围提醒」一节。
