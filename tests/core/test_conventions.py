# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""基组下标约定与 RZ 相位约定的可执行守卫。"""

import cmath

import pytest

import qaiji.core.conventions as conventions
from qaiji.exceptions import ConventionViolationError

pytestmark = pytest.mark.physics


def test_declared_conventions_match_the_adapter_contract() -> None:
    assert conventions.QASM3_INDEX_TO_PHYSICAL == {0: "ground", 1: "excited"}
    assert conventions.OPTICS_INDEX_TO_PHYSICAL == {0: "excited", 1: "ground"}
    assert conventions.QASM3_TO_OPTICS_BIT == {0: 1, 1: 0}
    assert conventions.RZ_PHASE_CONVENTION == "exp(-i*theta*Z/2)"


def test_self_check_accepts_the_declared_conventions() -> None:
    assert conventions.self_check() is None


def test_self_check_rejects_identity_bit_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conventions, "QASM3_TO_OPTICS_BIT", {0: 0, 1: 1})

    with pytest.raises(ConventionViolationError):
        conventions.self_check()


def test_self_check_wraps_a_malformed_bit_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conventions, "QASM3_TO_OPTICS_BIT", {0: 1})

    with pytest.raises(ConventionViolationError):
        conventions.self_check()


def test_self_check_rejects_an_inconsistent_physical_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        conventions,
        "OPTICS_INDEX_TO_PHYSICAL",
        {0: "ground", 1: "ground"},
    )

    with pytest.raises(ConventionViolationError):
        conventions.self_check()


def test_self_check_rejects_the_opposite_rz_sign(monkeypatch: pytest.MonkeyPatch) -> None:
    def rz_with_opposite_sign(theta: float) -> tuple[tuple[complex, complex], ...]:
        return (
            (cmath.exp(1j * theta / 2), 0j),
            (0j, cmath.exp(-1j * theta / 2)),
        )

    monkeypatch.setattr(conventions, "_rz", rz_with_opposite_sign)

    with pytest.raises(ConventionViolationError):
        conventions.self_check()
