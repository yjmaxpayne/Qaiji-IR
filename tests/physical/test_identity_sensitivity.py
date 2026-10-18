# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查冻结身份、语义字段和跨进程确定性。"""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from qaiji.core.physical import PContractError
from qaiji.core.physical.codec import load_problem, load_request

DATA = Path(__file__).with_name("data")
VECTORS = json.loads((DATA / "canonical-vectors.json").read_text())
EXAMPLE = json.loads((DATA / "schema-fields.json").read_text())["examples"]["request"]


def _identity():
    assert importlib.util.find_spec("qaiji.core.physical.identity") is not None
    return importlib.import_module("qaiji.core.physical.identity")


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _digest(domain, data):
    return "sha256:" + hashlib.sha256(domain.encode() + b"\0" + data).hexdigest()


def _assert_reference(wire):
    request = load_request(_json(wire))
    identity = _identity()
    expected = {key: value for key, value in wire.items() if key != "provenance"}
    problem_bytes, request_bytes = _json(wire["problem"]), _json(expected)
    assert identity.canonical_problem_bytes(request.problem) == problem_bytes
    assert identity.canonical_request_bytes(request) == request_bytes
    assert identity.problem_id(request.problem) == _digest(wire["problem"]["schema"], problem_bytes)
    assert identity.request_id(request) == _digest(wire["schema"], request_bytes)
    return identity.problem_id(request.problem), identity.request_id(request)


CHANGES = {
    "phase": (("problem", "h0", "terms", 0, "coefficient", 1), "3ff0000000000000"),
    "target": (("problem", "h0", "terms", 0, "factors", 0, "site"), "b"),
    "rate": (
        ("problem", "environment", "jumps", 0, "rate", "value"),
        "3fa47ae147ae147b",
    ),
    "extension": (("problem", "extensions", 0, "payload", "label"), "changed"),
    "observation": (("observations", 1, "operator", "terms", 0, "coefficient", 1), "0" * 16),
    "policy": (("policy", "atol"), "3ff0000000000000"),
    "coefficient": (("problem", "h0", "terms", 0, "coefficient", 0), "3ff0000000000000"),
    "basis": (("problem", "sites", 0, "basis", 0), "renamed"),
    "dimension": (
        ("problem", "sites", 0),
        {"id": "a", "dim": 3, "basis": ["ground", "excited", "extra"]},
    ),
    "site-id": (("problem", "sites", 0, "id"), "renamed"),
    "tensor-order": (("problem", "tensor_order"), ["a", "b"]),
    "frame": (("problem", "frame"), "rotating"),
    "signal-unit": (("problem", "drives", 0, "signal", "unit"), "dimensionless"),
    "negative-zero": (("problem", "drives", 0, "signal", "value"), "0" * 16),
    "signal-value": (
        ("problem", "drives", 1, "signal", "values", "data"),
        base64.b64encode(struct.pack("<d", 0.5)).decode(),
    ),
    "initial-state": (
        ("problem", "initial_state", "data", "data"),
        base64.b64encode(struct.pack("<12d", 0, 0, 1, *([0] * 9))).decode(),
    ),
    "signal-edges": (
        ("problem", "signal_edges", "data"),
        base64.b64encode(struct.pack("<2d", 0, 2)).decode(),
    ),
    "output-times": (
        ("output_times", "data"),
        base64.b64encode(struct.pack("<3d", 0, 0.25, 1)).decode(),
    ),
    "observation-id": (("observations", 0, "id"), "renamed"),
    "observation-order": (("observations",), list(reversed(EXAMPLE["observations"]))),
    "keep-sites": (("observations", 2, "keep_sites"), ["a"]),
    "projection-target": (("observations", 3, "input_sites"), ["b"]),
    "policy-rtol": (("policy", "rtol"), "3ddb7cdfd9d7bdbb"),
    "policy-step": (("policy", "max_step_ns"), "3ff0000000000000"),
    "policy-method": (("policy", "method", "allowed"), ["other-method"]),
    "policy-representation": (("policy", "representation"), "ket"),
    "extension-version": (("problem", "extensions", 0, "version"), "2.0"),
    "extension-namespace": (("problem", "extensions", 0, "namespace"), "org.example.changed"),
    "array-shape": (("problem", "extensions", 0, "payload", "lags", "$p_array", "shape"), [1, 2]),
    "array-dtype": (
        ("problem", "extensions", 0, "payload", "lags", "$p_array"),
        {
            **EXAMPLE["problem"]["extensions"][0]["payload"]["lags"]["$p_array"],
            "dtype": "c128le",
            "shape": [1],
        },
    ),
    "unicode-composed": (("problem", "extensions", 0, "payload", "label"), "é"),
    "unicode-decomposed": (("problem", "extensions", 0, "payload", "label"), "e\u0301"),
    "term-order": (("problem", "h0", "terms"), list(reversed(EXAMPLE["problem"]["h0"]["terms"]))),
}


def _changed(name):
    wire = copy.deepcopy(EXAMPLE)
    path, value = CHANGES[name]
    parent = wire
    for key in path[:-1]:
        parent = parent[key]
    assert parent[path[-1]] != value
    parent[path[-1]] = copy.deepcopy(value)
    return wire


@pytest.mark.parametrize(
    "case", ["baseline", "bath", "cross-process", "required", "affects_physics", *CHANGES]
)
def test_p_identity_sensitivity(case):
    if case in ("required", "affects_physics"):
        identity = _identity()
        request = load_request(_json(EXAMPLE))
        assert _assert_reference(EXAMPLE)
        object.__setattr__(request.problem.extensions[0], case, False)
        for value, encode in (
            (request.problem, identity.canonical_problem_bytes),
            (request, identity.canonical_request_bytes),
        ):
            with pytest.raises(PContractError) as caught:
                encode(value)
            assert caught.value.diagnostics[0].code == "EXTENSION_ENVELOPE"
        return
    if case in ("baseline", "bath"):
        vector = VECTORS[case]
        wire = json.loads(vector["request_bytes"])
        wire["provenance"] = copy.deepcopy(EXAMPLE["provenance"])
        assert _assert_reference(wire) == (vector["problem_id"], vector["request_id"])
        identity = _identity()
        assert identity.canonical_problem_bytes(load_problem(vector["problem_bytes"].encode())) == (
            vector["problem_bytes"].encode()
        )
        for kind in ("problem", "request"):
            frozen = vector[kind + "_bytes"].encode()
            assert _json(json.loads(frozen)) == frozen
            assert (
                _digest(wire["problem"]["schema"] if kind == "problem" else wire["schema"], frozen)
                == vector[kind + "_id"]
            )
        return
    baseline = _assert_reference(EXAMPLE)
    if case == "cross-process":
        script = (
            "import json,sys; from qaiji.core.physical.codec import load_request; "
            "from qaiji.core.physical.identity import canonical_request_bytes,problem_id,request_id; "
            "r=load_request(sys.stdin.buffer.read()); "
            "print(json.dumps([problem_id(r.problem),request_id(r),canonical_request_bytes(r).hex()]))"
        )
        expected = [*baseline, _json({k: v for k, v in EXAMPLE.items() if k != "provenance"}).hex()]
        for seed in ("0", "177"):
            result = subprocess.run(
                [sys.executable, "-c", script],
                input=_json(EXAMPLE),
                capture_output=True,
                check=True,
                timeout=30,
                env={**os.environ, "PYTHONHASHSEED": seed},
            )
            assert json.loads(result.stdout) == expected
        return
    changed = _assert_reference(_changed(case))
    assert changed[1] != baseline[1]
    assert (changed[0] != baseline[0]) == (CHANGES[case][0][0] == "problem")
    if case == "unicode-composed":
        assert changed != _assert_reference(_changed("unicode-decomposed"))


@pytest.mark.parametrize(
    "variant",
    [
        "omit-phase",
        "omit-target",
        "omit-rate",
        "omit-extension",
        "omit-observation",
        "omit-policy",
        "include-provenance",
    ],
)
def test_p_rejects_identity_omission(variant):
    baseline = _assert_reference(EXAMPLE)
    if variant == "include-provenance":
        wire = copy.deepcopy(EXAMPLE)
        wire["provenance"]["program_ref"] = "another-program"
        assert _assert_reference(wire) == baseline
        return
    changed = _assert_reference(_changed(variant.removeprefix("omit-")))
    assert changed[1] != baseline[1]
    assert (changed[0] != baseline[0]) == (variant not in ("omit-observation", "omit-policy"))
