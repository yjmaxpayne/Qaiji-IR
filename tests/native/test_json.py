# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Strict native JSON contracts, independent of the production field table."""

import copy
import importlib
import json
import math
import subprocess
import sys
from dataclasses import fields

import pytest

from _native_fixtures import FIELDS
from qaiji.core.native.errors import NativeInputError
from qaiji.core.native.model import (
    ConditionRead,
    ConditionRegion,
    MeasurementEvent,
    NativeOperation,
    NativeScheduleIR,
    RegisterDecl,
    SourceGroup,
    SourceLocation,
)


def document():
    return {
        "schema_version": "qaiji.native_schedule.v0",
        "ruleset_version": "qaiji.cz_basis.v0",
        "source_kernel_ref": "sha256:" + "a" * 64,
        "num_qubits": 2,
        "registers": [{"name": "r", "size": 1}],
        "operations": [
            {
                "kind": "MEASURE",
                "qubits": [0],
                "params": [],
                "source": {"gate_index": 0, "body_offset": None},
                "ordinal": 0,
                "start_ns": 0,
                "duration_ns": 30,
                "resources": ["readout"],
                "condition_id": None,
            },
            {
                "kind": "RX90",
                "qubits": [1],
                "params": [-0.0],
                "source": {"gate_index": 1, "body_offset": 0},
                "ordinal": 0,
                "start_ns": 40,
                "duration_ns": 20,
                "resources": ["drive"],
                "condition_id": "c1",
            },
        ],
        "groups": [
            {
                "source": {"gate_index": 0, "body_offset": None},
                "rule_id": "cz.v0.MEASURE",
                "op_start": 0,
                "op_stop": 1,
                "phase_rad": -0.0,
            },
            {
                "source": {"gate_index": 1, "body_offset": 0},
                "rule_id": "cz.v0.RX90",
                "op_start": 1,
                "op_stop": 2,
                "phase_rad": 0.25,
            },
        ],
        "events": [
            {
                "event_id": "m0",
                "source": {"gate_index": 0, "body_offset": None},
                "operation_index": 0,
                "qubit": 0,
                "register_name": "r",
                "bit_index": 0,
                "end_ns": 30,
                "ready_ns": 40,
            }
        ],
        "conditions": [
            {
                "condition_id": "c1",
                "gate_index": 1,
                "register_name": "r",
                "width": 1,
                "value": 0,
                "reads": [{"bit_index": 0, "event_id": "m0"}],
                "op_start": 1,
                "op_stop": 2,
                "start_ns": 40,
                "end_ns": 60,
            }
        ],
        "end_ns": 60,
    }


def read(text):
    method = getattr(NativeScheduleIR, "from_json", None)
    assert callable(method), "NativeScheduleIR.from_json must implement the strict JSON boundary"
    return method(text)


def write(value):
    method = getattr(value, "to_json", None)
    assert callable(method), "NativeScheduleIR.to_json must implement fixed-field projection"
    return method()


def reject(text, code, path="$"):
    with pytest.raises(Exception) as caught:
        read(text)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == (code, path)


def nodes(value, trail=()):
    if isinstance(value, dict):
        yield trail, value
        for key, child in value.items():
            yield from nodes(child, (*trail, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from nodes(child, (*trail, index))


def at(value, trail):
    for part in trail:
        value = value[part]
    return value


def path(trail):
    return "$" + "".join(f"[{p}]" if isinstance(p, int) else "." + p for p in trail)


OBJECTS = tuple(trail for trail, _ in nodes(document()))
FIELDS_IN_DOCUMENT = tuple((*trail, key) for trail, obj in nodes(document()) for key in obj)


@pytest.mark.parametrize("trail", OBJECTS, ids=path)
def test_every_object_key_matrix(trail):
    original = at(document(), trail)
    for key in (*original, "unexpected"):
        value = document()
        obj = at(value, trail)
        if key == "unexpected":
            obj[key] = 1
        else:
            del obj[key]
        reject(json.dumps(value), "keys", path(trail))


@pytest.mark.parametrize("trail", FIELDS_IN_DOCUMENT, ids=path)
def test_every_field_type_matrix(trail):
    original = at(document(), trail)
    kind = type(original)
    code = {dict: "container", list: "container", str: "type", int: "integer", float: "number"}.get(
        kind
    )
    if original is None:
        code = "integer" if trail[-1] == "body_offset" else "type"
    for bad in (None, True, "wrong", 1.5, [], {}):
        if bad is None and trail[-1] in ("body_offset", "condition_id"):
            continue
        if kind is list and isinstance(bad, list):
            continue
        if kind is dict and isinstance(bad, dict):
            continue
        if (kind is str or trail[-1] == "condition_id") and isinstance(bad, str):
            continue
        if kind is float and type(bad) is float:
            continue
        value = document()
        at(value, trail[:-1])[trail[-1]] = bad
        reject(json.dumps(value), code, path(trail))


@pytest.mark.parametrize("trail", OBJECTS, ids=path)
def test_duplicate_keys_at_every_object(trail):
    value = document()
    obj = at(value, trail)
    first = next(iter(obj))
    marker = "__duplicate_object_placeholder__"
    duplicate = json.dumps(obj)[:-1] + "," + json.dumps(first) + ":null}"
    if trail:
        at(value, trail[:-1])[trail[-1]] = marker
        text = json.dumps(value).replace(json.dumps(marker), duplicate)
    else:
        text = duplicate
    reject(text, "json_duplicate")


@pytest.mark.parametrize("size", [0, 1, 5])
def test_roundtrip_independent_sizes_and_pretty_input(size):
    value = document()
    if not size:
        value.update(registers=[], operations=[], groups=[], events=[], conditions=[], end_ns=0)
    else:
        value["registers"] += [{"name": f"unused{i}", "size": i + 1} for i in range(size)]
    try:
        recovered = read(json.dumps(value, indent=4))
    except NativeInputError as error:
        assert error is None, "合法非 canonical 空白 JSON 必须接受: " + str(error)
    assert json.loads(write(recovered)) == value
    assert write(recovered) == json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


@pytest.mark.parametrize("digits", [4095, 4096, 4097])
def test_parser_number_boundaries(digits):
    text = json.dumps(document()).replace('"end_ns": 60', '"end_ns": ' + "9" * digits)
    if digits == 4097:
        reject(text, "json_integer_limit")
    else:
        try:
            recovered = read(text)
        except NativeInputError as error:
            assert error is None, "不超过4096位的合法整数必须接受: " + str(error)
        assert recovered.end_ns == 10**digits - 1
    reject("-" + "9" * 4097, "json_integer_limit")


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_parser_nonfinite_constants(literal):
    reject(literal, "json_number")


def test_parser_float_overflow_is_field_error():
    reject(
        json.dumps(document()).replace("-0.0", "1e400", 1), "number", "$.operations[1].params[0]"
    )


@pytest.mark.parametrize("depth", [31, 32, 33])
def test_parser_depth_and_string_escapes(depth):
    reject("[" * depth + "0" + "]" * depth, "json_depth" if depth == 33 else "container")
    value = document()
    value["groups"][0]["rule_id"] = '["\\' * 80 + "]" * 80
    try:
        recovered = read(json.dumps(value))
    except NativeInputError as error:
        assert error is None, "引号内括号与转义不得增加JSON结构深度: " + str(error)
    assert recovered.groups[0].rule_id == value["groups"][0]["rule_id"]


@pytest.mark.parametrize("bad", [None, b"{}", bytearray(b"{}"), 0, [], {}])
def test_parser_requires_text(bad):
    reject(bad, "json_text")


@pytest.mark.parametrize("text", ["", "{", "{]", "[}", "0 trailing"])
def test_parser_invalid_syntax(text):
    reject(text, "json_parse")


@pytest.mark.parametrize("operation", ["loads", "dumps"])
@pytest.mark.parametrize("exception", [ValueError, OverflowError, RecursionError])
def test_parser_and_encoder_exception_normalization(monkeypatch, operation, exception):
    value = read(json.dumps(document()))
    module = importlib.import_module("qaiji.core.native.jsonio")

    def fail(*args, **kwargs):
        raise exception("controlled library failure")

    monkeypatch.setattr(module.json, operation, fail)
    code = (
        "json_depth"
        if exception is RecursionError
        else ("json_parse" if operation == "loads" else "json_encode")
    )
    with pytest.raises(Exception) as caught:
        read("{}") if operation == "loads" else write(value)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == (code, "$")


CLASSES = (
    SourceLocation,
    RegisterDecl,
    NativeOperation,
    SourceGroup,
    MeasurementEvent,
    ConditionRead,
    ConditionRegion,
    NativeScheduleIR,
)


@pytest.mark.parametrize("cls", CLASSES)
def test_subclass_fixed_projection(cls):
    value = read(json.dumps(document()))
    baseline = write(value)

    class Extended(cls):
        pass

    def extend(obj):
        if isinstance(obj, tuple):
            return tuple(extend(item) for item in obj)
        if type(obj) in CLASSES:
            if type(obj) is cls:
                obj = Extended(**{name: getattr(obj, name) for name in FIELDS[cls]})
                object.__setattr__(obj, "extension", "must not leak")
            for field in fields(type(obj)):
                object.__setattr__(obj, field.name, extend(getattr(obj, field.name)))
        return obj

    assert write(extend(value)) == baseline


def test_fresh_process_roundtrip(tmp_path):
    value = document()
    input_path = tmp_path / "schedule.json"
    input_path.write_text(json.dumps(value), encoding="utf-8")
    script = "from pathlib import Path; import sys; from qaiji.core.native.model import NativeScheduleIR; print(NativeScheduleIR.from_json(Path(sys.argv[1]).read_text()).to_json())"
    result = subprocess.run(
        [sys.executable, "-c", script, str(input_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == write(read(json.dumps(value)))


def test_hostile_integer_environment(tmp_path):
    input_path = tmp_path / "large.json"
    input_path.write_text(json.dumps(document()).replace('"end_ns": 60', '"end_ns": ' + "9" * 4096))
    script = """
import sys
from pathlib import Path
from qaiji.core.native.model import NativeScheduleIR
from qaiji.core.native.errors import NativeInputError
text = Path(sys.argv[1]).read_text()
sys.set_int_max_str_digits(0)
value = NativeScheduleIR.from_json(text)
sys.set_int_max_str_digits(640)
for operation, code in [(lambda: NativeScheduleIR.from_json(text), 'json_parse'), (value.to_json, 'json_encode')]:
    try:
        operation()
    except NativeInputError as error:
        assert (error.code, error.path) == (code, '$')
    else:
        raise AssertionError('low integer limit was ignored')
    assert sys.get_int_max_str_digits() == 640
print('ok')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(input_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_signed_zero_roundtrip():
    recovered = read(write(read(json.dumps(document()))))
    assert math.copysign(1.0, recovered.operations[1].params[0]) == -1
    assert math.copysign(1.0, recovered.groups[0].phase_rad) == -1


@pytest.mark.parametrize(
    "trail,bad,code",
    [
        (("operations", 1, "qubits", 0), True, "integer"),
        (("operations", 1, "resources", 0), None, "type"),
        (("operations", 1, "params", 0), True, "number"),
        (("groups", 0, "op_stop"), 9, "group_reference"),
        (("events", 0, "operation_index"), 1, "event_reference"),
        (("conditions", 0, "reads", 0, "event_id"), "absent", "event_reference"),
        (("conditions", 0, "width"), 2, "read_bits"),
        (("operations", 1, "condition_id"), "absent", "condition_reference"),
        (("operations", 1, "qubits", 0), 2, "qubit_range"),
    ],
)
def test_json_parent_graph_and_array_elements(trail, bad, code):
    value = document()
    at(value, trail[:-1])[trail[-1]] = bad
    expected = "$.conditions[0].reads" if code == "read_bits" else path(trail)
    reject(json.dumps(value), code, expected)


def varied_document(width, empty_body):
    value = document()
    measurement, body = value["operations"]
    event = value["events"][0]
    group_measurement, group_body = value["groups"]
    region = value["conditions"][0]
    value.update(num_qubits=width, operations=[], groups=[], events=[], conditions=[])
    value["registers"][0]["size"] = width
    for index in range(width):
        source = {"gate_index": index, "body_offset": None}
        value["operations"].append(measurement | {"source": source, "qubits": [index]})
        value["groups"].append(
            group_measurement | {"source": source, "op_start": index, "op_stop": index + 1}
        )
        value["events"].append(
            event
            | {
                "source": source,
                "operation_index": index,
                "qubit": index,
                "event_id": f"m{index}",
                "bit_index": index,
            }
        )
    for index in range(2):
        gate = width + index
        start = len(value["operations"])
        source = {"gate_index": gate, "body_offset": 0}
        if not empty_body:
            value["operations"].extend(
                body
                | {
                    "source": source,
                    "ordinal": ordinal,
                    "qubits": [index],
                    "condition_id": f"c{gate}",
                    "resources": ["z", "a"],
                }
                for ordinal in range(3)
            )
            value["groups"].append(
                group_body | {"source": source, "op_start": start, "op_stop": start + 3}
            )
        value["conditions"].append(
            region
            | {
                "condition_id": f"c{gate}",
                "gate_index": gate,
                "width": width,
                "reads": [{"bit_index": bit, "event_id": f"m{bit}"} for bit in range(width)],
                "op_start": start,
                "op_stop": len(value["operations"]),
            }
        )
    return value


@pytest.mark.parametrize("width", [2, 4])
@pytest.mark.parametrize("empty_body", [False, True])
def test_general_graph_roundtrip(width, empty_body):
    value = varied_document(width, empty_body)
    recovered = read(json.dumps(value, indent=2))
    assert len(recovered.events) == width
    assert len(recovered.conditions) == 2
    assert all(len(region.reads) == width for region in recovered.conditions)
    assert json.loads(write(recovered)) == value


def test_schema_field_table_matches_independent_declarations():
    module = importlib.import_module("qaiji.core.native.jsonio")
    assert set(module._SCHEMA) == set(CLASSES)
    for cls in CLASSES:
        assert tuple(module._SCHEMA[cls]) == FIELDS[cls]
        assert set(module._SCHEMA[cls]) == {field.name for field in fields(cls)}


def test_public_method_signatures_and_wrong_receiver():
    value = read(json.dumps(document()))
    for call in (
        lambda: NativeScheduleIR.from_json(),
        lambda: NativeScheduleIR.from_json("{}", value),
        lambda: NativeScheduleIR.from_json("{}", shape=value),
        lambda: NativeScheduleIR.from_json(unknown="{}"),
        lambda: value.to_json(1),
        lambda: value.to_json(unknown=1),
    ):
        with pytest.raises(TypeError):
            call()
    with pytest.raises(Exception) as caught:
        NativeScheduleIR.to_json(None)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == ("type", "$")


GRAPH_CASES = [
    ({("registers", 1): {"name": "r", "size": 1}}, "duplicate_register", "$.registers[1].name"),
    ({("groups",): []}, "group_reference", "$.groups"),
    (
        {("groups", 1, "source"): {"gate_index": 0, "body_offset": None}},
        "duplicate_source",
        "$.groups[1].source",
    ),
    (
        {("groups", 0, "op_start"): 1, ("groups", 0, "op_stop"): 2},
        "group_reference",
        "$.groups[0].op_start",
    ),
    ({("groups", 1, "op_stop"): 3}, "group_reference", "$.groups[1].op_stop"),
    ({("operations", 1, "source", "gate_index"): 2}, "group_reference", "$.operations[1].source"),
    ({("operations", 1, "ordinal"): 1}, "group_reference", "$.operations[1].ordinal"),
    ({("events",): []}, "event_reference", "$.events"),
    ({("events", 0, "event_id"): "m1"}, "event", "$.events[0].event_id"),
    ({("events", 0, "operation_index"): 2}, "event_reference", "$.events[0].operation_index"),
    ({("events", 0, "qubit"): 1}, "event_reference", "$.events[0].qubit"),
    ({("events", 0, "source", "gate_index"): 2}, "event_reference", "$.events[0].source"),
    ({("events", 0, "register_name"): "absent"}, "register_reference", "$.events[0].register_name"),
    ({("events", 0, "bit_index"): 1}, "register_reference", "$.events[0].bit_index"),
    ({("conditions",): []}, "condition_reference", "$.operations[1].condition_id"),
    (
        {("conditions", 0, "register_name"): "absent"},
        "register_reference",
        "$.conditions[0].register_name",
    ),
    ({("registers", 0, "size"): 2}, "register_reference", "$.conditions[0].width"),
    ({("conditions", 0, "op_stop"): 3}, "condition_reference", "$.conditions[0].op_stop"),
    (
        {("operations", 1, "condition_id"): None},
        "condition_reference",
        "$.operations[1].condition_id",
    ),
    ({("conditions", 0, "op_stop"): 1}, "condition_reference", "$.operations[1].condition_id"),
    (
        {("conditions", 0, "op_stop"): 1, ("operations", 1, "condition_id"): None},
        "condition_reference",
        "$.operations[1].condition_id",
    ),
    (
        {
            ("conditions", 0, "condition_id"): "c2",
            ("conditions", 0, "gate_index"): 2,
            ("operations", 1, "condition_id"): "c2",
        },
        "condition_reference",
        "$.operations[1].source",
    ),
    (
        {
            ("operations", 1, "source", "body_offset"): None,
            ("groups", 1, "source", "body_offset"): None,
        },
        "condition_reference",
        "$.operations[1].source",
    ),
]


@pytest.mark.parametrize("changes,code,expected_path", GRAPH_CASES)
def test_all_parent_graph_references(changes, code, expected_path):
    value = document()
    for trail, bad in changes.items():
        parent = at(value, trail[:-1])
        if isinstance(parent, list) and trail[-1] == len(parent):
            parent.append(bad)
        else:
            parent[trail[-1]] = bad
    reject(json.dumps(value), code, expected_path)


@pytest.mark.parametrize(
    "field,code,key",
    [
        ("events", "duplicate_event", "event_id"),
        ("conditions", "duplicate_condition", "condition_id"),
    ],
)
def test_duplicate_parent_graph_ids(field, code, key):
    value = document()
    value[field].append(copy.deepcopy(value[field][0]))
    reject(json.dumps(value), code, f"$.{field}[1].{key}")


def test_duplicate_measurement_operation_reference():
    value = document()
    value["events"].append(value["events"][0] | {"event_id": "m1"})
    reject(json.dumps(value), "event_reference", "$.events[1].operation_index")


@pytest.mark.parametrize(
    "trail,bad,code,expected_path",
    [
        (("schema_version",), "unknown", "enum", "$.schema_version"),
        (("ruleset_version",), "unknown", "enum", "$.ruleset_version"),
        (("source_kernel_ref",), "sha256:bad", "ref", "$.source_kernel_ref"),
        (("registers", 0, "name"), "not an identifier", "identifier", "$.registers[0].name"),
        (("operations", 0, "resources"), [], "resources", "$.operations[0].resources"),
        (("operations", 0, "resources"), ["r", "r"], "resources", "$.operations[0].resources"),
        (
            ("operations", 1, "params", 0),
            math.nextafter(math.tau, math.inf),
            "range",
            "$.operations[1].params[0]",
        ),
        (
            ("operations", 1, "params", 0),
            -math.nextafter(math.tau, math.inf),
            "range",
            "$.operations[1].params[0]",
        ),
        (("operations", 0, "duration_ns"), 0, "duration", "$.operations[0].duration_ns"),
        (("operations", 0, "source", "body_offset"), 0, "event", "$.operations[0].source"),
        (("conditions", 0, "value"), 2, "condition_value", "$.conditions[0].value"),
        (("conditions", 0, "condition_id"), "c2", "condition_id", "$.conditions[0].condition_id"),
        (("conditions", 0, "reads", 0, "bit_index"), 1, "read_bits", "$.conditions[0].reads"),
        (("events", 0, "ready_ns"), 29, "event", "$.events[0].ready_ns"),
        (("conditions", 0, "end_ns"), 39, "span", "$.conditions[0].end_ns"),
    ],
)
def test_local_value_domains(trail, bad, code, expected_path):
    value = document()
    at(value, trail[:-1])[trail[-1]] = bad
    reject(json.dumps(value), code, expected_path)


def test_writer_revalidates_nested_value_and_graph():
    value = read(json.dumps(document()))
    object.__setattr__(value.operations[1], "params", (True,))
    with pytest.raises(Exception) as caught:
        write(value)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == ("number", "$.operations[1].params[0]")
    value = read(json.dumps(document()))
    object.__setattr__(value, "events", ())
    with pytest.raises(Exception) as caught:
        write(value)
    assert type(caught.value) is NativeInputError, "拒收必须给出 NativeInputError 诊断"
    assert (caught.value.code, caught.value.path) == ("event_reference", "$.events")


def test_parser_rejects_text_subclass():
    class Text(str):
        pass

    reject(Text(json.dumps(document())), "json_text")


def test_hostile_integer_environment_during_writer_revalidation(tmp_path):
    value = document()
    gate_index = 10**700
    value["conditions"][0].update(gate_index=gate_index, condition_id="c" + str(gate_index))
    value["operations"][1]["condition_id"] = "c" + str(gate_index)
    value["operations"][1]["source"]["gate_index"] = gate_index
    value["groups"][1]["source"]["gate_index"] = gate_index
    input_path = tmp_path / "condition.json"
    input_path.write_text(json.dumps(value), encoding="utf-8")
    script = """
import sys
from pathlib import Path
from qaiji.core.native.model import NativeScheduleIR
from qaiji.core.native.errors import NativeInputError
value = NativeScheduleIR.from_json(Path(sys.argv[1]).read_text())
sys.set_int_max_str_digits(640)
try:
    value.to_json()
except NativeInputError as error:
    assert (error.code, error.path) == ('json_encode', '$')
else:
    raise AssertionError('low integer limit was ignored')
assert sys.get_int_max_str_digits() == 640
print('ok')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(input_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_writer_ascii_and_sequence_order():
    value = varied_document(2, False)
    value["groups"][0]["rule_id"] = "测量"
    recovered = read(json.dumps(value))
    encoded = write(recovered)
    assert encoded.isascii()
    assert encoded == json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    assert recovered.operations[-1].resources == ("z", "a")


@pytest.mark.parametrize("operation", ["loads", "dumps"])
def test_codec_does_not_hide_programming_errors(monkeypatch, operation):
    value = read(json.dumps(document()))
    module = importlib.import_module("qaiji.core.native.jsonio")

    def fail(*args, **kwargs):
        raise TypeError("internal programming error")

    monkeypatch.setattr(module.json, operation, fail)
    with pytest.raises(TypeError, match="internal programming error"):
        read("{}") if operation == "loads" else write(value)


def test_parser_depth_after_escaped_string():
    text = '{"prefix":"quoted\\" and slash\\\\", "nested":' + "[" * 32 + "0" + "]" * 32 + "}"
    reject(text, "json_depth")
