# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""双重门禁：守护 core/semantics 与 core/program 的导入纯度。

门禁 1 静态扫描两个子包及一跳依赖，涵盖相对导入及 from qaiji import codec；
其盲区只剩动态导入。门禁 2 在全新进程中对白名单之外的新增依赖报错；
codec 及其依赖已在包根导入的基线中，因此仍须门禁 1 补足覆盖。
"""

import ast
import json
import sys
from pathlib import Path

import pytest

import qaiji
from _fresh_process import run_fresh_process

_PACKAGE_ROOT = Path(qaiji.__file__).parent
_PROGRAM_DIR = _PACKAGE_ROOT / "core" / "program"
_SEMANTICS_DIR = _PACKAGE_ROOT / "core" / "semantics"
_ONE_HOP_FILES = (
    _PACKAGE_ROOT / "core" / "__init__.py",
    _PACKAGE_ROOT / "core" / "circuit.py",
    _PACKAGE_ROOT / "core" / "classical.py",
    _PACKAGE_ROOT / "constants.py",
    _PACKAGE_ROOT / "exceptions.py",
)
_BANNED_PREFIXES = ("qaiji.codec", "openqasm3", "numpy")


def _scan_targets() -> tuple[Path, ...]:
    """两个子包自身的模块（新模块自动纳入）加上一跳依赖。"""
    return (
        tuple(sorted(_SEMANTICS_DIR.glob("*.py")))
        + tuple(sorted(_PROGRAM_DIR.glob("*.py")))
        + _ONE_HOP_FILES
    )


def _imported_module_names(path: Path) -> set[str]:
    """文件中任何 import 语句所点名的每一个模块。"""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.add("." * node.level + (node.module or ""))
            elif node.module:
                names.add(node.module)
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _is_banned(module_name: str) -> bool:
    return module_name.startswith(".") or any(
        module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in _BANNED_PREFIXES
    )


# --- 门禁 1：静态 AST 扫描 -----------------------------------------------------


def test_gate1_scan_set_includes_core_init_and_every_semantics_module() -> None:
    """针对扫描集合本身的回归守卫，而不只是针对集合内容。

    core/__init__.py 必须留在一跳闭包里：它自身的 import 语句正是"一跳可达"这个
    定义的组成部分，把它剔除会制造一个无法被发现的缺口（ARCH A-P2-11）。
    """
    scan_targets = _scan_targets()

    assert set(_ONE_HOP_FILES) <= set(scan_targets)
    assert _SEMANTICS_DIR / "__init__.py" in scan_targets
    assert _SEMANTICS_DIR / "dataflow.py" in scan_targets
    assert _SEMANTICS_DIR / "summary.py" in scan_targets


@pytest.mark.parametrize(
    "path", _scan_targets(), ids=lambda path: path.relative_to(_PACKAGE_ROOT).as_posix()
)
def test_gate1_static_scan_excludes_codec_openqasm3_numpy(path: Path) -> None:
    offenders = {name for name in _imported_module_names(path) if _is_banned(name)}
    assert offenders == set()


def test_gate1_scan_detects_an_injected_banned_import(tmp_path: Path) -> None:
    """证明扫描机制真的能标出违规，而不只是证明当前没有违规。

    按 ARCH 对本子任务的 TDD 说明，这道门禁的"红"指的是扫描器抓到一个故意植入的
    坏导入，而不是针对生产代码的常规红/绿单测（这里没有待实现的东西，只有一个待
    证明的检测器）。把它写成一个真正走过 _imported_module_names / _is_banned 路径
    的测试，比开发期手工改一下再改回去要有力得多。
    """
    offender = tmp_path / "injected.py"
    offender.write_text(
        "import numpy\nfrom qaiji.codec import qasm3\nimport openqasm3.ast\nfrom qaiji import codec\nfrom . import sibling\n"
    )

    offenders = {name for name in _imported_module_names(offender) if _is_banned(name)}

    assert offenders == {"numpy", "qaiji.codec", "qaiji.codec.qasm3", "openqasm3.ast", "."}


# --- 门禁 2：全新进程的基线增量白名单 -------------------------------------------


def test_gate2_fresh_process_delta_is_whitelisted_to_qaiji_core() -> None:
    """运行时白名单：导入每个 semantics 子模块会拉进来的全部东西。

    `semantics/__init__.py` 会急切导入每个子模块来构建自己的 `__all__`，
    因此仅一句 `import qaiji.core.semantics` 就已足以加载
    dataflow.py/summary.py/registry.py 等等。本测试仍然按名字逐个显式导入每个子模块
    （和门禁 1 的扫描集合一样用 glob 发现，因此新模块会自动纳入）：这样白名单的断言
    才始终钉死在"逐个子模块"上，而不是暗中依赖 `__init__.py` 的导入顺序来覆盖它们。

    先跑 `import qaiji`，是为了让 qaiji/__init__.py 里急切的
    `from qaiji.codec import ...`（以及 OpenQASM 解析器随之带进来的一切）先被吸收进
    基线快照；只有 semantics 自身额外增加的部分才应当出现在增量里。
    """
    submodule_names = sorted(
        f"qaiji.core.{directory.name}.{path.stem}"
        for directory in (_SEMANTICS_DIR, _PROGRAM_DIR)
        for path in directory.glob("*.py")
        if path.stem != "__init__"
    )
    script = f"""
import json
import sys

import qaiji  # noqa: F401  (absorb package __init__ side effects)

baseline = set(sys.modules)
for name in {submodule_names!r}:
    __import__(name)

delta = sorted(
    name
    for name in set(sys.modules) - baseline
    if name.split(".")[0] not in sys.stdlib_module_names
)
print(json.dumps(delta))
"""
    delta = json.loads(run_fresh_process(script))

    missing = set(submodule_names) - set(delta)
    assert not missing, f"submodules never showed up in the delta: {missing}"
    assert all(name.startswith("qaiji.core") for name in delta)


def test_gate1_scan_set_includes_every_program_module() -> None:
    expected = {_PROGRAM_DIR / name for name in ("__init__.py", "model.py", "validation.py")}
    assert expected <= set(_scan_targets())
    assert set(_PROGRAM_DIR.glob("*.py")) <= set(_scan_targets())


def _non_stdlib_imports(path: Path) -> set[str]:
    """遍历所有静态导入；动态导入不在检查范围。"""
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add("." * node.level + (node.module or ""))
    return {name for name in names if name.split(".")[0] not in sys.stdlib_module_names}


def test_program_model_imports_only_stdlib() -> None:
    assert _non_stdlib_imports(_PROGRAM_DIR / "model.py") == set()


def test_stdlib_only_check_flags_non_stdlib_imports(tmp_path: Path) -> None:
    cases = [
        ("import qaiji", {"qaiji"}),
        ("import qaiji.core", {"qaiji.core"}),
        ("from qaiji.core import Circuit", {"qaiji.core"}),
        ("from . import validation", {"."}),
        ("from .validation import x", {".validation"}),
        ("import numpy as np", {"numpy"}),
        ("def f():\n    import qaiji.core.semantics", {"qaiji.core.semantics"}),
        (
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from qaiji.core import Circuit",
            {"qaiji.core"},
        ),
        (
            "from __future__ import annotations\nimport json, re, collections.abc, dataclasses, typing",
            set(),
        ),
        ("import json, qaiji", {"qaiji"}),
    ]
    for source, expected in cases:
        path = tmp_path / "injected.py"
        path.write_text(source)
        assert _non_stdlib_imports(path) == expected, source
