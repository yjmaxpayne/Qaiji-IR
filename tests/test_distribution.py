# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""分发守护：已安装的包与构建出的 wheel 都必须携带 PEP 561 的 ``py.typed`` 标记。"""

import importlib.resources
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# pyproject.toml 及其引用的元数据文件；不复制 .python-version，避免 uv 去冷下载别的解释器。
_BUILD_INPUTS = ("pyproject.toml", "README.md")


def _require_uv(which=None):
    """返回 uv 可执行文件路径；缺失时判失败而不是跳过，守护不能被环境悄悄关掉。"""
    uv = (which or shutil.which)("uv")
    if uv is None:
        pytest.fail("uv is required to build the wheel")
    return uv


def test_py_typed_marker_ships_in_package():
    marker = importlib.resources.files("qaiji") / "py.typed"
    assert marker.is_file(), "qaiji/py.typed is missing"
    assert marker.read_bytes() == b""


def test_wheel_contains_py_typed(tmp_path):
    """在副本中构建：原地构建会临时改写 version.py。"""
    uv = _require_uv()
    tree = tmp_path / "tree"
    shutil.copytree(ROOT / "src", tree / "src", ignore=shutil.ignore_patterns("__pycache__"))
    for name in _BUILD_INPUTS:
        if not (ROOT / name).is_file():
            pytest.fail(f"build input is missing: {name}")
        shutil.copy2(ROOT / name, tree / name)
    env = {**os.environ, "POETRY_DYNAMIC_VERSIONING_BYPASS": "0.0.0"}
    out = tmp_path / "dist"
    command = [uv, "build", "--wheel", "--python", sys.executable, "--out-dir", str(out)]
    result = subprocess.run(command, cwd=tree, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    (wheel,) = out.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert "qaiji/py.typed" in archive.namelist()


def test_missing_uv_is_a_failure_not_a_skip(monkeypatch):
    """注入路径与默认路径（wheel 测试实际走的那条）都必须判失败。"""
    monkeypatch.setattr(shutil, "which", lambda _: None)
    for call in (lambda: _require_uv(which=lambda _: None), _require_uv):
        with pytest.raises(BaseException) as exc:
            call()
        assert exc.type is pytest.fail.Exception
        assert str(exc.value) == "uv is required to build the wheel"
