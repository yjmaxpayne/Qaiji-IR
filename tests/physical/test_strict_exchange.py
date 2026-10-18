# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Compare complete wire fields with independent public fixtures."""

from __future__ import annotations

import copy
import importlib
import json
import struct
from pathlib import Path

import pytest

from qaiji.core.physical import PContractError

DATA = Path(__file__).with_name("data")
FIELDS = json.loads((DATA / "schema-fields.json").read_text())
KINDS = tuple(FIELDS["examples"])


def wire_examples():
    return copy.deepcopy(FIELDS["examples"])


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def codec():
    return importlib.import_module("qaiji.core.physical.codec")


def load(kind, wire, **kwargs):
    return getattr(codec(), "load_" + kind)(wire, **kwargs)


def dump(kind, obj, **kwargs):
    value = getattr(codec(), "dump_" + kind)(obj, **kwargs)
    return value if isinstance(value, bytes) else value.document


def rejection(kind, raw, code, path=None, **kwargs):
    with pytest.raises(PContractError) as caught:
        load(kind, raw, **kwargs)
    diagnostic = caught.value.diagnostics[0]
    assert diagnostic.code in code.split("|")
    assert diagnostic.category == (
        "RESOURCE_LIMIT"
        if code in ("BYTES", "DEPTH", "ATTACHMENT_BYTES")
        else "INVALID_RESULT"
        if kind == "result"
        else "INVALID_REQUEST"
    )
    if path is not None:
        assert diagnostic.path == path
    return caught.value


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("layout", ["inline", "attachments"])
def test_p_strict_exchange(kind, layout):
    raw = canonical(wire_examples()[kind])
    obj = load(kind, raw)
    assert dump(kind, obj) == raw  # Expected bytes never come from the codec.
    assert load(kind, json.dumps(json.loads(raw), indent=2).encode()) == obj
    if kind in ("problem", "request", "result"):
        artifact = getattr(codec(), "dump_" + kind)(obj, layout=layout)
        restored = load(kind, artifact.document, attachments=dict(artifact.attachments))
        assert restored == obj
        assert dump(kind, restored) == raw
        assert bool(artifact.attachments) == (layout == "attachments")
    if kind == "problem":
        vectors = json.loads((DATA / "canonical-vectors.json").read_text())
        for name in ("baseline", "bath"):
            frozen = vectors[name]["problem_bytes"].encode()
            assert dump(kind, load(kind, frozen)) == frozen
        assert obj.tensor_order == ("b", "a")
        assert obj.h0.terms[0].coefficient == 0.5 - 0.25j
        assert struct.pack(">d", obj.drives[0].signal.value).hex() == "8000000000000000"
        for state in (
            dict(
                kind="density",
                frame="lab",
                data=dict(dtype="c128le", shape=[1, 1], data="AAAAAAAA8D8AAAAAAAAAAA=="),
            ),
            dict(
                kind="product",
                frame="lab",
                factors=[
                    dict(
                        site="a",
                        kind="ket",
                        data=dict(dtype="c128le", shape=[1], data="AAAAAAAA8D8AAAAAAAAAAA=="),
                    ),
                    dict(
                        site="b",
                        kind="density",
                        data=dict(dtype="c128le", shape=[1, 1], data="AAAAAAAA8D8AAAAAAAAAAA=="),
                    ),
                ],
            ),
        ):
            doc = wire_examples()[kind]
            doc["initial_state"] = state
            assert dump(kind, load(kind, canonical(doc))) == canonical(doc)


@pytest.mark.parametrize(
    "variant",
    [
        "drop-imaginary",
        "replace-axis",
        "accept-unknown-key",
        "accept-duplicate-key",
        "accept-nonfinite",
        "accept-unknown-minor",
    ],
)
def test_p_rejects_codec_semantics(variant):
    doc = wire_examples()["problem"]
    raw = canonical(doc)
    # These assertions are also the oracles for single-mechanism mutation runs.
    assert dump("problem", load("problem", raw)) == raw
    if variant == "drop-imaginary":
        assert load("problem", raw).h0.terms[0].coefficient.imag == -0.25
    elif variant == "replace-axis":
        assert load("problem", raw).tensor_order == ("b", "a")
    elif variant == "accept-unknown-key":
        doc["extra"] = None
        rejection("problem", canonical(doc), "KEYS", "")
    elif variant == "accept-duplicate-key":
        rejection("problem", b'{"schema":"qaiji.p.problem/1.0",' + raw[1:], "DUPLICATE", "/schema")
    elif variant == "accept-nonfinite":
        doc["drives"][0]["signal"]["value"] = "7ff0000000000000"
        rejection("problem", canonical(doc), "NONFINITE", "/drives/0/signal/value")
    else:
        doc["schema"] = "qaiji.p.problem/1.1"
        rejection("problem", canonical(doc), "VERSION", "/schema")
