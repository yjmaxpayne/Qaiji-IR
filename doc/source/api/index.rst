接口参考
========

本节列出公开接口的完整签名与字段。每页开头写明导入路径，并链接对应的概念页与入门页。
页面顺序：先列各层共用的电路前端与约定，再按层自底向上排列，最后列侧层和通用类型。

导入规则
--------

包根 ``qaiji`` 只导出常用入口。各层的接口从各自的子包显式导入，
不向包根或 ``qaiji.core`` 顶层重新导出。约定常量与默认数值常量也使用显式模块路径，
以免把适配层的细节变成包根契约。包内附带 PEP 561 的 ``py.typed`` 标记，
类型检查器可以直接使用本包的类型注解。

.. list-table:: 模块、层与页面
   :header-rows: 1
   :widths: 34 14 52

   * - 模块
     - 层
     - 页面
   * - ``qaiji.core``\ （核心类型也从包根导出）
     - 前端
     - :doc:`core`
   * - ``qaiji.codec``\ （``from_qasm3``、``to_qasm3`` 也从包根导出）
     - 前端
     - :doc:`codec`
   * - ``qaiji.core.conventions``
     - 约定
     - :doc:`conventions`
   * - ``qaiji.core.native``
     - L2
     - :doc:`native`
   * - ``qaiji.core.semantics``
     - L4
     - :doc:`semantics`
   * - ``qaiji.core.program``
     - L5
     - :doc:`program`
   * - ``qaiji.core.program_native``
     - L5 / L2
     - :doc:`program_native`
   * - ``qaiji.core.physical``
     - P
     - :doc:`physical`
   * - ``qaiji`` 与各子包
     - 通用
     - :doc:`exceptions`
   * - ``qaiji``、``qaiji.constants``
     - 通用
     - :doc:`constants`

L3 没有独立的模块，它的接口分布在三个页面中：条件节点 :class:`qaiji.Conditional` 见
:doc:`core`；条件的依赖边 ``build_dataflow_summary`` 见 :doc:`semantics`；
条件读前写入与结果就绪的检查 ``validate_native_schedule`` 见 :doc:`native`。
L1、L0 与 T 层没有公开接口。各层的实现状态见 :doc:`/core-concepts/architecture`。

包根冻结导出
------------

``qaiji.__all__`` 当前包含 17 个名称：版本与格式元数据、七个核心类型、六个异常
类型，以及两个 OpenQASM 编解码函数。各名称的权威说明分布在下面的接口页面中。

.. list-table:: 包根公共入口
   :header-rows: 1
   :widths: 24 76

   * - 类别
     - 名称
   * - 元数据
     - :data:`qaiji.IR_SCHEMA_VERSION`、:data:`qaiji.__version__`
   * - 核心类型
     - :class:`qaiji.Gate`、:class:`qaiji.GateType`、:class:`qaiji.Circuit`、
       :class:`qaiji.ClassicalRegister`、:class:`qaiji.ClassicalBit`、
       :class:`qaiji.Measure`、:class:`qaiji.Conditional`
   * - 异常
     - :class:`qaiji.QaijiIRError`、:class:`qaiji.Qasm3ParseError`、
       :class:`qaiji.Qasm3UnsupportedConstructError`、
       :class:`qaiji.Qasm3UnsupportedGateError`、
       :class:`qaiji.ConventionViolationError`、
       :class:`qaiji.UnsupportedEquivLevelError`
   * - 编解码器
     - :func:`qaiji.from_qasm3`、:func:`qaiji.to_qasm3`

.. toctree::
   :maxdepth: 1

   core
   codec
   conventions
   native
   semantics
   program
   program_native
   physical
   exceptions
   constants
