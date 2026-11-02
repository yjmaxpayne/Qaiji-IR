# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1 严格编解码、内容身份、跨进程稳定性与解码负空间。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from _pulse_fixtures import (
    DRAG,
    FLAT,
    REF,
    acquire,
    lower_to_l1,
    play,
    program,
    rejects,
    schedule,
    shift,
)
from qaiji.core.pulse import (
    Frame,
    Port,
    PulseProgramIR,
    dump_pulse_program,
    load_pulse_program,
    native_schedule_ref,
    pulse_program_id,
)


def full_program() -> PulseProgramIR:
    """覆盖全部记录种类、3 种包络、条件记录、−0.0 与空 source。"""
    return program(
        [
            shift(at_ns=0, delta_rad=-0.0, source=0),
            play(frame="d0", start_ns=0, envelope=DRAG, phase_rad=-1.25, source=1),
            play(frame="f01", start_ns=40, duration_ns=96, envelope=FLAT, amplitude=-0.3),
            acquire(port="a0", start_ns=136, duration_ns=1000, event_id="m0"),
            play(frame="r0", start_ns=136, duration_ns=1000, envelope=FLAT, source=3),
            shift(frame="d1", at_ns=1336, delta_rad=-math.pi, condition_id="c1", source=4),
            shift(frame="d1", at_ns=1336, delta_rad=math.pi, condition_id="c1", source=5),
            play(frame="d1", start_ns=1336, condition_id="c1", source=6),
        ],
        [("c1", 1336, 1376)],
        end_ns=1376,
    )


def test_round_trip() -> None:
    """往返相等，−0.0 的符号位保留。"""
    original = full_program()
    restored = load_pulse_program(dump_pulse_program(original))
    assert restored == original
    assert math.copysign(1.0, restored.instructions[0].delta_rad) == -1.0


GOLDEN = (
    '{"conditions":[{"condition_id":"c1","end_ns":40,"start_ns":0}],"end_ns":40,'
    '"frames":[{"frequency_hz":5000000000,"id":"d0","phase_rad":"0000000000000000","port":"d0"}],'
    '"instructions":[{"at_ns":0,"condition_id":null,"delta_rad":"8000000000000000","frame":"d0",'
    '"kind":"shift_phase","origin":"gate","source":0},{"amplitude":"3fe0000000000000",'
    '"condition_id":null,"duration_ns":40,"envelope":{"beta_ns":"3fe6666666666666",'
    '"rel_sigma":"4014000000000000","shape":"drag"},"frame":"d0","kind":"play",'
    '"phase_rad":"0000000000000000","source":1,"start_ns":0}],'
    '"ports":[{"id":"d0","role":"drive","targets":[0]}],'
    '"schema":"qaiji.pulse/0.1","source_schedule_ref":"sha256:' + "0" * 64 + '"}'
).encode()


def test_dump_golden_bytes() -> None:
    """规范字节与手写金值相同。身份 = sha256(schema + 0 字节 + 规范字节)，由 hashlib 独立计算。"""
    built = PulseProgramIR(
        source_schedule_ref=REF,
        ports=(Port(id="d0", role="drive", targets=(0,)),),
        frames=(Frame(id="d0", port="d0", frequency_hz=5_000_000_000, phase_rad=0.0),),
        instructions=(shift(delta_rad=-0.0, source=0), play(envelope=DRAG, source=1)),
        conditions=(("c1", 0, 40),),
        end_ns=40,
    )
    assert dump_pulse_program(built) == GOLDEN
    expected = hashlib.sha256(b"qaiji.pulse/0.1\x00" + GOLDEN).hexdigest()
    assert pulse_program_id(built) == "sha256:" + expected


_SEED_SCRIPT = """
import json, sys
sys.path.insert(0, {tests!r})
from _pulse_fixtures import play, program
from qaiji.core.pulse import pulse_program_id
built = program([play()])
print(json.dumps([pulse_program_id(built), list({{port.id for port in built.ports}})]))
"""


def test_identity_is_stable_across_hash_seeds() -> None:
    """8 个 PYTHONHASHSEED 的子进程算出同一身份，与本进程相同。"""
    tests = str(Path(__file__).parents[1])
    env = {k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")}
    ids, orders = set(), set()
    for seed in range(8):
        result = subprocess.run(
            [sys.executable, "-c", _SEED_SCRIPT.format(tests=tests)],
            capture_output=True,
            text=True,
            env=env | {"PYTHONHASHSEED": str(seed)},
            check=True,
        )
        identity, order = json.loads(result.stdout)
        ids.add(identity)
        orders.add(tuple(order))
    # 夹具前提：不同种子下 set 的迭代顺序确实不同，否则本用例没有鉴别力。
    assert len(orders) > 1
    assert ids == {pulse_program_id(program([play()]))}


def test_native_schedule_ref() -> None:
    """L2 引用 = sha256(schema_version + 0 字节 + to_json 字节)。不同调度的引用不同。"""
    native = schedule("sx q[0];")
    content = native.schema_version.encode() + b"\x00" + native.to_json().encode()
    assert native_schedule_ref(native) == "sha256:" + hashlib.sha256(content).hexdigest()
    assert native_schedule_ref(schedule("sx q[1];")) != native_schedule_ref(native)
    assert lower_to_l1(native).source_schedule_ref == native_schedule_ref(native)


def _document() -> dict[str, Any]:
    return json.loads(dump_pulse_program(full_program()))


def _mutate(change: Callable[[dict[str, Any]], None]) -> bytes:
    document = _document()
    change(document)
    return json.dumps(document).encode()


def _text(old: str, new: str) -> bytes:
    raw = dump_pulse_program(full_program()).decode()
    assert raw.count(old) == 1
    return raw.replace(old, new).encode()


def _set(path: tuple[Any, ...], value: Any) -> Callable[[dict[str, Any]], None]:
    def change(document: dict[str, Any]) -> None:
        node = document
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return change


def _drop(path: tuple[Any, ...]) -> Callable[[dict[str, Any]], None]:
    def change(document: dict[str, Any]) -> None:
        node = document
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return change


NEGATIVE: list[tuple[str, Callable[[], bytes], str, str]] = [
    ("missing-key", lambda: _mutate(_drop(("end_ns",))), "KEYS", ""),
    ("extra-key", lambda: _mutate(_set(("extra",), 1)), "KEYS", ""),
    (
        "record-missing",
        lambda: _mutate(_drop(("instructions", 1, "source"))),
        "KEYS",
        "/instructions/1",
    ),
    (
        "envelope-extra",
        lambda: _mutate(_set(("instructions", 2, "envelope", "rel_sigma"), "4014000000000000")),
        "KEYS",
        "/instructions/2/envelope",
    ),
    (
        "duplicate-key",
        lambda: _text('"end_ns":1376,"frames"', '"end_ns":1376,"end_ns":1376,"frames"'),
        "DUPLICATE",
        "/end_ns",
    ),
    (
        "hex-nan",
        lambda: _mutate(_set(("instructions", 1, "amplitude"), "7ff8000000000000")),
        "NONFINITE",
        "/instructions/1/amplitude",
    ),
    (
        "hex-inf",
        lambda: _mutate(_set(("frames", 0, "phase_rad"), "7ff0000000000000")),
        "NONFINITE",
        "/frames/0/phase_rad",
    ),
    (
        "nan-literal",
        lambda: _text('"end_ns":1376,"frames"', '"end_ns":NaN,"frames"'),
        "NONFINITE",
        "/end_ns",
    ),
    (
        "json-float",
        lambda: _text('"end_ns":1376,"frames"', '"end_ns":1376.0,"frames"'),
        "NUMBER_ENCODING",
        "/end_ns",
    ),
    (
        "bool-int",
        lambda: _mutate(_set(("instructions", 1, "start_ns"), True)),
        "INTEGER",
        "/instructions/1/start_ns",
    ),
    (
        "upper-hex",
        lambda: _mutate(_set(("instructions", 1, "phase_rad"), "BFF4000000000000")),
        "BINARY64",
        "/instructions/1/phase_rad",
    ),
    ("schema", lambda: _mutate(_set(("schema",), "qaiji.pulse/0.2")), "SCHEMA", "/schema"),
    (
        "duration",
        lambda: _mutate(_set(("instructions", 1, "duration_ns"), 0)),
        "DURATION",
        "/instructions/1/duration_ns",
    ),
    (
        "shift-port",
        lambda: _mutate(_set(("instructions", 0, "frame"), "z0")),
        "SHIFT_PORT",
        "/instructions/0/frame",
    ),
    (
        "condition-phase",
        lambda: _mutate(_set(("instructions", 6, "delta_rad"), "3fd3333333333333")),
        "CONDITION_PHASE",
        "/conditions/0",
    ),
    (
        "frame-ref",
        lambda: _mutate(_set(("instructions", 2, "frame"), "nope")),
        "FRAME_REF",
        "/instructions/2/frame",
    ),
    ("port-ref", lambda: _mutate(_set(("frames", 0, "port"), "zz")), "PORT_REF", "/frames/0/port"),
    (
        "condition-ref",
        lambda: _mutate(_set(("instructions", 2, "condition_id"), "c9")),
        "CONDITION_REF",
        "/instructions/2/condition_id",
    ),
    (
        "order",
        lambda: _mutate(lambda d: d["instructions"].insert(0, d["instructions"].pop(2))),
        "ORDER",
        "/instructions/1",
    ),
    (
        "kind",
        lambda: _mutate(_set(("instructions", 0, "kind"), "delay")),
        "KIND",
        "/instructions/0/kind",
    ),
    (
        "shape",
        lambda: _mutate(_set(("instructions", 2, "envelope", "shape"), "samples")),
        "ENVELOPE",
        "/instructions/2/envelope/shape",
    ),
    ("root-type", lambda: b"[]", "JSON_TYPE", ""),
    ("depth-33", lambda: b"[" * 33 + b"]" * 33, "DEPTH", ""),
    ("depth-5000", lambda: b"[" * 5000 + b"]" * 5000, "DEPTH", ""),
    ("utf8", lambda: b"\xff", "UNICODE", ""),
    ("json", lambda: b"{", "JSON", ""),
]


def test_negative_space_base_document_loads() -> None:
    """正控：负空间用例的基准文档可以解码，且各用例改动的位置符合预期。"""
    document = _document()
    kinds = [item["kind"] for item in document["instructions"]]
    assert kinds[:3] == ["shift_phase", "play", "play"]
    assert document["instructions"][2]["envelope"] == {"shape": "constant"}
    assert document["instructions"][6]["condition_id"] == "c1"
    assert document["frames"][0]["id"] == "d0"
    load_pulse_program(json.dumps(document).encode())


@pytest.mark.parametrize(
    ("data", "code", "path"),
    [case[1:] for case in NEGATIVE],
    ids=[case[0] for case in NEGATIVE],
)
def test_decode_negative_space(data: Callable[[], bytes], code: str, path: str) -> None:
    """每个负例由目标守卫拒收：诊断码与路径都符合预期。"""
    rejects(code, path, load_pulse_program, data())
