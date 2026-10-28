# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""P 层诊断、检查预算与报告。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, NoReturn, cast

from qaiji.exceptions import QaijiIRError

if TYPE_CHECKING:
    from .arrays import FrozenJSON

type _Category = Literal[
    "INVALID_REQUEST",
    "UNSUPPORTED_CAPABILITY",
    "RESOURCE_LIMIT",
    "SOLVER_FAILURE",
    "INVALID_RESULT",
]
type _Level = Literal["transport", "structure", "physical"]

_CATEGORIES = (
    "INVALID_REQUEST",
    "UNSUPPORTED_CAPABILITY",
    "RESOURCE_LIMIT",
    "SOLVER_FAILURE",
    "INVALID_RESULT",
)
_LEVELS = ("transport", "structure", "physical")
_BUDGET_FIELDS = (
    "max_wire_bytes",
    "max_depth",
    "max_attachment_bytes",
    "max_dense_dimension",
    "max_numeric_elements",
    "max_rational_ops",
    "max_rational_bits",
)


def _fail(
    code: str,
    path: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
    cause: BaseException | None = None,
) -> NoReturn:
    from .arrays import FrozenJSON

    payload: dict[str, Any] = {"code": code}
    if details:
        payload.update(details)
    diagnostic = Diagnostic(
        category="INVALID_REQUEST",
        code=code,
        path=path,
        message=message,
        details=FrozenJSON(value=cast(Any, payload)),
    )
    raise PContractError(diagnostics=(diagnostic,)) from cause


def _set(obj: object, name: str, convert: Any) -> None:
    object.__setattr__(obj, name, convert(getattr(obj, name), "/" + name))


def _text(value: Any, path: str) -> str:
    if type(value) is not str:
        _fail("JSON_TYPE", path, "Expected a string.")
    if not value:
        _fail("UNICODE", path, "Expected nonempty text.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        _fail("UNICODE", path, "Expected Unicode scalar values.", cause=error)
    return value


def _boolean(value: Any, path: str) -> bool:
    if type(value) is not bool:
        _fail("JSON_TYPE", path, "Expected a boolean.")
    return value


def _index(value: Any, path: str) -> int:
    if type(value) is not int:
        _fail("INTEGER", path, "Expected an integer.")
    if value < 0:
        _fail("INTEGER", path, "Expected a nonnegative integer.")
    return value


def _literal(value: Any, allowed: tuple[str, ...], path: str) -> str:
    if type(value) is not str or value not in allowed:
        _fail("KEYS", path, "Expected one of the declared names.")
    return value


def _sequence(value: Any, path: str, convert: Any) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray, memoryview)) or not isinstance(value, Sequence):
        _fail("JSON_TYPE", path, "Expected a sequence.")
    return tuple(convert(item, f"{path}/{index}") for index, item in enumerate(value))


def _texts(value: Any, path: str) -> tuple[str, ...]:
    return _sequence(value, path, _text)


def _diagnostics(value: Any, path: str) -> tuple[Diagnostic, ...]:
    items = _sequence(value, path, _diagnostic)
    return _sorted_diagnostics(items)


def _diagnostic(value: Any, path: str) -> Diagnostic:
    if type(value) is not Diagnostic:
        _fail("JSON_TYPE", path, "Expected Diagnostic.")
    return value


def _pointer(value: Any, path: str) -> str:
    if type(value) is not str:
        _fail("JSON_TYPE", path, "Expected a JSON Pointer string.")
    if value == "":
        return ""
    text = _text(value, path)
    if not text.startswith("/"):
        _fail("JSON", path, "A JSON Pointer must be empty or start with '/'.")
    for token in text[1:].split("/"):
        index = 0
        while index < len(token):
            if token[index] == "~":
                if index + 1 >= len(token) or token[index + 1] not in "01":
                    _fail("JSON", path, "Invalid JSON Pointer escape.")
                index += 2
                continue
            index += 1
    return text


def _is_index_token(token: str) -> bool:
    return token.isascii() and token.isdecimal() and (token == "0" or not token.startswith("0"))


type _PointerToken = tuple[int, str | tuple[int, str]]
type _PathNode = str | tuple[str, str]

# 此表只列出固定容器。标量字段和未知字段的内部均不透明。
_PATH_FIELDS: dict[str, dict[str, _PathNode]] = {
    "problem": {
        "sites": ("array", "site"),
        "tensor_order": ("array", "scalar"),
        "h0": "operator",
        "drives": ("array", "drive"),
        "environment": "environment",
        "initial_state": "state",
        "signal_edges": "array",
        "rotation_freqs": ("array", "pair"),
        "approximations": ("array", "scalar"),
        "extensions": ("array", "extension"),
    },
    "site": {"basis": ("array", "scalar")},
    "operator": {"terms": ("array", "term")},
    "term": {"coefficient": ("array", "scalar"), "factors": ("array", "factor")},
    "factor": {"matrix": "array"},
    "signal": {"values": "array"},
    "drive": {"operator": "operator", "signal": "signal"},
    "jump": {"operator": "operator", "rate": "signal"},
    "environment": {"jumps": ("array", "jump")},
    "state": {"data": "array", "factors": ("array", "product_factor")},
    "product_factor": {"data": "array"},
    "extension": {},
    "observation": {
        "operator": "operator",
        "keep_sites": ("array", "scalar"),
        "input_sites": ("array", "scalar"),
        "isometry": "array",
        "data": "array",
        "block": "array",
        "leakage": "array",
        "input_trace": "array",
        "trace_error": "array",
    },
    "policy": {"method": "method"},
    "method": {"allowed": ("array", "scalar")},
    "provenance": {
        "device_snapshot": "snapshot",
        "calibration_snapshot": "snapshot",
        "basis_mapping": ("array", "basis_mapping"),
        "prior_transforms": ("array", "opaque"),
    },
    "snapshot": {},
    "basis_mapping": {},
    "report": {
        "actual_policy": "actual_policy",
        "policy_differences": ("array", "difference"),
        "transforms": ("array", "transform"),
        "state_representations": ("map", "scalar"),
        "diagnostics": ("array", "diagnostic"),
    },
    "actual_policy": {},
    "difference": {},
    "transform": {"authorization": "authorization"},
    "authorization": {},
    "diagnostic": {},
    "profile": {"output_kinds": ("array", "scalar"), "approximations": ("array", "scalar")},
    "precision": {},
    "array": {"shape": ("array", "scalar")},
}
_PATH_FIELDS["root"] = {
    **_PATH_FIELDS["problem"],
    "problem": "problem",
    "output_times": "array",
    "observations": ("array", "observation"),
    "policy": "policy",
    "provenance": "provenance",
    "report": "report",
    "profiles": ("array", "profile"),
    "precision": "precision",
    "required_extensions": ("array", "pair"),
    "output_kinds": ("array", "scalar"),
    "methods": ("array", "scalar"),
    "shape": ("array", "scalar"),
    "$p_array": "array",
}


def _path_step(node: _PathNode, token: str, hint: str | None) -> tuple[str, _PathNode]:
    if isinstance(node, tuple):
        container, child = node
        if container == "map":
            return "key", child
        if _is_index_token(token):
            return "index", ("array", "scalar") if child == "pair" else child
        return "key", "opaque"
    if node in _PATH_FIELDS:
        return "key", _PATH_FIELDS[node].get(token, "opaque")
    # 数组标记在不透明 JSON 中仍使用固定的传输结构。
    if token == "$p_array":
        return "key", "array"
    return hint or ("index" if _is_index_token(token) else "key"), "opaque"


def _pointer_tokens(path: str, kinds: tuple[str, ...] | None = None) -> tuple[_PointerToken, ...]:
    if path == "":
        return ()
    decoded = tuple(raw.replace("~1", "/").replace("~0", "~") for raw in path[1:].split("/"))
    if kinds is not None and (
        len(kinds) != len(decoded)
        or any(
            kind == "index" and not _is_index_token(token)
            for kind, token in zip(kinds, decoded, strict=False)
        )
    ):
        kinds = None
    tokens: list[_PointerToken] = []
    node: _PathNode = "root"
    for position, token in enumerate(decoded):
        kind, node = _path_step(node, token, kinds[position] if kinds is not None else None)
        if kind == "index":
            # 十进制位数和字典序可比较任意长度的非负下标。
            tokens.append((1, (len(token), token)))
        else:
            tokens.append((0, token))
    return tuple(tokens)


def _path_kinds(item: Diagnostic) -> tuple[str, ...] | None:
    from .arrays import _JSONArray, _JSONObject

    value = item.details.value
    if type(value) is not _JSONObject:
        return None
    hint = dict(value.items).get("path_kinds")
    if type(hint) is not _JSONArray:
        return None
    if not all(type(kind) is str and kind in ("key", "index") for kind in hint.items):
        return None
    return tuple(cast(str, kind) for kind in hint.items)


_STAGES = ("transport", "structure", "capability", "budget", "physical", "result")
_TRANSPORT_CODES = frozenset(
    {
        "UTF8",
        "JSON",
        "DUPLICATE",
        "VERSION",
        "KEYS",
        "KEY_TYPE",
        "JSON_TYPE",
        "INTEGER",
        "NUMBER_ENCODING",
        "BINARY64",
        "NONFINITE",
        "UNICODE",
        "DTYPE",
        "BYTE_LENGTH",
        "BASE64",
        "ATTACHMENT_MISSING",
        "ATTACHMENT_DIGEST",
    }
)
_PHYSICAL_CODES = frozenset({"HERMITIAN", "NORMALIZATION", "PSD", "ISOMETRY"})


def _diagnostic_stage(item: Diagnostic) -> int:
    from .arrays import _JSONObject

    value = item.details.value
    if type(value) is _JSONObject:
        stage = dict(value.items).get("stage")
        if type(stage) is str and stage in _STAGES:
            return _STAGES.index(stage)
    if item.category == "UNSUPPORTED_CAPABILITY":
        return 2
    if item.category == "RESOURCE_LIMIT":
        return 3
    if item.category in {"INVALID_RESULT", "SOLVER_FAILURE"}:
        return 5
    if item.code in _TRANSPORT_CODES:
        return 0
    if item.code in _PHYSICAL_CODES:
        return 4
    return 1


def _diagnostic_key(item: Diagnostic) -> tuple[int, tuple[_PointerToken, ...], str]:
    return (_diagnostic_stage(item), _pointer_tokens(item.path, _path_kinds(item)), item.code)


def _sorted_diagnostics(items: tuple[Diagnostic, ...]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(items, key=_diagnostic_key))


def _bytes(value: Any, path: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        _fail("BYTE_LENGTH", path, "Expected bytes, bytearray or memoryview.")
    try:
        return bytes(value)
    except (TypeError, ValueError) as error:
        _fail("BYTE_LENGTH", path, "The buffer cannot be copied.", cause=error)


def _attachments(value: Any, path: str) -> tuple[tuple[str, bytes], ...]:
    pairs = _sequence(value, path, _attachment)
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        _fail("KEYS", path, "Attachment keys must be unique.")
    return pairs


def _attachment(value: Any, path: str) -> tuple[str, bytes]:
    if isinstance(value, (str, bytes, bytearray, memoryview)) or not isinstance(value, Sequence):
        _fail("JSON_TYPE", path, "Expected a key and byte pair.")
    if len(value) != 2:
        _fail("KEYS", path, "Expected exactly two items.")
    key = _text(value[0], f"{path}/0")
    data = _bytes(value[1], f"{path}/1")
    return (key, data)


@dataclass(frozen=True, slots=True, kw_only=True)
class Diagnostic:
    """一条稳定的契约诊断。"""

    category: _Category
    code: str
    path: str
    message: str
    details: FrozenJSON
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "category", lambda value, path: _literal(value, _CATEGORIES, path))
        _set(self, "code", _text)
        _set(self, "path", _pointer)
        _set(self, "message", _text)
        from .arrays import FrozenJSON

        if type(self.details) is not FrozenJSON:
            _fail("JSON_TYPE", "/details", "Expected FrozenJSON.")


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckBudget:
    """一次检查请求的资源上限。"""

    max_wire_bytes: int = 16777216
    max_depth: int = 32
    max_attachment_bytes: int = 16777216
    max_dense_dimension: int = 64
    max_numeric_elements: int = 1048576
    max_rational_ops: int = 1000000
    max_rational_bits: int = 16384
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        for name in _BUDGET_FIELDS:
            _set(self, name, _index)


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckReport:
    """一次分级检查的结果。"""

    level: _Level
    complete: bool
    diagnostics: tuple[Diagnostic, ...]
    checked: tuple[str, ...]
    unchecked: tuple[str, ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "level", lambda value, path: _literal(value, _LEVELS, path))
        _set(self, "complete", _boolean)
        _set(self, "diagnostics", _diagnostics)
        _set(self, "checked", _texts)
        _set(self, "unchecked", _texts)
        _require_unique(self.checked, "/checked")
        _require_unique(self.unchecked, "/unchecked")


@dataclass(frozen=True, slots=True, kw_only=True)
class EncodedArtifact:
    """规范文档与显式附件。"""

    document: bytes
    attachments: tuple[tuple[str, bytes], ...]
    __hash__: ClassVar[Any] = None

    def __post_init__(self) -> None:
        _set(self, "document", _bytes)
        _set(self, "attachments", _attachments)


class PContractError(QaijiIRError):
    """P 层契约拒绝，携带排序后的不可变诊断序列。"""

    __slots__ = ("diagnostics",)

    def __init__(self, *, diagnostics: Sequence[Diagnostic]) -> None:
        if isinstance(diagnostics, (str, bytes, bytearray, memoryview)) or not isinstance(
            diagnostics, Sequence
        ):
            _fail("JSON_TYPE", "/diagnostics", "Expected a sequence of diagnostics.")
        items = tuple(
            _diagnostic(item, f"/diagnostics/{index}") for index, item in enumerate(diagnostics)
        )
        if not items:
            _fail("KEYS", "/diagnostics", "Expected at least one diagnostic.")
        self.diagnostics = _sorted_diagnostics(items)
        super().__init__(_summary(self.diagnostics))


def _require_unique(values: tuple[str, ...], path: str) -> None:
    if len(set(values)) != len(values):
        _fail("KEYS", path, "Expected unique entries.")


def _summary(items: tuple[Diagnostic, ...]) -> str:
    parts = [f"{item.category}/{item.code} at {item.path or '/'}" for item in items]
    return "P contract violation: " + "; ".join(parts)
