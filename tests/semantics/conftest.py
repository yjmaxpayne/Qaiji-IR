# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""为 semantics 中基于子进程的门禁提供全新进程的前置条件守卫。

作用域限定在 tests/semantics/（而非 tests/conftest.py），为导入纯净性的
门禁 2 与哈希稳定性测试（T2.3）提供前置条件；program 的 JSON 测试也使用全新解释器。
"""

from __future__ import annotations

import pytest

from _fresh_process import run_fresh_process


@pytest.fixture(scope="session", autouse=True)
def _fresh_process_can_import_qaiji() -> None:
    """本目录的前置条件：一句裸 ``import qaiji`` 必须能跑通。

    test_import_purity.py 中的两道门禁都建立在一个可用的全新解释器之上；如果这条
    基线本身坏了，在这里失败能直接指向环境问题，而不是让人困惑地失败在门禁 1 或
    门禁 2 内部。
    """
    run_fresh_process("import qaiji")
