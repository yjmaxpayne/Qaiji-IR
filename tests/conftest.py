# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""会话级测试准备：约定自检与确定性 profile。

电路工厂放在 tests/factories.py 而不是这里 —— 为什么它们不能驻留在 conftest.py 中，
见该模块的 docstring。
"""

import pytest
from hypothesis import settings

from qaiji.core.conventions import self_check
from qaiji.exceptions import ConventionViolationError

settings.register_profile("repro", deadline=None, derandomize=True)


@pytest.fixture(scope="session", autouse=True)
def validate_conventions() -> None:
    """在运行任何测试之前先校验物理约定。"""
    try:
        self_check()
    except ConventionViolationError as error:
        raise ConventionViolationError(
            "conventions self-check failed -> run: "
            "uv run --group tests pytest tests/core/test_conventions.py -m physics"
        ) from error
