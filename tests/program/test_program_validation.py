# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""固定配方、摘要版本绑定及程序校验契约。"""

import inspect

import pytest

import qaiji.core.semantics as semantics
from factories import bell_circuit, feedforward_circuit, ghz_circuit
from qaiji.core import Circuit, ClassicalBit, ClassicalRegister, Measure
from qaiji.core.program import (
    ExperimentMetadata,
    ProgramIR,
    ProgramValidationError,
    QuantumInvocation,
    ResultOutput,
    compute_kernel_ref,
    validate_program,
)
from qaiji.exceptions import QaijiIRError

_DRIFT_ACTION = (
    "stop and investigate L4 drift; "
    "report the impact and obtain a versioning decision before updating goldens."
)


def _rz_circuit() -> Circuit:
    circuit = Circuit(1)
    register = ClassicalRegister("c", 1)
    circuit.add_register(register)
    circuit.rz(0, 0.5)
    circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
    return circuit


@pytest.mark.parametrize(
    ("factory", "expected"),
    [
        pytest.param(
            bell_circuit,
            "sha256:afe9bc2fd0c5ae8b243a4a8615bbe457adde36c1753835884557bc2d31e043d1",
            id="G-1-bell",
        ),
        pytest.param(
            feedforward_circuit,
            "sha256:82687501ff4b7e29c24778be0577d11d4b1a6c194df2f9041158e4fa589eae2d",
            id="G-2-feedforward",
        ),
        pytest.param(
            _rz_circuit,
            "sha256:fc6d626b106f4203029114e068bdbb581e92b3f0d03d00294824c57b80606396",
            id="G-3-rz-float",
        ),
    ],
)
def test_kernel_ref_golden(factory, expected: str) -> None:
    assert compute_kernel_ref(factory()) == expected, _DRIFT_ACTION


def test_golden_refs_bind_summary_schema_v0() -> None:
    assert semantics.SUMMARY_SCHEMA_VERSION == "qaiji.semantic_summary.v0", _DRIFT_ACTION


def test_compute_kernel_ref_signature_is_circuit_only() -> None:
    assert list(inspect.signature(compute_kernel_ref).parameters) == ["circuit"]


_DANGLING = "sha256:" + "1" * 64


def _program(refs, outputs=((0, "c"),), metadata=None):
    return ProgramIR(
        quantum_invocations=tuple(QuantumInvocation(ref) for ref in refs),
        experiment_metadata=metadata or ExperimentMetadata(1000),
        result_outputs=tuple(ResultOutput(index, name) for index, name in outputs),
    )


def _edit_form(case):
    circuit = bell_circuit()
    ref = compute_kernel_ref(circuit)
    name = "c"
    if case == "mutated_after_hash":
        circuit.x(0)
    elif case == "dangling":
        return _program([_DANGLING]), {}
    elif case == "undeclared":
        name = "m"
    elif case == "recipe_drift":
        ref = semantics.canonical_summary_hash(
            semantics.build_semantic_summary(
                circuit=circuit,
                annotations=semantics.annotate_circuit(circuit),
                source_language="openqasm3",
            )
        )
    elif case == "canonicalized_cnot":
        circuit = Circuit(2)
        register = ClassicalRegister("c", 2)
        circuit.add_register(register)
        circuit.cnot(0, 1)
        for bit in range(2):
            circuit.add_measure(Measure(bit, ClassicalBit(register, bit)))
        ref = compute_kernel_ref(circuit)
        circuit = circuit.canonicalize()
    elif case == "unused_register":
        name = "unused"
        circuit.add_register(ClassicalRegister(name, 1))
        ref = compute_kernel_ref(circuit)
    elif case == "partial_register":
        circuit = Circuit(2)
        register = ClassicalRegister("c", 2)
        circuit.add_register(register)
        circuit.h(0)
        circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
        ref = compute_kernel_ref(circuit)
    elif case == "duplicate_name":
        circuit.cregs.append(ClassicalRegister("c", 2))
        ref = compute_kernel_ref(circuit)
    return _program([ref], [(0, name)]), {ref: circuit}


@pytest.mark.parametrize(
    ("case", "fragment"),
    [
        pytest.param("mutated_after_hash", "re-hashes to", id="V01-edited-after-hashing"),
        pytest.param("dangling", "not in the kernel table", id="V02-dangling-ref"),
        pytest.param("undeclared", "not declared", id="V03-undeclared-register"),
        pytest.param("recipe_drift", "re-hashes to", id="V04-recipe-drift"),
        pytest.param("canonicalized_cnot", "re-hashes to", id="V05-canonicalized-entry"),
        pytest.param(
            "unused_register", "bits [0] are never written", id="V06-register-never-written"
        ),
        pytest.param(
            "partial_register", "bits [1] are never written", id="V07-register-partially-written"
        ),
        pytest.param("duplicate_name", "declared 2 times", id="V08-duplicate-register-name"),
    ],
)
def test_edit_form_is_reported(case, fragment) -> None:
    program, kernels = _edit_form(case)
    with pytest.raises(ProgramValidationError) as caught:
        validate_program(program, kernels)
    assert len(caught.value.problems) == 1
    assert fragment in caught.value.problems[0]


def test_all_problems_are_reported_at_once() -> None:
    """认证问题先收集，输出问题随后追加且没有级联噪声。"""
    bell, ghz = bell_circuit(), ghz_circuit()
    bell_ref, ghz_ref = compute_kernel_ref(bell), compute_kernel_ref(ghz)
    bell.x(0)
    program = _program([bell_ref, _DANGLING, ghz_ref], [(0, "c"), (1, "c"), (2, "zz")])
    with pytest.raises(ProgramValidationError) as caught:
        validate_program(program, {bell_ref: bell, ghz_ref: ghz})
    assert len(caught.value.problems) == 3
    for problem, fragment in zip(
        caught.value.problems,
        (
            "invocation 0: kernel re-hashes to",
            "invocation 1: kernel_ref sha256:1111",
            "output (2, 'zz'): register is not declared",
        ),
        strict=True,
    ):
        assert fragment in problem


def test_unauthenticated_invocation_skips_output_checks() -> None:
    """表中内容未认证时，即使缺失输出寄存器也只报哈希问题。"""
    ref = compute_kernel_ref(bell_circuit())
    with pytest.raises(ProgramValidationError) as caught:
        validate_program(_program([ref]), {ref: Circuit(2)})
    assert len(caught.value.problems) == 1
    assert "invocation 0: kernel re-hashes to" in caught.value.problems[0]


def test_validation_error_message_lists_each_problem() -> None:
    """载荷与汇总消息逐项一致，异常仍可由全库基类捕获。"""
    with pytest.raises(ProgramValidationError) as caught:
        validate_program(_program([_DANGLING, _DANGLING]), {})
    error = caught.value
    assert isinstance(error, QaijiIRError)
    assert isinstance(error.problems, tuple)
    assert len(error.problems) == 2
    assert str(error) == "ProgramIR failed L4 validation with 2 problem(s):\n" + "\n".join(
        f"- {problem}" for problem in error.problems
    )

    supplied = list(error.problems)
    copied = ProgramValidationError(supplied)
    supplied.append("later mutation")
    assert copied.problems == error.problems
    assert str(copied) == str(error)


def test_problem_order_follows_declaration_not_sorting() -> None:
    """问题序列既不是字典序，也不是倒序输出。"""
    circuit = bell_circuit()
    ref = compute_kernel_ref(circuit)
    with pytest.raises(ProgramValidationError) as caught:
        validate_program(_program([ref, _DANGLING], [(0, "zz"), (0, "yy")]), {ref: circuit})
    assert len(caught.value.problems) == 3
    for problem, fragment in zip(
        caught.value.problems,
        (
            "invocation 1: kernel_ref",
            "output (0, 'zz'):",
            "output (0, 'yy'):",
        ),
        strict=True,
    ):
        assert fragment in problem


def test_repeated_dangling_ref_is_reported_per_invocation() -> None:
    """重复引用不折叠，保留每个调用的位置。"""
    with pytest.raises(ProgramValidationError) as caught:
        validate_program(_program([_DANGLING, _DANGLING]), {})
    assert len(caught.value.problems) == 2
    for index, problem in enumerate(caught.value.problems):
        assert f"invocation {index}:" in problem
        assert "not in the kernel table" in problem


def test_written_but_undeclared_output_is_legal() -> None:
    """被测量写入的寄存器不必全部作为程序输出。"""
    circuit = Circuit(2)
    for bit, name in enumerate(("c", "d")):
        register = ClassicalRegister(name, 1)
        circuit.add_register(register)
        circuit.add_measure(Measure(bit, ClassicalBit(register, 0)))
    ref = compute_kernel_ref(circuit)
    assert validate_program(_program([ref]), {ref: circuit}) is None


def test_feedforward_condition_register_output_is_legal() -> None:
    """说明性守护：条件所读寄存器仍可输出，不额外限制 L4 数据流。"""
    circuit = feedforward_circuit()
    ref = compute_kernel_ref(circuit)
    assert validate_program(_program([ref]), {ref: circuit}) is None


def test_same_kernel_invoked_twice_is_legal() -> None:
    """调用顺序允许重复，同一引用可对应多个输出位置。"""
    circuit = bell_circuit()
    ref = compute_kernel_ref(circuit)
    assert validate_program(_program([ref, ref], [(0, "c"), (1, "c")]), {ref: circuit}) is None


def test_opaque_refs_passthrough_leaves_verdict_unchanged() -> None:
    """不透明引用不参与成功或失败判决，问题载荷也必须相同。"""
    circuit = bell_circuit()
    ref = compute_kernel_ref(circuit)
    first = _program([ref], metadata=ExperimentMetadata(1000, calibration_set_ref="cal:A"))
    second = _program(
        [ref],
        metadata=ExperimentMetadata(
            1000,
            calibration_set_ref="校准:B",
            device_profile_ref="dev",
        ),
    )
    assert validate_program(first, {ref: circuit}) is None
    assert validate_program(second, {ref: circuit}) is None
    with pytest.raises(ProgramValidationError) as first_error:
        validate_program(first, {})
    with pytest.raises(ProgramValidationError) as second_error:
        validate_program(second, {})
    assert first_error.value.problems == second_error.value.problems
    assert str(first_error.value) == str(second_error.value)


def test_phantom_register_counts_by_name() -> None:
    """说明性守护：继承 L4 按名语义，不比较测量目标寄存器的对象身份。"""
    circuit = Circuit(2)
    register = ClassicalRegister("c", 2)
    circuit.add_register(register)
    circuit.add_measure(Measure(0, ClassicalBit(register, 0)))
    circuit.gates.append(Measure(1, ClassicalBit(ClassicalRegister("c", 3), 1)))
    ref = compute_kernel_ref(circuit)
    assert validate_program(_program([ref]), {ref: circuit}) is None


def test_unreferenced_table_entries_are_not_checked() -> None:
    """解析表可以包含程序没有引用的失配条目。"""
    circuit, junk = bell_circuit(), ghz_circuit()
    ref = compute_kernel_ref(circuit)
    junk.x(0)
    assert validate_program(_program([ref]), {ref: circuit, _DANGLING: junk}) is None


def test_table_content_not_caller_object_is_authenticated() -> None:
    """说明性守护：API 只接受解析表，调用方持有的旧对象不参与认证。"""
    pristine, edited = bell_circuit(), bell_circuit()
    ref, stale = compute_kernel_ref(pristine), compute_kernel_ref(edited)
    assert ref == stale
    edited.x(0)
    assert compute_kernel_ref(edited) != stale
    kernels = {stale: edited}
    kernels[ref] = pristine
    assert validate_program(_program([stale]), kernels) is None


def test_corrupted_circuit_type_error_propagates() -> None:
    """损坏的 L4 节点保留原异常，不伪装成程序自洽性问题。"""
    circuit = bell_circuit()
    ref = compute_kernel_ref(circuit)
    circuit.gates.append("corrupted")
    with pytest.raises(TypeError, match="Cannot classify"):
        validate_program(_program([ref]), {ref: circuit})
