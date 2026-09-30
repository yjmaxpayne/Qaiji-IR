安装指南
========

本页覆盖 Qaiji-IR 的用户安装、开发安装与安装后的验证步骤。

系统要求
--------

- Python 3.12–3.14（以 ``pyproject.toml`` 的 ``requires-python`` 为准）。
- 用户安装只需要 ``pip``；开发环境使用 ``uv``。
- 无 GPU 或系统级依赖要求：Slice A 是纯 Python 的电路级前端。

发布包名是 ``qaiji-ir``，Python 导入名是 ``qaiji``：安装时使用前者，
在 Python 中导入时使用后者。

用户安装
--------

.. code-block:: console

   pip install qaiji-ir

安装后在任何 Python 3.12–3.14 环境中都可以直接 ``import qaiji``。

.. note::

   ``qaiji-ir`` 尚未发布到 PyPI；在首个发布标签落地之前，请使用下文的
   源码安装方式。

开发安装
--------

从源码参与开发时，推荐用 ``uv`` 准备可复现的环境：

.. code-block:: bash

   # 同步开发依赖（自动创建 .venv）
   uv sync --group tests --group analysis

   # 需要构建本文档时再附加 docs 依赖组
   uv sync --group docs

   source .venv/bin/activate

依赖组的具体内容见 ``pyproject.toml``；``uv.lock`` 提供确定性的依赖解析。
构建文档的完整流程另见 ``doc/README.md``。

验证安装
--------

在激活的环境中执行：

.. code-block:: console

   python -c "import qaiji; print(qaiji.__version__, qaiji.IR_SCHEMA_VERSION)"

能打印版本号与中间表示格式版本号（如 ``qaiji.ir.v0``）即说明安装成功。
随后可以用 :doc:`quickstart` 中的 OpenQASM 往返示例做端到端验证；
如果这一步失败，请先查阅 :doc:`troubleshooting`。
