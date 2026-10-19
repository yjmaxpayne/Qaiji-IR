# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查六类机制的逐项负控与验收集合。"""

import copy
import json
from pathlib import Path

import pytest
from _p_mutations import (
    cases,
    check_acceptance_map,
    check_inventory,
    damage_inventory,
    exercise,
)

DATA = Path(__file__).with_name("data")


@pytest.mark.parametrize("case", cases(), ids=lambda case: case.key)
def test_p_six_internal_mutations(case, monkeypatch, record_property):
    receipt = exercise(case, monkeypatch)
    record_property("mutation_receipt", json.dumps(receipt, sort_keys=True))


@pytest.fixture(scope="module")
def receipts():
    with pytest.MonkeyPatch.context() as patch:
        return [exercise(case, patch) for case in cases()]


def test_p_mutation_inventory(receipts, request):
    inventory = json.loads((DATA / "negative-controls.json").read_text())
    check_inventory(inventory, receipts)
    mapping = json.loads((DATA / "acceptance-map.json").read_text())
    check_acceptance_map(mapping, inventory, {item.nodeid for item in request.session.items})


@pytest.mark.parametrize(
    "variant",
    [
        "remove-family",
        "rename-family",
        "skip-child",
        "wrong-assertion-counted-as-kill",
        "fake-kill-record",
        "extra-child",
        "duplicate-child",
        "import-error",
        "uncollected",
        "skip",
        "xfail",
        "remove-form",
        "remove-catalogue-child",
    ],
)
def test_p_rejects_mutation_inventory(variant, receipts):
    inventory = json.loads((DATA / "negative-controls.json").read_text())
    check_inventory(inventory, receipts)
    broken_inventory, broken_receipts = damage_inventory(inventory, receipts, variant)
    with pytest.raises(AssertionError, match="mutation inventory"):
        check_inventory(broken_inventory, broken_receipts)
    check_inventory(inventory, receipts)


@pytest.mark.parametrize("variant", ["missing-ac", "extra-ac", "missing-child", "wrong-node"])
def test_p_rejects_acceptance_map(variant):
    inventory = json.loads((DATA / "negative-controls.json").read_text())
    mapping = json.loads((DATA / "acceptance-map.json").read_text())
    check_acceptance_map(mapping, inventory)
    broken = copy.deepcopy(mapping)
    if variant == "missing-ac":
        broken.pop()
    elif variant == "extra-ac":
        broken.append(dict(broken[0], ac="AC-99"))
    elif variant == "missing-child":
        broken[0]["children"].clear()
    else:
        broken[0]["nodes"][0] = "tests/physical/test_restore_without_registry.py::invented_test"
    with pytest.raises(AssertionError, match="acceptance map"):
        check_acceptance_map(broken, inventory)
    check_acceptance_map(mapping, inventory)
