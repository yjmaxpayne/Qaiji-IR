# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""冻结验收资料与旧契约基线的完整性检查。"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from qaiji.core import (
    Circuit,
    ClassicalBit,
    ClassicalRegister,
    Conditional,
    Gate,
    GateType,
    Measure,
)
from qaiji.core.program import compute_kernel_ref

DATA_DIR = Path(__file__).resolve().with_name("data")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_NAMES = (
    "acceptance.feature",
    "public-api.json",
    "canonical-vectors.json",
    "bath-fixture.json",
)
EXPECTED_FIXTURE_SHA256 = {
    "acceptance.feature": "6e88c71ace53cb72dc527cd423be57f9b815768296f6afb7ae73d3e1d7cb0ce6",
    "public-api.json": "bd1629d30a29c7e12424cd26e86fca7a8aa687fd155df64062c05facb2210d6d",
    "canonical-vectors.json": "756a1dbc4e2f437ae2eb80f2a1a4a09b4674e5fe099829b220b5118e6febb8d8",
    "bath-fixture.json": "b61faff8ab45144c07e1351255a8a40adbd8d244f7852a0183531e284091fa8a",
}
EXPECTED_FIXTURE_BYTES = {
    "acceptance.feature": 16359,
    "public-api.json": 2325,
    "canonical-vectors.json": 6431,
    "bath-fixture.json": 1829,
}
EXPECTED_VECTOR_REVISION = 2
EXPECTED_PUBLIC_MODULES = (
    "qaiji",
    "qaiji.core",
    "qaiji.codec",
    "qaiji.core.semantics",
    "qaiji.core.program",
    "qaiji.core.native",
    "qaiji.core.program_native",
)
EXPECTED_SCHEMA_VERSIONS = {
    "qaiji.IR_SCHEMA_VERSION": "qaiji.ir.v0",
    "qaiji.core.semantics.SUMMARY_SCHEMA_VERSION": "qaiji.semantic_summary.v0",
    "qaiji.core.program.PROGRAM_SCHEMA_VERSION": "qaiji.program.v0",
    "qaiji.core.native.NATIVE_SCHEDULE_SCHEMA_VERSION": "qaiji.native_schedule.v0",
}
SCALAR_VECTORS = {
    "positive_zero": "0000000000000000",
    "negative_zero": "8000000000000000",
    "one": "3ff0000000000000",
    "min_subnormal": "0000000000000001",
}
PROBLEM_SCHEMA = "qaiji.p.problem/1.0"
REQUEST_SCHEMA = "qaiji.p.request/1.0"
BATH_NAMESPACE = "org.qaiji.fixtures.bath-correlation"
BATH_CONTENT_TYPE = "application/vnd.qaiji.p.opaque+json"
ABSOLUTE_PATH_MARKERS = ("/home/", "/Users/", "/root/", "\\\\Users\\\\", "file://")


class FixtureIntegrityError(ValueError):
    """冻结资料违反其公开契约。"""


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise FixtureIntegrityError(label)


def _load_bytes(name: str) -> bytes:
    return (DATA_DIR / name).read_bytes()


def _load_json(name: str) -> dict[str, Any]:
    value = json.loads(_load_bytes(name).decode("utf-8"))
    _require(isinstance(value, dict), f"{name}.object")
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _identity(domain: str, canonical_text: str) -> str:
    digest = hashlib.sha256(
        domain.encode("utf-8") + b"\x00" + canonical_text.encode("utf-8")
    ).hexdigest()
    return "sha256:" + digest


def _check_fixture_bytes(name: str, data: bytes) -> None:
    _require(name in EXPECTED_FIXTURE_SHA256, f"{name}.known")
    _require(len(data) == EXPECTED_FIXTURE_BYTES[name], f"{name}.bytes")
    actual = hashlib.sha256(data).hexdigest()
    _require(actual == EXPECTED_FIXTURE_SHA256[name], f"{name}.sha256")


def _sha256_path(path: str) -> str:
    return hashlib.sha256((REPOSITORY_ROOT / path).read_bytes()).hexdigest()


def _resolve_qualified(qualified: str) -> Any:
    module_name, attribute = qualified.rsplit(".", 1)
    return getattr(importlib.import_module(module_name), attribute)


def _assert_no_absolute_paths(name: str, text: str) -> None:
    for marker in ABSOLUTE_PATH_MARKERS:
        _require(marker not in text, f"{name}.absolute_path")


def _parse_canonical_json(label: str, text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise FixtureIntegrityError(label) from error
    _require(isinstance(value, dict), label)
    return value


def _validate_identity_section(section: str, item: dict[str, Any]) -> None:
    problem_text = item.get("problem_bytes")
    request_text = item.get("request_bytes")
    _require(isinstance(problem_text, str), f"{section}.problem_bytes")
    _require(isinstance(request_text, str), f"{section}.request_bytes")
    problem = _parse_canonical_json(f"{section}.problem_bytes", problem_text)
    request = _parse_canonical_json(f"{section}.request_bytes", request_text)
    _require(problem.get("schema") == PROBLEM_SCHEMA, f"{section}.problem.schema")
    _require(request.get("schema") == REQUEST_SCHEMA, f"{section}.request.schema")
    _require(request.get("problem") == problem, f"{section}.request_problem")
    _require(_canonical_json(problem) == problem_text, f"{section}.canonical_problem_bytes")
    _require(_canonical_json(request) == request_text, f"{section}.canonical_request_bytes")
    _require(
        item.get("problem_id") == _identity(PROBLEM_SCHEMA, problem_text),
        f"{section}.problem_id",
    )
    _require(
        item.get("request_id") == _identity(REQUEST_SCHEMA, request_text),
        f"{section}.request_id",
    )


def _validate_canonical_vectors(payload: dict[str, Any]) -> None:
    _require(payload.get("vector_revision") == EXPECTED_VECTOR_REVISION, "vector_revision")
    scalars = payload.get("scalar_vectors")
    _require(isinstance(scalars, dict), "scalar_vectors")
    for key, expected in SCALAR_VECTORS.items():
        _require(scalars.get(key) == expected, f"scalar_vectors.{key}")
    _require(set(scalars) == set(SCALAR_VECTORS), "scalar_vectors.keys")
    for section in ("baseline", "bath"):
        item = payload.get(section)
        _require(isinstance(item, dict), section)
        _validate_identity_section(section, item)
    baseline_problem = _parse_canonical_json(
        "baseline.problem_bytes", payload["baseline"]["problem_bytes"]
    )
    bath_problem = _parse_canonical_json("bath.problem_bytes", payload["bath"]["problem_bytes"])
    _require(baseline_problem.get("extensions") == [], "baseline.extensions")
    extensions = bath_problem.get("extensions")
    _require(isinstance(extensions, list) and len(extensions) == 1, "bath.extensions.length")
    _require(baseline_problem != bath_problem, "baseline.bath_problem")


def _validate_public_api(payload: dict[str, Any]) -> None:
    _require(payload.get("module") == "qaiji.core.physical", "public-api.module")
    _require(payload.get("status") == "planned", "public-api.status")
    types = payload.get("types")
    functions = payload.get("functions")
    exports = payload.get("exports")
    _require(isinstance(types, list), "public-api.types")
    _require(isinstance(functions, list), "public-api.functions")
    _require(isinstance(exports, list), "public-api.exports")
    _require(all(isinstance(name, str) for name in types), "public-api.types.item")
    _require(all(isinstance(name, str) for name in functions), "public-api.functions.item")
    _require(types == sorted(types), "public-api.types_order")
    _require(functions == sorted(functions), "public-api.functions_order")
    _require(len(types) == len(set(types)), "public-api.types_unique")
    _require(len(functions) == len(set(functions)), "public-api.functions_unique")
    _require(exports == types + functions, "public-api.exports_order")
    _require(len(exports) == len(set(exports)), "public-api.exports_unique")


def _validate_acceptance_feature(text: str) -> None:
    _require(text.startswith("Feature: "), "acceptance.feature.header")
    _require(text.count("\n  Scenario: ") == 21, "acceptance.feature.scenarios")
    _require(text.count("\n  Scenario Outline: ") == 5, "acceptance.feature.outlines")
    _require(text.count("\n    Examples:") == 5, "acceptance.feature.examples")


def _validate_bath_fixture(fixture: dict[str, Any], vectors: dict[str, Any]) -> None:
    _require(fixture.get("schema") == REQUEST_SCHEMA, "bath-fixture.schema")
    _require(isinstance(fixture.get("provenance"), dict), "bath-fixture.provenance")
    expected_request = json.loads(vectors["bath"]["request_bytes"])
    without_provenance = {key: value for key, value in fixture.items() if key != "provenance"}
    _require(without_provenance == expected_request, "bath-fixture.request")
    expected_problem = json.loads(vectors["bath"]["problem_bytes"])
    _require(fixture.get("problem") == expected_problem, "bath-fixture.problem")
    extensions = expected_problem.get("extensions")
    _require(isinstance(extensions, list) and len(extensions) == 1, "bath-fixture.extensions")
    extension = extensions[0]
    _require(extension.get("namespace") == BATH_NAMESPACE, "bath-fixture.extensions.namespace")
    _require(extension.get("version") == "1.0", "bath-fixture.extensions.version")
    _require(
        extension.get("content_type") == BATH_CONTENT_TYPE,
        "bath-fixture.extensions.content_type",
    )
    _require(extension.get("required") is True, "bath-fixture.extensions.required")
    _require(extension.get("affects_physics") is True, "bath-fixture.extensions.affects_physics")


def _kernel_ref(case_id: str) -> str:
    if case_id == "G-1-bell":
        circuit = Circuit(2)
        register = ClassicalRegister("c", 2)
        circuit.add_register(register)
        circuit.h(0)
        circuit.cx(0, 1)
        circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
        circuit.add_measure(Measure(1, ClassicalBit(register, 1)))
    elif case_id == "G-2-feedforward":
        circuit = Circuit(2)
        register = ClassicalRegister("c", 1)
        circuit.add_register(register)
        circuit.h(0)
        circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
        circuit.add_conditional(Conditional(register, 1, (Gate(GateType.X, (1,)),)))
    elif case_id == "G-3-rz-float":
        circuit = Circuit(1)
        register = ClassicalRegister("c", 1)
        circuit.add_register(register)
        circuit.rz(0, 0.5)
        circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
    else:
        raise FixtureIntegrityError(f"identity.{case_id}")
    return compute_kernel_ref(circuit)


def _check_evidence(label: str, evidence: dict[str, Any], count: int, phrase: str) -> None:
    _require(set(evidence) == {"path", "sha256", "total_line"}, f"{label}.keys")
    path = evidence.get("path")
    _require(isinstance(path, str), f"{label}.path")
    _require(path.startswith(".plan/"), f"{label}.path")
    _require(not Path(path).is_absolute(), f"{label}.path_absolute")
    digest = evidence.get("sha256")
    _require(isinstance(digest, str) and len(digest) == 64, f"{label}.sha256")
    _require(all(character in "0123456789abcdef" for character in digest), f"{label}.sha256")
    total_line = evidence.get("total_line")
    _require(isinstance(total_line, str), f"{label}.total_line")
    _require(total_line.startswith(f"{count} {phrase} in "), f"{label}.total_line")


def test_p_fixed_fixture_sources_match() -> None:
    for name in FIXTURE_NAMES:
        data = _load_bytes(name)
        _check_fixture_bytes(name, data)
        text = data.decode("utf-8")
        _assert_no_absolute_paths(name, text)
        _require(".plan/" not in text, f"{name}.plan_reference")
    _validate_acceptance_feature(_load_bytes("acceptance.feature").decode("utf-8"))
    _validate_public_api(_load_json("public-api.json"))
    vectors = _load_json("canonical-vectors.json")
    _validate_canonical_vectors(vectors)
    _validate_bath_fixture(_load_json("bath-fixture.json"), vectors)


def test_p_legacy_baseline_is_explicit() -> None:
    _assert_no_absolute_paths(
        "legacy-baseline.json", _load_bytes("legacy-baseline.json").decode("utf-8")
    )
    baseline = _load_json("legacy-baseline.json")
    _require(baseline.get("schema") == "qaiji.p.legacy-baseline/1.0", "legacy.schema")
    captured = baseline.get("captured_from", {})
    _require(set(captured) == {"repository", "commit", "date"}, "legacy.captured_from.keys")
    _require(captured.get("repository") == "Qaiji-IR", "legacy.captured_from.repository")
    _require(
        captured.get("commit") == "4ef6f1a07a9e03ca09fff13f7843e0404958f228",
        "legacy.captured_from.commit",
    )
    _require(captured.get("date") == "2026-10-18", "legacy.captured_from.date")
    _require(
        baseline.get("captured_environment") == {"python": "3.13.9", "pytest": "9.1.0"},
        "legacy.captured_environment",
    )
    _require(
        baseline.get("vector_revision") == EXPECTED_VECTOR_REVISION,
        "legacy.vector_revision",
    )

    fixtures = baseline.get("fixtures", {})
    _require(isinstance(fixtures, dict), "legacy.fixtures")
    _require(set(fixtures) == set(FIXTURE_NAMES), "legacy.fixtures.keys")
    for name in FIXTURE_NAMES:
        entry = fixtures.get(name, {})
        _require(entry.get("sha256") == EXPECTED_FIXTURE_SHA256[name], f"legacy.fixtures.{name}")
        _require(entry.get("bytes") == EXPECTED_FIXTURE_BYTES[name], f"legacy.fixtures.{name}")
        source = entry.get("source")
        _require(isinstance(source, str), f"legacy.fixtures.{name}.source")
        _require(source.startswith(".plan/"), f"legacy.fixtures.{name}.source")
        _require(not Path(source).is_absolute(), f"legacy.fixtures.{name}.source_absolute")

    public_exports = baseline.get("public_exports")
    _require(isinstance(public_exports, dict), "legacy.public_exports")
    _require(set(public_exports) == set(EXPECTED_PUBLIC_MODULES), "legacy.public_exports.keys")
    for module_name, expected in public_exports.items():
        module = importlib.import_module(module_name)
        exported = list(module.__all__)
        _require(len(exported) == len(set(exported)), f"legacy.public_exports.{module_name}")
        _require(set(exported) == set(expected), f"legacy.public_exports.{module_name}")
        _require(
            all(hasattr(module, name) for name in expected),
            f"legacy.public_exports.{module_name}",
        )

    schema_versions = baseline.get("schema_versions")
    _require(isinstance(schema_versions, dict), "legacy.schema_versions")
    _require(schema_versions == EXPECTED_SCHEMA_VERSIONS, "legacy.schema_versions.keys")
    for qualified, expected in schema_versions.items():
        _require(_resolve_qualified(qualified) == expected, f"legacy.schema_versions.{qualified}")

    identity = baseline.get("identity")
    _require(isinstance(identity, dict), "legacy.identity")
    _require(
        set(identity) == {"recipes", "compatibility_baseline", "kernel_ref_cases"},
        "legacy.identity.keys",
    )
    recipes = identity.get("recipes")
    _require(isinstance(recipes, dict), "legacy.identity.recipes")
    _require(
        set(recipes) == {"kernel_ref", "summary_hash", "summary_schema_version"},
        "legacy.identity.recipes.keys",
    )
    _require(
        callable(_resolve_qualified(recipes["kernel_ref"])),
        "legacy.identity.recipes.kernel_ref",
    )
    _require(
        callable(_resolve_qualified(recipes["summary_hash"])),
        "legacy.identity.recipes.summary_hash",
    )
    _require(
        recipes["summary_schema_version"]
        == schema_versions["qaiji.core.semantics.SUMMARY_SCHEMA_VERSION"],
        "legacy.identity.recipes.summary_schema_version",
    )
    compatibility = identity.get("compatibility_baseline")
    _require(isinstance(compatibility, dict), "legacy.identity.compatibility_baseline")
    _require(
        set(compatibility) == {"path", "sha256"},
        "legacy.identity.compatibility_baseline.keys",
    )
    _require(
        compatibility["sha256"] == _sha256_path(compatibility["path"]),
        "legacy.identity.compatibility_baseline.sha256",
    )
    cases = identity.get("kernel_ref_cases")
    _require(isinstance(cases, list), "legacy.identity.kernel_ref_cases")
    _require(
        all(set(case) == {"id", "expected"} for case in cases),
        "legacy.identity.kernel_ref_cases.keys",
    )
    _require(
        [case.get("id") for case in cases] == ["G-1-bell", "G-2-feedforward", "G-3-rz-float"],
        "legacy.identity.kernel_ref_cases.order",
    )
    for case in cases:
        _require(_kernel_ref(case["id"]) == case["expected"], f"legacy.identity.{case['id']}")

    source_digests = baseline.get("source_digests")
    _require(isinstance(source_digests, dict), "legacy.source_digests")
    _require(len(source_digests) == 25, "legacy.source_digests.count")
    for path, digest in source_digests.items():
        _require(_sha256_path(path) == digest, f"legacy.source_digests.{path}")

    selected = baseline.get("selected_legacy_tests")
    _require(isinstance(selected, dict), "legacy.selected_legacy_tests")
    _require(
        set(selected) == {"files", "passed", "evidence"},
        "legacy.selected_legacy_tests.keys",
    )
    _require(selected.get("passed") == 832, "legacy.selected_legacy_tests.passed")
    _require(
        isinstance(selected.get("files"), dict) and len(selected["files"]) == 6,
        "legacy.selected_legacy_tests.files",
    )
    for path, digest in selected["files"].items():
        _require(_sha256_path(path) == digest, f"legacy.selected_legacy_tests.{path}")
    _check_evidence(
        "legacy.selected_legacy_tests.evidence",
        selected["evidence"],
        selected["passed"],
        "passed",
    )

    collection = baseline.get("baseline_collection")
    _require(isinstance(collection, dict), "legacy.baseline_collection")
    _require(
        set(collection) == {"collected", "evidence"},
        "legacy.baseline_collection.keys",
    )
    _require(collection.get("collected") == 5331, "legacy.baseline_collection.collected")
    _check_evidence(
        "legacy.baseline_collection.evidence",
        collection["evidence"],
        collection["collected"],
        "tests collected",
    )


def test_p_fixture_rejects_rewritten_vector() -> None:
    raw = _load_bytes("canonical-vectors.json")
    _check_fixture_bytes("canonical-vectors.json", raw)
    payload = json.loads(raw.decode("utf-8"))
    _validate_canonical_vectors(payload)

    rewritten = copy.deepcopy(payload)
    original_problem = rewritten["baseline"]["problem_bytes"]
    mutated_problem = original_problem.replace('"frame":"lab"', '"frame":"LAB"', 1)
    _require(mutated_problem != original_problem, "rewrite.fixture")
    rewritten["baseline"]["problem_bytes"] = mutated_problem
    rewritten["baseline"]["problem_id"] = _identity(PROBLEM_SCHEMA, mutated_problem)
    request = json.loads(rewritten["baseline"]["request_bytes"])
    request["problem"] = json.loads(mutated_problem)
    mutated_request = _canonical_json(request)
    rewritten["baseline"]["request_bytes"] = mutated_request
    rewritten["baseline"]["request_id"] = _identity(REQUEST_SCHEMA, mutated_request)
    rewritten_bytes = (json.dumps(rewritten, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _validate_canonical_vectors(rewritten)
    with pytest.raises(FixtureIntegrityError, match=r"canonical-vectors\.json\.sha256"):
        _check_fixture_bytes("canonical-vectors.json", rewritten_bytes)

    mismatched_id = copy.deepcopy(payload)
    mismatched_id["baseline"]["problem_id"] = "sha256:" + "0" * 64
    with pytest.raises(FixtureIntegrityError, match=r"baseline\.problem_id"):
        _validate_canonical_vectors(mismatched_id)

    mismatched_request = copy.deepcopy(payload)
    mismatched_request["baseline"]["request_bytes"] = mismatched_request["baseline"][
        "request_bytes"
    ].replace('"id":"full"', '"id":"rewritten"', 1)
    with pytest.raises(FixtureIntegrityError, match=r"baseline\.request_id"):
        _validate_canonical_vectors(mismatched_request)

    mismatched_bath = copy.deepcopy(payload)
    mismatched_bath["bath"]["problem_id"] = "sha256:" + "1" * 64
    with pytest.raises(FixtureIntegrityError, match=r"bath\.problem_id"):
        _validate_canonical_vectors(mismatched_bath)

    noncanonical = copy.deepcopy(payload)
    noncanonical["baseline"]["problem_bytes"] = noncanonical["baseline"]["problem_bytes"].replace(
        "{", "{ ", 1
    )
    with pytest.raises(FixtureIntegrityError, match=r"baseline\.canonical_problem_bytes"):
        _validate_canonical_vectors(noncanonical)

    wrong_revision = copy.deepcopy(payload)
    wrong_revision["vector_revision"] = 1
    with pytest.raises(FixtureIntegrityError, match=r"vector_revision"):
        _validate_canonical_vectors(wrong_revision)

    wrong_scalar = copy.deepcopy(payload)
    wrong_scalar["scalar_vectors"]["negative_zero"] = wrong_scalar["scalar_vectors"][
        "positive_zero"
    ]
    with pytest.raises(FixtureIntegrityError, match=r"scalar_vectors\.negative_zero"):
        _validate_canonical_vectors(wrong_scalar)
