# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查受检机制的逐项负控收据。"""

from __future__ import annotations

import ast
import bisect
import copy
import importlib
import json
import math
import re
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from _p_analytic_reference import decay_density, decay_exponent, drive_angle, x_density, y_density
from _p_fixtures import (
    Y,
    asymmetric_request,
    consumer,
    damping_request,
    drive_request,
    operator,
    payload,
    product_request,
    request,
    run,
    states,
)
from _p_matrix_ops import ConsumerError, fvalues, scale

from qaiji.core.physical.diagnostics import CheckBudget, PContractError
from qaiji.core.physical.model import Problem, State

DATA = Path(__file__).with_name("data")
REQUIRED = {
    "tensor assembly": ("AC-02/factor-reversal",),
    "operator assembly": (
        "AC-03/reverse-Y",
        "AC-03/wrong-Hamiltonian-sign",
        "AC-15/A-only-target-change",
    ),
    "unit interpretation": ("AC-03/extra-2pi",),
    "dissipator adaptation": ("AC-04/rate-as-amplitude",),
    "time interpretation": (
        "AC-05/left-boundary",
        "AC-05/snapped-time-label",
        "AC-05/left-edge-state-with-original-label",
        "AC-05/right-edge-state-with-original-label",
        "AC-05/first-rate-extended",
    ),
    "codec": (
        "AC-08/drop-imaginary",
        "AC-08/replace-axis",
        "AC-08/accept-unknown-key",
        "AC-08/accept-duplicate-key",
    ),
}
FORMS = (
    "boundary-plus-minus-one",
    "regex-quantifier-character-class",
    "sort-reverse-deduplicate",
    "missing-inner-guard",
    "implicit-default-fill",
    "tighten-permitted-reader",
    "mutable-wrapper",
)


@dataclass(frozen=True)
class Case:
    """标识一个机制、子项与受检实现。"""

    mechanism: str
    child: str
    implementation: str

    @property
    def key(self):
        return f"{self.child}/{self.implementation}"


def cases():
    """返回全部要求实例。

    Returns:
        机制子项与实现的固定组合。
    """
    return tuple(
        Case(mechanism, child, implementation)
        for mechanism, children in REQUIRED.items()
        for child in children
        for implementation in (
            ("codec",)
            if mechanism == "codec"
            else ("a",)
            if child == "AC-15/A-only-target-change"
            else ("a", "b")
        )
    ) + tuple(Case("implementation form", f"FORM/{form}", "form") for form in FORMS)


@dataclass
class Probe:
    """保存受检入口、固定参考与单项变异。"""

    module: object
    target: str
    observe: object
    perturb: object
    expected: object
    assertion: str
    input_bytes: bytes
    approximate: bool = True


class TargetMismatch(AssertionError):
    """表示指定判据拒绝了受检输出。"""


_EXECUTED = object()


class _Receipt(dict):
    """收据保留实际运行结果。普通字典不能替代运行收据。"""

    def __init__(self, data, token):
        if token is not _EXECUTED:
            raise ValueError("Receipt requires an executed probe.")
        super().__init__(data)
        self.snapshot = tuple(data.items())

    def __deepcopy__(self, memo):
        result = _Receipt(dict(self.snapshot), _EXECUTED)
        result.update(copy.deepcopy(dict(self), memo))
        return result


def _matches(actual, expected, approximate):
    if isinstance(expected, (list, tuple)):
        return (
            isinstance(actual, (list, tuple))
            and len(actual) == len(expected)
            and all(_matches(a, b, approximate) for a, b in zip(actual, expected, strict=True))
        )
    if approximate and isinstance(expected, (int, float, complex)):
        return abs(actual - expected) <= 1e-10
    return actual == expected


def _check(probe, actual):
    if not _matches(actual, probe.expected, probe.approximate):
        raise TargetMismatch(probe.assertion)


def _assembly_probe(case):
    module = consumer(case.implementation)
    req = asymmetric_request()
    expected = [[complex(row == (col + 3) % 6) for col in range(6)] for row in range(6)]

    def perturb(original, problem, op):
        if case.child.endswith("factor-reversal"):
            return original(
                replace(problem, tensor_order=tuple(reversed(problem.tensor_order))), op
            )
        return original(problem, operator([[0, 1, 0], [1, 0, 0], [0, 0, 1]], site="b"))

    def observe():
        # B 是 A 专属变异的独立正控。
        if case.child == "AC-15/A-only-target-change":
            other = consumer("b").assemble(req.problem, req.problem.h0)
            if not _matches(other, expected, True):
                raise RuntimeError("Unmodified consumer B changed.")
        return module.assemble(req.problem, req.problem.h0)

    return Probe(
        module, "assemble", observe, perturb, expected, "tensor-physical-values", payload(req)
    )


def _dynamics_probe(case):
    module = consumer(case.implementation)
    variant = case.child.split("/", 1)[1]
    if variant == "rate-as-amplitude":
        req, expected, target = damping_request(), decay_density(1), "signal_value"

        def perturb(original, signal, edges, time):
            value = original(signal, edges, time)
            return value * value if signal.unit == "1/ns" else value

    else:
        req, expected = request(h0=operator(Y, coefficient=0.2)), y_density(0.2)
        target = {
            "extra-2pi": "hamiltonian",
            "reverse-Y": "assemble",
            "wrong-Hamiltonian-sign": "generator",
        }[variant]

        def perturb(original, *args):
            result = original(*args)
            if variant == "reverse-Y":
                return [[value.conjugate() for value in row] for row in result]
            return scale(result, 2 * math.pi if variant == "extra-2pi" else -1)

    return Probe(
        module,
        target,
        lambda: states(run(case.implementation, req))[-1],
        perturb,
        expected,
        "evolved-physical-values",
        payload(req),
    )


def _time_probe(case):
    module = consumer(case.implementation)
    variant = case.child.split("/", 1)[1]
    req = damping_request(sampled=True) if variant == "first-rate-extended" else drive_request()
    edges = fvalues(req.problem.signal_edges)
    times = fvalues(req.output_times)
    target, approximate = "signal_value", False
    if variant == "left-boundary":
        expected = 0.4

        def observe():
            return module.signal_value(req.problem.drives[0].signal, edges, 1)

        def perturb(original, signal, bounds, time):
            if signal.kind != "zoh":
                return original(signal, bounds, time)
            return fvalues(signal.values)[max(0, bisect.bisect_left(bounds, time) - 1)]

    elif variant == "snapped-time-label":
        target, expected = "output_times", times

        def observe():
            return fvalues(run(case.implementation, req).output_times)

        def perturb(original, value):
            return [edges[max(0, bisect.bisect_right(edges, t) - 1)] for t in original(value)]

    else:
        approximate = True
        expected = [
            decay_density(decay_exponent(t))
            if variant == "first-rate-extended"
            else x_density(drive_angle(t))
            for t in times
        ]

        def observe():
            return states(run(case.implementation, req))

        if variant == "first-rate-extended":

            def perturb(original, signal, bounds, time):
                return (
                    fvalues(signal.values)[0]
                    if signal.kind == "zoh"
                    else original(signal, bounds, time)
                )

        else:
            target = "state_time"

            def perturb(original, problem, time):
                if variant.startswith("right"):
                    return edges[min(len(edges) - 1, bisect.bisect_left(edges, time))]
                return edges[max(0, bisect.bisect_right(edges, time) - 1)]

    return Probe(module, target, observe, perturb, expected, variant, payload(req), approximate)


def _codec_probe(case):
    module = importlib.import_module("qaiji.core.physical.codec")
    doc = json.loads((DATA / "schema-fields.json").read_text())["examples"]["problem"]
    raw = json.dumps(doc, separators=(",", ":")).encode()
    variant = case.child.split("/", 1)[1]
    if variant == "drop-imaginary":
        target, expected = "_decode", 0.5 - 0.25j

        def perturb(original, value, spec, path, ctx):
            result = original(value, spec, path, ctx)
            return complex(result.real) if spec == "c128" else result

        def observe():
            return module.load_problem(raw).h0.terms[0].coefficient

    elif variant == "replace-axis":
        target, expected = "_decode_record", ("b", "a")

        def perturb(original, value, cls, path, ctx):
            result = original(value, cls, path, ctx)
            return (
                replace(result, tensor_order=tuple(reversed(result.tensor_order)))
                if cls is Problem
                else result
            )

        def observe():
            return module.load_problem(raw).tensor_order

    else:
        if variant == "accept-unknown-key":
            doc["extra"] = None
            raw = json.dumps(doc).encode()
            target, expected = "_keys", ("KEYS", "")

            def perturb(original, value, declared, path, ctx):
                if path == "":
                    return None
                return original(value, declared, path, ctx)

        else:
            raw = b'{"schema":"qaiji.p.problem/1.0",' + raw[1:]
            target, expected = "_materialize", ("DUPLICATE", "/schema")

            def perturb(original, value, path, ctx):
                if path == "" and isinstance(value, module._Pairs):
                    value = module._Pairs(list(dict(value.items).items()))
                return original(value, path, ctx)

        def observe():
            try:
                module.load_problem(raw)
            except PContractError as error:
                diagnostic = error.diagnostics[0]
                return diagnostic.code, diagnostic.path
            return None

    return Probe(module, target, observe, perturb, expected, variant, raw, False)


def _form_probe(case):
    variant = case.child.split("/", 1)[1]
    if variant == "sort-reverse-deduplicate":
        return _codec_probe(Case("codec", "AC-08/replace-axis", "codec"))
    if variant == "mutable-wrapper":
        module = importlib.import_module("qaiji.core.physical.arrays")

        def observe():
            source = bytearray(8)
            array = module.ArrayData(dtype="f64le", shape=(1,), data=source)
            source[0] = 1
            return bytes(array.data)

        return Probe(
            module,
            "_buffer",
            observe,
            lambda original, value, path: value,
            bytes(8),
            "buffer-copy",
            bytes(8),
            False,
        )
    if variant == "implicit-default-fill":
        module, good = consumer("a"), product_request()
        problem = replace(
            good.problem,
            initial_state=State(
                kind="product", frame="lab", factors=good.problem.initial_state.factors[:1]
            ),
        )

        def observe():
            try:
                module.initial_density(problem)
            except ConsumerError as error:
                return error.category, error.code
            return None

        def perturb(original, value):
            return original(
                replace(
                    value,
                    initial_state=State(
                        kind="product",
                        frame="lab",
                        factors=(
                            *value.initial_state.factors,
                            good.problem.initial_state.factors[1],
                        ),
                    ),
                )
            )

        return Probe(
            module,
            "initial_density",
            observe,
            perturb,
            ("INVALID_REQUEST", "PRODUCT_COVERAGE"),
            variant,
            payload(replace(good, problem=problem)),
            False,
        )
    module = importlib.import_module("qaiji.core.physical.codec")
    doc = json.loads((DATA / "schema-fields.json").read_text())["examples"]["problem"]
    budget = CheckBudget()
    if variant == "boundary-plus-minus-one":
        target, patched = "limit", module._Context
        expected = "accepted"

        def perturb(original, ctx, resource, required, limit, code):
            return original(ctx, resource, required + (resource == "max_wire_bytes"), limit, code)

    elif variant == "regex-quantifier-character-class":
        target, patched = "_f64", module
        doc["drives"][0]["signal"]["value"] = "800000000000000"
        expected = ("BINARY64", "/drives/0/signal/value")

        def perturb(original, value, path, ctx):
            if isinstance(value, str) and len(value) == 15:
                value += "0"
            return original(value, path, ctx)

    elif variant == "missing-inner-guard":
        target, patched = "_keys", module
        doc["h0"]["terms"][0]["extra"] = None
        expected = ("KEYS", "/h0/terms/0")

        def perturb(original, value, declared, path, ctx):
            return None if path == "/h0/terms/0" else original(value, declared, path, ctx)

    else:
        target, patched, expected = "_parse", module, "accepted"

        def perturb(original, data, ctx):
            if data.startswith(b" "):
                ctx.fail("JSON", "", "Unexpected whitespace.")
            return original(data, ctx)

    raw = json.dumps(doc).encode()
    if variant == "boundary-plus-minus-one":
        budget = CheckBudget(max_wire_bytes=len(raw))
    if variant == "tighten-permitted-reader":
        raw = b" " + raw

    def observe():
        try:
            module.load_problem(raw, budget=budget)
        except PContractError as error:
            diagnostic = error.diagnostics[0]
            return diagnostic.code, diagnostic.path
        return "accepted"

    return Probe(patched, target, observe, perturb, expected, variant, raw, False)


def _probe(case):
    if case.mechanism == "implementation form":
        return _form_probe(case)
    if case.mechanism == "codec":
        return _codec_probe(case)
    if case.mechanism == "time interpretation":
        return _time_probe(case)
    if case.child in ("AC-02/factor-reversal", "AC-15/A-only-target-change"):
        return _assembly_probe(case)
    return _dynamics_probe(case)


def exercise(case, monkeypatch):
    """检查正控、缺陷与恢复。

    Args:
        case: 固定的机制实例。
        monkeypatch: pytest 的替换夹具。

    Returns:
        仅在四个阶段通过后返回运行收据。

    Raises:
        AssertionError: 目标判据未拒绝缺陷。
    """
    probe = _probe(case)
    original = getattr(probe.module, probe.target)
    digest = sha256(probe.input_bytes).hexdigest()
    reference = repr(probe.expected)
    active, calls = False, []

    def wrapper(*args, **kwargs):
        calls.append(active)
        return probe.perturb(original, *args, **kwargs) if active else original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(probe.module, probe.target, wrapper)
        _check(probe, probe.observe())
        assert calls and not any(calls), "baseline did not reach mechanism"
        calls.clear()
        active = True
        actual = probe.observe()
        assert calls and all(calls), "mutation did not reach mechanism"
        try:
            _check(probe, actual)
        except TargetMismatch as rejection:
            assert str(rejection) == probe.assertion
        else:
            raise AssertionError(f"mutation survived: {case.key}")
        # 只关闭目标断言，受检路径须正常返回。
        unguarded = probe.observe()
        assert _matches(actual, unguarded, probe.approximate), "unstable mutation output"
        active = False
        calls.clear()
        _check(probe, probe.observe())
        assert calls and not any(calls), "restored wrapper did not reach mechanism"
    assert getattr(probe.module, probe.target) is original
    _check(probe, probe.observe())
    assert sha256(probe.input_bytes).hexdigest() == digest
    assert repr(probe.expected) == reference
    return _Receipt(
        dict(
            child=case.child,
            mechanism=case.mechanism,
            implementation=case.implementation,
            input_sha256=digest,
            target=f"{probe.module.__name__}.{probe.target}",
            assertion=probe.assertion,
            baseline=True,
            injected="designated-assertion",
            reason=probe.assertion,
            unguarded=True,
            restored=True,
            exit_code=0,
            node=f"tests/physical/test_six_internal_mutations.py::test_p_six_internal_mutations[{case.key}]",
        ),
        _EXECUTED,
    )


def required_from_feature():
    """从公开 Gherkin 读取机制标签。"""
    text = (DATA / "acceptance.feature").read_text()
    section = text.split("Scenario: AC-16 ", 1)[1].split("Scenario:", 1)[0]
    rows = [line.strip().strip("|").split("|") for line in section.splitlines() if "|" in line]
    return {row[0].strip() for row in rows[1:]}


def check_inventory(inventory, receipts):
    """要求冻结集合与实际运行集合完全相等。

    Args:
        inventory: 公开负控清单。
        receipts: 本次逐项运行的收据。

    Raises:
        AssertionError: 清单缺项、错标或伪报。
    """
    message = "mutation inventory mismatch"
    assert set(inventory["required_six"]) == required_from_feature() == set(REQUIRED), message
    assert {k: tuple(v) for k, v in inventory["required_six"].items()} == REQUIRED, message
    assert {row[0] for row in inventory["implementation_forms"]} == set(FORMS), message
    children = [row["id"] for row in inventory["children"]]
    assert len(children) == len(set(children)), message
    assert {child for values in REQUIRED.values() for child in values} <= set(children), message
    expected = {(c.child, c.mechanism, c.implementation) for c in cases()}
    actual = {(r["child"], r["mechanism"], r["implementation"]) for r in receipts}
    assert len(receipts) == len(actual) and actual == expected, message
    declared = {(r["child"], r["mechanism"], r["implementation"]) for r in inventory["instances"]}
    assert len(inventory["instances"]) == len(declared) and declared == expected, message
    bindings = {(r["child"], r["implementation"]): r for r in inventory["instances"]}
    probes = {(c.child, c.implementation): _probe(c) for c in cases()}
    for receipt in receipts:
        assert isinstance(receipt, _Receipt) and dict(receipt.snapshot) == receipt, message
        probe = probes[receipt["child"], receipt["implementation"]]
        assert receipt["baseline"] is True and receipt["restored"] is True, message
        assert receipt["unguarded"] is True and receipt["exit_code"] == 0, message
        assert receipt["injected"] == "designated-assertion", message
        assert receipt["assertion"] == receipt["reason"] == probe.assertion, message
        assert receipt["target"] == f"{probe.module.__name__}.{probe.target}", message
        assert receipt["input_sha256"] == sha256(probe.input_bytes).hexdigest(), message
        binding = bindings[receipt["child"], receipt["implementation"]]
        for field in ("node", "target", "assertion"):
            assert receipt[field] == binding[field], message
        key = f"{receipt['child']}/{receipt['implementation']}"
        assert (
            receipt["node"]
            == f"tests/physical/test_six_internal_mutations.py::test_p_six_internal_mutations[{key}]"
        ), message


def check_acceptance_map(mapping, inventory, collected=()):
    """检查公开场景、子项与测试节点的对应关系。"""
    message = "acceptance map mismatch"
    feature = (DATA / "acceptance.feature").read_text()
    required = set(re.findall(r"Scenario(?: Outline)?: (AC-\d+)", feature))
    assert len(mapping) == len(required) and {row["ac"] for row in mapping} == required, message
    catalogue = {child["id"]: child for child in inventory["children"]}
    mapped = [child for row in mapping for child in row["children"]]
    assert len(mapped) == len(set(mapped)) and set(mapped) == set(catalogue), message
    root = DATA.parents[2]
    for child in catalogue.values():
        assert child["nodes"], message
        for node in child["nodes"]:
            assert node.split("[")[0] == child["entry"], message
            if any(n.startswith(child["entry"].split("::")[0] + "::") for n in collected):
                assert node in collected, message
    for row in mapping:
        assert row["status"] == "planned", message
        assert set(row["children"]) == {c for c in catalogue if c.startswith(row["ac"] + "/")}, (
            message
        )
        path = root / row["test_file"]
        assert path.is_file(), message
        assert row["nodes"] and len(row["nodes"]) == len(set(row["nodes"])), message
        entries = {f"{row['test_file']}::{row[key]}" for key in ("positive", "negative")}
        assert {node.split("[")[0] for node in row["nodes"]} == entries, message
        supporting = row["support_nodes"]
        assert not set(supporting) & set(row["nodes"]), message
        assert len(supporting) == len(set(supporting)), message
        for node in row["nodes"] + supporting:
            source = root / node.split("::")[0]
            assert source.is_file(), message
            functions = {
                item.name
                for item in ast.parse(source.read_text()).body
                if isinstance(item, ast.FunctionDef)
            }
            assert node.split("::")[1].split("[")[0] in functions, message
        declared_files = {node.split("::")[0] for node in row["nodes"] + supporting}
        for filename in declared_files:
            actual = {node for node in collected if node.split("::")[0] == filename}
            if actual:
                expected = {
                    node for node in row["nodes"] + supporting if node.split("::")[0] == filename
                }
                assert expected == actual, message


def damage_inventory(inventory, receipts, variant):
    """只修改一个集合条件。"""
    inventory, receipts = copy.deepcopy(inventory), copy.deepcopy(receipts)
    if variant == "remove-family":
        del inventory["required_six"]["codec"]
    elif variant == "rename-family":
        inventory["required_six"]["encoder"] = inventory["required_six"].pop("codec")
    elif variant == "skip-child":
        receipts = [row for row in receipts if row["child"] != "AC-03/reverse-Y"]
    elif variant == "wrong-assertion-counted-as-kill":
        receipts[0]["assertion"] = receipts[0]["reason"] = "unrelated-guard"
    elif variant == "fake-kill-record":
        receipts[0] = dict(receipts[0])
    elif variant == "extra-child":
        receipts.append(dict(receipts[0], child="AC-02/fabricated"))
    elif variant == "duplicate-child":
        receipts.append(dict(receipts[0]))
    elif variant in ("import-error", "uncollected", "skip", "xfail"):
        receipts[0]["injected"] = variant
    elif variant == "remove-form":
        inventory["implementation_forms"].pop()
    elif variant == "remove-catalogue-child":
        inventory["children"] = [
            c for c in inventory["children"] if c["id"] != "AC-02/factor-reversal"
        ]
    else:
        raise ValueError("Unknown inventory mutation.")
    return inventory, receipts
