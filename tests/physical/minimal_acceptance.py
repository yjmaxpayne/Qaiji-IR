# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""用标准库验收 wheel 安装、导入隔离与公开契约。"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

DATA = Path(__file__).resolve().with_name("data")
BLOCKED = frozenset({"numpy", "scipy", "qutip", "emuplat", "emulator_platform", "quantempo"})


class ContractViolation(AssertionError):
    """最小安装未满足指定契约。"""


def require(condition: bool, label: str) -> None:
    """条件为假时抛出带标签的异常。"""
    if not condition:
        raise ContractViolation(label)


class BlockNumericalImports(importlib.abc.MetaPathFinder):
    """显式阻断数值框架，避免依赖本机缺包状态。"""

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0].lower() in BLOCKED:
            raise ContractViolation("forbidden-import:" + fullname)
        return None


def check_dependencies(requirements: list[str]) -> None:
    """检查 wheel 的必需依赖精确集合。"""
    normalized = [re.sub(r"[\s()]", "", item).lower() for item in requirements]
    require(normalized == ["openqasm3[parser]>=1.0.1,<2.0.0"], "required-dependencies")


def check_wheel_origin(origin: Path) -> None:
    """检查导入路径属于当前解释器的安装目录。"""
    expected = {
        (Path(sysconfig.get_path(key)) / "qaiji/__init__.py").resolve()
        for key in ("purelib", "platlib")
    }
    require(origin.resolve() in expected, "wheel-origin")


def check_fresh_import(module: str) -> None:
    """在新进程检查单个模块的导入边界。"""
    require(
        not any(name == "qaiji" or name.startswith("qaiji.") for name in sys.modules),
        "fresh-process",
    )
    sys.meta_path.insert(0, BlockNumericalImports())
    importlib.import_module(module)
    if module == "qaiji":
        require(
            not any(name.startswith("qaiji.core.physical") for name in sys.modules),
            "eager-physical-import",
        )
    require(
        not any(name.split(".")[0].lower() in BLOCKED for name in sys.modules),
        "loaded-numerical-module",
    )


def check_legacy_contract() -> None:
    """检查旧导出、编解码与冻结的 L4/L5 身份。"""
    from qaiji import Circuit, from_qasm3, to_qasm3
    from qaiji.core import ClassicalBit, ClassicalRegister, Conditional, Gate, GateType, Measure
    from qaiji.core.program import compute_kernel_ref

    baseline = json.loads((DATA / "legacy-baseline.json").read_bytes())
    for module, exports in baseline["public_exports"].items():
        require(
            sorted(importlib.import_module(module).__all__) == sorted(exports),
            "legacy-exports:" + module,
        )
    for qualified, expected in baseline["schema_versions"].items():
        module, attribute = qualified.rsplit(".", 1)
        require(
            getattr(importlib.import_module(module), attribute) == expected,
            "legacy-schema:" + qualified,
        )
    for case in baseline["identity"]["kernel_ref_cases"]:
        name = case["id"]
        circuit = Circuit(1 if name == "G-3-rz-float" else 2)
        register = ClassicalRegister("c", 2 if name == "G-1-bell" else 1)
        circuit.add_register(register)
        if name == "G-3-rz-float":
            circuit.rz(0, 0.5)
        else:
            circuit.h(0)
        if name == "G-1-bell":
            circuit.cx(0, 1)
        circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
        if name == "G-1-bell":
            circuit.add_measure(Measure(1, ClassicalBit(register, 1)))
        elif name == "G-2-feedforward":
            circuit.add_conditional(Conditional(register, 1, (Gate(GateType.X, (1,)),)))
        require(compute_kernel_ref(circuit) == case["expected"], "legacy-identity:" + name)
        require(from_qasm3(to_qasm3(circuit)) == circuit, "legacy-codec:" + name)


def check_physical_contract() -> None:
    """检查公开 P 接口、严格交换与结构检查。"""
    import qaiji.core.physical as p

    api = json.loads((DATA / "public-api.json").read_bytes())
    require(sorted(p.__all__) == sorted(api["exports"]), "physical-exports")
    vectors = json.loads((DATA / "canonical-vectors.json").read_bytes())
    for label in ("baseline", "bath"):
        vector = vectors[label]
        raw = json.loads(vector["request_bytes"])
        raw["provenance"] = {
            "kind": "manual",
            "program_ref": None,
            "binder_version": None,
            "device_snapshot": None,
            "calibration_snapshot": None,
            "basis_mapping": [],
            "prior_transforms": [],
        }
        request = p.load_request(json.dumps(raw).encode())
        require(p.problem_id(request.problem) == vector["problem_id"], "problem-identity:" + label)
        require(p.request_id(request) == vector["request_id"], "request-identity:" + label)
        encoded = p.dump_request(request, layout="attachments")
        require(
            p.load_request(encoded.document, attachments=dict(encoded.attachments)) == request,
            "request-roundtrip:" + label,
        )
        p.require_valid(p.check_request(request, level="structure"))
        require(
            p.canonical_problem_bytes(request.problem) == vector["problem_bytes"].encode(),
            "problem-bytes:" + label,
        )
        require(
            p.canonical_request_bytes(request) == vector["request_bytes"].encode(),
            "request-bytes:" + label,
        )
    require(
        not any(name.split(".")[0].lower() in BLOCKED for name in sys.modules),
        "explicit-numerical-import",
    )


def main() -> None:
    """验收实际安装位置，再执行独立进程与契约检查。"""
    distribution = importlib.metadata.distribution("qaiji-ir")
    check_dependencies(distribution.requires or [])
    files = distribution.files or []
    modules = sorted(
        {
            str(path).removesuffix(".py").replace("/", ".").removesuffix(".__init__")
            for path in files
            if str(path).startswith("qaiji/core/physical/") and str(path).endswith(".py")
        }
    )
    require("qaiji.core.physical" in modules and len(modules) >= 10, "physical-modules")
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    for module in ["qaiji", *modules]:
        subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--import", module],
            env=env,
            check=True,
            timeout=30,
        )
    import qaiji

    check_wheel_origin(Path(qaiji.__file__))
    sys.meta_path.insert(0, BlockNumericalImports())
    check_legacy_contract()
    check_physical_contract()
    print(json.dumps({"accepted": True, "modules": len(modules), "origin": qaiji.__file__}))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--import":
        check_fresh_import(sys.argv[2])
    else:
        require(len(sys.argv) == 1, "arguments")
        main()
