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


def _pointer_tokens(path: str) -> tuple[tuple[int, str | int], ...]:
    if path == "":
        return ()
    tokens: list[tuple[int, str | int]] = []
    for raw in path[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if token.isdigit() and (token == "0" or not token.startswith("0")):
            tokens.append((1, int(token)))
        else:
            tokens.append((0, token))
    return tuple(tokens)


def _diagnostic_key(item: Diagnostic) -> tuple[tuple[tuple[int, str | int], ...], str]:
    return (_pointer_tokens(item.path), item.code)


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
