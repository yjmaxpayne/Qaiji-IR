# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Strict P-v1 JSON exchange with explicit, content-addressed attachments."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any, Literal, NoReturn, cast

from . import model as m
from .arrays import ArrayData, FrozenJSON, _JSONArray, _JSONObject
from .diagnostics import CheckBudget, Diagnostic, EncodedArtifact, PContractError, _Category

_DEFAULT_BUDGET = CheckBudget()
_EMPTY_ATTACHMENTS: Mapping[str, bytes] = MappingProxyType({})
_HEX = re.compile(r"[0-9a-f]{16}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")

# Descriptors specify wire types. Constructors enforce model-local constraints.
# Only declared branches enter the wire; nullable fields remain mandatory keys.
_FIELDS: dict[type[Any], dict[str, Any]] = {
    m.Site: dict(id=str, dim=int, basis=("list", str)),
    m.LocalFactor: dict(site=str, matrix=ArrayData),
    m.OperatorTerm: dict(coefficient="c128", factors=("list", m.LocalFactor)),
    m.OperatorSum: dict(unit=str, terms=("list", m.OperatorTerm)),
    m.Signal: dict(kind=str, unit=str, value="f64", values=ArrayData),
    m.Drive: dict(id=str, operator=m.OperatorSum, signal=m.Signal),
    m.Jump: dict(id=str, operator=m.OperatorSum, rate=m.Signal),
    m.Environment: dict(kind=str, jumps=("list", m.Jump)),
    m.ProductFactor: dict(site=str, kind=str, data=ArrayData),
    m.State: dict(kind=str, frame=str, data=ArrayData, factors=("list", m.ProductFactor)),
    m.RequiredExtension: dict(
        namespace=str,
        version=str,
        content_type=str,
        required=bool,
        affects_physics=bool,
        payload=FrozenJSON,
    ),
    m.SnapshotRef: dict(id=str, version=("optional", str), digest=("optional", str)),
    m.BasisMapping: dict(logical_bit=int, site=str, zero_label=str, one_label=str),
    m.Provenance: dict(
        kind=str,
        program_ref=("optional", str),
        binder_version=("optional", str),
        device_snapshot=("optional", m.SnapshotRef),
        calibration_snapshot=("optional", m.SnapshotRef),
        basis_mapping=("list", m.BasisMapping),
        prior_transforms=("list", FrozenJSON),
    ),
    m.Observation: dict(
        id=str,
        kind=str,
        representation=str,
        operator=m.OperatorSum,
        keep_sites=("list", str),
        input_sites=("list", str),
        isometry=ArrayData,
    ),
    m.ObservationValue: dict(
        id=str,
        kind=str,
        representation=str,
        data=ArrayData,
        keep_sites=("list", str),
        input_sites=("list", str),
        block=ArrayData,
        leakage=ArrayData,
        input_trace=ArrayData,
        trace_error=ArrayData,
    ),
    m.MethodChoice: dict(mode=str, value=("optional", str), allowed=("list", str)),
    m.ExecutionPolicy: dict(
        method=m.MethodChoice,
        atol="f64",
        rtol="f64",
        max_step_ns=("optional", "f64"),
        representation=str,
    ),
    m.PolicyDifference: dict(path=str, requested=FrozenJSON, actual=FrozenJSON, basis=str),
    m.TransformRecord: dict(name=str, kind=str, authorization=FrozenJSON),
    m.ExecutionReport: dict(
        backend_id=str,
        backend_version=str,
        actual_policy=FrozenJSON,
        policy_differences=("list", m.PolicyDifference),
        transforms=("list", m.TransformRecord),
        state_representations=FrozenJSON,
        validation_level=str,
        diagnostics=("list", Diagnostic),
    ),
    m.Problem: dict(
        sites=("list", m.Site),
        tensor_order=("list", str),
        h0=m.OperatorSum,
        drives=("list", m.Drive),
        environment=m.Environment,
        initial_state=m.State,
        signal_edges=ArrayData,
        time_unit=str,
        frame=str,
        approximations=("list", str),
        extensions=("list", m.RequiredExtension),
        schema=str,
    ),
    m.Request: dict(
        problem=m.Problem,
        output_times=ArrayData,
        observations=("list", m.Observation),
        policy=m.ExecutionPolicy,
        provenance=m.Provenance,
        schema=str,
    ),
    m.Result: dict(
        request_id=str,
        output_times=ArrayData,
        tensor_order=("list", str),
        frame=str,
        observations=("list", m.ObservationValue),
        report=m.ExecutionReport,
        schema=str,
    ),
    m.Requirements: dict(
        profiles=("list", FrozenJSON),
        dimension=int,
        precision=FrozenJSON,
        required_extensions=("list", ("pair", str)),
        output_kinds=("list", str),
        methods=("list", str),
        schema=str,
    ),
    m.Capabilities: dict(
        consumer_id=str,
        consumer_version=str,
        profiles=("list", FrozenJSON),
        max_dimension=int,
        precision=FrozenJSON,
        required_extensions=("list", ("pair", str)),
        output_kinds=("list", str),
        methods=("list", str),
        schema=str,
    ),
    Diagnostic: dict(category=str, code=str, path=str, message=str, details=FrozenJSON),
}
_BRANCHES: dict[type[Any], dict[str, tuple[str, ...]]] = {
    m.Signal: {"constant": ("kind", "unit", "value"), "zoh": ("kind", "unit", "values")},
    m.State: {
        "ket": ("kind", "frame", "data"),
        "density": ("kind", "frame", "data"),
        "product": ("kind", "frame", "factors"),
    },
    m.Observation: {
        "full_state": ("id", "kind", "representation"),
        "expectation": ("id", "kind", "operator"),
        "partial_trace": ("id", "kind", "keep_sites"),
        "projection": ("id", "kind", "input_sites", "isometry"),
    },
    m.ObservationValue: {
        "full_state": ("id", "kind", "representation", "data"),
        "expectation": ("id", "kind", "data"),
        "partial_trace": ("id", "kind", "keep_sites", "data"),
        "projection": (
            "id",
            "kind",
            "input_sites",
            "block",
            "leakage",
            "input_trace",
            "trace_error",
        ),
    },
}
_SCHEMAS: dict[type[Any], str] = {
    cls: "qaiji.p." + cls.__name__.lower() + "/1.0"
    for cls in (m.Problem, m.Request, m.Result, m.Requirements, m.Capabilities)
}


def _at(path: str, key: str | int) -> str:
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


@dataclass
class _Context:
    category: _Category
    budget: CheckBudget
    attachments: Mapping[str, bytes]

    def fail(
        self,
        code: str,
        path: str,
        message: str,
        *,
        cause: BaseException | None = None,
        details: dict[str, Any] | None = None,
    ) -> NoReturn:
        category: _Category = (
            "RESOURCE_LIMIT" if code in ("BYTES", "DEPTH", "ATTACHMENT_BYTES") else self.category
        )
        diagnostic = Diagnostic(
            category=category,
            code=code,
            path=path,
            message=message,
            details=FrozenJSON(value=cast(Any, details or {})),
        )
        raise PContractError(diagnostics=(diagnostic,)) from cause

    def limit(self, resource: str, required: int, limit: int, code: str) -> None:
        if required > limit:
            self.fail(
                code,
                "",
                "The transport budget was exceeded.",
                details=dict(resource=resource, required=required, limit=limit),
            )

    def construct[T](self, cls: type[T], values: dict[str, Any], path: str) -> T:
        try:
            return cls(**values)
        except PContractError as error:
            diagnostic = error.diagnostics[0]
            self.fail(
                diagnostic.code,
                path + re.sub(r"\[(\d+)\]", r"/\1", diagnostic.path),
                diagnostic.message,
                cause=error,
                details=_thaw(diagnostic.details.value, "", self),
            )


def _context(cls: type[Any], budget: CheckBudget, attachments: Mapping[str, bytes]) -> _Context:
    ctx = _Context(
        "INVALID_RESULT" if cls is m.Result else "INVALID_REQUEST", _DEFAULT_BUDGET, attachments
    )
    if type(budget) is not CheckBudget:
        ctx.fail("JSON_TYPE", "/budget", "Expected CheckBudget.")
    ctx.budget = ctx.construct(
        CheckBudget,
        _attributes(budget, tuple(f.name for f in fields(CheckBudget)), "/budget", ctx),
        "/budget",
    )
    return ctx


@dataclass
class _Pairs:
    items: list[tuple[str, Any]]


@dataclass
class _Number:
    text: str
    code: str = "INTEGER"


def _unicode(text: str, path: str, ctx: _Context) -> str:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as error:
        ctx.fail("UNICODE", path, "Expected Unicode scalar values.", cause=error)
    return text


def _integer(value: Any, path: str, ctx: _Context) -> int:
    if type(value) is not int or not -(1 << 63) <= value < (1 << 63):
        ctx.fail("INTEGER", path, "Expected a signed64 integer.")
    return cast(int, value)


def _materialize(value: Any, path: str, ctx: _Context) -> Any:
    if isinstance(value, _Pairs):
        result: dict[str, Any] = {}
        for key, child in value.items:
            _unicode(key, _at(path, key), ctx)
            if key in result:
                ctx.fail("DUPLICATE", _at(path, key), "Object keys must be unique.")
            result[key] = _materialize(child, _at(path, key), ctx)
        return result
    if isinstance(value, list):
        return [_materialize(child, _at(path, i), ctx) for i, child in enumerate(value)]
    if isinstance(value, _Number):
        if value.code != "INTEGER":
            ctx.fail(value.code, path, "JSON numbers must be signed64 integers.")
        if len(value.text.lstrip("-")) > 19:
            ctx.fail("INTEGER", path, "Expected a signed64 integer.")
        return _integer(int(value.text), path, ctx)
    if isinstance(value, str):
        return _unicode(value, path, ctx)
    return value


def _depth(text: str, ctx: _Context) -> None:
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            ctx.limit("max_depth", depth, ctx.budget.max_depth, "DEPTH")
        elif char in "]}":
            depth -= 1


def _parse(data: bytes, ctx: _Context) -> Any:
    if type(data) is not bytes:
        ctx.fail("JSON_TYPE", "", "Expected bytes.")
    ctx.limit("max_wire_bytes", len(data), ctx.budget.max_wire_bytes, "BYTES")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        ctx.fail("UNICODE", "", "Expected UTF-8 bytes.", cause=error)
    _depth(text, ctx)
    try:
        tree = json.loads(
            text,
            object_pairs_hook=_Pairs,
            parse_int=_Number,
            parse_float=lambda s: _Number(s, "NUMBER_ENCODING"),
            parse_constant=lambda s: _Number(s, "NONFINITE"),
        )
    except (ValueError, TypeError) as error:
        ctx.fail("JSON", "", "Invalid JSON document.", cause=error)
    return _materialize(tree, "", ctx)


def _attachments(ctx: _Context) -> None:
    if not isinstance(ctx.attachments, Mapping):
        ctx.fail("JSON_TYPE", "/attachments", "Expected an explicit attachment mapping.")
    total = 0
    snapshot: dict[str, bytes] = {}
    for digest, data in ctx.attachments.items():
        if type(digest) is not str or not _DIGEST.fullmatch(digest):
            ctx.fail("ATTACHMENT_DIGEST", "/attachments", "Expected a lowercase SHA-256 key.")
        if type(data) is not bytes:
            ctx.fail("JSON_TYPE", _at("/attachments", digest), "Attachment values must be bytes.")
        if digest in snapshot:
            ctx.fail("KEYS", _at("/attachments", digest), "Attachment keys must be unique.")
        snapshot[digest] = data
        total += len(data)
    ctx.limit("max_attachment_bytes", total, ctx.budget.max_attachment_bytes, "ATTACHMENT_BYTES")
    for digest, data in snapshot.items():
        if _digest(data) != digest:
            ctx.fail(
                "ATTACHMENT_DIGEST",
                _at("/attachments", digest),
                "Attachment bytes do not match their digest.",
            )
    ctx.attachments = snapshot


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _keys(value: dict[str, Any], expected: Sequence[str], path: str, ctx: _Context) -> None:
    if set(value) != set(expected):
        ctx.fail(
            "KEYS",
            path,
            "Fields do not match the declared record.",
            details=dict(
                missing=sorted(set(expected) - set(value)), extra=sorted(set(value) - set(expected))
            ),
        )


def _object(value: Any, path: str, ctx: _Context) -> dict[str, Any]:
    if type(value) is not dict:
        ctx.fail("JSON_TYPE", path, "Expected an object.")
    return cast(dict[str, Any], value)


def _record_fields(
    cls: type[Any], value: dict[str, Any], path: str, ctx: _Context
) -> dict[str, Any]:
    all_fields = _FIELDS[cls]
    if cls in _BRANCHES:
        kind = value.get("kind")
        if type(kind) is not str or kind not in _BRANCHES[cls]:
            ctx.fail("KEYS", _at(path, "kind"), "Unknown record branch.")
        return {name: all_fields[name] for name in _BRANCHES[cls][kind]}
    return all_fields


def _finite(value: float, path: str, ctx: _Context) -> float:
    if not math.isfinite(value):
        ctx.fail("NONFINITE", path, "Expected finite binary64 components.")
    return value


def _f64(value: Any, path: str, ctx: _Context) -> float:
    if type(value) is not str or not _HEX.fullmatch(value):
        ctx.fail("BINARY64", path, "Expected 16 lowercase hexadecimal digits.")
    return _finite(struct.unpack(">d", bytes.fromhex(value))[0], path, ctx)


def _array(value: Any, path: str, ctx: _Context) -> ArrayData:
    obj = _object(value, path, ctx)
    key = "attachment" if "attachment" in obj else "data"
    _keys(obj, ("dtype", "shape", key), path, ctx)
    if type(obj["dtype"]) is not str or obj["dtype"] not in ("f64le", "c128le"):
        ctx.fail("DTYPE", _at(path, "dtype"), "Expected dtype f64le or c128le.")
    if type(obj["shape"]) is not list:
        ctx.fail("SHAPE", _at(path, "shape"), "Expected a shape array.")
    for i, size in enumerate(obj["shape"]):
        if type(size) is not int or not 0 <= size < (1 << 63):
            ctx.fail("SHAPE", _at(_at(path, "shape"), i), "Expected a nonnegative signed64 size.")
    if key == "attachment":
        digest = obj[key]
        if type(digest) is not str or not _DIGEST.fullmatch(digest):
            ctx.fail("ATTACHMENT_DIGEST", _at(path, key), "Expected a lowercase SHA-256 digest.")
        if digest not in ctx.attachments:
            ctx.fail(
                "ATTACHMENT_MISSING", _at(path, key), "The caller must supply the attachment bytes."
            )
        data = ctx.attachments[digest]
    else:
        encoded = obj[key]
        if type(encoded) is not str:
            ctx.fail("BASE64", _at(path, key), "Expected a padded base64 string.")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            ctx.fail("BASE64", _at(path, key), "Invalid base64 data.", cause=error)
        if base64.b64encode(data).decode("ascii") != encoded:
            ctx.fail("BASE64", _at(path, key), "Expected canonical padded base64 data.")
    return ctx.construct(ArrayData, dict(dtype=obj["dtype"], shape=obj["shape"], data=data), path)


def _inline(array: ArrayData) -> dict[str, Any]:
    return dict(
        dtype=array.dtype,
        shape=list(array.shape),
        data=base64.b64encode(array.data).decode("ascii"),
    )


def _opaque(value: Any, path: str, ctx: _Context) -> Any:
    if type(value) is dict:
        if "$p_array" in value:
            _keys(value, ("$p_array",), path, ctx)
            return {"$p_array": _inline(_array(value["$p_array"], _at(path, "$p_array"), ctx))}
        return {key: _opaque(child, _at(path, key), ctx) for key, child in value.items()}
    if type(value) is list:
        return [_opaque(child, _at(path, i), ctx) for i, child in enumerate(value)]
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return _integer(value, path, ctx)
    if type(value) is str:
        return _unicode(value, path, ctx)
    ctx.fail("JSON_TYPE", path, "Expected a JSON value with integer numbers.")


def _decode(value: Any, spec: Any, path: str, ctx: _Context) -> Any:
    if isinstance(spec, tuple):
        mode, child = spec
        if mode == "optional":
            return None if value is None else _decode(value, child, path, ctx)
        if type(value) is not list:
            ctx.fail("JSON_TYPE", path, "Expected an array.")
        if mode == "pair" and len(value) != 2:
            ctx.fail("KEYS", path, "Expected exactly two entries.")
        return tuple(_decode(item, child, _at(path, i), ctx) for i, item in enumerate(value))
    if spec == "f64":
        return _f64(value, path, ctx)
    if spec == "c128":
        if type(value) is not list or len(value) != 2:
            ctx.fail("BINARY64", path, "Expected two binary64 components.")
        return complex(_f64(value[0], _at(path, 0), ctx), _f64(value[1], _at(path, 1), ctx))
    if spec is ArrayData:
        return _array(value, path, ctx)
    if spec is FrozenJSON:
        return ctx.construct(FrozenJSON, dict(value=_opaque(value, path, ctx)), path)
    if spec is int:
        return _integer(value, path, ctx)
    if spec in (str, bool):
        if type(value) is not spec:
            ctx.fail("JSON_TYPE", path, "Unexpected field type.")
        return _unicode(value, path, ctx) if spec is str else value
    return _decode_record(value, spec, path, ctx)


def _decode_record[T](value: Any, cls: type[T], path: str, ctx: _Context) -> T:
    obj = _object(value, path, ctx)
    if cls is m.RequiredExtension:
        for name in (
            "namespace",
            "version",
            "content_type",
            "required",
            "affects_physics",
            "payload",
        ):
            if name not in obj:
                ctx.fail(
                    "EXTENSION_ENVELOPE", _at(path, name), "The extension envelope is incomplete."
                )
        if obj["required"] is not True or obj["affects_physics"] is not True:
            ctx.fail("EXTENSION_ENVELOPE", path, "Extensions must be required and affect physics.")
    declared = _record_fields(cls, obj, path, ctx)
    _keys(obj, tuple(declared), path, ctx)
    if cls in _SCHEMAS and obj["schema"] != _SCHEMAS[cls]:
        ctx.fail("VERSION", _at(path, "schema"), "Unexpected schema version.")
    values = {
        name: _decode(obj[name], spec, _at(path, name), ctx) for name, spec in declared.items()
    }
    return ctx.construct(cls, values, path)


def _thaw(value: Any, path: str, ctx: _Context) -> Any:
    if type(value) is _JSONObject:
        result: dict[str, Any] = {}
        for key, child in value.items:
            if type(key) is not str:
                ctx.fail("KEY_TYPE", path, "Object keys must be strings.")
            _unicode(key, _at(path, key), ctx)
            if key in result:
                ctx.fail("DUPLICATE", _at(path, key), "Object keys must be unique.")
            result[key] = _thaw(child, _at(path, key), ctx)
        return result
    if type(value) is _JSONArray:
        return [_thaw(child, _at(path, i), ctx) for i, child in enumerate(value.items)]
    return value


def _attributes(value: Any, names: Sequence[str], path: str, ctx: _Context) -> dict[str, Any]:
    result = {}
    for name in names:
        try:
            result[name] = getattr(value, name)
        except AttributeError as error:
            ctx.fail("KEYS", _at(path, name), "A model field is missing.", cause=error)
    return result


def _encode(value: Any, spec: Any, path: str, ctx: _Context) -> Any:
    if isinstance(spec, tuple):
        mode, child = spec
        if mode == "optional":
            return None if value is None else _encode(value, child, path, ctx)
        if not isinstance(value, Sequence) or isinstance(
            value, (str, bytes, bytearray, memoryview)
        ):
            ctx.fail("JSON_TYPE", path, "Expected a sequence.")
        return [_encode(item, child, _at(path, i), ctx) for i, item in enumerate(value)]
    if spec == "f64":
        if type(value) not in (int, float):
            ctx.fail("BINARY64", path, "Expected a real number.")
        try:
            return struct.pack(">d", _finite(float(value), path, ctx)).hex()
        except OverflowError as error:
            ctx.fail("NONFINITE", path, "Number exceeds binary64 range.", cause=error)
    if spec == "c128":
        if type(value) not in (int, float, complex):
            ctx.fail("BINARY64", path, "Expected a complex number.")
        try:
            number = complex(value)
        except OverflowError as error:
            ctx.fail("NONFINITE", path, "Number exceeds binary64 range.", cause=error)
        return [
            _encode(number.real, "f64", _at(path, 0), ctx),
            _encode(number.imag, "f64", _at(path, 1), ctx),
        ]
    if spec is FrozenJSON:
        if type(value) is not FrozenJSON:
            ctx.fail("JSON_TYPE", path, "Expected FrozenJSON.")
        raw = _attributes(value, ("value",), path, ctx)["value"]
        return _opaque(_thaw(raw, path, ctx), path, ctx)
    if spec is ArrayData:
        if type(value) is not ArrayData:
            ctx.fail("JSON_TYPE", path, "Expected ArrayData.")
        checked = ctx.construct(
            ArrayData, _attributes(value, ("dtype", "shape", "data"), path, ctx), path
        )
        return _inline(checked)
    if spec in (int, str, bool):
        return _decode(value, spec, path, ctx)
    return _encode_record(value, spec, path, ctx)


def _encode_record(value: Any, cls: type[Any], path: str, ctx: _Context) -> dict[str, Any]:
    if type(value) is not cls:
        ctx.fail("JSON_TYPE", path, "Unexpected model type.")
    obj = _attributes(value, tuple(_FIELDS[cls]), path, ctx)
    declared = _record_fields(cls, obj, path, ctx)
    for name in obj.keys() - declared.keys():
        if obj[name] is not None:
            ctx.fail("KEYS", _at(path, name), "Inactive branch fields must be absent.")
    return {name: _encode(obj[name], spec, _at(path, name), ctx) for name, spec in declared.items()}


def _json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _load[T](data: bytes, cls: type[T], attachments: Mapping[str, bytes], budget: CheckBudget) -> T:
    ctx = _context(cls, budget, attachments)
    try:
        obj = _parse(data, ctx)
        _attachments(ctx)
        return _decode_record(obj, cls, "", ctx)
    except RecursionError as error:
        ctx.fail(
            "DEPTH",
            "",
            "The interpreter recursion limit was reached.",
            cause=error,
            details=dict(resource="recursion", required=1, limit=0),
        )


def _externalize(value: Any, attachments: dict[str, bytes]) -> Any:
    if type(value) is dict:
        if set(value) == {"$p_array"}:
            return {"$p_array": _externalize_array(value["$p_array"], attachments)}
        return {key: _externalize(child, attachments) for key, child in value.items()}
    if type(value) is list:
        return [_externalize(child, attachments) for child in value]
    return value


def _externalize_array(obj: dict[str, Any], attachments: dict[str, bytes]) -> dict[str, Any]:
    data = base64.b64decode(obj["data"])
    digest = _digest(data)
    attachments[digest] = data
    return dict(dtype=obj["dtype"], shape=obj["shape"], attachment=digest)


def _layout_record(value: Any, cls: type[Any], attachments: dict[str, bytes]) -> dict[str, Any]:
    # Walk schema descriptors rather than guessing array envelopes from key names.
    return {
        name: _layout_field(child, _FIELDS[cls][name], attachments) for name, child in value.items()
    }


def _layout_field(value: Any, spec: Any, attachments: dict[str, bytes]) -> Any:
    if isinstance(spec, tuple):
        mode, child = spec
        if mode == "optional":
            return None if value is None else _layout_field(value, child, attachments)
        return [_layout_field(item, child, attachments) for item in value]
    if spec is ArrayData:
        return _externalize_array(value, attachments)
    if spec is FrozenJSON:
        return _externalize(value, attachments)
    if spec in _FIELDS:
        return _layout_record(value, spec, attachments)
    return value


def _dump(value: Any, cls: type[Any], layout: str, budget: CheckBudget) -> EncodedArtifact:
    ctx = _context(cls, budget, _EMPTY_ATTACHMENTS)
    if layout not in ("inline", "attachments"):
        ctx.fail("KEYS", "/layout", "Expected layout inline or attachments.")
    try:
        obj = _encode_record(value, cls, "", ctx)
        # Reconstruct every nested record, including tampered frozen instances.
        _decode_record(obj, cls, "", ctx)
        attachments: dict[str, bytes] = {}
        if layout == "attachments":
            obj = _layout_record(obj, cls, attachments)
        document = _json(obj)
        _parse(document, ctx)
        ctx.attachments = attachments
        _attachments(ctx)
        return EncodedArtifact(document=document, attachments=tuple(sorted(attachments.items())))
    except RecursionError as error:
        ctx.fail(
            "DEPTH",
            "",
            "The interpreter recursion limit was reached.",
            cause=error,
            details=dict(resource="recursion", required=1, limit=0),
        )


def load_problem(
    data: bytes,
    *,
    attachments: Mapping[str, bytes] = _EMPTY_ATTACHMENTS,
    budget: CheckBudget = _DEFAULT_BUDGET,
) -> m.Problem:
    return _load(data, m.Problem, attachments, budget)


def load_request(
    data: bytes,
    *,
    attachments: Mapping[str, bytes] = _EMPTY_ATTACHMENTS,
    budget: CheckBudget = _DEFAULT_BUDGET,
) -> m.Request:
    return _load(data, m.Request, attachments, budget)


def load_result(
    data: bytes,
    *,
    attachments: Mapping[str, bytes] = _EMPTY_ATTACHMENTS,
    budget: CheckBudget = _DEFAULT_BUDGET,
) -> m.Result:
    return _load(data, m.Result, attachments, budget)


def dump_problem(
    problem: m.Problem,
    *,
    layout: Literal["inline", "attachments"] = "inline",
    budget: CheckBudget = _DEFAULT_BUDGET,
) -> EncodedArtifact:
    return _dump(problem, m.Problem, layout, budget)


def dump_request(
    request: m.Request,
    *,
    layout: Literal["inline", "attachments"] = "inline",
    budget: CheckBudget = _DEFAULT_BUDGET,
) -> EncodedArtifact:
    return _dump(request, m.Request, layout, budget)


def dump_result(
    result: m.Result,
    *,
    layout: Literal["inline", "attachments"] = "inline",
    budget: CheckBudget = _DEFAULT_BUDGET,
) -> EncodedArtifact:
    return _dump(result, m.Result, layout, budget)


def load_requirements(data: bytes, *, budget: CheckBudget = _DEFAULT_BUDGET) -> m.Requirements:
    return _load(data, m.Requirements, _EMPTY_ATTACHMENTS, budget)


def load_capabilities(data: bytes, *, budget: CheckBudget = _DEFAULT_BUDGET) -> m.Capabilities:
    return _load(data, m.Capabilities, _EMPTY_ATTACHMENTS, budget)


def dump_requirements(requirements: m.Requirements) -> bytes:
    return _dump(requirements, m.Requirements, "inline", _DEFAULT_BUDGET).document


def dump_capabilities(capabilities: m.Capabilities) -> bytes:
    return _dump(capabilities, m.Capabilities, "inline", _DEFAULT_BUDGET).document
