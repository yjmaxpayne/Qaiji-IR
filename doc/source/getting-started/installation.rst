安装指南
========

本页说明用户安装、开发安装，以及安装后的验证方法。

系统要求
--------

- Python 3.12–3.14（以 ``pyproject.toml`` 的 ``requires-python`` 为准）。
- 用户安装只需要 ``pip``；开发环境使用 ``uv``。
- 无 GPU 或系统级依赖要求：Qaiji-IR 是纯 Python 包。

发布包名是 ``qaiji-ir``，Python 导入名是 ``qaiji``：``pip list``、``pip uninstall``
使用前者，在 Python 中导入时使用后者。

用户安装
--------

.. code-block:: console

   pip install qaiji-ir

需要 ``main`` 分支上尚未发布的改动时，从 Git 仓库安装：

.. code-block:: console

   pip install "git+https://github.com/yjmaxpayne/Qaiji-IR.git"

在安装了本包的 Python 3.12–3.14 环境中，可以直接 ``import qaiji``。

开发安装
--------

从源码参与开发时，推荐用 ``uv`` 准备可复现的环境：

.. code-block:: bash

   # 同步开发依赖（自动创建 .venv）
   uv sync --group tests --group analysis

   # 需要构建本文档时，在同一条命令中加入 docs 依赖组。
   # uv sync 默认精确同步：只写 --group docs 会卸载 tests 与 analysis 组。
   uv sync --group tests --group analysis --group docs

   source .venv/bin/activate

依赖组的具体内容见 ``pyproject.toml``；``uv.lock`` 提供确定性的依赖解析。
构建文档的完整流程见 ``doc/README.md``。开发流程见 :doc:`/development/contributing`。

验证安装
--------

在激活的环境中执行：

.. code-block:: console

   python -c "import qaiji; print(qaiji.__version__, qaiji.IR_SCHEMA_VERSION)"

命令打印出版本号和 IR 格式版本号（例如 ``qaiji.ir.v0``）时，安装成功。
安装或导入失败时，见 :doc:`troubleshooting`。

下一步：:doc:`quickstart` 用 OpenQASM 往返示例做端到端验证。
