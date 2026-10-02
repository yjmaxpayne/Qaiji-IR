接口参考
========

公共接口使用显式模块入口：包根 ``qaiji`` 提供稳定的常用入口；``qaiji.core`` 和
``qaiji.codec`` 暴露对应子系统的完整导出；``qaiji.core.semantics`` 是独立的
L4 语义授权层，``qaiji.core.program`` 提供 L5 程序描述与校验，二者均不向包根或
``qaiji.core`` 顶层重新导出；约定常量与默认数值常量
使用显式模块路径，避免把适配层细节提升为包根契约。包内附带 PEP 561 的 ``py.typed``
标记，类型检查器可以直接使用 qaiji 的类型注解。

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

``qaiji.core.semantics.__all__`` 另有 20 个名称，属于语义层自己的导出面，见
:doc:`semantics`。

``qaiji.core.program.__all__`` 有 8 个名称，属于程序层自己的导出面，见 :doc:`program`。

``qaiji.core.native`` 提供 L2 时序与认证，``qaiji.core.program_native`` 提供
L5 / L2 桥接，均不向包根或 ``qaiji.core`` 顶层重新导出。

.. toctree::
   :maxdepth: 1

   core
   semantics
   program
   native
   program_native
   codec
   exceptions
   constants
   conventions
