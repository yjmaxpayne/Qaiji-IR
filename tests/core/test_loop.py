# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""有界循环容器与展开的契约。"""

import json
import math
import re
from pathlib import Path
from typing import Any

import pytest

from _fresh_process import run_fresh_process
from qaiji import from_qasm3
from qaiji.core._codec import canonical_json, f64_to_hex
from qaiji.core.circuit import Circuit, Gate, GateType
from qaiji.core.classical import ClassicalBit, ClassicalRegister, Conditional, Measure
from qaiji.core.loop import (
    BoundedLoop,
    ConditionalTemplate,
    GateTemplate,
    LoopedCircuit,
    LoopIndex,
    MeasureTemplate,
    OperationProvenance,
    SourceSpan,
)
from qaiji.core.program.validation import compute_kernel_ref
from qaiji.core.semantics.registry import annotate_circuit
from qaiji.core.semantics.summary import build_semantic_summary, canonical_summary_hash
from qaiji.exceptions import LoopedCircuitError, LoopNotExpandedError, QaijiIRError

SPAN = SourceSpan(line=1, column=0, end_line=1, end_column=1)
INDEX = LoopIndex()

# Two-round repetition code: data qubits 0-2, ancilla 3, syndrome register s per round.
SYNDROME_BODY = (
    GateTemplate(GateType.H, (3,)),
    GateTemplate(GateType.CZ, (0, 3)),
    GateTemplate(GateType.CZ, (3, 1)),
    GateTemplate(GateType.H, (3,)),
    MeasureTemplate(3, "s", 0),
    GateTemplate(GateType.H, (3,)),
    GateTemplate(GateType.CZ, (1, 3)),
    GateTemplate(GateType.CZ, (2, 3)),
    GateTemplate(GateType.H, (3,)),
    MeasureTemplate(3, "s", 1),
    ConditionalTemplate("s", 3, (GateTemplate(GateType.X, (0,)),)),
    ConditionalTemplate("s", 1, (GateTemplate(GateType.X, (1,)),)),
    ConditionalTemplate("s", 2, (GateTemplate(GateType.X, (2,)),)),
    ConditionalTemplate("s", 1, (GateTemplate(GateType.X, (3,)),), bit=1),
)
FLAT_ROUND = """h q[3]; cz q[0], q[3]; cz q[3], q[1]; h q[3]; s[0] = measure q[3];
h q[3]; cz q[1], q[3]; cz q[2], q[3]; h q[3]; s[1] = measure q[3];
if (s == 3) { x q[0]; }
if (s == 1) { x q[1]; }
if (s == 2) { x q[2]; }
if (s[1] == 1) { x q[3]; }
"""


def repetition_code(last: int) -> LoopedCircuit:
    loop = BoundedLoop("r", 0, last, (ClassicalRegister("s", 2),), SYNDROME_BODY, SPAN)
    return LoopedCircuit(4, (), (loop,))


def hand_written_flat(rounds: int) -> Circuit:
    text = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[4] q;\n'
    text += "".join(f"bit[2] s__{r};\n" for r in range(rounds))
    for r in range(rounds):
        text += FLAT_ROUND.replace("s[", f"s__{r}[").replace("(s ==", f"(s__{r} ==")
    return from_qasm3(text)


def summary_hash(circuit: Circuit) -> str:
    summary = build_semantic_summary(circuit=circuit, annotations=annotate_circuit(circuit))
    return canonical_summary_hash(summary)


def test_gates_raises_until_the_circuit_is_expanded() -> None:
    looped = repetition_code(1)

    with pytest.raises(LoopNotExpandedError):
        _ = looped.gates
    assert looped.expand().circuit.gates


def test_loop_values_include_both_bounds() -> None:
    assert BoundedLoop("i", 2, 4, (), (), SPAN).values == (2, 3, 4)
    assert BoundedLoop("i", 5, 5, (), (), SPAN).values == (5,)


def test_loop_values_are_empty_when_stop_precedes_start() -> None:
    loop = BoundedLoop("i", 1, 0, (ClassicalRegister("s", 1),), SYNDROME_BODY[:1], SPAN)
    expanded = LoopedCircuit(4, (), (loop,)).expand()

    assert loop.values == ()
    assert expanded.circuit.gates == []
    assert expanded.circuit.cregs == []
    assert expanded.provenance == ()


def test_expanded_register_names_use_the_iteration_number_not_the_loop_value() -> None:
    loop = BoundedLoop(
        "i",
        3,
        4,
        (ClassicalRegister("m", 1),),
        (GateTemplate(GateType.X, (INDEX,)), MeasureTemplate(INDEX, "m", 0)),
        SPAN,
    )
    assert loop.values != tuple(range(len(loop.values)))

    circuit = LoopedCircuit(5, (), (loop,)).expand().circuit

    m0, m1 = ClassicalRegister("m__0", 1), ClassicalRegister("m__1", 1)
    assert circuit.cregs == [m0, m1]
    assert circuit.gates == [
        Gate(GateType.X, (3,)),
        Measure(3, ClassicalBit(m0, 0)),
        Gate(GateType.X, (4,)),
        Measure(4, ClassicalBit(m1, 0)),
    ]


def test_expansion_rejects_a_generated_name_that_is_already_declared() -> None:
    looped = repetition_code(1)
    clashing = LoopedCircuit(4, (ClassicalRegister("s__0", 1),), looped.operations)

    with pytest.raises(LoopedCircuitError, match="s__0"):
        clashing.expand()


def test_expansion_rejects_two_loops_that_declare_the_same_register() -> None:
    loop = repetition_code(0).operations[0]

    with pytest.raises(LoopedCircuitError, match="s__0"):
        LoopedCircuit(4, (), (loop, loop)).expand()


def test_loop_errors_join_the_package_hierarchy() -> None:
    assert issubclass(LoopNotExpandedError, QaijiIRError)
    assert not issubclass(LoopNotExpandedError, ValueError)
    assert issubclass(LoopedCircuitError, QaijiIRError)
    assert issubclass(LoopedCircuitError, ValueError)


def test_provenance_is_aligned_with_gates_and_names_region_and_iteration() -> None:
    flag = ClassicalRegister("c", 1)
    loop = BoundedLoop(
        "i",
        0,
        1,
        (ClassicalRegister("s", 1),),
        (
            GateTemplate(GateType.X, (INDEX,)),
            MeasureTemplate(INDEX, "s", 0),
            ConditionalTemplate("s", 1, (GateTemplate(GateType.X, (INDEX,)),)),
        ),
        SPAN,
    )
    top_conditional = Conditional(flag, 1, (Gate(GateType.Z, (0,)),))
    looped = LoopedCircuit(2, (flag,), (Gate(GateType.H, (0,)), loop, top_conditional))

    expanded = looped.expand()

    assert len(expanded.provenance) == len(expanded.circuit.gates)
    # The first loop-body gate sits at gate index 1 but at body position 0.
    assert expanded.circuit.gates[1] == Gate(GateType.X, (0,))
    assert expanded.provenance == (
        OperationProvenance(None, None),
        OperationProvenance("loop:1", 0),
        OperationProvenance("loop:1", 0),
        OperationProvenance("loop:1/if:2", 0),
        OperationProvenance("loop:1", 1),
        OperationProvenance("loop:1", 1),
        OperationProvenance("loop:1/if:2", 1),
        OperationProvenance("if:2", None),
    )


def test_equality_ignores_the_source_span() -> None:
    other_span = SourceSpan(line=7, column=2, end_line=9, end_column=1)
    loop = repetition_code(1).operations[0]
    assert isinstance(loop, BoundedLoop)
    moved = BoundedLoop(loop.variable, loop.start, loop.stop, loop.registers, loop.body, other_span)

    assert LoopedCircuit(4, (), (moved,)) == repetition_code(1)
    assert repetition_code(2) != repetition_code(1)


def test_expanded_two_round_code_matches_the_hand_written_flat_circuit() -> None:
    circuit = repetition_code(1).expand().circuit
    flat = hand_written_flat(2)

    assert [register.name for register in circuit.cregs] == ["s__0", "s__1"]
    assert sum(isinstance(node, Measure) for node in circuit.gates) == 4
    assert circuit == flat
    assert compute_kernel_ref(circuit) == compute_kernel_ref(flat)
    assert summary_hash(circuit) == summary_hash(flat)


def test_changing_the_upper_bound_changes_the_identity() -> None:
    two_rounds = repetition_code(1).expand().circuit
    three_rounds = repetition_code(2).expand().circuit
    assert len(hand_written_flat(3).gates) != len(hand_written_flat(2).gates)

    assert compute_kernel_ref(three_rounds) != compute_kernel_ref(two_rounds)
    assert summary_hash(three_rounds) != summary_hash(two_rounds)
    assert three_rounds == hand_written_flat(3)


SPAN_A = SourceSpan(line=3, column=5, end_line=7, end_column=11)
SPAN_B = SourceSpan(line=13, column=2, end_line=17, end_column=19)


def rich_looped_circuit() -> LoopedCircuit:
    """Build a program that touches every JSON node kind and breaks ordering regularities."""
    z, a, m = ClassicalRegister("z", 1), ClassicalRegister("a", 2), ClassicalRegister("m", 3)
    body = (
        GateTemplate(GateType.RX, (INDEX,), (0.7,)),
        GateTemplate(GateType.CZ, (0, INDEX)),
        MeasureTemplate(INDEX, "t", INDEX),
        MeasureTemplate(0, "t", 0),
        ConditionalTemplate("t", 1, (GateTemplate(GateType.RZ, (INDEX,), (-1.25,)),), bit=INDEX),
        ConditionalTemplate("a", 0, (GateTemplate(GateType.X, (1,)),)),
    )
    operations = (
        Gate(GateType.U3, (0,), (0.1, -2 * math.pi / 3, 1e-300)),
        Measure(1, ClassicalBit(m, 2)),
        Conditional(a, 3, (Gate(GateType.RY, (2,), (0.3,)),)),
        BoundedLoop("r", 2, 4, (ClassicalRegister("t", 5),), body, SPAN_A),
        Conditional(m, 1, (Gate(GateType.X, (5,)),), bit_index=1),
        BoundedLoop("k", 5, 4, (), (GateTemplate(GateType.H, (INDEX,)),), SPAN_B),
    )
    return LoopedCircuit(6, (z, a, m), operations)


def _node(tree: Any, path: tuple[str | int, ...]) -> Any:
    for key in path:
        tree = tree[key]
    return tree


def test_json_is_canonical_and_names_the_schema() -> None:
    data = rich_looped_circuit().to_json()

    assert data == canonical_json(json.loads(data))
    assert json.loads(data)["schema"] == "qaiji.looped_circuit/0.1"


def _leaves(tree: Any) -> list[Any]:
    if isinstance(tree, dict):
        return [leaf for value in tree.values() for leaf in _leaves(value)]
    if isinstance(tree, list):
        return [leaf for value in tree for leaf in _leaves(value)]
    return [tree]


def test_json_writes_float_parameters_as_binary64_hex() -> None:
    tree = json.loads(rich_looped_circuit().to_json())
    operations = tree["operations"]

    def hexes(*values: float) -> list[str]:
        return [f64_to_hex(value) for value in values]

    assert not [leaf for leaf in _leaves(tree) if isinstance(leaf, float)]
    assert operations[0]["params"] == hexes(0.1, -2 * math.pi / 3, 1e-300)
    assert operations[2]["body"][0]["params"] == hexes(0.3)
    assert operations[3]["body"][0]["params"] == hexes(0.7)
    assert operations[3]["body"][4]["body"][0]["params"] == hexes(-1.25)


def test_json_round_trip_restores_the_circuit_and_spans() -> None:
    original = rich_looped_circuit()
    loop = original.operations[3]
    assert isinstance(loop, BoundedLoop)
    assert loop.start != 0 and loop.stop != loop.start
    data = original.to_json()

    restored = LoopedCircuit.from_json(data)

    assert restored == original
    assert restored.to_json() == data
    spans = [node.span for node in restored.operations if isinstance(node, BoundedLoop)]
    assert spans == [SPAN_A, SPAN_B]
    assert restored.expand() == original.expand()


# Each case names a JSON object inside the encoded rich circuit and a key it must carry.
NODE_KEYS = [
    pytest.param((), "num_qubits", id="circuit"),
    pytest.param(("cregs", 0), "size", id="register"),
    pytest.param(("operations", 0), "params", id="gate"),
    pytest.param(("operations", 1), "bit", id="measure"),
    pytest.param(("operations", 2), "bit", id="conditional"),
    pytest.param(("operations", 3), "stop", id="loop"),
    pytest.param(("operations", 3, "span"), "end_column", id="span"),
    pytest.param(("operations", 3, "body", 0), "qubits", id="gate-template"),
    pytest.param(("operations", 3, "body", 0, "qubits", 0), "kind", id="loop-index"),
    pytest.param(("operations", 3, "body", 2), "register", id="measure-template"),
    pytest.param(("operations", 3, "body", 4), "bit", id="conditional-template"),
]


@pytest.mark.parametrize(("path", "key"), NODE_KEYS)
def test_from_json_rejects_unknown_fields(path: tuple[str | int, ...], key: str) -> None:
    tree = json.loads(rich_looped_circuit().to_json())
    _node(tree, path)["extra_field"] = 0

    with pytest.raises(LoopedCircuitError, match=re.escape("unknown ['extra_field']")):
        LoopedCircuit.from_json(canonical_json(tree))


@pytest.mark.parametrize(("path", "key"), NODE_KEYS)
def test_from_json_rejects_missing_fields(path: tuple[str | int, ...], key: str) -> None:
    tree = json.loads(rich_looped_circuit().to_json())
    del _node(tree, path)[key]

    with pytest.raises(LoopedCircuitError, match=re.escape(f"missing keys ['{key}']")):
        LoopedCircuit.from_json(canonical_json(tree))


def test_from_json_rejects_another_schema() -> None:
    tree = json.loads(rich_looped_circuit().to_json())
    tree["schema"] = "qaiji.looped_circuit/0.2"

    with pytest.raises(LoopedCircuitError, match=re.escape("qaiji.looped_circuit/0.2")):
        LoopedCircuit.from_json(canonical_json(tree))


def test_json_bytes_are_identical_across_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Different hash seeds expose output that follows set order or object identity."""
    here = Path(__file__).resolve().parent
    script = (
        f"import sys; sys.path[:0] = [{str(here)!r}, {str(here.parent)!r}]\n"
        "from test_loop import rich_looped_circuit\n"
        "print(rich_looped_circuit().to_json().hex())\n"
    )
    outputs = []
    for seed in ("1", "2"):
        monkeypatch.setenv("PYTHONHASHSEED", seed)
        outputs.append(run_fresh_process(script).strip())

    assert outputs == [rich_looped_circuit().to_json().hex()] * 2
