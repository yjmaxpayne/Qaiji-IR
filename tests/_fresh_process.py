# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""启动一个全新解释器并返回其 stdout，否则让测试大声失败。

文件名以下划线开头（而不是叫 conftest.py），这样 pytest 绝不会把它当作测试模块
收集，同时它的 basename 在整个 tests/ 下保持唯一 —— 一旦 tests/ 下存在多个
conftest.py，裸名 "conftest" 的跨目录导入为何不安全，见 tests/factories.py 的
docstring。
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


def _clean_subprocess_env() -> dict[str, str]:
    """剥掉 COVERAGE_*，确保被启动的解释器不会同时被插桩。

    xdist worker fork 出 sys.executable、而 coverage 又对子进程一并插桩，这种组合
    曾经损坏过 coverage 的 SQLite 存储；修法是从一开始就不让子
    进程继承 coverage 的子进程触发器。
    """
    return {key: value for key, value in os.environ.items() if not key.startswith("COVERAGE_")}


def run_fresh_process(script: str) -> str:
    """在一个全新解释器中运行 ``script`` 并返回其 stdout。

    Args:
        script: 经由 ``sys.executable -c`` 运行的 Python 源码。

    Returns:
        子进程的 stdout。

    Raises:
        pytest.fail.Exception: 子进程以非零码退出（这是断言惯用法，不是 ``skip``）：
            用 skip 会让套件保持绿色，而它本该守护的那个事实却没被检查
            （R-P05，与覆盖率虚高属于同一类失效）。
    """
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=_clean_subprocess_env(),
    )
    if result.returncode != 0:
        pytest.fail(f"fresh subprocess failed (exit {result.returncode}):\n{result.stderr}")
    return result.stdout
