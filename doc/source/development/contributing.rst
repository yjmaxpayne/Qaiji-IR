贡献指南
========

贡献可以是新能力、缺陷修复、测试补强或文档改进。本页覆盖开发环境、
必跑检查与仓库约定。

开发环境
--------

Qaiji-IR 使用 ``uv`` 管理依赖与打包（``poetry-dynamic-versioning`` 仅作为
PEP 517 构建后端，版本号取自 Git 标签）：

.. code-block:: bash

   # 同步开发依赖（自动创建 .venv）
   uv sync --group tests --group analysis

   # 构建文档需要附加 docs 依赖组
   uv sync --group docs

   source .venv/bin/activate

常用命令
--------

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - 任务
     - 命令
   * - 测试
     - ``uv run pytest``
   * - 物理约定测试
     - ``uv run pytest -m physics``
   * - 覆盖率
     - ``uv run pytest --cov=qaiji``
   * - 静态检查与格式化
     - ``uv run ruff check src tests`` / ``uv run ruff format src tests``
   * - 类型检查
     - ``uv run mypy src``
   * - 提交前检查
     - ``uv run pre-commit run --all-files``
   * - 更新日志
     - ``uv run cz changelog``
   * - 文档
     - ``make -C doc html``（详见 ``doc/README.md``）

测试与 TDD
----------

- 所有功能代码走 **TDD**：先写测试复现问题或固化契约，再写实现。
  测试应编码"为何重要"，而不是给当前实现拍快照。
- 测试标记：``physics``（基组约定 / 数值保真度，HP 容差）、
  ``integration``（编解码器与核心层的边界）、``pbt``（Hypothesis 属性测试）。
  标记已在 ``pyproject.toml`` 注册。
- 覆盖率要求：整体 ≥90%，核心中间表示与编解码器 ≥95%。
- 数值精度分三级：HP（atol 1e-10）用于约定接缝与往返等价性，
  SP（1e-6）用于一般结构性验证，LP（1e-3）仅限近似方法。

跨库证伪测试
------------

``tests/core/test_conventions_crossrepo.py`` 用光学适配器源码的冻结快照证伪基组约定。
判据只读快照，不需要对方仓库，任何环境都会运行。另有两道防腐门：

- **保鲜**：快照中任一事实的提取日期超过 180 天（或写成了未来日期），测试失败。
  失败消息列出过期的事实与完整的刷新步骤，按步骤更新
  ``tests/core/_optics_snapshot.py`` 即可。
- **实时重核**：逐条确认快照原文在对方源码中恰好出现一次。对方仓库按以下顺序查找：

  - 设置了 ``QAIJI_QUANTEMPO_ROOT`` 时只认该路径（相对路径按当前工作目录解析，请在仓库根目录
    运行）；路径下没有 ``src/quantempo/`` 即判为配置错误，测试**失败**，设成空串也一样；
  - 未设置时查找本仓的兄弟目录 ``../QuanTempo``；不存在则**跳过**，
    跳过理由会写出变量名与默认路径（``addopts`` 中的 ``-rfEs`` 让它出现在摘要里）。

刷新快照后，用下面的命令确认全部事实与对方源码一致：

.. code-block:: bash

   QAIJI_QUANTEMPO_ROOT=../QuanTempo uv run pytest tests/core/test_conventions_crossrepo.py --no-cov -rfEs

编码规范
--------

- PEP 8，行宽 100（ruff），4 空格缩进，类型注解，f-string。
- 现代类型写法：``list[int]`` 而非 ``List[int]``；``int | None`` 而非
  ``Optional[int]``。
- 每个新文件都要带许可证头：

  .. code-block:: python

     # Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
     # SPDX-License-Identifier: Apache-2.0

- 文档字符串正文用中文；Google 风格的分节关键字
  （``Args:``/``Returns:``/``Raises:``/``Example:``）保持英文，
  以便 Sphinx napoleon 正确解析参数表。
- 异常消息字符串保持英文：它们面向日志与 ``pytest.raises(match=...)`` 断言。
- 注释解释*为什么*，而不是*是什么*。

提交规范
--------

- Conventional Commits：``feat``/``fix``/``docs``/``refactor``/``test``/
  ``perf``/``chore``，提交信息用简洁英文。
- 仓库根目录和 ``src/`` 下不留临时文件。

版本号与发布标签
----------------

版本号在构建时由 ``poetry-dynamic-versioning`` 从 Git 标签推导，并开启了 ``strict`` 与
``latest-tag``：没有合适的标签时，``uv build``、``uv sync`` 等需要构建本项目的命令会直接报错，
而不是生成 ``0.0.0`` 开头的版本。常见报错与处理：

- ``No tags available and fallbacks disabled by strict mode``：从 ``HEAD`` 上溯不到任何标签
  （例如克隆时没有取标签），执行 ``git fetch --tags``；fork 的克隆要从上游仓库取，
  即 ``git fetch <上游远端> --tags``。
- ``This is a shallow repository``：浅克隆（例如 ``git clone --depth 1``），
  执行 ``git fetch --unshallow``。
- ``The pattern did not match the latest tag '<标签>'``：离 ``HEAD`` 最近的标签不符合版本模式，
  见下一段。

发布只打 ``vX.Y.Z`` 形式的附注标签（``git tag -a vX.Y.Z -m "vX.Y.Z"``）。版本模式之外的标签
（如 ``v0.2.0rc1``、``release-0.2``）一旦成为离 ``HEAD`` 最近的可达标签，构建就会失败。
同一提交上有多个附注标签时以较晚打的为准，所以不要给已发布的提交补打其他附注标签。

发布到 PyPI 由 ``Publish to PyPI`` 工作流完成（Trusted Publishing，不使用令牌）：在 GitHub 上发布
``vX.Y.Z`` 标签的 Release 即触发，前提是标签所在提交已包含该工作流；标为预发布的 Release 不发布。
上传前要求：标签提交可从 ``main`` 到达、元数据检查通过、wheel 装入干净环境后
``qaiji.__version__`` 等于标签版本；Release 上已附包文件或 ``SHA256SUMS`` 时，构建结果还须与之
逐字节一致。任一项不满足即不上传。通过后上传 PyPI，再把 wheel、sdist 和 ``SHA256SUMS`` 附到
该 Release。对已存在的标签，可在 Actions 页面手动运行该工作流并填入标签名补发，补发不改动 Release。

范围提醒
--------

本仓库实现电路前端、L4 语义、L5 程序、L2 原生调度及其桥接层；脉冲、波形、
硬件 ISA、反馈运行时与 QIR 不在公开接口内。新增层级或扩大公开接口之前，
先在议题或设计文档中对齐范围。
