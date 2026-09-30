# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""冻结的 semantic-IR 句柄：schema 字面量、深度冻结与哈希一致性（AC-Q9）。"""

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from factories import bell_circuit
from qaiji.core.circuit import Circuit
from qaiji.core.semantics.handle import HandleStatus, SemanticIRHandle, freeze_summary
from qaiji.core.semantics.registry import annotate_circuit
from qaiji.core.semantics.summary import build_semantic_summary, canonical_summary_hash


def _summary_for(circuit: Circuit) -> dict:
    return build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))


def test_handle_status_has_exactly_the_four_documented_values() -> None:
    assert {member.value for member in HandleStatus} == {
        "available",
        "planned",
        "omitted",
        "failed",
    }


def test_default_handle_is_planned_with_an_empty_frozen_summary() -> None:
    handle = SemanticIRHandle()

    assert handle.schema_version == "qaiji.semantic_ir_handle.v0"
    assert handle.handle_id is None
    assert handle.producer is None
    assert handle.summary == {}
    assert isinstance(handle.summary, MappingProxyType)
    assert handle.content_hash is None
    assert handle.status is HandleStatus.PLANNED


def test_handle_is_frozen() -> None:
    handle = SemanticIRHandle()

    with pytest.raises(FrozenInstanceError):
        handle.status = HandleStatus.AVAILABLE  # type: ignore[misc]


def test_schema_version_literal_is_enforced() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        SemanticIRHandle(schema_version="qaiji.semantic_ir_handle.v1")


def test_summary_dicts_and_lists_are_deep_frozen_on_construction() -> None:
    handle = SemanticIRHandle(
        summary={"gate_coverage": {"covered": 1, "total_gate_types": 19}, "cregs": [["c", 1]]}
    )

    assert isinstance(handle.summary, MappingProxyType)
    assert isinstance(handle.summary["gate_coverage"], MappingProxyType)
    assert handle.summary["cregs"] == (("c", 1),)
    with pytest.raises(TypeError):
        handle.summary["cregs"] = ()  # type: ignore[index]
    with pytest.raises(AttributeError):
        handle.summary["cregs"].append(("d", 2))  # type: ignore[union-attr]


def test_freeze_summary_is_idempotent_on_an_already_frozen_tree() -> None:
    once = freeze_summary({"a": {"b": [1, 2]}})
    twice = freeze_summary(once)

    assert twice == once
    assert isinstance(twice["a"], MappingProxyType)


def test_freeze_summary_rejects_non_str_keys() -> None:
    with pytest.raises(TypeError):
        freeze_summary({1: "x"})  # type: ignore[dict-item]


def test_freeze_summary_rejects_non_json_compatible_values() -> None:
    with pytest.raises(TypeError):
        freeze_summary({"x": object()})


def test_content_hash_matches_canonical_summary_hash_of_the_frozen_summary() -> None:
    """AC-Q9 的核心承诺：对冻结摘要重新哈希应当复现出 content_hash。"""
    circuit = bell_circuit()
    summary = _summary_for(circuit)
    digest = canonical_summary_hash(summary)

    handle = SemanticIRHandle(
        handle_id=digest,
        producer="qaiji.core.semantics",
        summary=summary,
        content_hash=digest,
        status=HandleStatus.AVAILABLE,
    )

    assert canonical_summary_hash(handle.summary) == handle.content_hash
