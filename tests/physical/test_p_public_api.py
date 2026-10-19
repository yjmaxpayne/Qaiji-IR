# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""P 层导出集合与逐模块导入隔离检查。"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DATA = Path(__file__).with_name("data")
PHYSICAL = Path(__file__).parents[2] / "src/qaiji/core/physical"
MODULES = tuple(
    "qaiji.core.physical" + ("" if path.stem == "__init__" else "." + path.stem)
    for path in sorted(PHYSICAL.glob("*.py"))
)


def test_p_final_public_exports_are_exact() -> None:
    """公开入口匹配冻结集合，根入口保持原样。"""
    physical = importlib.import_module("qaiji.core.physical")
    expected = json.loads((DATA / "public-api.json").read_bytes())
    assert len(physical.__all__) == len(set(physical.__all__))
    assert set(physical.__all__) == set(expected["exports"])
    assert all(callable(getattr(physical, name)) for name in expected["functions"])
    baseline = json.loads((DATA / "legacy-baseline.json").read_bytes())
    for name, exports in baseline["public_exports"].items():
        module = importlib.import_module(name)
        assert sorted(module.__all__) == sorted(exports)


def _fresh_import(module: str) -> None:
    script = Path(__file__).with_name("minimal_acceptance.py")
    code = (
        "import runpy; "
        f"ns = runpy.run_path({str(script.resolve())!r}); "
        f"ns['check_fresh_import']({module!r})"
    )
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_p_root_import_does_not_load_physical() -> None:
    """新进程的根导入不加载 P 层。"""
    _fresh_import("qaiji")


@pytest.mark.parametrize("module", MODULES)
def test_p_each_module_import_is_isolated(module: str) -> None:
    """每个 P 子模块在独立进程阻断数值依赖。"""
    assert len(MODULES) == 10
    _fresh_import(module)
