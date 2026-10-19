# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""最小验收入口的正控与单侧注入负控。"""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import minimal_acceptance as acceptance
import pytest

SCRIPT = Path(acceptance.__file__).resolve()
CHILDREN = (
    "numerical-wheel-dependency",
    "eager-P-root-import",
    "eager-solver-import",
    "source-tree-shadowing-install",
)


def _process(code: str, package_root: Path | None = None) -> subprocess.CompletedProcess[str]:
    prefix = "import runpy, sys; "
    if package_root is not None:
        prefix += f"sys.path.insert(0, {str(package_root)!r}); "
    prefix += f"ns = runpy.run_path({str(SCRIPT)!r}); "
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c", prefix + code],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_p_legacy_minimal_install() -> None:
    """开发环境执行契约断言，wheel 安装另由显式入口验收。"""
    acceptance.check_dependencies(importlib.metadata.requires("qaiji-ir") or [])
    result = _process(
        "sys.meta_path.insert(0, ns['BlockNumericalImports']()); "
        "ns['check_legacy_contract'](); ns['check_physical_contract']()"
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("child", CHILDREN)
def test_p_rejects_dependency_or_eager_import(child: str, tmp_path: Path) -> None:
    """每个注入先通过正控，再命中独立判据，最后恢复。"""
    if child == "numerical-wheel-dependency":
        metadata_dir = tmp_path / "qaiji_ir-0.dist-info"
        metadata_dir.mkdir()
        metadata = metadata_dir / "METADATA"
        original = importlib.metadata.distribution("qaiji-ir").read_text("METADATA")
        assert original is not None
        metadata.write_text(original, encoding="utf-8")

        def check() -> None:
            distribution = importlib.metadata.Distribution.at(metadata_dir)
            acceptance.check_dependencies(distribution.requires or [])

        check()
        header, separator, body = original.partition("\n\n")
        assert separator
        metadata.write_text(header + "\nRequires-Dist: numpy>=2\n\n" + body, encoding="utf-8")
        with pytest.raises(acceptance.ContractViolation, match=r"^required-dependencies$"):
            check()
        metadata.write_text(original, encoding="utf-8")
        check()
        return

    if child == "source-tree-shadowing-install":
        installed = Path(sysconfig.get_path("purelib")) / "qaiji/__init__.py"
        acceptance.check_wheel_origin(installed)
        source = tmp_path / "src/qaiji/__init__.py"
        source.parent.mkdir(parents=True)
        source.write_text("", encoding="utf-8")
        with pytest.raises(acceptance.ContractViolation, match=r"^wheel-origin$"):
            acceptance.check_wheel_origin(source)
        acceptance.check_wheel_origin(installed)
        return

    import qaiji

    package = tmp_path / "qaiji"
    shutil.copytree(
        Path(qaiji.__file__).parent, package, ignore=shutil.ignore_patterns("__pycache__")
    )
    entry = package / "__init__.py"
    original = entry.read_text(encoding="utf-8")
    command = "ns['check_fresh_import']('qaiji')"
    assert _process(command, tmp_path).returncode == 0
    if child == "eager-P-root-import":
        injection, target = "import qaiji.core.physical\n", "eager-physical-import"
    else:
        # 替身保证拒绝来自导入边界，而非本机缺包。
        (tmp_path / "numpy.py").write_text("sentinel = True\n", encoding="utf-8")
        injection, target = "import numpy\n", "forbidden-import:numpy"
    entry.write_text(original + "\n" + injection, encoding="utf-8")
    rejected = _process(command, tmp_path)
    assert rejected.returncode != 0
    assert target in rejected.stderr
    assert "ModuleNotFoundError" not in rejected.stderr
    unchecked = _process("import qaiji", tmp_path)
    assert unchecked.returncode == 0, unchecked.stderr
    entry.write_text(original, encoding="utf-8")
    restored = _process(command, tmp_path)
    assert restored.returncode == 0, restored.stderr
