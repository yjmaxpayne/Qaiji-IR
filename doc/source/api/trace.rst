T 层轨迹与保持证书接口
======================

从 ``qaiji.core.trace`` 显式导入；包根与 ``qaiji.core`` 不导出这些名称。
本层只依赖标准库与 ``qaiji``。

值类型
------

``TraceLog`` 保存一条来源记录的事件，``TraceSource`` 标识该记录；本层不解析记录格式。
``TraceEvent`` 是一个测量、分支或可观测事件。
事件按规范顺序排列：测量在前，按 id 排序；其次是分支，按（键长，键）排序；
最后是可观测量，按名称排序。id 唯一。

``PreservationCertificate`` 给出一个程序的符号级别与数值判决。
符号级别与数值判决是两个独立字段；任何判决都不改变符号级别。
证书的 ``numerical_verdict`` 必须等于 ``numerical_verdict_of`` 的结果：
任一比较超限时为 ``exceeded``；否则有层被排除时为 ``excluded``；否则为 ``within``。
``ToleranceTable`` 是冻结容差文件，每个跨层比较名一项。

值或编码文档违反本层契约时，抛出 ``TraceInputError``。

编解码
------

``dump_trace_log``、``dump_certificate``、``dump_tolerances`` 输出规范 JSON 字节。
轨迹日志与容差表中的浮点数写为 binary64 十六进制字符串。
对应的 ``load_*`` 函数只接受各自的模式字面量：
``qaiji.t.trace_log/1.0``、``qaiji.t.preservation_certificate/1.0``、
``qaiji.t.tolerances/1.0``。``load_tolerances`` 不检查精度阶梯。

证书检查
--------

``check_certificate`` 用轨迹日志、理想主导键、冻结容差文件与结果文档，
独立重算证书中的每条结论。
它返回无重复、顺序固定的失败码；证书成立时返回值为空。
检查每个引用时，依次检查其种类、记录与事件；引用有误时，不进入后续检查。
每份文档先核对哈希，再解析。
检查器只接受 ``EXACT`` 与 ``UP_TO_PHASE`` 两个符号级别。

符号级别的来源
--------------

:func:`qaiji.core.native.equiv_level_of_native` 从原生验证报告给出符号等价级别。
报告无效时返回 ``None``。每个组相位均为 0 或 ``None`` 时返回 ``EXACT``，
否则返回 ``UP_TO_PHASE``。该函数从 ``qaiji.core.native`` 导入，接口说明见 :doc:`native`。

自动生成的接口说明
------------------

.. automodule:: qaiji.core.trace
   :members:
   :undoc-members:
   :show-inheritance:
