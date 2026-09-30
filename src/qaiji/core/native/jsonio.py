# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Fixed-schema native JSON with bounded parsing and normalized library errors.

The host's integer-to-string limit may be lower than the schema's 4096 digit
budget. Such reads and writes fail as json_parse and json_encode respectively;
this module never changes process-wide interpreter limits.
"""

from __future__ import annotations

import json
from typing import Any, cast

from .errors import NativeInputError
from .model import (
    ConditionRead,
    ConditionRegion,
    MeasurementEvent,
    NativeOperation,
    NativeScheduleIR,
    RegisterDecl,
    SourceGroup,
    SourceLocation,
    _copy,
)

# None denotes a scalar validated by the value constructor; a one-item tuple
# denotes an array. Object descriptors always name the declared base class.
_SCHEMA: dict[type, dict[str, Any]] = {
    SourceLocation: {"gate_index": None, "body_offset": None},
    RegisterDecl: {"name": None, "size": None},
    NativeOperation: {
        "kind": None,
        "qubits": (None,),
        "params": (None,),
        "source": SourceLocation,
        "ordinal": None,
        "start_ns": None,
        "duration_ns": None,
        "resources": (None,),
        "condition_id": None,
    },
    SourceGroup: {
        "source": SourceLocation,
        "rule_id": None,
        "op_start": None,
        "op_stop": None,
        "phase_rad": None,
    },
    MeasurementEvent: {
        "event_id": None,
        "source": SourceLocation,
        "operation_index": None,
        "qubit": None,
        "register_name": None,
        "bit_index": None,
        "end_ns": None,
        "ready_ns": None,
    },
    ConditionRead: {"bit_index": None, "event_id": None},
    ConditionRegion: {
        "condition_id": None,
        "gate_index": None,
        "register_name": None,
        "width": None,
        "value": None,
        "reads": (ConditionRead,),
        "op_start": None,
        "op_stop": None,
        "start_ns": None,
        "end_ns": None,
    },
    NativeScheduleIR: {
        "schema_version": None,
        "source_kernel_ref": None,
        "num_qubits": None,
        "registers": (RegisterDecl,),
        "ruleset_version": None,
        "operations": (NativeOperation,),
        "groups": (SourceGroup,),
        "events": (MeasurementEvent,),
        "conditions": (ConditionRegion,),
        "end_ns": None,
    },
}


def _depth(text: str) -> None:
    depth = 0
    quoted = False
    escaped = False
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
            if depth > 32:
                raise NativeInputError("json_depth", "$", "JSON nesting exceeds 32 containers.")
        elif char in "]}":
            depth -= 1


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NativeInputError("json_duplicate", "$", "Duplicate JSON object key.")
        result[key] = value
    return result


def _integer(text: str) -> int:
    if len(text.lstrip("-")) > 4096:
        raise NativeInputError("json_integer_limit", "$", "Integer exceeds 4096 digits.")
    return int(text)


def _constant(text: str) -> Any:
    raise NativeInputError("json_number", "$", "Nonfinite JSON numeric constant.")


def _construct(value: Any, descriptor: Any, path: str) -> Any:
    if descriptor is None:
        return value
    if isinstance(descriptor, tuple):
        if type(value) is not list:
            raise NativeInputError("container", path, "Expected a JSON array.")
        return tuple(
            _construct(item, descriptor[0], f"{path}[{index}]") for index, item in enumerate(value)
        )
    if type(value) is not dict:
        raise NativeInputError("container", path, "Expected a JSON object.")
    schema = _SCHEMA[descriptor]
    if value.keys() != schema.keys():
        raise NativeInputError("keys", path, "JSON object fields differ from the schema.")
    kwargs = {
        name: _construct(value[name], child, f"{path}.{name}") for name, child in schema.items()
    }
    try:
        return descriptor(**kwargs)
    except NativeInputError as error:
        raise NativeInputError(error.code, path + error.path[1:], str(error)) from error


def _project(value: Any, descriptor: Any) -> Any:
    if descriptor is None:
        return value
    if isinstance(descriptor, tuple):
        return [_project(item, descriptor[0]) for item in value]
    return {
        name: _project(getattr(value, name), child) for name, child in _SCHEMA[descriptor].items()
    }


def from_json(text: str) -> NativeScheduleIR:
    """Parse an independently complete schedule without assuming an instance shape."""
    if type(text) is not str:
        raise NativeInputError("json_text", "$", "Expected JSON text.")
    _depth(text)
    try:
        value = json.loads(
            text, object_pairs_hook=_pairs, parse_int=_integer, parse_constant=_constant
        )
    except NativeInputError:
        raise
    except RecursionError as error:
        raise NativeInputError("json_depth", "$", "JSON parser recursion limit reached.") from error
    except (ValueError, OverflowError) as error:
        raise NativeInputError(
            "json_parse", "$", "Invalid JSON or parser limit reached."
        ) from error
    return cast(NativeScheduleIR, _construct(value, NativeScheduleIR, "$"))


def to_json(schedule: NativeScheduleIR) -> str:
    """Revalidate declared fields and serialize with stable, lossless numeric encoding."""
    try:
        value = _copy(schedule, NativeScheduleIR, "$")
        return json.dumps(
            _project(value, NativeScheduleIR),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except NativeInputError:
        raise
    except RecursionError as error:
        raise NativeInputError(
            "json_depth", "$", "JSON encoder recursion limit reached."
        ) from error
    except (ValueError, OverflowError) as error:
        raise NativeInputError(
            "json_encode", "$", "JSON encoding failed or reached a limit."
        ) from error
