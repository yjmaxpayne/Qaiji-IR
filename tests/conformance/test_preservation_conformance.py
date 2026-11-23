# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""保持性判定的一致性：EXACT 拒绝全局相位 −1，两级都拒绝单比特相对相位；
UP_TO_LOCAL 按 region 判定，通过、失败、不判定 3 类路径各有夹具。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qaiji.codec import parse_looped_qasm3
from qaiji.core.circuit import Circuit
from qaiji.core.semantics.preservation import check_preservation
from qaiji.core.semantics.types import EquivLevel

FIXTURES = json.loads((Path(__file__).with_name("data") / "preservation.json").read_text())
LEVELS = (EquivLevel.EXACT, EquivLevel.UP_TO_PHASE)
LOCAL_CASES = FIXTURES["up_to_local"]
LOCAL_PATHS = {
    "passed": ("passed", EquivLevel.UP_TO_LOCAL),
    "failed": ("failed", None),
    "unsupported": ("unsupported", None),
}


def _circuit(name: str) -> Circuit:
    circuit = Circuit(FIXTURES["num_qubits"])
    for method, *args in FIXTURES[name]:
        getattr(circuit, method)(*args)
    return circuit


def _check(name: str, level: EquivLevel):
    return check_preservation(_circuit("original"), _circuit(name), requested_level=level)


@pytest.mark.parametrize("level", LEVELS, ids=lambda level: level.value)
def test_exact_pass_fixture_passes_at_both_levels(level):
    """别名与偶数整圈不改算符：两级请求都判 EXACT 通过。"""
    summary = _check("exact_pass", level)
    assert (summary.status, summary.equiv_level) == ("passed", EquivLevel.EXACT)


def test_global_phase_violation_fails_exact_only():
    """奇数整圈带来全局相位 −1：EXACT 请求拒绝，UP_TO_PHASE 请求接受。"""
    exact = _check("exact_violation", EquivLevel.EXACT)
    assert (exact.status, exact.equiv_level) == ("unsupported", EquivLevel.UP_TO_PHASE)
    up_to_phase = _check("exact_violation", EquivLevel.UP_TO_PHASE)
    assert (up_to_phase.status, up_to_phase.equiv_level) == (
        "passed",
        EquivLevel.UP_TO_PHASE,
    )


@pytest.mark.parametrize("level", LEVELS, ids=lambda level: level.value)
def test_relative_phase_violation_fails_at_both_levels(level):
    """q2 上 0.37 rad 的相对相位改变算符：两级都拒绝，诊断指向第 2 个位置。"""
    summary = _check("phase_violation", level)
    assert (summary.status, summary.failed_gate_indices, summary.equiv_level) == (
        "unsupported",
        (2,),
        None,
    )


def test_local_region_fixtures_cover_every_path():
    """UP_TO_LOCAL 的 3 类判定路径都要有夹具：通过、失败、不判定。"""
    assert {case["path"] for case in LOCAL_CASES} == set(LOCAL_PATHS)


@pytest.mark.parametrize("case", LOCAL_CASES, ids=lambda case: case["path"])
def test_local_region_fixture_matches_its_path(case):
    """按 region 请求 UP_TO_LOCAL：每条夹具的 (status, equiv_level) 落在它声明的路径上。"""
    original, transformed = (
        parse_looped_qasm3(case[side]).circuit for side in ("original", "transformed")
    )
    summary = check_preservation(
        original, transformed, requested_level=EquivLevel.UP_TO_LOCAL, region=case["region"]
    )
    assert (summary.status, summary.equiv_level) == LOCAL_PATHS[case["path"]]
