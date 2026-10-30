P 动力学：构造与检查
====================

本页构造一个最小的连续演化问题，按 ``physical`` 级别检查它，再以附件布局交换它，
最后演示资源预算不足时的检查报告。本包只检查这些记录，不执行时间演化。

P 层不依赖电路模型。调用方须从 ``qaiji.core.physical`` 显式导入；包根的导出保持不变。
单位、张量顺序、参考系、时间网格与检查级别的定义见 :doc:`/core-concepts/physical`。

构造、检查与交换
----------------

下例只使用标准库和 Qaiji-IR，构造一个二能级闭系统，不调用求解器。
物理量按 :doc:`/core-concepts/physical` 中的单位显式声明：时间单位为 ``ns``，
``h0`` 的单位为 ``rad/ns``。数组采用小端二进制与 C 顺序；``c128le`` 按实部、虚部交错保存。

.. testcode:: physical-contract

   from qaiji.core.physical import (
       ArrayData, Environment, OperatorSum, Problem, Site, State,
       check_problem, dump_problem, load_problem, problem_id, require_valid,
   )

   problem = Problem(
       sites=(Site(id="q0", dim=2, basis=("0", "1")),),
       tensor_order=("q0",),
       h0=OperatorSum(unit="rad/ns", terms=()),
       drives=(),
       environment=Environment(kind="closed", jumps=()),
       initial_state=State(
           kind="ket", frame="lab",
           data=ArrayData.from_values(dtype="c128le", shape=(2,), values=(1, 0)),
       ),
       signal_edges=ArrayData.from_values(dtype="f64le", shape=(2,), values=(0, 10)),
       time_unit="ns", frame="lab", rotation_freqs=(), approximations=(), extensions=(),
   )
   report = check_problem(problem, level="physical")
   require_valid(report)
   assert report.complete and not report.diagnostics
   artifact = dump_problem(problem, layout="attachments")
   restored = load_problem(artifact.document, attachments=dict(artifact.attachments))
   assert restored == problem
   assert problem_id(restored) == problem_id(problem)

``check_problem`` 只检查调用方选择的级别；本例选择最高的 ``physical`` 级。
``require_valid`` 拒绝失败或未完成的报告。
``dump_problem(..., layout="attachments")`` 把数组写为附件；
读回时须用 ``dict(artifact.attachments)`` 显式传入附件。
读回的问题与原问题相等，``problem_id`` 也相同。

请求与结果
----------

``Request`` 在问题之上加入输出网格、观测和执行策略。
``Provenance`` 保存来源快照与基组映射。``Result`` 保存结果值与实际的执行报告。
结果须按原请求检查：调用 ``check_result(request, result, ...)``。

资源预算
--------

``CheckBudget`` 设置检查的资源上限。预算不足时，报告不完整，并含 ``RESOURCE_LIMIT``
诊断；检查器不会静默跳过超出预算的检查工作并报告成功。默认上限见 :doc:`/core-concepts/physical`。

.. testcode:: physical-contract

   from qaiji.core.physical import CheckBudget

   limited = check_problem(
       problem, level="physical", budget=CheckBudget(max_dense_dimension=1),
   )
   assert not limited.complete
   assert any(d.category == "RESOURCE_LIMIT" for d in limited.diagnostics)

``transport`` 级通过不等于 ``physical`` 级通过。调用方须读取报告的 ``diagnostics``
和 ``unchecked``。

最小安装验收
------------

wheel 只声明 OpenQASM 前端的必需依赖。
P 层不依赖 NumPy、SciPy 或 QuTiP。
仓库提供标准库验收入口。
在含完整 Git 历史和版本标签的克隆中构建：版本号取自 Git 标签。
在独立环境安装 wheel 后执行以下命令。

.. code-block:: bash

   uv build --wheel --out-dir dist
   uv venv /tmp/qaiji-minimal
   uv pip install --python /tmp/qaiji-minimal/bin/python dist/*.whl
   /tmp/qaiji-minimal/bin/python -I -B tests/physical/minimal_acceptance.py

入口检查 wheel 的实际导入路径，在新进程中分别导入每个 P 子模块，并显式阻断数值框架导入；
还检查已有接口的导出、编解码与冻结的 L4/L5 身份，
以及 P 层接口、严格交换与结构检查。
两个独立消费者的数值验收由完整测试套件负责。

相关页面：契约规格见 :doc:`/core-concepts/physical`；完整接口见 :doc:`/api/physical`。

下一步：检查失败或导入失败时，见 :doc:`troubleshooting`。
