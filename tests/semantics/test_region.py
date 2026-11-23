# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""region 的结构路径标识、父子关系、字段白名单与 L4 注解引用。"""

import dataclasses
import json

import pytest

from _fresh_process import run_fresh_process
from qaiji.codec import from_qasm3, parse_looped_qasm3
from qaiji.core.loop import BoundedLoop, ConditionalTemplate
from qaiji.core.semantics import annotate_circuit
from qaiji.core.semantics.region import Region, annotate_looped, regions_of

# 两轮重复码：循环前注入一个错误，循环体在两次症状测量后做 4 个条件纠正。
# 注入使循环位于顶层位置 1；循环体内的声明 `bit[2] s;` 不计位置，
# 10 个门与测量节点之后，4 个条件体位于位置 10 至 13。
CORRECTED_TWO_ROUND_CODE = """OPENQASM 3.0;
include "stdgates.inc";
qubit[4] q;
x q[1];
for int r in [0:1] {
  bit[2] s;
  h q[3]; cz q[0], q[3]; cz q[3], q[1]; h q[3]; s[0] = measure q[3];
  h q[3]; cz q[1], q[3]; cz q[2], q[3]; h q[3]; s[1] = measure q[3];
  if (s == 3) { x q[0]; }
  if (s == 1) { x q[1]; }
  if (s == 2) { x q[2]; }
  if (s[1] == 1) { x q[3]; }
}
"""

# 两个内容相同的顶层条件体；它们之前有 2 个声明（不计位置）与 1 个测量。
TWIN_CONDITIONALS = """OPENQASM 3.0;
qubit[1] q;
bit[1] c;
c[0] = measure q[0];
if (c == 1) { x q[0]; }
if (c == 1) { x q[0]; }
"""

LOOP = "loop:1"
INNER = tuple(f"loop:1/if:{position}" for position in range(10, 14))
BODY_LENGTH = 14


def _corrected_code():
    circuit = parse_looped_qasm3(CORRECTED_TWO_ROUND_CODE).circuit
    injected, loop = circuit.operations
    assert not isinstance(injected, BoundedLoop)
    assert isinstance(loop, BoundedLoop)
    assert len(loop.body) == BODY_LENGTH
    conditional_positions = [
        position for position, node in enumerate(loop.body) if isinstance(node, ConditionalTemplate)
    ]
    assert conditional_positions == [10, 11, 12, 13]
    return circuit


def test_loop_and_inner_conditional_bodies_have_structural_paths():
    """位置按节点计数且不计声明；内层条件体带循环前缀，父 region 是循环体。"""
    regions = regions_of(_corrected_code())
    assert regions == (
        Region(id=LOOP, kind="loop_body", parent=None),
        *(Region(id=inner, kind="conditional_body", parent=LOOP) for inner in INNER),
    )
    assert sum(region.kind == "loop_body" for region in regions) == 1
    assert [region.parent for region in regions if region.kind == "conditional_body"] == [LOOP] * 4


@pytest.mark.parametrize(
    "parse",
    [
        pytest.param(lambda text: parse_looped_qasm3(text).circuit, id="looped"),
        pytest.param(from_qasm3, id="flat"),
    ],
)
def test_top_level_conditional_bodies_have_distinct_ids_and_no_parent(parse):
    """内容相同的两个条件体按位置区分；顶层条件体没有父 region。"""
    flat = from_qasm3(TWIN_CONDITIONALS)
    assert flat.gates[1] == flat.gates[2]
    assert regions_of(parse(TWIN_CONDITIONALS)) == (
        Region(id="if:1", kind="conditional_body", parent=None),
        Region(id="if:2", kind="conditional_body", parent=None),
    )


def test_region_ids_match_in_two_fresh_processes():
    """标识不依赖对象地址或进程内的字符串哈希种子。"""
    script = (
        "import json\n"
        "from qaiji.codec import parse_looped_qasm3\n"
        "from qaiji.core.semantics.region import regions_of\n"
        f"circuit = parse_looped_qasm3({CORRECTED_TWO_ROUND_CODE!r}).circuit\n"
        "print(json.dumps([[r.id, r.kind, r.parent] for r in regions_of(circuit)]))\n"
    )
    first = json.loads(run_fresh_process(script))
    second = json.loads(run_fresh_process(script))
    assert first == second
    assert first == [[r.id, r.kind, r.parent] for r in regions_of(_corrected_code())]


def test_region_fields_are_exactly_id_kind_parent():
    """region 只描述结构位置，不携带条件、寄存器或其他量子控制字段。"""
    assert {field.name for field in dataclasses.fields(Region)} == {"id", "kind", "parent"}


def _expected_region_id(gate_index):
    # 展开后：位置 0 是注入的门，之后每次迭代依次是 14 个循环体节点。
    if gate_index == 0:
        return None
    offset = (gate_index - 1) % BODY_LENGTH
    return LOOP if offset < 10 else f"{LOOP}/if:{offset}"


def test_annotate_looped_references_the_region_ids():
    """每条注解按展开位置引用 region；其余字段与展开电路上的 annotate_circuit 相同。"""
    circuit = _corrected_code()
    expanded = circuit.expand().circuit
    assert len(expanded.gates) == 1 + 2 * BODY_LENGTH
    annotations = annotate_looped(circuit)
    assert [annotation.region_id for annotation in annotations] == [
        _expected_region_id(annotation.gate_index) for annotation in annotations
    ]
    assert {annotation.gate_index for annotation in annotations} == set(range(len(expanded.gates)))
    referenced = {annotation.region_id for annotation in annotations} - {None}
    assert referenced == {region.id for region in regions_of(circuit)}
    assert [dataclasses.replace(a, region_id=None) for a in annotations] == list(
        annotate_circuit(expanded)
    )


def test_annotate_circuit_leaves_region_id_empty():
    """平坦入口不知道 region，注解字段保持默认值。"""
    expanded = _corrected_code().expand().circuit
    assert all(annotation.region_id is None for annotation in annotate_circuit(expanded))
