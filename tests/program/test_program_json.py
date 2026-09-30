# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""JSON 输入拒收、规范写出和跨进程字节稳定性。"""

import dataclasses
import json
import re

import pytest

from _fresh_process import run_fresh_process
from factories import bell_circuit, feedforward_circuit, ghz_circuit
from qaiji.core.program import (
    ExperimentMetadata,
    ProgramIR,
    QuantumInvocation,
    ResultOutput,
    compute_kernel_ref,
)

_REF = "sha256:" + "a" * 64
_GOLDEN_TEXT = (
    '{"experiment_metadata":{"calibration_set_ref":"\\u6821\\u51c6","device_profile_ref":null,'
    '"shot_count":1000},"quantum_invocations":[{"kernel_ref":"' + _REF + '"}],'
    '"result_outputs":[{"invocation_index":0,"register_name":"c"}],"schema_version":"qaiji.program.v0"}'
)


def _golden_sample() -> ProgramIR:
    return ProgramIR(
        quantum_invocations=[QuantumInvocation(_REF)],
        experiment_metadata=ExperimentMetadata(1000, "校准"),
        result_outputs=[ResultOutput(0, "c")],
    )


def _changed(path, value=None, *, remove=False) -> str:
    payload = json.loads(_GOLDEN_TEXT)
    target = payload
    for key in path[:-1]:
        target = target[key]
    if remove:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return json.dumps(payload)


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        pytest.param("[]", "must be a JSON object", id="J01-top-level-array"),
        pytest.param(
            _changed(["result_outputs"], remove=True), "exactly keys", id="J02-top-missing-key"
        ),
        pytest.param(_changed(["extra"], 1), "exactly keys", id="J03-top-extra-key"),
        pytest.param(
            _changed(["quantum_invocations", 0, "kernel_ref"], remove=True),
            "exactly keys",
            id="J04-invocation-missing-key",
        ),
        pytest.param(
            _changed(["quantum_invocations", 0, "extra"], 1),
            "exactly keys",
            id="J05-invocation-extra-key",
        ),
        pytest.param(
            _changed(["experiment_metadata", "device_profile_ref"], remove=True),
            "exactly keys",
            id="J06-metadata-missing-null-key",
        ),
        pytest.param(
            _changed(["experiment_metadata", "extra"], 1),
            "exactly keys",
            id="J07-metadata-extra-key",
        ),
        pytest.param(
            _changed(["result_outputs", 0, "register_name"], remove=True),
            "exactly keys",
            id="J08-output-missing-key",
        ),
        pytest.param(
            _changed(["result_outputs", 0, "extra"], 1), "exactly keys", id="J09-output-extra-key"
        ),
        pytest.param(
            _changed(["quantum_invocations"], {}),
            "must be a JSON array",
            id="J10-invocations-object",
        ),
        pytest.param(
            _changed(["quantum_invocations"], None),
            "must be a JSON array",
            id="J11-invocations-null",
        ),
        pytest.param(
            _changed(["result_outputs"], 5), "must be a JSON array", id="J12-outputs-number"
        ),
        pytest.param(
            _changed(["result_outputs"], "c"), "must be a JSON array", id="J13-outputs-string"
        ),
        pytest.param(
            _changed(["quantum_invocations", 0], _REF),
            "must be a JSON object",
            id="J14-invocation-element-str",
        ),
        pytest.param(
            _changed(["experiment_metadata"], []), "must be a JSON object", id="J15-metadata-array"
        ),
        pytest.param(
            _GOLDEN_TEXT.replace('"shot_count":1000', '"shot_count":1,"shot_count":1000'),
            "duplicate JSON object keys",
            id="J16-duplicate-key-metadata",
        ),
        pytest.param(
            _GOLDEN_TEXT.replace(
                '"schema_version":', '"schema_version":"qaiji.program.v0","schema_version":'
            ),
            "duplicate JSON object keys",
            id="J17-duplicate-key-top",
        ),
        pytest.param(
            _GOLDEN_TEXT.replace('"shot_count":1000', '"shot_count":1e3'),
            "positive int",
            id="J18-shot-exponent",
        ),
        pytest.param(
            _GOLDEN_TEXT.replace('"shot_count":1000', '"shot_count":NaN'),
            "positive int",
            id="J19-shot-nan-literal",
        ),
        pytest.param(
            _changed(["experiment_metadata", "shot_count"], True),
            "positive int",
            id="J20-shot-true",
        ),
        pytest.param(
            _changed(["experiment_metadata", "shot_count"], None),
            "positive int",
            id="J21-shot-null",
        ),
        pytest.param("{", "Expecting", id="J22-invalid-json"),
        pytest.param(
            _changed(["quantum_invocations", 0, "kernel_ref"], 5),
            "must be a str",
            id="J23-kernel-ref-number",
        ),
        pytest.param(
            _changed(["result_outputs", 0, "register_name"], None),
            "identifier",
            id="J24-register-name-null",
        ),
        pytest.param(
            _changed(["result_outputs", 0, "invocation_index"], "0"),
            "non-negative int",
            id="J25-index-string",
        ),
        pytest.param(_changed(["schema_version"], 0), "schema_version", id="J26-schema-number"),
        pytest.param(
            _changed(["result_outputs"], [5]),
            "must be a JSON object",
            id="J32-output-element-number",
        ),
        pytest.param(
            _changed(["schema_version"], remove=True),
            "exactly keys",
            id="J33-top-missing-schema-version",
        ),
    ],
)
def test_from_json_rejects(text: str, fragment: str) -> None:
    exception_type = json.JSONDecodeError if text == "{" else ValueError
    with pytest.raises(exception_type, match=re.escape(fragment)):
        ProgramIR.from_json(text)


def test_from_json_rejects_deep_array_with_default_parser() -> None:
    """默认解析器可能先触发递归限制，也可能把数组交给结构校验。"""
    text = "[" * 100000 + "]" * 100000
    try:
        payload = json.loads(text, object_pairs_hook=dict)
    except RecursionError:
        expected = "JSON nested too deeply"
        cause_type = RecursionError
    else:
        assert isinstance(payload, list)
        expected = "must be a JSON object"
        cause_type = type(None)
    with pytest.raises(ValueError) as error:
        ProgramIR.from_json(text)
    assert str(error.value) == expected
    assert isinstance(error.value.__cause__, cause_type)


def test_from_json_converts_real_scanner_recursion_error() -> None:
    """在独立进程选择标准库 Python scanner，验证真实递归错误的转换。"""
    script = r"""
import json
import json.scanner
import sys
import pytest
from qaiji.core.program import ProgramIR

sys.setrecursionlimit(1000)
json.scanner.make_scanner = json.scanner.py_make_scanner
text = "[" * 2000 + "]" * 2000
with pytest.raises(RecursionError):
    json.loads(text, object_pairs_hook=dict)
with pytest.raises(ValueError) as error:
    ProgramIR.from_json(text)
assert str(error.value) == "JSON nested too deeply"
assert isinstance(error.value.__cause__, RecursionError)
print("real recursion converted with cause")
"""
    assert run_fresh_process(script).strip() == "real recursion converted with cause"


def _rich_sample() -> ProgramIR:
    return ProgramIR(
        quantum_invocations=[
            QuantumInvocation(compute_kernel_ref(factory()))
            for factory in (bell_circuit, ghz_circuit, feedforward_circuit, bell_circuit)
        ],
        experiment_metadata=ExperimentMetadata(2**63 + 1, "校准\ud800", "设备"),
        result_outputs=[ResultOutput(index, "c") for index in (3, 0, 2, 1)],
    )


def test_roundtrip_preserves_passthrough_refs_bigint_and_ascii() -> None:
    program = _rich_sample()
    text = program.to_json()
    assert ProgramIR.from_json(text) == program
    assert program.to_json() == text
    assert text.isascii()


def test_to_json_matches_golden_text() -> None:
    assert _golden_sample().to_json() == _GOLDEN_TEXT
    assert ProgramIR.from_json(_GOLDEN_TEXT) == _golden_sample()

    @dataclasses.dataclass(frozen=True, slots=True)
    class TaggedInvocation(QuantumInvocation):
        tag: str = "extra"

    @dataclasses.dataclass(frozen=True, slots=True)
    class TaggedMetadata(ExperimentMetadata):
        tag: str = "extra"

    @dataclasses.dataclass(frozen=True, slots=True)
    class TaggedOutput(ResultOutput):
        tag: str = "extra"

    @dataclasses.dataclass(frozen=True, slots=True)
    class TaggedProgram(ProgramIR):
        tag: str = "extra"

    program = TaggedProgram(
        quantum_invocations=[TaggedInvocation(_REF)],
        experiment_metadata=TaggedMetadata(1000, "校准"),
        result_outputs=[TaggedOutput(0, "c")],
    )
    assert program.to_json() == _GOLDEN_TEXT
    assert ProgramIR.from_json(program.to_json()) == _golden_sample()
    assert ProgramIR.from_json(program.to_json()).to_json() == program.to_json()


def test_roundtrip_escapes_control_characters() -> None:
    program = ProgramIR(
        quantum_invocations=[QuantumInvocation(_REF)],
        experiment_metadata=ExperimentMetadata(1, '\n\t"\\', '\\"\t\n'),
        result_outputs=[ResultOutput(0, "c")],
    )
    text = program.to_json()
    assert ProgramIR.from_json(text) == program
    assert text.isascii()


def test_to_json_is_byte_identical_across_fresh_processes(monkeypatch) -> None:
    program = _rich_sample()
    refs = [item.kernel_ref for item in program.quantum_invocations]
    script = f"""
from qaiji.core.program import ExperimentMetadata, ProgramIR, QuantumInvocation, ResultOutput
program = ProgramIR(
    quantum_invocations=[QuantumInvocation(ref) for ref in {refs!r}],
    experiment_metadata=ExperimentMetadata({2**63 + 1}, {"校准" + chr(0xD800)!a}, {"设备"!a}),
    result_outputs=[ResultOutput(index, 'c') for index in (3, 0, 2, 1)],
)
print(program.to_json(), end='')
"""
    for seed in ("0", "1", "2"):
        monkeypatch.setenv("PYTHONHASHSEED", seed)
        assert run_fresh_process(script).encode("ascii") == program.to_json().encode("ascii")


def test_from_json_accepts_noncanonical_whitespace_and_key_order() -> None:
    payload = json.loads(_GOLDEN_TEXT)
    text = "\n " + json.dumps(dict(reversed(list(payload.items()))), indent=2) + " \t"
    assert ProgramIR.from_json(text) == _golden_sample()
    assert ProgramIR.from_json(text).to_json() == _GOLDEN_TEXT
