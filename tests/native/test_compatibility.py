# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""冻结兼容合同，并扫描完整新增包与一跳依赖。"""

import ast
import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from factories import bell_circuit, feedforward_circuit
from qaiji import Circuit, ClassicalBit, ClassicalRegister, Gate, GateType, Measure
from qaiji.codec import to_qasm3
from qaiji.core.program import compute_kernel_ref
from qaiji.exceptions import Qasm3UnsupportedGateError

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).with_name("compatibility_baseline.json")
PACKAGES = ("qaiji.core.native", "qaiji.core.program_native")
BANNED = (
    "qaiji.codec",
    "openqasm3",
    "numpy",
    "scipy",
    "qutip",
    "qubic",
    "emuplat",
    "qiskit",
    "pennylane",
    "runtime",
)


def _banned(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in BANNED)


def _references(path, module):
    tree = ast.parse(path.read_text())
    names = set()
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = importlib.util.resolve_name("." * node.level + base, package)
            names.add(base)
            names.update(base + "." + alias.name for alias in node.names)
        elif isinstance(node, ast.Attribute):
            parts = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                names.add(".".join([current.id, *reversed(parts)]))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # 同时检查前向注解和动态导入的字面字符串。
            names.update(node.value.replace("[", " ").replace("]", " ").split())
    return names


def _module_file(src, name):
    path = src.joinpath(*name.split("."))
    if path.with_suffix(".py").is_file():
        return path.with_suffix(".py")
    if (path / "__init__.py").is_file():
        return path / "__init__.py"
    return None


def _closure(src):
    primary = {}
    for package in PACKAGES:
        directory = src.joinpath(*package.split("."))
        for path in directory.rglob("*.py"):
            parts = path.relative_to(src).with_suffix("").parts
            primary[path] = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
    closure = dict(primary)
    for path, module in primary.items():
        for name in _references(path, module):
            if name.startswith("qaiji.") and (target := _module_file(src, name)):
                closure[target] = name
                if target.name == "__init__.py":
                    for sibling in target.parent.rglob("*.py"):
                        parts = sibling.relative_to(src).with_suffix("").parts
                        closure[sibling] = ".".join(
                            parts[:-1] if parts[-1] == "__init__" else parts
                        )
    return closure


def _offenders(src):
    offenders = {}
    for path, module in _closure(src).items():
        bad = set(filter(_banned, _references(path, module)))
        # 所有实际导入都限定为标准库或本工程，注解/字符串另做禁用依赖扫描。
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            else:
                continue
            bad.update(
                name
                for name in names
                if name.partition(".")[0] not in sys.stdlib_module_names | {"qaiji", "__future__"}
            )
        if bad:
            offenders[str(path.relative_to(src))] = sorted(bad)
    return offenders


def test_old_and_new_public_sets():
    frozen = json.loads(CASES.read_text())["public"]
    assert len(frozen) == 7
    for name, expected in frozen.items():
        module = importlib.import_module(name)
        assert sorted(module.__all__) == sorted(expected), name
        assert all(hasattr(module, member) for member in expected)


def test_old_schema_kernel_goldens_and_preservation():
    baseline = json.loads(CASES.read_text())
    for key, expected in baseline["schemas"].items():
        module, attribute = key.rsplit(".", 1)
        assert getattr(importlib.import_module(module), attribute) == expected
    rz = Circuit(1)
    register = ClassicalRegister("c", 1)
    rz.add_register(register)
    rz.rz(0, 0.5)
    rz.add_measure(Measure(0, ClassicalBit(register, 0)))
    assert [compute_kernel_ref(c) for c in (bell_circuit(), feedforward_circuit(), rz)] == baseline[
        "kernel_goldens"
    ]
    # 字节指纹共同保护旧 R1–R4、stage/status 与 EquivLevel。
    for path, expected in baseline["frozen_sources"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path


@pytest.mark.parametrize("kind", ["RX90", "RX180", "ISWAP", "SQISWAP"])
def test_four_gate_codec_rejection_unchanged(kind):
    qubits = (0,) if kind.startswith("RX") else (0, 1)
    circuit = Circuit(len(qubits))
    circuit.add_gate(Gate(GateType[kind], qubits, (0.0,) if len(qubits) == 1 else ()))
    with pytest.raises(Qasm3UnsupportedGateError) as caught:
        to_qasm3(circuit)
    assert kind.lower() in str(caught.value).lower()


def test_static_import_closure_and_dynamic_strings():
    closure = _closure(ROOT / "src")
    for package in PACKAGES:
        assert set((ROOT / "src").joinpath(*package.split(".")).rglob("*.py")) <= closure.keys()
    assert ROOT / "src/qaiji/core/circuit.py" in closure
    assert ROOT / "src/qaiji/core/program/validation.py" in closure
    assert _offenders(ROOT / "src") == {}


def test_fresh_process_incremental_imports():
    script = """
import importlib, json, pathlib, sys
import qaiji
baseline = set(sys.modules)
root = pathlib.Path(qaiji.__file__).parent
for package in ('native', 'program_native'):
    for path in (root / 'core' / package).rglob('*.py'):
        relative = path.relative_to(root).with_suffix('').parts
        name = 'qaiji.' + '.'.join(relative[:-1] if relative[-1] == '__init__' else relative)
        importlib.import_module(name)
print(json.dumps(sorted(set(sys.modules) - baseline)))
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    delta = json.loads(result.stdout)
    assert any(name.startswith(PACKAGES) for name in delta)
    assert not any(_banned(name) for name in delta)
    assert all(
        name.startswith("qaiji.core.") or name.partition(".")[0] in sys.stdlib_module_names
        for name in delta
    )


@pytest.mark.parametrize(
    "payload",
    [
        "import numpy\n",
        "import unlisted_runtime_dependency\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n import qutip\n",
        "def f(x: 'numpy.ndarray'): pass\n",
        "def f(x: numpy.ndarray): pass\n",
        "__import__('openqasm3')\n",
        "from qaiji import codec\n",
        "from ... import codec\n",
    ],
)
@pytest.mark.parametrize("location", ["new_module", "one_hop"])
def test_purity_oracle_detects_injected_import(tmp_path, payload, location):
    package = tmp_path / "qaiji/core/native"
    package.mkdir(parents=True)
    entry = package / "__init__.py"
    entry.write_text("from qaiji.core import helper\n")
    helper = tmp_path / "qaiji/core/helper.py"
    helper.write_text("")
    assert _offenders(tmp_path) == {}
    target = package / "untracked.py" if location == "new_module" else helper
    # 按模块层级调整相对导入的点数。
    if location == "one_hop" and payload == "from ... import codec\n":
        payload = "from .. import codec\n"
    target.write_text(payload)
    assert str(target.relative_to(tmp_path)) in _offenders(tmp_path)
    target.write_text("")
    assert _offenders(tmp_path) == {}


# 已计划但尚未落行的 L7 行；每张卡落行时移出本卡的行，全部落行后为空。
_PENDING_L7 = frozenset({"L7-04", "L7-05", "L7-08"})


def _ledger_errors(baseline, root):
    """按仓库内测试函数校验注入的基线，返回首个具体违约消息，不修改输入。

    哈希只证明跳转连续性；冻结文件的真实字节由上面的既有测试校验。
    """
    for key in ("origin", "ledger", "frozen_sources"):
        if key not in baseline:
            return [f"missing baseline field: {key}"]
    origin, ledger, frozen = (baseline[key] for key in ("origin", "ledger", "frozen_sources"))
    if not isinstance(origin, dict) or not isinstance(frozen, dict) or not isinstance(ledger, list):
        return ["origin/frozen_sources must be objects and ledger must be a list"]
    if not origin:
        return ["origin must be a nonempty object"]
    required = {
        "id",
        "kind",
        "surface",
        "before",
        "after",
        "decision",
        "tests_rewritten",
        "guard_tests",
        "sources",
    }
    planned = {f"L6-{i:02d}" for i in range(1, 11)} | {f"L7-{i:02d}" for i in range(1, 9)}
    # starts：每条链的起点，创建 hop 的起点是 None；touched：账本顺序中已经出现过的路径。
    seen, touched, starts = set(), set(), dict(origin)
    for row in ledger:
        if not isinstance(row, dict):
            return ["ledger row must be an object"]
        identity = row.get("id", "<missing>")
        missing = required - row.keys()
        if missing:
            return [f"{identity}: missing ledger fields: {', '.join(sorted(missing))}"]
        if not isinstance(identity, str) or identity not in planned:
            return [f"unplanned ledger ID: {identity}"]
        if identity in seen:
            return [f"duplicate ledger ID: {identity}"]
        seen.add(identity)
        if row["kind"] not in ("narrow", "fix", "extend", "docs"):
            return [f"{identity}: invalid ledger kind: {row['kind']}"]
        for key in ("surface", "before", "after", "decision"):
            if not isinstance(row[key], str) or not row[key].strip():
                return [f"{identity}: {key} must be nonempty text"]
        for key in ("tests_rewritten", "guard_tests"):
            if not isinstance(row[key], list) or not all(isinstance(ref, str) for ref in row[key]):
                return [f"{identity}: {key} must be a list of references"]
        if not isinstance(row["sources"], dict) or not row["sources"]:
            return [f"{identity}: sources must be a nonempty object"]
        for path, hop in row["sources"].items():
            created = isinstance(hop, dict) and "before" in hop and hop["before"] is None
            if path not in starts and not created:
                return [f"{identity}: source is not in origin: {path}"]
            for side in ("after",) if created else ("before", "after"):
                if not isinstance(hop, dict) or not _ledger_sha256(hop.get(side)):
                    return [f"{identity}: invalid source hash: {path}: {side}"]
            if not created:
                continue
            if row["kind"] != "extend":
                return [f"{identity}: creation hop requires an extend row: {path}"]
            if path not in {"src/qaiji/py.typed"}:
                return [f"{identity}: path may not be created: {path}"]
            if path in origin:
                return [f"{identity}: creation hop for an origin path: {path}"]
            if path in touched:
                return [f"{identity}: creation hop after earlier hops: {path}"]
            starts[path] = None
        touched.update(row["sources"])
    for path, initial in starts.items():
        if path not in frozen:
            return [f"{path}: origin path is not frozen"]
        if (path in origin and not _ledger_sha256(initial)) or not _ledger_sha256(frozen[path]):
            return [f"{path}: invalid origin or frozen hash"]
        # 同跳组：与前一行相邻、同为 extend 且 sources 逐字相同的行不另算一跳。
        hops, previous = [], None
        for row in ledger:
            grouped = (
                previous is not None
                and row["kind"] == previous["kind"] == "extend"
                and row["sources"] == previous["sources"]
            )
            if path in row["sources"] and not grouped:
                hops.append(row["sources"][path])
            previous = row
        links = {}
        for hop in hops:
            if hop["before"] in links:
                return [f"{path}: fork at {hop['before']}"]
            links[hop["before"]] = hop["after"]
        if hops and initial not in links:
            return [f"{path}: first hop does not start at origin"]
        current, visited = initial, set()
        while current in links:
            if current in visited:
                return [f"{path}: cycle in hash chain"]
            visited.add(current)
            current = links[current]
        if current != frozen[path]:
            if len(visited) != len(hops):
                return [f"{path}: interrupted hash chain"]
            return [f"{path}: last hop does not match frozen_sources"]
        if len(visited) != len(hops):
            return [f"{path}: orphan ledger hops"]
    pins = {
        "tests/test_public_api.py::test_public_exports_are_the_exact_contract",
        "tests/test_distribution.py::test_wheel_contains_py_typed",
    }
    for row in ledger:
        identity = row["id"]
        references = row["tests_rewritten"] + row["guard_tests"]
        for reference in references:
            if not _ledger_test_reference(reference, root):
                return [f"{identity}: reference is not a test function: {reference}"]
        if row["kind"] == "narrow" and not any(
            ref.startswith("tests/codec/test_acceptance_m1.py::") for ref in row["guard_tests"]
        ):
            return [f"{identity}: narrow row has no acceptance test"]
        if row["kind"] == "extend" and not any(ref in pins for ref in references):
            return [f"{identity}: extend row has no surface pin test"]
        if row["kind"] == "extend" and all(ref in pins for ref in references):
            return [f"{identity}: extend row has no behaviour guard test"]
        ast_guard = "tests/native/test_compatibility.py::test_docs_rows_preserve_stripped_ast"
        if row["kind"] == "docs" and ast_guard not in references:
            return [f"{identity}: docs row has no stripped-AST guard"]
    return []


def _origin_errors(origin):
    """origin 必须恰为 8 个钉住的路径，且每个值等于钉住时的字面哈希。"""
    pins = {
        "src/qaiji/codec/qasm3.py": (
            "231237a1bee5a2a480e90dde0a662fdec6753312f921a6e5d96a3886f63964ac"
        ),
        "src/qaiji/codec/_stdgates.py": (
            "b1738a3335907d5475279edd952c98a91ffb254193cbeab867700909137fcda7"
        ),
        "src/qaiji/codec/__init__.py": (
            "ec466fa1f5033b27937afb9801a6197547ff22dd2901e0fa01b9ef5346d8d22f"
        ),
        "src/qaiji/core/conventions.py": (
            "1e2334251a1fd414d47746715041aa4e2f60fde6471d228d7d852b0d2b1e4cc4"
        ),
        "src/qaiji/core/semantics/dataflow.py": (
            "ef8ccb0ccfede1d88e25b7efbfa39ee8f3c73427cf6a8d3e8bd8e3a72e3e1b21"
        ),
        "src/qaiji/core/semantics/handle.py": (
            "4aad5a694292022a0922d74e803df65c1715eb7ad97e2ed0f7a34683b7acfec8"
        ),
        "src/qaiji/core/semantics/summary.py": (
            "1f049c343b017377b232099050df1635bbc12356e2f480bb66a9fb659694f8a6"
        ),
        "src/qaiji/core/semantics/types.py": (
            "990effb63a98f75cd7bba34d567904a008ce3f9e070b091aca060fea325dd415"
        ),
    }
    for path, value in origin.items():
        if path not in pins:
            return [f"origin path is not allowed: {path}"]
        if value != pins[path]:
            return [f"origin hash changed: {path}"]
    missing = sorted(set(pins) - set(origin))
    return [f"origin path is missing: {missing[0]}"] if missing else []


def _pending_errors(identities):
    """已经落行却仍登记为 pending 的账本 ID。"""
    landed = sorted(_PENDING_L7 & set(identities))
    return [f"pending ledger ID has a row: {landed[0]}"] if landed else []


def _ledger_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _ledger_test_reference(reference, root):
    path, separator, node = reference.partition("::")
    if "[" in reference:
        return False
    # 只认规范相对路径：别名写法会让同一测试在钉值集合的字面比较中被当成另一条引用
    if any(part in ("", ".", "..") for part in path.split("/")):
        return False
    name = node
    target = (root / path).resolve()
    if not separator or not target.is_relative_to(root.resolve()) or not target.is_file():
        return False
    module_name = "_qm6_ledger_" + hashlib.sha256(str(target).encode()).hexdigest()
    spec = importlib.util.spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return name.startswith("test") and callable(getattr(module, name, None))
    except Exception:
        return False
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous


def _ledger_sample(root):
    """独立构造三跳链，故意打乱 ID 与行顺序。"""
    target = root / "tests/codec/test_acceptance_m1.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_accepts(): pass\ndef helper(): pass\ntest_value = 1\n")
    path = "src/qaiji/codec/qasm3.py"
    hashes = [str(i) * 64 for i in range(5)]
    reference = "tests/codec/test_acceptance_m1.py::test_accepts"
    rows = [
        {
            "id": identity,
            "kind": "narrow",
            "surface": "OPENQASM",
            "before": "rejected",
            "after": "accepted",
            "decision": "D6-14",
            "tests_rewritten": [reference],
            "guard_tests": [reference],
            "sources": {path: {"before": hashes[i], "after": hashes[i + 1]}},
        }
        for i, identity in enumerate(("L6-01", "L6-05", "L6-10"))
    ]
    return {
        "origin": {path: hashes[0]},
        "frozen_sources": {path: hashes[3]},
        "ledger": [rows[2], rows[0], rows[1]],
    }


def _l7_sample(root):
    """在三跳链之后接上 L7 形态：同跳组、组后单跳、创建 hop 与 docs 行。"""
    sample = _ledger_sample(root)
    (root / "tests/test_public_api.py").write_text(
        "def test_public_exports_are_the_exact_contract(): pass\n"
        "def test_public_exports_are_the_exact_contract_extra(): pass\n"
    )
    (root / "tests/test_distribution.py").write_text(
        "def test_wheel_contains_py_typed(): pass\n"
        "def test_py_typed_marker_ships_in_package(): pass\n"
    )
    (root / "tests/native").mkdir()
    (root / "tests/native/test_compatibility.py").write_text(
        "def test_docs_rows_preserve_stripped_ast(): pass\n"
    )
    qasm3, init = "src/qaiji/codec/qasm3.py", "src/qaiji/codec/__init__.py"
    typed, docs = "src/qaiji/py.typed", "src/qaiji/core/conventions.py"
    empty = hashlib.sha256(b"").hexdigest()
    guard = "tests/codec/test_acceptance_m1.py::test_accepts"
    group = {
        qasm3: {"before": "3" * 64, "after": "5" * 64},
        init: {"before": "a" * 64, "after": "b" * 64},
    }

    def row(identity, kind, sources, rewritten, guards):
        return {
            "id": identity,
            "kind": kind,
            "surface": "codec",
            "before": "old",
            "after": "new",
            "decision": "D7-1",
            "tests_rewritten": rewritten,
            "guard_tests": guards,
            "sources": json.loads(json.dumps(sources)),
        }

    pin = "tests/test_public_api.py::test_public_exports_are_the_exact_contract"
    sample["ledger"] += [
        *(row(f"L7-0{i}", "extend", group, [pin], [guard]) for i in (1, 2, 3)),
        row("L7-04", "fix", {qasm3: {"before": "5" * 64, "after": "6" * 64}}, [], [guard]),
        row(
            "L7-06",
            "extend",
            {typed: {"before": None, "after": empty}},
            ["tests/test_distribution.py::test_wheel_contains_py_typed"],
            ["tests/test_distribution.py::test_py_typed_marker_ships_in_package"],
        ),
        row(
            "L7-07",
            "docs",
            {docs: {"before": "c" * 64, "after": "d" * 64}},
            ["tests/native/test_compatibility.py::test_docs_rows_preserve_stripped_ast"],
            [],
        ),
    ]
    sample["origin"].update({init: "a" * 64, docs: "c" * 64})
    sample["frozen_sources"].update({qasm3: "6" * 64, init: "b" * 64, typed: empty, docs: "d" * 64})
    return sample


def test_ledger_hash_chain_matches_frozen_sources(tmp_path):
    baseline = json.loads(CASES.read_text())
    assert "origin" in baseline, "ledger origin is missing"
    assert "src/qaiji/codec/qasm3.py" in baseline["origin"], "qasm3 ledger origin is missing"
    assert "ledger" in baseline, "ledger rows are missing"
    assert _ledger_errors(baseline, ROOT) == []
    sample = _ledger_sample(tmp_path)
    assert _ledger_errors(sample, tmp_path) == []
    sample["ledger"].reverse()
    assert _ledger_errors(sample, tmp_path) == []
    second_path = "src/qaiji/codec/another.py"
    sample["origin"][second_path] = "a" * 64
    sample["frozen_sources"][second_path] = "b" * 64
    sample["ledger"][0]["sources"][second_path] = {"before": "a" * 64, "after": "b" * 64}
    assert _ledger_errors(sample, tmp_path) == []
    sample["ledger"] = []
    sample["frozen_sources"] = dict(sample["origin"])
    assert _ledger_errors(sample, tmp_path) == []


def test_ledger_references_resolve_to_test_functions(tmp_path):
    baseline = json.loads(CASES.read_text())
    assert "ledger" in baseline, "ledger rows are missing"
    assert _ledger_errors(baseline, ROOT) == []
    assert _ledger_errors(_ledger_sample(tmp_path), tmp_path) == []
    assert _ledger_test_reference("tests/codec/test_rejection.py::test_for_loop_is_rejected", ROOT)


def test_ledger_narrow_rows_have_acceptance_tests(tmp_path):
    baseline = json.loads(CASES.read_text())
    assert "ledger" in baseline, "ledger rows are missing"
    assert _ledger_errors(baseline, ROOT) == []
    sample = _ledger_sample(tmp_path)
    sample["ledger"][0]["kind"] = "fix"
    sample["ledger"][0]["guard_tests"] = []
    assert _ledger_errors(sample, tmp_path) == []


def test_ledger_rows_are_well_formed(tmp_path):
    baseline = json.loads(CASES.read_text())
    assert "ledger" in baseline, "ledger rows are missing"
    assert _ledger_errors(baseline, ROOT) == []
    assert _ledger_errors(_ledger_sample(tmp_path), tmp_path) == []


# 以下各测试只证接受域的分区；对应规则的拒收形态都在 test_ledger_guards_detect_tampering 中。
def test_ledger_accepts_extend_and_docs_kinds(tmp_path):
    sample = _l7_sample(tmp_path)
    assert {row["kind"] for row in sample["ledger"]} == {"narrow", "fix", "extend", "docs"}
    assert _ledger_errors(sample, tmp_path) == []


def test_extend_row_requires_surface_pin_and_behaviour_guard(tmp_path):
    """钉值与行为守护在改写列表或守护列表中都算引用；两个面钉值都可满足。"""
    sample = _l7_sample(tmp_path)
    for row in sample["ledger"]:
        if row["kind"] == "extend":
            row["tests_rewritten"], row["guard_tests"] = row["guard_tests"], row["tests_rewritten"]
    assert _ledger_errors(sample, tmp_path) == []


def test_docs_row_requires_stripped_ast_guard(tmp_path):
    sample = _l7_sample(tmp_path)
    (docs,) = (row for row in sample["ledger"] if row["kind"] == "docs")
    docs["guard_tests"], docs["tests_rewritten"] = docs["tests_rewritten"], []
    assert _ledger_errors(sample, tmp_path) == []


def test_creation_hop_is_allowed_only_for_new_extend_paths(tmp_path):
    """创建 hop 从无到有；创建之后同一路径仍可接普通跳。"""
    sample = _l7_sample(tmp_path)
    typed = "src/qaiji/py.typed"
    assert typed not in sample["origin"]
    assert _ledger_errors(sample, tmp_path) == []
    later = json.loads(json.dumps(sample["ledger"][-3]))
    assert later["id"] == "L7-04"
    later["id"] = "L7-05"
    later["sources"] = {typed: {"before": sample["frozen_sources"][typed], "after": "e" * 64}}
    sample["ledger"].append(later)
    sample["frozen_sources"][typed] = "e" * 64
    assert _ledger_errors(sample, tmp_path) == []


def test_extend_rows_with_identical_sources_share_one_hop(tmp_path):
    """三行同跳组只占一跳；单行组同样合法。"""
    sample = _l7_sample(tmp_path)
    group = [row for row in sample["ledger"] if row["id"] in {"L7-01", "L7-02", "L7-03"}]
    assert group[0]["sources"] == group[1]["sources"] == group[2]["sources"]
    assert _ledger_errors(sample, tmp_path) == []
    for row in group[1:]:
        sample["ledger"].remove(row)
    assert _ledger_errors(sample, tmp_path) == []


def test_ledger_pending_l7_rows_are_declared():
    """pending 只能是计划内的 L7 行；行落入账本之前必须先移出 pending。"""
    identities = {row["id"] for row in json.loads(CASES.read_text())["ledger"]}
    assert _PENDING_L7 <= {f"L7-{i:02d}" for i in range(1, 9)}
    assert _pending_errors(identities) == []
    for identity in sorted(_PENDING_L7):
        expected = [f"pending ledger ID has a row: {identity}"]
        assert _pending_errors(identities | {identity}) == expected


_GUARDED_HELPERS = (
    "_ledger_errors",
    "_ledger_test_reference",
    "_origin_errors",
    "_pending_errors",
    "_l707_reverse_edits",
    "_strip_bare_strings",
)


def _module_bindings(source):
    """列出模块作用域内每个名字的全部绑定形态。

    顶层无装饰器的 def 记为 ``def``，其余 def/class 记节点类型；函数体与类体是局部作用域，
    只继续检查其中在模块作用域求值的装饰器、默认值与基类，再加上任意深度的 global 声明。
    星号导入记为 ``*``，``globals``/``vars``/``setattr``/``exec``/``eval`` 调用记为 ``<dynamic>``。
    """
    tree = ast.parse(source)
    bindings = {}
    pending = list(tree.body)
    while pending:
        node = pending.pop()
        name, form = None, type(node).__name__
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            if node in tree.body and isinstance(node, ast.FunctionDef) and not node.decorator_list:
                form = "def"
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            name = node.id
        elif isinstance(node, ast.alias):
            name = node.asname or node.name.split(".")[0]
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            name = node.name
        elif isinstance(node, ast.MatchMapping):
            name = node.rest
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"globals", "vars", "setattr", "exec", "eval"}:
                name = "<dynamic>"
        if name:
            bindings.setdefault(name, []).append(form)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            pending.extend(getattr(node, "decorator_list", []))
            pending.extend(getattr(node, "bases", []) + getattr(node, "keywords", []))
            if not isinstance(node, ast.ClassDef):
                pending.extend(node.args.defaults + [d for d in node.args.kw_defaults if d])
        else:
            pending.extend(ast.iter_child_nodes(node))
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            for name in node.names:
                bindings.setdefault(name, []).append("Global")
    return bindings


def _guard_violations(source):
    """未恰好由一条顶层无装饰器 def 绑定的受守护 helper，以及无法静态归属的重绑。"""
    bindings = _module_bindings(source)
    offenders = [name for name in _GUARDED_HELPERS if bindings.get(name) != ["def"]]
    return offenders + [marker for marker in ("*", "<dynamic>") if marker in bindings]


_DEF = "\ndef _pending_errors("  # 带换行：只命中顶层 def 行，不命中字符串字面量
_NESTED = "if True:\n    def _pending_errors(identities):\n        return []\n"


@pytest.mark.parametrize(
    ("old", "new", "appended", "expected"),
    [
        pytest.param("", "", "", [], id="real-file"),
        *(
            pytest.param("", "", source, ["_pending_errors"], id=name)
            for name, source in {
                "duplicate-def": "def _pending_errors(identities):\n    return []\n",
                "assign": "_pending_errors = None\n",
                "annotated": "_pending_errors: object = None\n",
                "augmented": "_pending_errors += ()\n",
                "tuple-target": "_other, _pending_errors = None, None\n",
                "walrus": "(_pending_errors := None)\n",
                "type-alias": "type _pending_errors = None\n",
                "import": "import _pending_errors\n",
                "import-as": "from os import sep as _pending_errors\n",
                "for-target": "for _pending_errors in ():\n    pass\n",
                "with-as": "with open(__file__) as _pending_errors:\n    pass\n",
                "except-as": "try:\n    pass\nexcept OSError as _pending_errors:\n    pass\n",
                "nested-def": "if True:\n    def _pending_errors(identities):\n        return []\n",
                "class": "class _pending_errors:\n    pass\n",
                "match-as": "match None:\n    case _pending_errors:\n        pass\n",
                "match-star": "match None:\n    case [*_pending_errors]:\n        pass\n",
                "match-rest": "match None:\n    case {**_pending_errors}:\n        pass\n",
                "global": "def _rebind():\n    global _pending_errors\n",
                "default-walrus": "def _other(x=(_pending_errors := None)):\n    pass\n",
                "decorator-walrus": "@(_pending_errors := (lambda f: f))\ndef _other():\n    pass\n",
                "base-walrus": "class _Other((_pending_errors := object)):\n    pass\n",
                "lambda-default-walrus": "_other = lambda x=(_pending_errors := None): x\n",
            }.items()
        ),
        pytest.param(_DEF, "\n@(lambda f: f)" + _DEF, "", ["_pending_errors"], id="decorated"),
        pytest.param(_DEF, "\ndef _moved(", _NESTED, ["_pending_errors"], id="moved-into-if"),
        pytest.param("", "", "from os import *\n", ["*"], id="star-import"),
        pytest.param("", "", "globals()['_pending_errors'] = None\n", ["<dynamic>"], id="globals"),
        pytest.param(
            "", "", "setattr(sys, '_pending_errors', None)\n", ["<dynamic>"], id="setattr"
        ),
        pytest.param("", "", "exec('_pending_errors = None')\n", ["<dynamic>"], id="exec"),
    ],
)
def test_guarded_helpers_are_bound_once(old, new, appended, expected):
    """受守护 helper 被同名遮蔽或包装后，变异体改的就不是实际被调用的那份；
    所以每个 helper 必须只由一条顶层无装饰器 def 绑定。每种重绑形态都必须被识别。
    """
    source = Path(__file__).read_text()
    if old:
        assert source.count(old) == 1
        source = source.replace(old, new)
    assert _guard_violations(source + "\n" + appended) == expected


_L7_TAMPERS = (
    "unplanned-l7",
    "extend-without-pin",
    "extend-without-behaviour",
    "extend-pin-twice",
    "extend-pin-prefix",
    "extend-pin-alias-dot",
    "extend-pin-alias-double-slash",
    "extend-pin-alias-parent",
    "docs-without-guard",
    "docs-without-references",
    "create-as-fix",
    "create-unlisted-path",
    "create-origin-path",
    "create-twice",
    "create-end-mismatch",
    "create-missing-before",
    "group-after-differs",
    "group-has-fix",
    "group-not-adjacent",
)


@pytest.mark.parametrize(
    "tamper",
    [
        "first-hop",
        "interrupted",
        "last-hop",
        "fork",
        "orphan",
        "cycle",
        "missing-reference",
        "helper-reference",
        "noncallable-reference",
        "parameter-reference",
        "narrow-without-positive",
        "duplicate-id",
        "unknown-id",
        "unknown-source",
        "missing-field",
        "bad-kind",
        "bad-hash",
        "empty-sources",
        "deleted-first",
        "deleted-middle",
        "deleted-last",
        "past-frozen",
        "disconnected-cycle",
        "empty-origin",
        *_L7_TAMPERS,
    ],
)
def test_ledger_guards_detect_tampering(tmp_path, tamper):
    """R6-13：无跳转路径同时篡改 origin 与 frozen_sources 的哈希无法检出；
    有跳转路径还须同时伪造账本哈希才能蒙混。因此仍须评审提交差异，
    此局限不计作变异被杀。
    """
    sample = _l7_sample(tmp_path) if tamper in _L7_TAMPERS else _ledger_sample(tmp_path)
    path = "src/qaiji/codec/qasm3.py"
    first, middle, last = sample["ledger"][1], sample["ledger"][2], sample["ledger"][0]
    rows = {row["id"]: row for row in sample["ledger"]}
    typed = "src/qaiji/py.typed"
    if tamper == "first-hop":
        first["sources"][path]["before"] = "4" * 64
        expected = f"{path}: first hop does not start at origin"
    elif tamper == "interrupted":
        middle["sources"][path]["before"] = "4" * 64
        expected = f"{path}: interrupted hash chain"
    elif tamper == "last-hop":
        last["sources"][path]["after"] = "4" * 64
        expected = f"{path}: last hop does not match frozen_sources"
    elif tamper == "fork":
        middle["sources"][path]["before"] = "0" * 64
        expected = f"{path}: fork at {'0' * 64}"
    elif tamper == "orphan":
        extra = json.loads(json.dumps(first))
        extra["id"] = "L6-02"
        extra["sources"][path] = {"before": "4" * 64, "after": "5" * 64}
        sample["ledger"].append(extra)
        expected = f"{path}: orphan ledger hops"
    elif tamper == "cycle":
        last["sources"][path]["after"] = "0" * 64
        expected = f"{path}: cycle in hash chain"
    elif tamper in {
        "missing-reference",
        "helper-reference",
        "noncallable-reference",
        "parameter-reference",
    }:
        name = {
            "missing-reference": "test_missing",
            "helper-reference": "helper",
            "noncallable-reference": "test_value",
            "parameter-reference": "test_accepts[stale]",
        }[tamper]
        reference = f"tests/codec/test_acceptance_m1.py::{name}"
        first["tests_rewritten"] = [reference]
        expected = f"L6-01: reference is not a test function: {reference}"
    elif tamper == "narrow-without-positive":
        first["guard_tests"] = []
        expected = "L6-01: narrow row has no acceptance test"
    elif tamper == "duplicate-id":
        middle["id"] = first["id"]
        expected = "duplicate ledger ID: L6-01"
    elif tamper == "unknown-id":
        first["id"] = "L6-11"
        expected = "unplanned ledger ID: L6-11"
    elif tamper == "unknown-source":
        first["sources"]["src/unknown.py"] = first["sources"].pop(path)
        expected = "L6-01: source is not in origin: src/unknown.py"
    elif tamper in {"deleted-first", "deleted-middle", "deleted-last"}:
        selected = {"deleted-first": first, "deleted-middle": middle, "deleted-last": last}[tamper]
        sample["ledger"].remove(selected)
        detail = {
            "deleted-first": "first hop does not start at origin",
            "deleted-middle": "interrupted hash chain",
            "deleted-last": "last hop does not match frozen_sources",
        }[tamper]
        expected = f"{path}: {detail}"
    elif tamper == "past-frozen":
        sample["frozen_sources"][path] = middle["sources"][path]["after"]
        expected = f"{path}: last hop does not match frozen_sources"
    elif tamper == "disconnected-cycle":
        for i, (before, after) in enumerate((("4", "5"), ("5", "4")), 2):
            extra = json.loads(json.dumps(first))
            extra["id"] = f"L6-{i:02d}"
            extra["sources"][path] = {"before": before * 64, "after": after * 64}
            sample["ledger"].append(extra)
        expected = f"{path}: orphan ledger hops"
    elif tamper == "empty-origin":
        sample["origin"] = {}
        sample["ledger"] = []
        expected = "origin must be a nonempty object"
    elif tamper == "unplanned-l7":
        rows["L7-04"]["id"] = "L7-09"
        expected = "unplanned ledger ID: L7-09"
    elif tamper in {"extend-without-pin", "extend-without-behaviour", "extend-pin-twice"}:
        pin = "tests/test_distribution.py::test_wheel_contains_py_typed"
        guard = "tests/test_distribution.py::test_py_typed_marker_ships_in_package"
        rows["L7-06"]["tests_rewritten"], rows["L7-06"]["guard_tests"] = {
            "extend-without-pin": ([], [guard]),
            "extend-without-behaviour": ([pin], []),
            "extend-pin-twice": ([pin], [pin]),
        }[tamper]
        detail = "surface pin" if tamper == "extend-without-pin" else "behaviour guard"
        expected = f"L7-06: extend row has no {detail} test"
    elif tamper == "extend-pin-prefix":
        rows["L7-01"]["tests_rewritten"] = [
            "tests/test_public_api.py::test_public_exports_are_the_exact_contract_extra"
        ]
        expected = "L7-01: extend row has no surface pin test"
    elif tamper.startswith("extend-pin-alias-"):
        # 同一钉值测试换一种路径写法再引用一次，不能冒充行为守护
        pin = "tests/test_distribution.py::test_wheel_contains_py_typed"
        alias = {
            "extend-pin-alias-dot": "./" + pin,
            "extend-pin-alias-double-slash": pin.replace("tests/", "tests//"),
            "extend-pin-alias-parent": pin.replace("tests/", "tests/../tests/"),
        }[tamper]
        rows["L7-06"]["tests_rewritten"], rows["L7-06"]["guard_tests"] = [pin], [alias]
        expected = f"L7-06: reference is not a test function: {alias}"
    elif tamper in {"docs-without-guard", "docs-without-references"}:
        rows["L7-07"]["tests_rewritten"] = (
            ["tests/codec/test_acceptance_m1.py::test_accepts"]
            if tamper == "docs-without-guard"
            else []
        )
        expected = "L7-07: docs row has no stripped-AST guard"
    elif tamper == "create-as-fix":
        rows["L7-06"]["kind"] = "fix"
        expected = f"L7-06: creation hop requires an extend row: {typed}"
    elif tamper == "create-unlisted-path":
        other = "src/qaiji/codec/py.typed"
        rows["L7-06"]["sources"] = {other: rows["L7-06"]["sources"].pop(typed)}
        sample["frozen_sources"][other] = sample["frozen_sources"].pop(typed)
        expected = f"L7-06: path may not be created: {other}"
    elif tamper == "create-origin-path":
        sample["origin"][typed] = sample["frozen_sources"][typed]
        expected = f"L7-06: creation hop for an origin path: {typed}"
    elif tamper == "create-twice":
        again = json.loads(json.dumps(rows["L7-06"]))
        again["id"] = "L7-08"
        sample["ledger"].append(again)
        expected = f"L7-08: creation hop after earlier hops: {typed}"
    elif tamper == "create-end-mismatch":
        sample["frozen_sources"][typed] = "e" * 64
        expected = f"{typed}: last hop does not match frozen_sources"
    elif tamper == "create-missing-before":
        # 缺 before 键不是创建 hop；只有显式的 null 才是
        del rows["L7-06"]["sources"][typed]["before"]
        expected = f"L7-06: source is not in origin: {typed}"
    elif tamper in {"group-after-differs", "group-has-fix", "group-not-adjacent"}:
        if tamper == "group-after-differs":
            rows["L7-02"]["sources"]["src/qaiji/codec/__init__.py"]["after"] = "e" * 64
        elif tamper == "group-has-fix":
            rows["L7-02"]["kind"] = "fix"
        else:
            sample["ledger"].remove(rows["L7-03"])
            sample["ledger"].append(rows["L7-03"])
        expected = f"{path}: fork at {'3' * 64}"
    elif tamper == "missing-field":
        first.pop("decision")
        expected = "L6-01: missing ledger fields: decision"
    elif tamper == "bad-kind":
        first["kind"] = "widen"
        expected = "L6-01: invalid ledger kind: widen"
    elif tamper == "bad-hash":
        first["sources"][path]["after"] = "not-a-sha256"
        expected = f"L6-01: invalid source hash: {path}: after"
    else:
        first["sources"] = {}
        expected = "L6-01: sources must be a nonempty object"
    errors = _ledger_errors(sample, tmp_path)
    assert errors == [expected]


def test_ledger_origin_is_pinned_to_the_qm5_baseline():
    """钉住已发布源文件的初始哈希与允许纳入账本的 8 个路径；每个路径的改值与缺失都须报出。"""
    baseline = json.loads(CASES.read_text())
    origin = baseline["origin"]
    assert "src/qaiji/codec/qasm3.py" in origin
    assert origin["src/qaiji/codec/qasm3.py"] == (
        "231237a1bee5a2a480e90dde0a662fdec6753312f921a6e5d96a3886f63964ac"
    )
    assert _origin_errors(origin) == []
    extra = {**origin, "src/qaiji/py.typed": "0" * 64}
    assert _origin_errors(extra) == ["origin path is not allowed: src/qaiji/py.typed"]
    for path in origin:
        assert _origin_errors({**origin, path: "0" * 64}) == [f"origin hash changed: {path}"]
        missing = {key: value for key, value in origin.items() if key != path}
        assert _origin_errors(missing) == [f"origin path is missing: {path}"]


@pytest.mark.parametrize(
    "tamper", ["last-hop", "orphan", "cycle", "unknown-id", "unknown-source", "empty-origin"]
)
def test_ledger_guards_detect_missing_validation(tmp_path, tamper):
    """逐项隔离拒收条件，删除目标守卫后须接受非法账本。"""
    sample = _ledger_sample(tmp_path)
    path = "src/qaiji/codec/qasm3.py"
    first, last = sample["ledger"][1], sample["ledger"][0]
    if tamper == "last-hop":
        last["sources"][path]["after"] = "4" * 64
        expected = f"{path}: last hop does not match frozen_sources"
    elif tamper == "orphan":
        extra = json.loads(json.dumps(first))
        extra["id"] = "L6-02"
        extra["sources"][path] = {"before": "4" * 64, "after": "5" * 64}
        sample["ledger"].append(extra)
        expected = f"{path}: orphan ledger hops"
    elif tamper == "cycle":
        # 环回到 frozen，使移除拒收且保留终止的变异不能靠末跳检查被杀。
        last["sources"][path]["after"] = sample["origin"][path]
        sample["frozen_sources"][path] = sample["origin"][path]
        expected = f"{path}: cycle in hash chain"
    elif tamper == "unknown-id":
        first["id"] = "L6-11"
        expected = "unplanned ledger ID: L6-11"
    elif tamper == "unknown-source":
        # 保留原链，仅增加未登记路径，避免断链检查替代目标守卫。
        first["sources"]["src/unknown.py"] = dict(first["sources"][path])
        expected = "L6-01: source is not in origin: src/unknown.py"
    else:
        sample["origin"] = {}
        sample["ledger"] = []
        expected = "origin must be a nonempty object"
    errors = _ledger_errors(sample, tmp_path)
    assert errors == [expected]


def test_stdgates_origin_is_pinned_to_the_t2_delivery():
    baseline = json.loads(CASES.read_text())
    assert baseline["origin"]["src/qaiji/codec/_stdgates.py"] == (
        "b1738a3335907d5475279edd952c98a91ffb254193cbeab867700909137fcda7"
    )


def test_ledger_covers_all_planned_rows():
    """账本 ID 必须与「计划 − pending」双向相等。"""
    baseline = json.loads(CASES.read_text())
    planned = {f"L6-{i:02d}" for i in range(1, 11)} | {f"L7-{i:02d}" for i in range(1, 9)}
    assert {row["id"] for row in baseline["ledger"]} == planned - _PENDING_L7


def _l707_reverse_edits():
    """L7-07 的反向编辑表：``(path, line, new_text, old_text)``，new_text 是改写后的整行。"""
    conventions = "src/qaiji/core/conventions.py"
    types = "src/qaiji/core/semantics/types.py"
    return [
        (
            conventions,
            22,
            "证伪状态：已跨库证伪（判据 R0–R4，范围限于光学适配器的门、电路与原生后端层）。",
            "证伪状态：已跨库证伪（QM3，判据 R0–R4，范围限于光学适配器的门、电路与原生后端层）。",
        ),
        (
            conventions,
            38,
            "证伪状态：已跨库证伪（判据 R3a、R3b）。快照事实 XR-RZ、XR-Z，",
            "证伪状态：已跨库证伪（QM3，判据 R3a、R3b）。快照事实 XR-RZ、XR-Z，",
        ),
        (
            "src/qaiji/core/semantics/dataflow.py",
            45,
            "    之前，边依然会连上 —— 顺序与因果属于 L2 调度层的议题，不由语义层判定。",
            "    之前，边依然会连上 —— 顺序与因果是 QM5 的调度议题，不是 QM2 的。",
        ),
        (
            "src/qaiji/core/semantics/handle.py",
            71,
            '    """下游坍缩阶段消费的唯一对象：摘要、哈希与状态。',
            '    """QM6 坍缩阶段消费的唯一对象：摘要、哈希与状态。',
        ),
        (
            "src/qaiji/core/semantics/summary.py",
            97,
            "        status_label: 取自 ``HandleStatus`` 的值（本函数不做校验，按原样写入的",
            "        status_label: 取自 ``HandleStatus`` 的值（T3.4；在该枚举落地前是未经校验的",
        ),
        (
            types,
            33,
            "    只有 ``EXACT`` 与 ``UP_TO_PHASE`` 是可判定的；``UP_TO_LOCAL`` 与",
            "    本切片中只有 ``EXACT`` 与 ``UP_TO_PHASE`` 是可判定的；``UP_TO_LOCAL`` 与",
        ),
        (
            types,
            55,
            "    ``FPROC_PLACEHOLDER`` 没有任何生产路径 —— 它只是为多条件前馈预留",
            "    ``FPROC_PLACEHOLDER`` 在本切片中没有任何生产路径 —— 它只是为多条件前馈预留",
        ),
    ]


def _strip_bare_strings(tree):
    """删除每个语句体中的裸字符串表达式语句，原地修改并返回该树。

    不只 docstring：``conventions.py`` 的属性说明字符串跟在赋值之后，也是裸字符串语句。
    """
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            node.body = [
                statement
                for statement in body
                if not (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                )
            ]
    return tree


def test_docs_rows_preserve_stripped_ast():
    """L7-07 只改措辞：反向编辑还原出 hop 的 before 字节，且剥去裸字符串后 AST 不变。

    当前文件已离开这一跳的 after 字节时，账本中该路径必须另有后续 hop。
    """
    kept = "def f():\n    g()\n    ...\n    1\n"
    stripped_kept = ast.dump(_strip_bare_strings(ast.parse('"""doc"""\n' + kept)))
    assert stripped_kept == ast.dump(ast.parse(kept)), "_strip_bare_strings removed code"
    ledger = json.loads(CASES.read_text())["ledger"]
    # L7-07 落行时已存在的行：重排它们不能充当「后续 hop」
    landed = {f"L6-{i:02d}" for i in range(1, 11)} | {"L7-06", "L7-07"}
    index = next((i for i, row in enumerate(ledger) if row["id"] == "L7-07"), None)
    hops = ledger[index]["sources"] if index is not None else {}
    edits = _l707_reverse_edits()
    for path in dict.fromkeys(edit[0] for edit in edits):
        text = (ROOT / path).read_bytes().decode()
        hop = hops.get(path)
        if hop is not None and hashlib.sha256(text.encode()).hexdigest() != hop["after"]:
            later = [
                row["id"]
                for row in ledger[index + 1 :]
                if path in row["sources"] and row["id"] not in landed
            ]
            assert later, f"{path}: changed after its L7-07 hop without a later hop"
            continue
        lines = text.split("\n")
        for _, line, new_text, old_text in (edit for edit in edits if edit[0] == path):
            assert lines[line - 1] == new_text, f"{path}:{line} is not the target text"
            lines[line - 1] = old_text
        restored = "\n".join(lines)
        assert hop is not None, f"L7-07 has no hop for {path}"
        restored_sha = hashlib.sha256(restored.encode()).hexdigest()
        assert restored_sha == hop["before"], f"{path}: reverse edits do not restore the hop bytes"
        stripped = [ast.dump(_strip_bare_strings(ast.parse(source))) for source in (text, restored)]
        assert stripped[0] == stripped[1], f"{path}: code changed beyond bare strings"
    assert set(hops) == {edit[0] for edit in edits}
