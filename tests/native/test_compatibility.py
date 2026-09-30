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
    planned = {f"L6-{i:02d}" for i in range(1, 11)}
    seen = set()
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
        if row["kind"] not in ("narrow", "fix"):
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
            if path not in origin:
                return [f"{identity}: source is not in origin: {path}"]
            for side in ("before", "after"):
                if not isinstance(hop, dict) or not _ledger_sha256(hop.get(side)):
                    return [f"{identity}: invalid source hash: {path}: {side}"]
    for path, initial in origin.items():
        if path not in frozen:
            return [f"{path}: origin path is not frozen"]
        if not _ledger_sha256(initial) or not _ledger_sha256(frozen[path]):
            return [f"{path}: invalid origin or frozen hash"]
        hops = [row["sources"][path] for row in ledger if path in row["sources"]]
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
    for row in ledger:
        identity = row["id"]
        for reference in row["tests_rewritten"] + row["guard_tests"]:
            if not _ledger_test_reference(reference, root):
                return [f"{identity}: reference is not a test function: {reference}"]
        if row["kind"] == "narrow" and not any(
            ref.startswith("tests/codec/test_acceptance_m1.py::") for ref in row["guard_tests"]
        ):
            return [f"{identity}: narrow row has no acceptance test"]
    return []


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
    ],
)
def test_ledger_guards_detect_tampering(tmp_path, tamper):
    """R6-13：无跳转路径同时篡改 origin 与 frozen_sources 的哈希无法检出；
    有跳转路径还须同时伪造账本哈希才能蒙混。因此仍须评审提交差异，
    此局限不计作变异被杀。
    """
    sample = _ledger_sample(tmp_path)
    path = "src/qaiji/codec/qasm3.py"
    first, middle, last = sample["ledger"][1], sample["ledger"][2], sample["ledger"][0]
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
    """钉住已发布源文件的初始哈希与允许纳入账本的路径集合。"""
    baseline = json.loads(CASES.read_text())
    origin = baseline["origin"]
    assert "src/qaiji/codec/qasm3.py" in origin
    assert origin["src/qaiji/codec/qasm3.py"] == (
        "231237a1bee5a2a480e90dde0a662fdec6753312f921a6e5d96a3886f63964ac"
    )
    assert set(origin) <= {"src/qaiji/codec/qasm3.py", "src/qaiji/codec/_stdgates.py"}


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
    """账本 ID 必须与十项合同双向相等。"""
    baseline = json.loads(CASES.read_text())
    assert {row["id"] for row in baseline["ledger"]} == {
        "L6-01",
        "L6-02",
        "L6-03",
        "L6-04",
        "L6-05",
        "L6-06",
        "L6-07",
        "L6-08",
        "L6-09",
        "L6-10",
    }
