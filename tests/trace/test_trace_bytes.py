# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""T 层编码与孵化期编码逐字节相等。"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from _trace_fixtures import FIXTURE_NAMES, documents

import qaiji.core.trace as trace
from qaiji.core.trace import load_certificate, load_tolerances, load_trace_log

INCUBATION = json.loads((Path(__file__).parent / "data" / "incubation_bytes.json").read_text())
LOADERS: dict[str, Callable[[bytes], object]] = {
    "trace_log": load_trace_log,
    "certificate": load_certificate,
    "tolerances": load_tolerances,
}
DUMPERS = {
    "trace_log": trace.dump_trace_log,
    "certificate": trace.dump_certificate,
    "tolerances": trace.dump_tolerances,
}


def _expected(name: str) -> bytes:
    entry = INCUBATION[name]
    data = base64.b64decode(entry["base64"], validate=True)
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    return data


def _family(name: str) -> str:
    return next(family for family in LOADERS if name.startswith(family))


def test_incubation_fixture_names_are_complete() -> None:
    assert set(INCUBATION) == set(FIXTURE_NAMES)
    assert {_family(name) for name in FIXTURE_NAMES} == set(LOADERS)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_encoding_matches_incubation_bytes(name: str) -> None:
    assert documents(trace)[name] == _expected(name)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_decoding_restores_incubation_bytes(name: str) -> None:
    family = _family(name)
    value = LOADERS[family](_expected(name))
    assert DUMPERS[family](value) == _expected(name)  # type: ignore[operator]
