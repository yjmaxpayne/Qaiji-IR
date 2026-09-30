# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""公开元数据、常量与异常层级的契约。"""

import ast
from pathlib import Path
from types import ModuleType

import pytest

import qaiji
import qaiji.codec as codec
import qaiji.core as core
import qaiji.core.program as program
import qaiji.core.semantics as semantics
from qaiji.constants import DEFAULT_TOLERANCE
from qaiji.core.program import ProgramValidationError
from qaiji.exceptions import (
    ConventionViolationError,
    QaijiIRError,
    Qasm3ParseError,
    Qasm3UnsupportedConstructError,
    Qasm3UnsupportedGateError,
    UnsupportedEquivLevelError,
)

ROOT_PUBLIC_NAMES = {
    "Circuit",
    "ClassicalBit",
    "ClassicalRegister",
    "Conditional",
    "ConventionViolationError",
    "Gate",
    "GateType",
    "IR_SCHEMA_VERSION",
    "Measure",
    "QaijiIRError",
    "Qasm3ParseError",
    "Qasm3UnsupportedConstructError",
    "Qasm3UnsupportedGateError",
    "UnsupportedEquivLevelError",
    "__version__",
    "from_qasm3",
    "to_qasm3",
}
CORE_PUBLIC_NAMES = {
    "CANONICAL_ALIASES",
    "PARAM_REQUIREMENTS",
    "SINGLE_QUBIT_GATES",
    "TWO_QUBIT_GATES",
    "Circuit",
    "ClassicalBit",
    "ClassicalRegister",
    "Conditional",
    "Gate",
    "GateType",
    "Measure",
}
CODEC_PUBLIC_NAMES = {"GateSpec", "from_qasm3", "to_qasm3"}
SEMANTICS_PUBLIC_NAMES = {
    "CartanRole",
    "ClassicalEdge",
    "ConditionModel",
    "EquivLevel",
    "GATE_COVERAGE_TOTAL",
    "HandleStatus",
    "JSONValue",
    "MeasurementHandle",
    "MorphismType",
    "PreservationSummary",
    "SUMMARY_SCHEMA_VERSION",
    "SemanticAnnotation",
    "SemanticIRHandle",
    "annotate_circuit",
    "build_dataflow_summary",
    "build_semantic_summary",
    "canonical_summary_hash",
    "check_preservation",
    "classify_operation",
    "freeze_summary",
}

PROGRAM_PUBLIC_NAMES = {
    "PROGRAM_SCHEMA_VERSION",
    "ExperimentMetadata",
    "ProgramIR",
    "ProgramValidationError",
    "QuantumInvocation",
    "ResultOutput",
    "compute_kernel_ref",
    "validate_program",
}


def test_package_metadata_is_readable() -> None:
    assert isinstance(qaiji.__version__, str)
    assert qaiji.__version__
    assert qaiji.IR_SCHEMA_VERSION == "qaiji.ir.v0"


@pytest.mark.parametrize(
    ("module", "expected_names"),
    [
        (qaiji, ROOT_PUBLIC_NAMES),
        (core, CORE_PUBLIC_NAMES),
        (codec, CODEC_PUBLIC_NAMES),
        (semantics, SEMANTICS_PUBLIC_NAMES),
        (program, PROGRAM_PUBLIC_NAMES),
    ],
)
def test_public_exports_are_the_exact_contract(
    module: ModuleType, expected_names: set[str]
) -> None:
    exported_names = module.__all__

    assert set(exported_names) == expected_names
    assert len(exported_names) == len(expected_names)
    assert all(hasattr(module, name) for name in expected_names)


def test_package_root_exports_construct_a_gate() -> None:
    gate = qaiji.Gate(qaiji.GateType.H, (0,))

    assert gate.gate_type is qaiji.GateType.H
    assert gate.qubits == (0,)


def test_non_codec_source_files_do_not_reference_openqasm3() -> None:
    package_root = Path(qaiji.__file__).parent
    codec_root = package_root / "codec"
    offenders = [
        path.relative_to(package_root)
        for path in package_root.rglob("*.py")
        if codec_root not in path.parents and "openqasm3" in path.read_text()
    ]

    assert offenders == []


@pytest.mark.parametrize(
    ("exception_type", "base_type"),
    [
        (QaijiIRError, Exception),
        (ProgramValidationError, QaijiIRError),
        (Qasm3ParseError, QaijiIRError),
        (Qasm3UnsupportedConstructError, QaijiIRError),
        (Qasm3UnsupportedGateError, QaijiIRError),
        (ConventionViolationError, QaijiIRError),
        (UnsupportedEquivLevelError, QaijiIRError),
    ],
)
def test_exception_type_has_expected_base(
    exception_type: type[BaseException], base_type: type[BaseException]
) -> None:
    assert issubclass(exception_type, base_type)


def test_gate_error_is_caught_as_unsupported_construct() -> None:
    assert issubclass(Qasm3UnsupportedGateError, Qasm3UnsupportedConstructError)

    with pytest.raises(Qasm3UnsupportedConstructError):
        raise Qasm3UnsupportedGateError("x at 1:1: gate is not supported")


def test_default_tolerance_is_high_precision_value() -> None:
    assert DEFAULT_TOLERANCE == 1e-10


def test_circuit_imports_classical_only_for_types_and_runtime_dispatch() -> None:
    circuit_path = Path(qaiji.__file__).parent / "core" / "circuit.py"
    module = ast.parse(circuit_path.read_text())
    classical_imports = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.ImportFrom) and node.module == "qaiji.core.classical"
    ]
    type_checking_block = next(
        node
        for node in module.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "TYPE_CHECKING"
    )
    dispatch_function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_node_eq"
    )
    circuit_class = next(
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Circuit"
    )
    canonicalize_method = next(
        node
        for node in circuit_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "canonicalize"
    )
    allowed_imports = [
        node
        for scope in (type_checking_block, dispatch_function, canonicalize_method)
        for node in ast.walk(scope)
        if isinstance(node, ast.ImportFrom) and node.module == "qaiji.core.classical"
    ]

    assert {id(node) for node in classical_imports} == {id(node) for node in allowed_imports}

    # Gate.canonicalize（另一个类上的同名方法）不得被只按名字匹配的扫描
    # 误判为 Circuit.canonicalize。
    gate_class = next(
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Gate"
    )
    gate_canonicalize_method = next(
        node
        for node in gate_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "canonicalize"
    )
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "qaiji.core.classical"
        for node in ast.walk(gate_canonicalize_method)
    )


def test_exceptions_module_matches_root_exception_exports() -> None:
    module = ast.parse((Path(qaiji.__file__).parent / "exceptions.py").read_text())
    declared = {node.name for node in module.body if isinstance(node, ast.ClassDef)}
    exported = {
        name
        for name in qaiji.__all__
        if isinstance(getattr(qaiji, name), type)
        and issubclass(getattr(qaiji, name), BaseException)
    }
    assert declared == exported
