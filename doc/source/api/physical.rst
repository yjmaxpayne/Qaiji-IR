P 动力学接口
============

公开入口为 ``qaiji.core.physical``。
该入口包含 33 个类型与 20 个函数。
这些名称不加入包根的 ``__all__``。
P 层只依赖标准库、同层模块与基础异常。

相关页面：契约规格与检查边界见 :doc:`/core-concepts/physical`；示例见
:doc:`/getting-started/physical`。

记录与异常
----------

模型记录使用关键字参数。
模型复制输入，保持深层不可变。
``ArrayData`` 使用显式数据类型、形状与字节。
``FrozenJSON`` 保存不透明 JSON 值。
``PContractError`` 继承 ``QaijiIRError``。
诊断路径采用 JSON Pointer。

.. automodule:: qaiji.core.physical
   :members:
   :imported-members:
   :undoc-members:
   :member-order: bysource

交换与认证边界
--------------

``dump_problem``、``dump_request`` 和 ``dump_result`` 返回制品。
``EncodedArtifact.document`` 是 JSON 字节。
``attachments`` 按顺序列出由名称和字节组成的对。
恢复时须用 ``dict(artifact.attachments)`` 显式传入附件。
能力摘要的 dump 函数直接返回 JSON 字节。
load 函数拒绝非法交换内容。
check 函数把领域拒绝写入报告。
调用方用 ``require_valid`` 将失败报告转为异常。

``canonical_problem_bytes`` 和 ``canonical_request_bytes`` 返回规范字节。
它们不认证物理等价或执行正确性。
``check_result`` 检查结果与请求的一致性。
它不重放演化，也不替代独立数值参考。
