# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""位级条件在原生调度中的区域、检查与谓词一致性。"""

import json
from dataclasses import replace
from itertools import product

import pytest

from qaiji.core.circuit import Circuit
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.native.config import OperationSpec, QubitResource, ScheduleConfig
from qaiji.core.native.errors import NativeInputError
from qaiji.core.native.jsonio import from_json, to_json
from qaiji.core.native.model import ConditionRead, ConditionRegion
from qaiji.core.native.rules import _expand_source
from qaiji.core.native.scheduler import _schedule_source
from qaiji.core.native.source import _capture_source
from qaiji.core.native.timing import _check_source_layout, _check_timing


def schedule(width, value, bit_index):
    """比特 i 由量子比特 i 测量；测量顺序倒序，各比特结果延迟不同。"""
    register = ClassicalRegister("s", width)
    circuit = Circuit(width)
    circuit.cregs = [register]
    circuit.gates = [Measure(i, ClassicalBit(register, i)) for i in reversed(range(width))]
    circuit.gates.append(Conditional(register, value, (), bit_index=bit_index))
    config = ScheduleConfig(
        qubit_resources=tuple(QubitResource(qubit=i, resource=f"q{i}") for i in range(width)),
        operation_specs=tuple(
            OperationSpec(
                kind="MEASURE",
                qubits=(i,),
                duration_ns=3,
                resources=(f"q{i}",),
                result_latency_ns=5 + 4 * i,
            )
            for i in range(width)
        ),
        cz_couplings=(),
    )
    source = _capture_source(circuit)
    return source, _schedule_source(source, config, _expand_source(source)), config


def source_enters(node, outcome):
    """参考谓词：结果串最右一位是 s[0]。"""
    number = int(outcome, 2)
    if node.bit_index is None:
        return number == node.value
    return (number >> node.bit_index) & 1 == node.value


def region_enters(region, events, outcome):
    """只用区域读取的事件与其比特求值。"""
    bit_of = {event.event_id: event.bit_index for event in events}
    bits = {bit_of[r.event_id]: int(outcome[-1 - bit_of[r.event_id]]) for r in region.reads}
    if region.bit_index is None:
        return sum(bit << index for index, bit in bits.items()) == region.value
    return bits[region.bit_index] == region.value


CASES = [
    *((width, value, None) for width in (1, 2, 3) for value in (0, 1)),
    (2, 3, None),
    (3, 7, None),
    *((width, value, bit) for width in (2, 3) for bit in range(width) for value in (0, 1)),
    (1, 1, 0),
]


@pytest.mark.parametrize(("width", "value", "bit_index"), CASES)
def test_scheduled_region_agrees_with_source_predicate(width, value, bit_index):
    source, scheduled, config = schedule(width, value, bit_index)
    node, region = source.gates[-1], scheduled.conditions[0]
    assert _check_source_layout(source, scheduled).code is None
    assert _check_timing(source, scheduled, config).code is None
    # 位级区域的 width 仍是寄存器宽度。
    assert region.width == width
    for bits in product("01", repeat=width):
        outcome = "".join(bits)
        entered = region_enters(region, scheduled.events, outcome)
        assert entered == source_enters(node, outcome), outcome


def test_bit_order_reads_the_rightmost_character_as_bit_zero():
    source, scheduled, _ = schedule(3, 1, 2)
    region, node = scheduled.conditions[0], source.gates[-1]
    assert [o for o in ("001", "100") if region_enters(region, scheduled.events, o)] == ["100"]
    assert source_enters(node, "100") and not source_enters(node, "001")


@pytest.mark.parametrize("changed", [1, None])
def test_layout_check_flags_changed_bit_index(changed):
    source, scheduled, _ = schedule(3, 1, 2)
    event_of = {event.bit_index: event.event_id for event in scheduled.events}
    bits = range(3) if changed is None else (changed,)
    region = replace(
        scheduled.conditions[0],
        bit_index=changed,
        reads=tuple(ConditionRead(bit_index=bit, event_id=event_of[bit]) for bit in bits),
    )
    check = _check_source_layout(source, replace(scheduled, conditions=(region,)))
    assert (check.code, check.path) == ("source_conditions", "$.conditions[0].bit_index")


def region_fields(**changes):
    fields = dict(
        condition_id="c3",
        gate_index=3,
        register_name="s",
        width=3,
        value=1,
        reads=(ConditionRead(bit_index=2, event_id="m0"),),
        op_start=3,
        op_stop=3,
        start_ns=20,
        end_ns=20,
        bit_index=2,
    )
    fields.update(changes)
    return fields


@pytest.mark.parametrize(
    ("changes", "code", "path"),
    [
        (
            {
                "reads": (
                    ConditionRead(bit_index=1, event_id="m1"),
                    ConditionRead(bit_index=2, event_id="m0"),
                )
            },
            "read_bits",
            "$.reads",
        ),
        ({"reads": (ConditionRead(bit_index=0, event_id="m2"),)}, "read_bits", "$.reads"),
        ({"value": 2}, "condition_value", "$.value"),
        ({"bit_index": 3}, "register_reference", "$.bit_index"),
    ],
)
def test_region_constructor_rejects_inconsistent_bit_reads(changes, code, path):
    assert ConditionRegion(**region_fields()).bit_index == 2
    with pytest.raises(NativeInputError) as error:
        ConditionRegion(**region_fields(**changes))
    assert (error.value.code, error.value.path) == (code, path)


def test_single_bit_region_normalizes_bit_zero():
    single = dict(width=1, reads=(ConditionRead(bit_index=0, event_id="m0"),))
    region = ConditionRegion(**region_fields(bit_index=0, **single))
    assert region.bit_index is None
    assert region == ConditionRegion(**region_fields(bit_index=None, **single))


def test_region_json_writes_bit_index_only_when_set():
    _, bit_level, _ = schedule(3, 0, 1)
    _, whole, _ = schedule(3, 5, None)
    assert json.loads(to_json(bit_level))["conditions"][0]["bit_index"] == 1
    assert from_json(to_json(bit_level)) == bit_level
    document = json.loads(to_json(whole))
    assert "bit_index" not in document["conditions"][0]
    assert from_json(to_json(whole)) == whole
    document["conditions"][0]["bit_index"] = None
    with pytest.raises(NativeInputError) as error:
        from_json(json.dumps(document))
    assert (error.value.code, error.value.path) == ("keys", "$.conditions[0]")
