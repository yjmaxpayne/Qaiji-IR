P 层连续演化契约
================

``qaiji.core.physical`` 提供连续演化的交换契约。
它描述问题、请求、结果与能力。
本包检查这些记录，不执行时间演化。
调用方须显式导入 P 层。
包根导出保持原样。

单位、时间与顺序
----------------

契约采用以下单位。
输入端须显式声明单位。
检查器不补充物理默认值。

.. list-table:: 物理量与单位
   :header-rows: 1
   :widths: 45 55

   * - 物理量
     - 单位或约束
   * - 时间与最大步长
     - ``ns``
   * - 静态 Hamiltonian 与驱动信号
     - ``rad/ns``
   * - 驱动算子与跳跃算子
     - ``1``，即无量纲
   * - Lindblad 速率
     - ``1/ns``，且不得为负

Hamiltonian 使用角频率。
消费者不得额外乘以 ``2π``。
Lindblad 项使用速率乘以耗散子。
适配振幅接口时须取速率的平方根。
本包不执行这项适配。

``tensor_order`` 决定张量积顺序。
最左站点对应最慢变化的索引。
``sites`` 的记录顺序不替代此字段。
约化态按观测的 ``keep`` 顺序排列。
投影使用 ``V†ρV``，不重新归一化。
``frame`` 是显式参考系标签。
本包不自动转换参考系。
``h0`` 与驱动始终按实验室系给出。
``frame="rotating"`` 时，``rotation_freqs`` 给出每个站点的旋转频率。
频率单位为 rad/ns，条目按 ``tensor_order`` 排列，且覆盖全部站点。
``frame="lab"`` 时，``rotation_freqs`` 必须为空。
近似列表含 ``rwa`` 时，消费者在该旋转系中丢弃反旋项。
``rwa`` 只能与 ``frame="rotating"`` 同用，结构检查拒收实验室系中的 ``rwa``。
旋转频率可以与漂移频率不同，差值作为失谐留在演化中。
旋转系中的态由实验室系的态变换得到：ψ_r(t) = U_r(t) ψ(t)，ρ_r(t) = U_r(t) ρ(t) U_r(t)†。
其中 U_r(t) = exp(+i Σ_k ω_k n_k t)，ω_k 是站点 k 的旋转频率，n_k 是站点 k 的能级序号算符，对角元为 0, 1, …, d_k − 1。
t 是问题时间轴上的绝对时刻，原点为 t = 0，不是第一个信号边界。
初态是第一个信号边界时刻 t₀ 的旋转系态 U_r(t₀) ψ(t₀)；结果中的态是各输出时刻的旋转系态。
回到实验室系时，用 U_r(−t) 变换。
消费者可以施加更严格的规则，例如要求旋转频率等于漂移频率。
逻辑基组与相位约定见 :doc:`/conventions`。

``signal_edges`` 定义连续演化区间。
零阶保持（ZOH）在每个区间内保持常值。
内部区间采用左闭右开边界。
内部边界时刻使用右侧样本。
终点沿用最后一个样本。
常值信号支持零时长问题。
ZOH 信号要求非空演化区间。

``output_times`` 是独立的输出网格。
它可以不落在信号边界上。
消费者须在请求时刻输出结果。
消费者不得吸附时刻或重写时间标签。

构造与交换
----------

下例只使用标准库和 Qaiji-IR。
它构造二能级闭系统，不调用求解器。
数组采用小端二进制与 C 顺序。
``c128le`` 按实部、虚部交错保存。

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

``Request`` 加入输出网格、观测和执行策略。
``Provenance`` 保存来源快照与基组映射。
``Result`` 保存结果值与实际执行报告。
结果须按原请求检查。
使用 ``check_result(request, result, ...)`` 完成绑定检查。
完整签名见 :doc:`/api/physical`。

检查级别与资源
--------------

调用方须显式选择检查级别。

.. list-table:: 检查范围
   :header-rows: 1
   :widths: 22 78

   * - 级别
     - 范围
   * - ``transport``
     - 严格 JSON、字段、类型、版本、数值编码与附件
   * - ``structure``
     - 包含传输检查，另查引用、形状、单位与时间网格
   * - ``physical``
     - 包含结构检查，另查能力、数值条件与资源预算

``complete`` 只表示请求级别的检查完成。
``transport`` 通过不等于物理检查通过。
调用方须读取 ``diagnostics`` 和 ``unchecked``。
``require_valid`` 拒绝失败或未完成的报告。
检查器不裁剪、归一化或修复输入。
物理检查使用总算子检查 Hermitian 条件。
检查器不以逐项 Hermitian 检查替代总和检查。

``CheckBudget`` 配置显式资源上限。
默认全局 Hilbert 维度上限为 64。
数值工作槽位上限为 1048576。
有理数更新次数上限为 1000000。
分子或分母的位长上限为 16384。
JSON 和附件各有 16777216 字节上限。
JSON 嵌套深度上限为 32。
这些界限不承诺性能或内存占用。
预算不足时返回 ``RESOURCE_LIMIT``。
检查器不得降级后报告成功。
当前物理检查仅支持 ``lab`` 参考系。
非空近似列表返回 ``UNSUPPORTED_CAPABILITY``。
旋转系请求只认证到 ``structure`` 级。
结构检查核对 ``rotation_freqs`` 的站点与顺序，不核对数值。
物理检查不能区分按 GHz 写入、少乘 2π 的频率。
这类错误只能由消费者的检查或数值回环比对发现。

.. testcode:: physical-contract

   from qaiji.core.physical import CheckBudget

   limited = check_problem(
       problem, level="physical", budget=CheckBudget(max_dense_dimension=1),
   )
   assert not limited.complete
   assert any(d.category == "RESOURCE_LIMIT" for d in limited.diagnostics)

能力、扩展与身份
----------------

``extract_requirements`` 提取请求的能力需求。
``match_capabilities`` 检查完整能力组合。
每个 profile 含 ``approximations``：需求列出请求的近似，能力列出允许的近似。
请求的近似都在允许集合中，且参考系相同，才能匹配。
能力摘要不替代物理输入。
能力匹配不证明求解结果正确。
执行策略固定或限定算法选择。
实际选择须写入执行报告。

当前版本不提供 bath 求解器。
显式必需扩展可以携带 bath 数据。
编解码器保留这些数据。
扩展 ``qaiji.p.bath`` 版本 ``1.0`` 有公开 schema。
其内容类型为 ``application/vnd.qaiji.p.bath+json``。
payload 含耦合算符、谱密度、温度与 PSD 约定四个字段。
耦合算符是单位为 ``"1"`` 的 ``OperatorSum``，使用交换格式编码。
谱密度 ``kind`` 取 ``drude_lorentz``、``one_over_f`` 或 ``tabulated``。
``drude_lorentz`` 的参数为 ``lam`` 与 ``gamma``。
``one_over_f`` 的参数为 ``eta``、``w_lc`` 与 ``w_hc``，且 ``w_lc < w_hc``。
``tabulated`` 的参数为一维 f64 数组 ``omega`` 与 ``J``，两者等长，至少 2 个样本。
``omega`` 从 0 或以上严格递增；``J`` 非负，且在 ``omega = 0`` 处为 0。
``drude_lorentz`` 与 ``one_over_f`` 的参数都为正。
温度为 k_BT/ħ，为正。频率类参数与温度的单位都为 rad/ns。
标量使用 binary64 十六进制字符串编码。
PSD 约定必填，当前只接受 ``rad/ns``、``one_sided``、``1/pi``。
结构检查校验该 payload；bath 请求只认证到 ``structure`` 级。
消费者须在 ``required_extensions`` 中声明 ``("qaiji.p.bath", "1.0")`` 才能匹配。
一个问题可以带多个 bath 扩展，每个扩展独立描述一个库。
结构检查可以接受完整的不透明扩展。
未知必需扩展阻止完整物理认证。
该拒绝发生在稠密装配之前。
本包不通过外部注册表补全扩展。

``problem_id`` 标识问题内容。
``request_id`` 还覆盖输出网格、观测与策略。
来源快照不参与这两项身份。
规范字节保留顺序和显式物理字段。
身份相同不等于已证明物理等价。
交换器拒绝未知字段、重复键与未知版本。
全部 P 文档使用 schema 版本 1.1。
本版本不读取 1.0 文档。
附件恢复须检查内容摘要。
交换器不通过路径或 URL 读取附件。

最小安装验收
------------

wheel 只声明 OpenQASM 前端的必需依赖。
P 层不依赖 NumPy、SciPy 或 QuTiP。
仓库提供标准库验收入口。
从含完整历史与可达标签的副本构建。
在独立环境安装 wheel 后执行以下命令。

.. code-block:: bash

   uv build --wheel --out-dir dist
   uv venv /tmp/qaiji-minimal
   uv pip install --python /tmp/qaiji-minimal/bin/python dist/*.whl
   /tmp/qaiji-minimal/bin/python -I -B tests/physical/minimal_acceptance.py

入口检查 wheel 的实际导入路径。
它分别在新进程中导入每个 P 子模块。
它显式阻断数值框架导入。
它还执行旧身份、交换与结构检查。
两消费者数值验收由完整测试套件负责。
