版本与数值常量
==============

版本元数据
----------

.. autodata:: qaiji.__version__

.. autodata:: qaiji.IR_SCHEMA_VERSION

``IR_SCHEMA_VERSION`` 标识 OpenQASM 黄金往返契约。任何破坏该契约的变更都必须提升
格式版本，并在 ``CHANGELOG.md`` 中记录。

数值容差
--------

.. autodata:: qaiji.constants.DEFAULT_TOLERANCE

该容差用于电路参数比较和约定自检。它通过 ``qaiji.constants`` 显式导入，
不属于包根导出。
