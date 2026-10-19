# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查来源保留、附件寻址和内联身份。"""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib
import importlib.util
import json
import struct
from pathlib import Path

import pytest

from qaiji.core.physical import PContractError
from qaiji.core.physical.codec import dump_request, load_request

EXAMPLE = json.loads((Path(__file__).with_name("data") / "schema-fields.json").read_text())[
    "examples"
]["request"]


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _identity():
    assert importlib.util.find_spec("qaiji.core.physical.identity") is not None
    return importlib.import_module("qaiji.core.physical.identity")


def _externalize(value, attachments):
    if isinstance(value, list):
        return [_externalize(child, attachments) for child in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"dtype", "shape", "data"} and value["dtype"] in ("f64le", "c128le"):
        raw = base64.b64decode(value["data"], validate=True)
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        attachments[digest] = raw
        return dict(dtype=value["dtype"], shape=value["shape"], attachment=digest)
    return {key: _externalize(child, attachments) for key, child in value.items()}


@pytest.mark.parametrize(
    "case",
    [
        "inline",
        "attachments",
        "mixed",
        "manual",
        "program_ref",
        "binder_version",
        "device_snapshot",
        "calibration_snapshot",
        "basis_mapping",
        "prior_transforms",
    ],
)
def test_p_provenance_attachments(case):
    identity = _identity()
    baseline = load_request(_json(EXAMPLE))
    wire = copy.deepcopy(EXAMPLE)
    if case == "manual":
        wire["provenance"] = dict(
            kind="manual",
            program_ref=None,
            binder_version=None,
            device_snapshot=None,
            calibration_snapshot=None,
            basis_mapping=[],
            prior_transforms=[],
        )
    elif case in ("program_ref", "binder_version"):
        wire["provenance"][case] = "other"
    elif case in ("device_snapshot", "calibration_snapshot"):
        wire["provenance"][case]["id"] = "other"
    elif case == "basis_mapping":
        wire["provenance"][case][0]["zero_label"] = "renamed"
    elif case == "prior_transforms":
        wire["provenance"][case].append({"name": "transform", "record": [1, True, None]})
    attachments = {}
    if case in ("attachments", "mixed"):
        wire = _externalize(wire, attachments)
        assert attachments
        if case == "mixed":
            wire["output_times"] = copy.deepcopy(EXAMPLE["output_times"])
    restored = load_request(_json(wire), attachments=dict(reversed(list(attachments.items()))))
    expected = copy.deepcopy(EXAMPLE)
    expected["provenance"] = wire["provenance"]
    assert dump_request(restored).document == _json(expected)
    assert identity.canonical_request_bytes(restored) == _json(
        {k: v for k, v in expected.items() if k != "provenance"}
    )
    assert identity.canonical_problem_bytes(restored.problem) == _json(EXAMPLE["problem"])
    assert identity.problem_id(restored.problem) == identity.problem_id(baseline.problem)
    assert identity.request_id(restored) == identity.request_id(baseline)
    exported = dump_request(restored, layout="attachments")
    assert load_request(exported.document, attachments=dict(exported.attachments)) == restored


@pytest.mark.parametrize(
    "variant", ["skip-attachment-digest", "missing-attachment", "drop-provenance"]
)
def test_p_rejects_attachment_digest_bypass(variant):
    attachments = {}
    wire = _externalize(copy.deepcopy(EXAMPLE), attachments)
    restored = load_request(_json(wire), attachments=attachments)
    assert dump_request(restored).document == _json(EXAMPLE)
    if variant == "drop-provenance":
        assert json.loads(dump_request(restored).document)["provenance"] == EXAMPLE["provenance"]
        return
    # 只改变目标附件。损坏字节仍满足长度和有限数值约束。
    digest = wire["output_times"]["attachment"]
    assert attachments[digest] == struct.pack("<3d", 0, 0.5, 1)
    changed = dict(attachments)
    if variant == "missing-attachment":
        del changed[digest]
        code, path = "ATTACHMENT_MISSING", "/output_times/attachment"
    else:
        changed[digest] = struct.pack("<3d", 0, 0.25, 1)
        assert len(changed[digest]) == len(attachments[digest])
        assert "sha256:" + hashlib.sha256(changed[digest]).hexdigest() != digest
        code, path = "ATTACHMENT_DIGEST", "/attachments/" + digest
    with pytest.raises(PContractError) as caught:
        load_request(_json(wire), attachments=changed)
    diagnostic = caught.value.diagnostics[0]
    assert (diagnostic.category, diagnostic.code, diagnostic.path) == (
        "INVALID_REQUEST",
        code,
        path,
    )
