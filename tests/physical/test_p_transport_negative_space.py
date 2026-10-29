# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查传输语法、记录分支和显式资源上限。"""

from __future__ import annotations

import base64
import builtins
import copy
import hashlib
import json
import struct
import sys
from dataclasses import fields

import pytest
from test_strict_exchange import (
    FIELDS,
    KINDS,
    canonical,
    codec,
    dump,
    load,
    rejection,
    wire_examples,
)

from qaiji.core.physical import CheckBudget, PContractError


def pointer(path):
    return "".join("/" + str(key).replace("~", "~0").replace("/", "~1") for key in path)


def get(doc, path):
    for key in path:
        doc = doc[key]
    return doc


def replace(doc, path, value):
    if not path:
        return value
    get(doc, path[:-1])[path[-1]] = value
    return doc


def duplicate(doc, path, key):
    if not path:
        raw = canonical(doc)
        return b"{" + canonical(key) + b":" + canonical(doc[key]) + b"," + raw[1:]
    first, *rest = path
    if isinstance(doc, list):
        return (
            b"["
            + b",".join(
                duplicate(v, rest, key) if i == first else canonical(v) for i, v in enumerate(doc)
            )
            + b"]"
        )
    return (
        b"{"
        + b",".join(
            canonical(k) + b":" + (duplicate(v, rest, key) if k == first else canonical(v))
            for k, v in sorted(doc.items())
        )
        + b"}"
    )


# 路径标识交换记录，不依赖生产代码的分派表。
BRANCHES = [
    ("problem", (), "Problem"),
    ("problem", ("sites", 0), "Site"),
    ("problem", ("h0",), "OperatorSum"),
    ("problem", ("h0", "terms", 0), "OperatorTerm"),
    ("problem", ("h0", "terms", 0, "factors", 0), "LocalFactor"),
    ("problem", ("h0", "terms", 0, "factors", 0, "matrix"), "ArrayData"),
    ("problem", ("drives", 0), "Drive"),
    ("problem", ("drives", 0, "signal"), "Signal"),
    ("problem", ("drives", 1, "signal"), "Signal"),
    ("problem", ("environment",), "Environment"),
    ("problem", ("environment", "jumps", 0), "Jump"),
    ("problem", ("initial_state",), "State"),
    ("problem", ("extensions", 0), "RequiredExtension"),
    ("problem", ("extensions", 0, "payload", "correlation", "$p_array"), "ArrayData"),
    ("request", (), "Request"),
    ("request", ("policy",), "ExecutionPolicy"),
    ("request", ("policy", "method"), "MethodChoice"),
    ("request", ("provenance",), "Provenance"),
    ("request", ("provenance", "device_snapshot"), "SnapshotRef"),
    ("request", ("provenance", "basis_mapping", 0), "BasisMapping"),
    *[("request", ("observations", i), "Observation") for i in range(4)],
    ("result", (), "Result"),
    *[("result", ("observations", i), "ObservationValue") for i in range(4)],
    ("result", ("report",), "ExecutionReport"),
    ("result", ("report", "policy_differences", 0), "PolicyDifference"),
    ("result", ("report", "transforms", 0), "TransformRecord"),
    ("result", ("report", "diagnostics", 0), "Diagnostic"),
    ("requirements", (), "Requirements"),
    ("capabilities", (), "Capabilities"),
]

BRANCHES += [
    ("problem", ("initial_state",), "State-density"),
    ("problem", ("initial_state",), "State-product"),
    ("problem", ("initial_state", "factors", 0), "ProductFactor-ket"),
    ("problem", ("initial_state", "factors", 1), "ProductFactor-density"),
    ("problem", ("signal_edges",), "ArrayData-attachment"),
    ("request", ("policy", "method"), "MethodChoice-fixed"),
]


def branch_example(kind, name):
    doc = wire_examples()[kind]
    attachments = {}
    if name in ("State-product", "ProductFactor-ket", "ProductFactor-density"):
        doc["initial_state"] = dict(
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
        )
    if name == "State-density":
        doc["initial_state"] = dict(
            kind="density",
            frame="lab",
            data=dict(dtype="c128le", shape=[1, 1], data="AAAAAAAA8D8AAAAAAAAAAA=="),
        )
    if name == "ArrayData-attachment":
        raw = base64.b64decode(doc["signal_edges"].pop("data"))
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        doc["signal_edges"]["attachment"] = digest
        attachments[digest] = raw
    if name == "MethodChoice-fixed":
        doc["policy"]["method"] = dict(mode="fixed", value="exact", allowed=[])
    return doc, ({"attachments": attachments} if attachments else {})


@pytest.mark.parametrize("kind,path,name", BRANCHES, ids=lambda x: str(x))
@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "container"])
def test_p_decoder_checks_every_branch_keyset(kind, path, name, change):
    doc, options = branch_example(kind, name)
    name = name.split("-")[0]
    original = get(doc, path)
    assert any(set(original) == set(branch) for branch in FIELDS["branches"][name])
    expected = copy.deepcopy(doc)
    if options:
        expected["signal_edges"].pop("attachment")
        expected["signal_edges"]["data"] = base64.b64encode(
            next(iter(options["attachments"].values()))
        ).decode()
    assert dump(kind, load(kind, canonical(doc), **options)) == canonical(expected)
    if change in ("missing", "duplicate"):
        for key in original:
            if change == "duplicate":
                rejection(
                    kind, duplicate(doc, path, key), "DUPLICATE", pointer((*path, key)), **options
                )
            else:
                variant = copy.deepcopy(doc)
                del get(variant, path)[key]
                rejection(
                    kind,
                    canonical(variant),
                    "EXTENSION_ENVELOPE" if name == "RequiredExtension" else "KEYS",
                    **options,
                )
    elif change == "extra":
        for key in {
            "extra",
            *(key for branch in FIELDS["branches"][name] for key in branch),
        } - original.keys():
            variant = copy.deepcopy(doc)
            get(variant, path)[key] = None
            rejection(kind, canonical(variant), "KEYS", **options)
    else:
        for value in ([], "", None, False, 0):
            if value is None and name == "SnapshotRef":
                variant = replace(copy.deepcopy(doc), path, value)
                variant["provenance"]["kind"] = "manual"
                assert dump(kind, load(kind, canonical(variant))) == canonical(variant)
                continue
            rejection(
                kind,
                canonical(replace(copy.deepcopy(doc), path, value)),
                "JSON_TYPE",
                pointer(path),
            )


NEGATIVE = [
    ("root-array", (), [], "JSON_TYPE"),
    ("root-string", (), "", "JSON_TYPE"),
    ("root-null", (), None, "JSON_TYPE"),
    ("root-bool", (), True, "JSON_TYPE"),
    ("root-int", (), 1, "JSON_TYPE"),
    ("version-major", ("schema",), "qaiji.p.problem/2.0", "VERSION"),
    ("version-minor", ("schema",), "qaiji.p.problem/1.2", "VERSION"),
    ("boolean-dimension", ("sites", 0, "dim"), True, "INTEGER"),
    ("empty-id", ("sites", 0, "id"), "", "UNICODE"),
    ("surrogate", ("sites", 0, "id"), "\ud800", "UNICODE"),
    ("short-f64", ("drives", 0, "signal", "value"), "0" * 15, "BINARY64"),
    ("long-f64", ("drives", 0, "signal", "value"), "0" * 17, "BINARY64"),
    ("uppercase-f64", ("drives", 0, "signal", "value"), "3FF0000000000000", "BINARY64"),
    ("nonhex-f64", ("drives", 0, "signal", "value"), "x" * 16, "BINARY64"),
    ("nan-f64", ("drives", 0, "signal", "value"), "7ff8000000000000", "NONFINITE"),
    ("inf-f64", ("drives", 0, "signal", "value"), "7ff0000000000000", "NONFINITE"),
    ("negative-inf-f64", ("drives", 0, "signal", "value"), "fff0000000000000", "NONFINITE"),
    ("dtype", ("signal_edges", "dtype"), "float64", "DTYPE"),
    ("boolean-shape", ("signal_edges", "shape"), [True], "SHAPE"),
    ("negative-shape", ("signal_edges", "shape"), [-1], "SHAPE"),
    ("shape-mismatch", ("signal_edges", "shape"), [3], "BYTE_LENGTH"),
    ("rank", ("signal_edges", "shape"), [1, 2], "SHAPE"),
    (
        "nonfinite-array",
        ("signal_edges", "data"),
        base64.b64encode(struct.pack("<dd", 1, float("nan"))).decode(),
        "NONFINITE",
    ),
    ("base64-alphabet", ("signal_edges", "data"), "!!!!", "BASE64"),
    ("base64-padding", ("signal_edges", "data"), "AA", "BASE64"),
    ("base64-pad-bits", ("signal_edges", "data"), "AB==", "BASE64"),
    ("base64-type", ("signal_edges", "data"), 1, "BASE64"),
    ("base64-unicode", ("signal_edges", "data"), "μ", "BASE64"),
    (
        "both-layouts",
        ("signal_edges",),
        dict(dtype="f64le", shape=[0], data="", attachment="sha256:" + "0" * 64),
        "KEYS",
    ),
    ("neither-layout", ("signal_edges",), dict(dtype="f64le", shape=[0]), "KEYS"),
    ("empty-p-array", ("extensions", 0, "payload", "correlation", "$p_array"), {}, "KEYS"),
    (
        "p-array-sibling",
        ("extensions", 0, "payload", "correlation"),
        {"$p_array": {"dtype": "f64le", "shape": [0], "data": ""}, "extra": None},
        "KEYS",
    ),
    ("extension-required", ("extensions", 0, "required"), False, "EXTENSION_ENVELOPE"),
    ("extension-affects", ("extensions", 0, "affects_physics"), False, "EXTENSION_ENVELOPE"),
    ("unknown-branch", ("initial_state", "kind"), "unknown", "KEYS"),
]


@pytest.mark.parametrize("case,path,value,code", NEGATIVE, ids=[r[0] for r in NEGATIVE])
def test_p_transport_negative_space_matrix(case, path, value, code):
    doc = replace(wire_examples()["problem"], path, value)
    raw = json.dumps(doc, ensure_ascii=True, separators=(",", ":")).encode()
    rejection("problem", raw, code)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("configuration", ["default", "smaller", "larger"])
@pytest.mark.parametrize("resource", ["max_wire_bytes", "max_depth", "max_attachment_bytes"])
def test_p_transport_budget_config_matrix(kind, configuration, resource):
    if resource == "max_attachment_bytes" and kind in ("requirements", "capabilities"):
        # 这些函数的签名没有附件参数。下方检查其空附件映射。
        assert load(
            kind, canonical(wire_examples()[kind]), budget=CheckBudget(max_attachment_bytes=0)
        )
        return
    defaults = CheckBudget()
    limit = getattr(defaults, resource)
    if configuration == "smaller":
        limit = 16384 if resource == "max_wire_bytes" else 16 if resource == "max_depth" else 32
    elif configuration == "larger":
        limit += 1024 if resource != "max_depth" else 16
    kwargs = {} if configuration == "default" else {"budget": CheckBudget(**{resource: limit})}
    doc = wire_examples()[kind]
    if resource == "max_wire_bytes":
        raw = canonical(doc)
        assert len(raw) < limit
        bounded = raw + b" " * (limit - len(raw))
        assert load(kind, bounded, **kwargs)
        rejection(kind, bounded + b" ", "BYTES", "", **kwargs)
    elif resource == "max_depth":
        path = (
            ("extensions", 0, "payload")
            if kind == "problem"
            else ("provenance", "prior_transforms", 0)
            if kind == "request"
            else ("report", "actual_policy")
            if kind == "result"
            else ("precision",)
        )
        # 根对象和路径中的每个祖先各贡献一层容器深度。
        nested = 0
        for _ in range(limit - len(path)):
            nested = [nested]
        replace(doc, path, nested)
        raw = canonical(doc)
        assert load(kind, raw, **kwargs)
        replace(doc, path, [nested])
        rejection(kind, canonical(doc), "DEPTH", "", **kwargs)
    else:
        data = b"a" * limit
        attachments = {"sha256:" + hashlib.sha256(data).hexdigest(): data}
        assert load(kind, canonical(doc), attachments=attachments, **kwargs)
        data += b"b"
        attachments = {"sha256:" + hashlib.sha256(data).hexdigest(): data}
        rejection(kind, canonical(doc), "ATTACHMENT_BYTES", "", attachments=attachments, **kwargs)


def test_p_decoder_never_resolves_external_paths(monkeypatch):
    doc = wire_examples()["problem"]
    c = codec()
    raw = canonical(doc)
    artifact = c.dump_problem(c.load_problem(raw), layout="attachments")

    def no_io(*args, **kwargs):
        raise AssertionError("The decoder attempted external I/O.")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", no_io)
        assert c.load_problem(artifact.document, attachments=dict(artifact.attachments))
        rejection("problem", artifact.document, "ATTACHMENT_MISSING")
        for resolver in ("/tmp/array", "file:///tmp/array", "https://invalid.example/array"):
            rejection("problem", artifact.document, "JSON_TYPE", attachments=resolver)
            data = json.loads(artifact.document)
            data["signal_edges"]["attachment"] = resolver
            rejection(
                "problem",
                canonical(data),
                "ATTACHMENT_DIGEST",
                attachments=dict(artifact.attachments),
            )


@pytest.mark.parametrize("kind", KINDS)
def test_p_transport_parser_boundaries(kind):
    doc = wire_examples()[kind]
    # 选取不透明 JSON 树的叶节点。
    # 整数上限检查不依赖记录语义。
    path = (
        ("extensions", 0, "payload")
        if kind == "problem"
        else ("provenance", "prior_transforms", 0)
        if kind == "request"
        else ("report", "actual_policy")
        if kind == "result"
        else ("precision",)
    )
    for token, expected in [
        (b"1.5", "NUMBER_ENCODING"),
        (b"1e3", "NUMBER_ENCODING"),
        (b"NaN", "NONFINITE"),
        (b"Infinity", "NONFINITE"),
        (b"-Infinity", "NONFINITE"),
        (b"9223372036854775808", "INTEGER"),
        (b"-9223372036854775809", "INTEGER"),
        (b"9" * 5000, "INTEGER"),
    ]:
        variant = copy.deepcopy(doc)
        replace(variant, path, "TOKEN")
        raw = canonical(variant).replace(b'"TOKEN"', token)
        rejection(kind, raw, expected, pointer(path))
    for value in (-(1 << 63), (1 << 63) - 1, True, False, None, "0" * 16, '[{}]\\"'):
        variant = replace(copy.deepcopy(doc), path, value)
        assert dump(kind, load(kind, canonical(variant))) == canonical(variant)
    variant = replace(copy.deepcopy(doc), path, "TOKEN")
    raw = canonical(variant).replace(b'"TOKEN"', b"-0")
    obj = load(kind, raw)
    assert dump(kind, obj) == canonical(replace(variant, path, 0))
    for raw, code in [
        (b"\xff", "UNICODE"),
        (b"\xef\xbb\xbf{}", "JSON"),
        (b"{", "JSON"),
        (b"{} trailing", "JSON"),
    ]:
        error = rejection(kind, raw, code)
        assert error.__cause__ is not None
    for version in ("2.0", "1.2"):
        variant = copy.deepcopy(doc)
        variant["schema"] = "qaiji.p." + kind + "/" + version
        rejection(kind, canonical(variant), "VERSION", "/schema")
    assert isinstance(load(kind, canonical(doc)), object)


def test_p_transport_attachment_integrity():
    doc = wire_examples()["problem"]
    raw = canonical(doc)
    obj = load("problem", raw)
    artifact = codec().dump_problem(obj, layout="attachments")
    attachments = dict(artifact.attachments)
    key, value = next(iter(attachments.items()))
    bad = dict(attachments)
    bad[key] = bytes([value[0] ^ 1]) + value[1:]
    rejection("problem", artifact.document, "ATTACHMENT_DIGEST", attachments=bad)
    for mapping, code in [
        ({"path": b"a"}, "ATTACHMENT_DIGEST"),
        ({key: "file:///x"}, "JSON_TYPE"),
        ({key: bytearray(value)}, "JSON_TYPE"),
    ]:
        rejection("problem", raw, code, attachments=mapping)
    for token in ("0000000000000000", "8000000000000000", "0000000000000001"):
        doc["drives"][0]["signal"]["value"] = token
        assert dump("problem", load("problem", canonical(doc))) == canonical(doc)
    doc["drives"][1]["signal"]["values"] = dict(dtype="f64le", shape=[0], data="")
    assert dump("problem", load("problem", canonical(doc))) == canonical(doc)
    # 即使字节相同，不同的 shape 或 dtype 仍须保留各自的信封。
    payload = doc["extensions"][0]["payload"]
    payload["same-bytes-real"] = {
        "$p_array": dict(dtype="f64le", shape=[2], data=base64.b64encode(b"\0" * 16).decode())
    }
    payload["same-bytes-complex"] = {
        "$p_array": dict(dtype="c128le", shape=[1], data=base64.b64encode(b"\0" * 16).decode())
    }
    raw = canonical(doc)
    artifact = codec().dump_problem(load("problem", raw), layout="attachments")
    assert (
        dump("problem", load("problem", artifact.document, attachments=dict(artifact.attachments)))
        == raw
    )
    # 摘要正确但长度错误时，必须触发长度守卫。
    doc["signal_edges"] = dict(dtype="f64le", shape=[3], attachment=key)
    rejection("problem", canonical(doc), "BYTE_LENGTH", attachments=attachments)
    nan = struct.pack("<d", float("nan"))
    key = "sha256:" + hashlib.sha256(nan).hexdigest()
    doc["signal_edges"] = dict(dtype="f64le", shape=[1], attachment=key)
    rejection("problem", canonical(doc), "NONFINITE", attachments={key: nan})


@pytest.mark.parametrize("kind", KINDS)
def test_p_dump_rechecks_fields(kind):
    obj = load(kind, canonical(wire_examples()[kind]))
    # 调用 object.__setattr__ 可能篡改 frozen 数据类。
    # dump 必须重新检查这些对象。
    for field in fields(obj):
        changed = copy.deepcopy(obj)
        object.__setattr__(changed, field.name, object())
        with pytest.raises(PContractError):
            dump(kind, changed)
    if kind in ("problem", "request", "result"):
        with pytest.raises(PContractError):
            dump(kind, obj, layout="path")
        with pytest.raises(PContractError) as caught:
            dump(kind, obj, budget=CheckBudget(max_wire_bytes=1))
        assert caught.value.diagnostics[0].code == "BYTES"
        with pytest.raises(PContractError) as caught:
            dump(kind, obj, layout="attachments", budget=CheckBudget(max_attachment_bytes=0))
        assert caught.value.diagnostics[0].code == "ATTACHMENT_BYTES"
    if kind == "problem":
        changed = copy.deepcopy(obj)
        object.__setattr__(changed.drives[1].signal, "value", 0.0)
        with pytest.raises(PContractError) as caught:
            dump(kind, changed)
        assert caught.value.diagnostics[0].path == "/drives/1/signal/value"
        changed = copy.deepcopy(obj)
        object.__setattr__(changed.sites[0], "basis", ("ground",))
        with pytest.raises(PContractError) as caught:
            dump(kind, changed)
        assert caught.value.diagnostics[0].path == "/sites/0/basis"


def test_p_transport_preserves_interpreter_limits():
    recursion = sys.getrecursionlimit()
    digits = sys.get_int_max_str_digits()
    rejection("problem", b"[" * 1500 + b"0" + b"]" * 1500, "DEPTH")
    rejection(
        "problem", b"[" * 1500 + b"0" + b"]" * 1500, "DEPTH", budget=CheckBudget(max_depth=2000)
    )
    rejection("problem", b"9" * 5000, "INTEGER")
    assert sys.getrecursionlimit() == recursion
    assert sys.get_int_max_str_digits() == digits
    # 字节预算检查先于 UTF-8 解码和嵌套深度检查。
    rejection("problem", b"\xff[[[", "BYTES", budget=CheckBudget(max_wire_bytes=1))


def test_p_dump_rejects_incomplete_and_duplicate_frozen_objects():
    from qaiji.core.physical import Problem
    from qaiji.core.physical.arrays import _JSONObject

    with pytest.raises(PContractError) as caught:
        dump("problem", object.__new__(Problem))
    assert caught.value.diagnostics[0].code == "KEYS"
    obj = load("problem", canonical(wire_examples()["problem"]))
    object.__setattr__(obj.extensions[0].payload, "value", _JSONObject((("key", 1), ("key", 2))))
    with pytest.raises(PContractError) as caught:
        dump("problem", obj)
    assert caught.value.diagnostics[0].code == "DUPLICATE"
    assert caught.value.diagnostics[0].path == "/extensions/0/payload/key"


def test_p_transport_escaped_paths_and_nullable_fields():
    doc = wire_examples()["problem"]
    payload = doc["extensions"][0]["payload"]
    payload["a~/b"] = {"key": 1}
    path = ("extensions", 0, "payload", "a~/b")
    rejection(
        "problem", duplicate(doc, path, "key"), "DUPLICATE", "/extensions/0/payload/a~0~1b/key"
    )
    doc = wire_examples()["request"]
    doc["provenance"]["basis_mapping"][0]["logical_bit"] = True
    rejection("request", canonical(doc), "INTEGER", "/provenance/basis_mapping/0/logical_bit")
    doc = wire_examples()["request"]
    doc["policy"]["method"] = dict(mode="fixed", value="exact", allowed=[])
    doc["policy"]["max_step_ns"] = struct.pack(">d", 0.125).hex()
    doc["provenance"] = dict(
        kind="manual",
        program_ref=None,
        binder_version=None,
        device_snapshot=None,
        calibration_snapshot=None,
        basis_mapping=[],
        prior_transforms=[],
    )
    assert dump("request", load("request", canonical(doc))) == canonical(doc)
    doc = wire_examples()["requirements"]
    doc["required_extensions"][0][0] = ""
    rejection("requirements", canonical(doc), "UNICODE", "/required_extensions/0/0")


@pytest.mark.parametrize("kind,path,name", [row for row in BRANCHES if "$p_array" not in row[1]])
def test_p_dump_rechecks_nested_records(kind, path, name):
    doc, options = branch_example(kind, name)
    original = load(kind, canonical(doc), **options)
    target = original
    for key in path:
        target = target[key] if isinstance(key, int) else getattr(target, key)
    for field in fields(target):
        changed = copy.deepcopy(original)
        target = changed
        for key in path:
            target = target[key] if isinstance(key, int) else getattr(target, key)
        object.__setattr__(target, field.name, object())
        with pytest.raises(PContractError):
            dump(kind, changed)


def test_p_transport_snapshots_attachment_mapping():
    from collections.abc import Mapping

    doc = wire_examples()["problem"]
    raw = base64.b64decode(doc["signal_edges"].pop("data"))
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    doc["signal_edges"]["attachment"] = digest

    class ChangingMapping(Mapping):
        def __init__(self):
            self.reads = 0

        def __iter__(self):
            return iter([digest])

        def __len__(self):
            return 1

        def __getitem__(self, key):
            assert key == digest
            self.reads += 1
            return raw if self.reads == 1 else b"\0" * len(raw)

    attachments = ChangingMapping()
    restored = load("problem", canonical(doc), attachments=attachments)
    assert restored.signal_edges.data == raw
    assert attachments.reads == 1


@pytest.mark.parametrize("target", ["array", "json", "budget"])
def test_p_dump_rejects_incomplete_support_objects(target):
    from qaiji.core.physical import ArrayData, FrozenJSON

    obj = load("problem", canonical(wire_examples()["problem"]))
    options = {}
    if target == "array":
        object.__setattr__(obj, "signal_edges", object.__new__(ArrayData))
    elif target == "json":
        object.__setattr__(obj.extensions[0], "payload", object.__new__(FrozenJSON))
    else:
        options["budget"] = object.__new__(CheckBudget)
    with pytest.raises(PContractError) as caught:
        dump("problem", obj, **options)
    assert caught.value.diagnostics[0].code == "KEYS"
