# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""独立端口资源记录的身份、严格交换与逐 Play 覆盖契约。"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from dataclasses import FrozenInstanceError, replace
from types import ModuleType

import pytest

from _pulse_fixtures import lower_to_l1, schedule
from qaiji.core.pulse import (
    Play,
    PulseContractError,
    PulseProgramIR,
    native_schedule_ref,
    pulse_program_id,
)


def _api() -> ModuleType:
    name = "qaiji.core.pulse.resources"
    assert importlib.util.find_spec(name) is not None, "Port resource records are not implemented."
    return importlib.import_module(name)


def _mapping(pulse: PulseProgramIR, entries: tuple[tuple[str, tuple[str, ...]], ...]):
    api = _api()
    return api.PortResourceMap(
        pulse_program_ref=pulse_program_id(pulse),
        entries=tuple(api.PortResourceEntry(port=p, resources=r) for p, r in entries),
    )


def _case():
    native = schedule("sx q[0]; cz q[0], q[1]; c[0] = measure q[0]; rz(0.2) q[0];")
    pulse = lower_to_l1(native)
    return native, pulse, _mapping(pulse, (("d0", ("q0",)), ("f01", ("q0", "q1")), ("r0", ("q0",))))


def _diagnostic(code, path, call, *args, category="resources"):
    with pytest.raises(PulseContractError) as caught:
        call(*args)
    (diagnostic,) = caught.value.diagnostics
    assert (diagnostic.category, diagnostic.code, diagnostic.path) == (category, code, path)
    return diagnostic


def test_mapping_canonical_bytes_and_independent_identity() -> None:
    api = _api()
    mapping = api.PortResourceMap(
        pulse_program_ref="sha256:" + "0" * 64,
        entries=(api.PortResourceEntry(port="d0", resources=("q0",)),),
    )
    golden = (
        b'{"entries":[{"port":"d0","resources":["q0"]}],"pulse_program_ref":"sha256:'
        + b"0" * 64
        + b'","schema":"qaiji.port_resources/0.1"}'
    )
    assert api.dump_port_resources(mapping) == golden
    assert api.dump_port_resources(api.load_port_resources(golden)) == golden
    assert (
        api.port_resources_id(mapping)
        == "sha256:" + hashlib.sha256(b"qaiji.port_resources/0.1\0" + golden).hexdigest()
    )
    changed = replace(mapping, entries=(api.PortResourceEntry(port="d0", resources=("q1",)),))
    assert api.port_resources_id(changed) != api.port_resources_id(mapping)
    assert api.port_resources_id(replace(mapping, pulse_program_ref="sha256:" + "1" * 64)) != (
        api.port_resources_id(mapping)
    )


def test_mapping_copies_mutable_inputs_and_is_frozen() -> None:
    api = _api()
    resources = ["q0"]
    entry = api.PortResourceEntry(port="d0", resources=resources)
    entries = [entry]
    mapping = api.PortResourceMap(pulse_program_ref="sha256:" + "0" * 64, entries=entries)
    resources.append("q1")
    entries.clear()
    assert mapping.entries == (entry,)
    assert entry.resources == ("q0",)
    with pytest.raises(FrozenInstanceError):
        mapping.entries = ()
    with pytest.raises(FrozenInstanceError):
        entry.port = "other"


@pytest.mark.parametrize("resources", [(), ("q0", "q0"), ("q1", "q0"), ("",), (True,), "q0"])
def test_entry_rejects_invalid_resource_names(resources) -> None:
    api = _api()
    api.PortResourceEntry(port="d0", resources=("q0",))
    with pytest.raises(PulseContractError):
        api.PortResourceEntry(port="d0", resources=resources)


@pytest.mark.parametrize("ports", [("d1", "d0"), ("d0", "d0")])
def test_entries_require_unique_sorted_ports(ports) -> None:
    api = _api()
    with pytest.raises(PulseContractError):
        api.PortResourceMap(
            pulse_program_ref="sha256:" + "0" * 64,
            entries=tuple(api.PortResourceEntry(port=p, resources=("q0",)) for p in ports),
        )


@pytest.mark.parametrize(
    "ref", [None, True, "sha256:" + "A" * 64, "sha256:0", "sha256:" + "0" * 64 + "\n"]
)
def test_mapping_rejects_malformed_reference(ref) -> None:
    api = _api()
    with pytest.raises(PulseContractError):
        api.PortResourceMap(pulse_program_ref=ref, entries=())


@pytest.mark.parametrize(
    "change,code,path",
    [
        (lambda d: d.update(extra=0), "KEYS", ""),
        (lambda d: d.update(schema="qaiji.port_resources/0.2"), "SCHEMA", "/schema"),
        (lambda d: d.update(entries={}), "JSON_TYPE", "/entries"),
        (lambda d: d["entries"][0].update(extra=0), "KEYS", "/entries/0"),
        (lambda d: d["entries"][0].update(resources=[]), "RESOURCES", "/entries/0/resources"),
        (
            lambda d: d["entries"][0].update(resources=["q0", "q0"]),
            "RESOURCES",
            "/entries/0/resources",
        ),
        (lambda d: d["entries"][0].update(resources="q0"), "JSON_TYPE", "/entries/0/resources"),
    ],
)
def test_mapping_decoder_rejects_invalid_records(change, code, path) -> None:
    api = _api()
    _, _, mapping = _case()
    document = json.loads(api.dump_port_resources(mapping))
    change(document)
    _diagnostic(
        code,
        path,
        api.load_port_resources,
        json.dumps(document).encode(),
        category="INVALID_PROGRAM",
    )


@pytest.mark.parametrize("data", [b'{"schema":0,"schema":1}', b"\xff", b"[]", b'{"x":NaN}'])
def test_mapping_decoder_rejects_invalid_json(data: bytes) -> None:
    with pytest.raises(PulseContractError):
        _api().load_port_resources(data)


def test_all_sourced_plays_are_covered_and_nonplays_are_excluded() -> None:
    native, pulse, mapping = _case()
    api = _api()
    api.check_port_resources(native, pulse, mapping)
    assert {e.port for e in mapping.entries} == {"d0", "f01", "r0"}
    # a0 的 Acquire 与 d1 的 ShiftPhase 不要求新增映射条目。
    native = schedule("c[0] = measure q[0]; rz(0.2) q[1];")
    pulse = lower_to_l1(native)
    api.check_port_resources(native, pulse, _mapping(pulse, (("r0", ("q0",)),)))


def test_reference_mismatch_points_to_mapping_field() -> None:
    native, pulse, mapping = _case()
    api = _api()
    api.check_port_resources(native, pulse, mapping)
    _diagnostic(
        "RESOURCE_REF",
        "/pulse_program_ref",
        api.check_port_resources,
        native,
        pulse,
        replace(mapping, pulse_program_ref="sha256:" + "f" * 64),
    )


def test_unknown_port_points_to_entry_field() -> None:
    native, pulse, mapping = _case()
    api = _api()
    api.check_port_resources(native, pulse, mapping)
    changed = replace(
        mapping, entries=(*mapping.entries, api.PortResourceEntry(port="zz", resources=("q0",)))
    )
    _diagnostic(
        "RESOURCE_PORT", "/entries/3/port", api.check_port_resources, native, pulse, changed
    )


def test_deleted_mapping_points_to_uncovered_play() -> None:
    native, pulse, mapping = _case()
    api = _api()
    api.check_port_resources(native, pulse, mapping)
    changed = replace(mapping, entries=tuple(e for e in mapping.entries if e.port != "f01"))
    index = next(
        i for i, p in enumerate(pulse.instructions) if isinstance(p, Play) and p.frame == "f01"
    )
    _diagnostic(
        "RESOURCE_MISSING",
        f"/instructions/{index}",
        api.check_port_resources,
        native,
        pulse,
        changed,
    )


def test_wrong_resources_point_to_play_and_name_its_index() -> None:
    native, pulse, mapping = _case()
    api = _api()
    api.check_port_resources(native, pulse, mapping)
    changed = replace(
        mapping,
        entries=tuple(
            replace(e, resources=("outside",)) if e.port == "f01" else e for e in mapping.entries
        ),
    )
    index = next(
        i for i, p in enumerate(pulse.instructions) if isinstance(p, Play) and p.frame == "f01"
    )
    diagnostic = _diagnostic(
        "RESOURCE_COVERAGE",
        f"/instructions/{index}",
        api.check_port_resources,
        native,
        pulse,
        changed,
    )
    assert f"Play {index}" in diagnostic.message


def test_each_play_is_checked_when_a_port_has_multiple_sources() -> None:
    api = _api()
    native = schedule("sx q[0]; sx q[1];")
    pulse = lower_to_l1(native)
    # 两个来源共用 d0。第一个来源覆盖 q0，第二个来源只覆盖 q1。
    pulse = replace(pulse, instructions=tuple(replace(p, frame="d0") for p in pulse.instructions))
    mapping = _mapping(pulse, (("d0", ("q0",)),))
    _diagnostic(
        "RESOURCE_COVERAGE", "/instructions/1", api.check_port_resources, native, pulse, mapping
    )


def test_resource_subset_is_valid_and_sourceless_play_is_excluded() -> None:
    api = _api()
    native, pulse, mapping = _case()
    api.check_port_resources(
        native,
        pulse,
        replace(
            mapping,
            entries=tuple(
                replace(e, resources=("q0",)) if e.port == "f01" else e for e in mapping.entries
            ),
        ),
    )
    pulse = replace(
        pulse,
        instructions=tuple(
            replace(p, source=None) if isinstance(p, Play) else p for p in pulse.instructions
        ),
    )
    api.check_port_resources(native, pulse, _mapping(pulse, ()))


def test_mapping_checker_rejects_wrong_schedule_and_out_of_range_source() -> None:
    api = _api()
    native, pulse, mapping = _case()
    wrong = replace(
        native, operations=tuple(replace(op, resources=("foreign",)) for op in native.operations)
    )
    _diagnostic(
        "SCHEDULE_REF",
        "/source_schedule_ref",
        api.check_port_resources,
        wrong,
        pulse,
        mapping,
        category="SCHEDULE_MISMATCH",
    )
    pulse = replace(
        pulse,
        instructions=tuple(
            replace(p, source=len(native.operations)) if isinstance(p, Play) else p
            for p in pulse.instructions
        ),
    )
    index = next(i for i, p in enumerate(pulse.instructions) if isinstance(p, Play))
    _diagnostic(
        "SOURCE",
        f"/instructions/{index}/source",
        api.check_port_resources,
        native,
        pulse,
        _mapping(pulse, ()),
        category="SCHEDULE_MISMATCH",
    )
    assert pulse.source_schedule_ref == native_schedule_ref(native)


def test_mapping_resolves_frame_to_port() -> None:
    api = _api()
    native, pulse, _ = _case()
    pulse = replace(
        pulse,
        frames=tuple(replace(f, id="d0-alias") if f.id == "d0" else f for f in pulse.frames),
        instructions=tuple(
            replace(p, frame="d0-alias") if getattr(p, "frame", None) == "d0" else p
            for p in pulse.instructions
        ),
    )
    mapping = _mapping(pulse, (("d0", ("q0",)), ("f01", ("q0", "q1")), ("r0", ("q0",))))
    api.check_port_resources(native, pulse, mapping)


def test_mapping_records_and_entry_type_boundaries() -> None:
    api = _api()
    for port in ("", True, "\ud800"):
        with pytest.raises(PulseContractError):
            api.PortResourceEntry(port=port, resources=("q0",))
    for entries in ((object(),), "d0"):
        with pytest.raises(PulseContractError):
            api.PortResourceMap(pulse_program_ref="sha256:" + "0" * 64, entries=entries)
    native, pulse, mapping = _case()
    with pytest.raises(TypeError):
        hash(mapping)
    with pytest.raises(TypeError):
        hash(mapping.entries[0])
    for call in (api.dump_port_resources, api.port_resources_id, api.load_port_resources):
        with pytest.raises(PulseContractError):
            call(object())
    for arguments in (
        (object(), pulse, mapping),
        (native, object(), mapping),
        (native, pulse, object()),
    ):
        _diagnostic("TYPE", "", api.check_port_resources, *arguments, category="INVALID_PROGRAM")


def test_decoder_preserves_strict_resource_order_and_unicode_paths() -> None:
    api = _api()
    _, _, mapping = _case()
    document = json.loads(api.dump_port_resources(mapping))
    document["entries"][1]["resources"] = ["q1", "q0"]
    _diagnostic(
        "RESOURCES",
        "/entries/1/resources",
        api.load_port_resources,
        json.dumps(document).encode(),
        category="INVALID_PROGRAM",
    )
    document["entries"][1]["resources"] = ["\ud800"]
    _diagnostic(
        "UNICODE",
        "/entries/1/resources/0",
        api.load_port_resources,
        json.dumps(document).encode(),
        category="INVALID_PROGRAM",
    )
