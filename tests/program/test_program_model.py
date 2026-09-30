# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""程序模型构造、冻结及容许边界的契约。"""

import dataclasses
import re

import pytest

from qaiji.core.program import ExperimentMetadata, ProgramIR, QuantumInvocation, ResultOutput

_REF = "sha256:" + "a" * 64


@dataclasses.dataclass(frozen=True, slots=True)
class _TaggedOutput(ResultOutput):
    tag: str = "extra"


def _program(**changes):
    fields = {
        "quantum_invocations": [QuantumInvocation(_REF)],
        "experiment_metadata": ExperimentMetadata(1),
        "result_outputs": [ResultOutput(0, "c")],
    }
    fields.update(changes)
    return ProgramIR(**fields)


@pytest.mark.parametrize(
    ("build", "fragment"),
    [
        pytest.param(lambda: QuantumInvocation(5), "must be a str", id="M01-ref-not-str"),
        pytest.param(
            lambda: QuantumInvocation("sha256:" + "A" * 64), "lowercase hex", id="M02-ref-uppercase"
        ),
        pytest.param(
            lambda: QuantumInvocation(_REF + "\n"), "lowercase hex", id="M03-ref-trailing-newline"
        ),
        pytest.param(
            lambda: QuantumInvocation("sha256:" + "a" * 63), "lowercase hex", id="M04-ref-63-hex"
        ),
        pytest.param(
            lambda: QuantumInvocation("sha1:" + "a" * 64), "lowercase hex", id="M05-ref-sha1-prefix"
        ),
        pytest.param(lambda: ExperimentMetadata(True), "positive int", id="M06-shot-true"),
        pytest.param(lambda: ExperimentMetadata(1.0), "positive int", id="M07-shot-float"),
        pytest.param(lambda: ExperimentMetadata(0), "positive int", id="M08-shot-zero"),
        pytest.param(lambda: ExperimentMetadata(-1), "positive int", id="M09-shot-negative"),
        pytest.param(
            lambda: ExperimentMetadata(1, calibration_set_ref=""),
            "calibration_set_ref",
            id="M10-cal-ref-empty",
        ),
        pytest.param(
            lambda: ExperimentMetadata(1, calibration_set_ref=5),
            "calibration_set_ref",
            id="M11-cal-ref-int",
        ),
        pytest.param(
            lambda: ExperimentMetadata(1, device_profile_ref=""),
            "device_profile_ref",
            id="M12-dev-ref-empty",
        ),
        pytest.param(
            lambda: ExperimentMetadata(1, device_profile_ref=5),
            "device_profile_ref",
            id="M13-dev-ref-int",
        ),
        pytest.param(lambda: ResultOutput(True, "c"), "non-negative int", id="M14-index-bool"),
        pytest.param(lambda: ResultOutput(-1, "c"), "non-negative int", id="M15-index-negative"),
        pytest.param(lambda: ResultOutput(0, 5), "identifier", id="M16-name-int"),
        pytest.param(lambda: ResultOutput(0, "1c"), "identifier", id="M17-name-not-identifier"),
        pytest.param(
            lambda: _program(schema_version="qaiji.program.v1"),
            "schema_version",
            id="M18-schema-v1",
        ),
        pytest.param(
            lambda: _program(quantum_invocations=[], result_outputs=[]),
            "at least one quantum invocation",
            id="M19-zero-invocations",
        ),
        pytest.param(
            lambda: _program(result_outputs=[]), "at least one result output", id="M20-zero-outputs"
        ),
        pytest.param(
            lambda: _program(result_outputs=[ResultOutput(1, "c")]),
            "points past",
            id="M21-index-past-end",
        ),
        pytest.param(
            (
                lambda: _program(result_outputs=[ResultOutput(0, "c")] * 2),
                lambda: _program(
                    result_outputs=[_TaggedOutput(0, "c", "a"), _TaggedOutput(0, "c", "b")]
                ),
            ),
            "must not repeat",
            id="M22-duplicate-output",
        ),
        pytest.param(
            lambda: _program(quantum_invocations=[_REF]),
            "only QuantumInvocation",
            id="M23-raw-str-invocation",
        ),
        pytest.param(
            lambda: _program(result_outputs=[(0, "c")]),
            "only ResultOutput",
            id="M24-raw-tuple-output",
        ),
        pytest.param(
            lambda: _program(experiment_metadata={"shot_count": 1}),
            "ExperimentMetadata",
            id="M25-dict-metadata",
        ),
        pytest.param(
            lambda: QuantumInvocation("sha256:" + "a" * 65), "lowercase hex", id="M30-ref-65-hex"
        ),
        pytest.param(
            lambda: _program(result_outputs=[ResultOutput(0, "c"), ResultOutput(1, "c")]),
            "points past",
            id="M31-index-past-end-two-outputs",
        ),
        pytest.param(
            lambda: QuantumInvocation("sha256:" + "\u0660" * 64),
            "lowercase hex",
            id="M32-ref-unicode-digit",
        ),
        pytest.param(
            lambda: _program(
                result_outputs=[ResultOutput(0, "c"), ResultOutput(0, "d"), ResultOutput(0, "c")]
            ),
            "must not repeat",
            id="M33-duplicate-output-non-adjacent",
        ),
        pytest.param(
            lambda: _program(quantum_invocations={QuantumInvocation(_REF)}),
            "must be a list or tuple",
            id="M35-set-invocations",
        ),
        pytest.param(
            lambda: _program(result_outputs={ResultOutput(0, "c")}),
            "must be a list or tuple",
            id="M36-set-outputs",
        ),
        pytest.param(
            lambda: _program(quantum_invocations=(QuantumInvocation(_REF) for _ in range(1))),
            "must be a list or tuple",
            id="M37-generator-invocations",
        ),
    ],
)
def test_construction_rejects(build, fragment: str) -> None:
    for factory in build if isinstance(build, tuple) else (build,):
        with pytest.raises(ValueError, match=re.escape(fragment)):
            factory()


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(
            lambda: _program(quantum_invocations=[QuantumInvocation(_REF)] * 2),
            id="M26-same-kernel-twice",
        ),
        pytest.param(
            lambda: _program(experiment_metadata=ExperimentMetadata(1, " ", "\t")),
            id="M27-whitespace-ref",
        ),
        pytest.param(
            lambda: _program(experiment_metadata=ExperimentMetadata(2**63 + 1)),
            id="M28-shot-above-int64",
        ),
        pytest.param(
            lambda: _program(experiment_metadata=ExperimentMetadata(1)), id="M34-shot-one"
        ),
    ],
)
def test_construction_accepts(build) -> None:
    assert isinstance(build(), ProgramIR)


def test_program_is_frozen_with_tuple_fields() -> None:
    invocations = [QuantumInvocation(_REF)]
    outputs = [ResultOutput(0, "c")]
    program = _program(quantum_invocations=invocations, result_outputs=outputs)
    assert program.quantum_invocations == tuple(invocations)
    assert program.result_outputs == tuple(outputs)
    assert hash(program) == hash(_program())
    invocations.clear()
    outputs.clear()
    assert program == _program()
    for instance in (program, QuantumInvocation(_REF), ExperimentMetadata(1), ResultOutput(0, "c")):
        assert not hasattr(instance, "__dict__")
        for field in dataclasses.fields(instance):
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(instance, field.name, getattr(instance, field.name))
