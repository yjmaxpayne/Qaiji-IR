# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""region 的结构路径标识、父子关系、字段白名单与 L4 注解引用。"""

import dataclasses
import json

import pytest

from _fresh_process import run_fresh_process
from factories import CORRECTED_TWO_ROUND_CODE, LOOP_WITH_CONDITIONAL
from qaiji.codec import from_qasm3, parse_looped_qasm3
from qaiji.core.loop import BoundedLoop, ConditionalTemplate, LoopedCircuit
from qaiji.core.semantics import annotate_circuit
from qaiji.core.semantics.region import Region, annotate_looped, regions_of

# 两个内容相同的顶层条件体；它们之前有 2 个声明（不计位置）与 1 个测量。
TWIN_CONDITIONALS = """OPENQASM 3.0;
qubit[1] q;
bit[1] c;
c[0] = measure q[0];
if (c == 1) { x q[0]; }
if (c == 1) { x q[0]; }
"""

# 顶层条件体（位置 1）含两个门，条件头本身不在条件体内。
TOP_LEVEL_CONDITIONAL = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
bit[1] c;
c[0] = measure q[0];
if (c[0] == 1) { x q[1]; h q[1]; }
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


def _expected_region_id(annotation):
    # 展开后：位置 0 是注入的门，之后每次迭代依次是 14 个循环体节点。
    # 条件头（body_offset 为 None）属于外层循环体，条件体内的门属于条件体。
    if annotation.gate_index == 0:
        return None
    offset = (annotation.gate_index - 1) % BODY_LENGTH
    if offset < 10 or annotation.body_offset is None:
        return LOOP
    return f"{LOOP}/if:{offset}"


def test_annotate_looped_references_the_region_ids():
    """每条注解按展开位置引用 region；其余字段与展开电路上的 annotate_circuit 相同。"""
    circuit = _corrected_code()
    expanded = circuit.expand().circuit
    assert len(expanded.gates) == 1 + 2 * BODY_LENGTH
    annotations = annotate_looped(circuit)
    assert [annotation.region_id for annotation in annotations] == [
        _expected_region_id(annotation) for annotation in annotations
    ]
    assert sum(annotation.region_id == LOOP for annotation in annotations) == 2 * (10 + 4)
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


def _loop_with_conditional(stop):
    circuit = parse_looped_qasm3(LOOP_WITH_CONDITIONAL.format(stop=stop)).circuit
    loop = circuit.operations[1]
    assert isinstance(loop, BoundedLoop)
    assert isinstance(loop.body[1], ConditionalTemplate)
    return circuit


@pytest.mark.parametrize("stop", [-1, 0, 2])
def test_region_set_does_not_depend_on_iteration_count(stop):
    """region 由结构决定：0 次迭代的循环与它的内层条件体也列出。"""
    circuit = _loop_with_conditional(stop)
    assert len(circuit.operations[1].values) == max(0, stop + 1)
    assert regions_of(circuit) == (
        Region(id=LOOP, kind="loop_body", parent=None),
        Region(id=f"{LOOP}/if:1", kind="conditional_body", parent=LOOP),
    )


def test_empty_body_loop_is_a_region():
    """循环体只有声明时没有节点，循环体仍是一个 region。"""
    circuit = parse_looped_qasm3(
        'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[1] q;\nfor int i in [0:1] { bit[1] s; }\n'
    ).circuit
    (loop,) = circuit.operations
    assert isinstance(loop, BoundedLoop)
    assert loop.body == ()
    assert regions_of(circuit) == (Region(id="loop:0", kind="loop_body", parent=None),)


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        pytest.param(
            _corrected_code,
            (
                Region(id=LOOP, kind="loop_body", parent=None),
                *(Region(id=inner, kind="conditional_body", parent=LOOP) for inner in INNER),
            ),
            id="looped",
        ),
        pytest.param(
            lambda: from_qasm3(TWIN_CONDITIONALS),
            (
                Region(id="if:1", kind="conditional_body", parent=None),
                Region(id="if:2", kind="conditional_body", parent=None),
            ),
            id="flat",
        ),
    ],
)
def test_regions_of_reads_structure_without_expanding(monkeypatch, build, expected):
    """列出 region 不展开循环，所以成本与迭代数无关，展开失败也不影响结构查询。"""
    circuit = build()

    def refuse_expansion(self):
        raise AssertionError("regions_of must not expand the circuit")

    monkeypatch.setattr(LoopedCircuit, "expand", refuse_expansion)
    assert regions_of(circuit) == expected


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(_corrected_code, id="two_rounds"),
        pytest.param(lambda: parse_looped_qasm3(TWIN_CONDITIONALS).circuit, id="twins"),
        pytest.param(lambda: _loop_with_conditional(0), id="one_iteration"),
        pytest.param(lambda: _loop_with_conditional(2), id="three_iterations"),
        pytest.param(lambda: parse_looped_qasm3(TOP_LEVEL_CONDITIONAL).circuit, id="header"),
    ],
)
def test_annotated_region_ids_are_listed_regions(build):
    """展开路径与结构路径用同一标识规则：注解引用的标识都在 regions_of 中。"""
    circuit = build()
    referenced = {annotation.region_id for annotation in annotate_looped(circuit)} - {None}
    assert referenced
    assert referenced <= {region.id for region in regions_of(circuit)}


def test_condition_header_annotation_belongs_to_the_parent_region():
    """条件头是经典控制，不在条件体内：顶层条件头为 None，循环内条件头为循环体。"""
    top = annotate_looped(parse_looped_qasm3(TOP_LEVEL_CONDITIONAL).circuit)
    assert [(a.gate_index, a.body_offset, a.region_id) for a in top] == [
        (0, None, None),
        (1, None, None),
        (1, 0, "if:1"),
        (1, 1, "if:1"),
    ]
    inner = annotate_looped(_loop_with_conditional(0))
    assert [(a.gate_index, a.body_offset, a.region_id) for a in inner] == [
        (0, None, None),
        (1, None, LOOP),
        (2, None, LOOP),
        (2, 0, f"{LOOP}/if:1"),
    ]
