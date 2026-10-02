# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""跨库证伪的纯函数：受限求值器与判据。

快照内容只被 AST 解析、从不 ``exec`` / ``eval``；白名单外的构造一律抛 ``UnsupportedEvidenceError``。
"""

import ast
import cmath
import enum
import itertools
import math
import re
import textwrap
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from _optics_snapshot import Fact

import qaiji.core.conventions as conventions
from qaiji.constants import DEFAULT_TOLERANCE

type Matrix2 = tuple[tuple[complex, complex], tuple[complex, complex]]
type Facts = Mapping[str, Fact]
type Check = Callable[[Facts, tuple[float, ...]], str | None]

NON_DEGENERATE_THETAS = (0.7, 1.1, math.pi, -0.3)

COUNTERPART_CALLEES = ("_semantic_parameter", "_assemble")
"""求值器当作已知语义（恒等透传）调用的对方方法；每个都必须有一条事实钉住。"""

_BINARY: dict[type[ast.operator], Callable[[complex, complex], complex]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}


class UnsupportedEvidenceError(ValueError):
    """快照中出现了受限求值器白名单之外的构造。"""


def _unsupported(node: ast.AST) -> UnsupportedEvidenceError:
    return UnsupportedEvidenceError(f"unsupported evidence: {ast.unparse(node)[:80]}")


def _is_self(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "self"


def _is_gate_attribute(node: ast.expr, attr: str | None = None) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Gate"
        and node.attr in ({attr} if attr else {"dtype", "device"})
    )


def _gate_keywords_only(call: ast.Call) -> bool:
    # 只放行 dtype=Gate.dtype / device=Gate.device：换成 float32 之类会静默降精度。
    return all(
        keyword.arg in {"dtype", "device"} and _is_gate_attribute(keyword.value, keyword.arg)
        for keyword in call.keywords
    )


def _torch_call(node: ast.AST, name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "torch"
        and node.func.attr == name
    )


def _scalar(value: Any, node: ast.AST) -> complex:
    # 四则运算与 exp 只作用于标量：张量上的逐元素语义与 Python 序列的拼接/重复不同。
    if not isinstance(value, complex):
        raise _unsupported(node)
    return value


def _evaluate(node: ast.expr, env: dict[str, complex]) -> Any:
    match node:
        case ast.Constant(value=bool()):
            raise _unsupported(node)
        case ast.Constant(value=int() | float() | complex() as value):
            return complex(value)
        case ast.Name(id=name) if name in env:
            return env[name]
        case ast.List(elts=items) | ast.Tuple(elts=items):
            return tuple(_evaluate(item, env) for item in items)
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            return -_scalar(_evaluate(operand, env), node)
        case ast.BinOp(left=left, op=op, right=right) if type(op) in _BINARY:
            return _BINARY[type(op)](
                _scalar(_evaluate(left, env), node), _scalar(_evaluate(right, env), node)
            )
        case ast.Call(args=[literal]) if _torch_call(node, "tensor") and _gate_keywords_only(node):
            return _evaluate(literal, env)
        case ast.Call(args=[ast.Tuple(elts=[])]) if (
            _torch_call(node, "zeros") or _torch_call(node, "ones")
        ) and _gate_keywords_only(node):
            return 0j if _torch_call(node, "zeros") else 1 + 0j
        case ast.Call(args=[rows], keywords=[]) if _torch_call(node, "stack"):
            # 任何关键字都拒收：dim=1 会把行堆成列，等于静默转置。
            return _evaluate(rows, env)
        case ast.Call(args=[exponent], keywords=[]) if _torch_call(node, "exp"):
            return cmath.exp(_scalar(_evaluate(exponent, env), node))
        case ast.Call(func=ast.Attribute(value=inner, attr="to"), args=args) if (
            (args or node.keywords)
            and all(_is_gate_attribute(arg) for arg in args)
            and _gate_keywords_only(node)
        ):
            return _evaluate(inner, env)
        case ast.Call(
            func=ast.Attribute(value=owner, attr="_semantic_parameter"),
            args=[ast.Constant(value=str()), value],
            keywords=[],
        ) if _is_self(owner):
            return _evaluate(value, env)
    raise _unsupported(node)


def _as_matrix2(value: Any, node: ast.AST) -> Matrix2:
    if not (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(row, tuple) and len(row) == 2 for row in value)
    ):
        raise _unsupported(node)
    (a, b), (c, d) = value
    return (_scalar(a, node), _scalar(b, node)), (_scalar(c, node), _scalar(d, node))


def _init_of_single_class(fact: Fact) -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(fact.verbatim))
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    if len(classes) != 1:
        raise UnsupportedEvidenceError(f"{fact.fact_id}: expected 1 class, found {len(classes)}")
    (cls,) = classes
    match cls:
        case ast.ClassDef(bases=[ast.Name(id="Gate")], keywords=[], decorator_list=[]):
            pass
        case _:
            raise UnsupportedEvidenceError(f"{fact.fact_id}: class must plainly subclass Gate")
    # 类体里重写的方法（例如 _assemble）会绕过事实钉住的那一份，所以只放行 __init__ 与 __str__。
    members = cls.body[1:] if ast.get_docstring(cls) is not None else cls.body
    if not all(
        isinstance(m, ast.FunctionDef) and m.name in {"__init__", "__str__"} for m in members
    ):
        raise UnsupportedEvidenceError(
            f"{fact.fact_id}: class may only define __init__ and __str__"
        )
    inits = [m for m in members if isinstance(m, ast.FunctionDef) and m.name == "__init__"]
    if len(inits) != 1:
        raise UnsupportedEvidenceError(f"{fact.fact_id}: expected 1 __init__, found {len(inits)}")
    return inits[0]


def gate_matrix(fact: Fact, **params: float) -> Matrix2:
    """从类块事实的 ``__init__`` 派生门矩阵。

    Args:
        fact: verbatim 为完整类块的事实。
        **params: 参数化门的参数，例如 ``theta``。

    Returns:
        按存储下标排列的 2×2 复矩阵。

    Raises:
        UnsupportedEvidenceError: 类块结构或 ``__init__`` 中出现白名单之外的构造。
    """
    env = {name: complex(value) for name, value in params.items()}
    assembled: list[Matrix2] = []
    for statement in _init_of_single_class(fact).body:
        match statement:
            case ast.Assign(
                targets=[ast.Attribute(value=owner, attr="target_qubits")],
                value=ast.Tuple(elts=qubits),
            ) if _is_self(owner) and all(isinstance(qubit, ast.Name) for qubit in qubits):
                continue
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                env[name] = _evaluate(value, env)
            case ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(value=owner, attr="_assemble"), args=[matrix], keywords=[]
                )
            ) if _is_self(owner):
                # 带 mpo_shape 会走 reshape 分支，单站点「原样存储」的前提就不成立了。
                assembled.append(_as_matrix2(_evaluate(matrix, env), matrix))
            case _:
                raise _unsupported(statement)
    if len(assembled) != 1:
        raise UnsupportedEvidenceError(
            f"{fact.fact_id}: expected 1 _assemble call, found {len(assembled)}"
        )
    return assembled[0]


def unpinned_callees(facts: Iterable[Fact]) -> set[str]:
    """返回没有被任何方法块事实钉住的对方方法名。"""
    heads = {fact.verbatim.lstrip() for fact in facts}
    return {
        name
        for name in COUNTERPART_CALLEES
        if not any(head.startswith(f"def {name}(") for head in heads)
    }


# 判据：每个子句返回 None（成立）或观察值字符串。约定一律在调用时读 conventions 的模块属性，
# 这样 monkeypatch 注入才会生效。


def _parse(fact: Fact) -> ast.Module:
    return ast.parse(textwrap.dedent(fact.verbatim))


def _inverse(index_map: Mapping[int, str]) -> dict[str, int]:
    return {name: index for index, name in index_map.items()}


def _function(fact: Fact) -> ast.FunctionDef:
    functions = [node for node in _parse(fact).body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1:
        raise UnsupportedEvidenceError(
            f"{fact.fact_id}: expected 1 function, found {len(functions)}"
        )
    return functions[0]


def _code(function: ast.FunctionDef) -> list[ast.stmt]:
    return function.body[1:] if ast.get_docstring(function) is not None else function.body


def _assemble_passes_through(facts: Facts, _thetas: tuple[float, ...]) -> str | None:
    code = _code(_function(facts["XR-ASSEMBLE"]))
    match code:
        case [
            ast.Assign(
                targets=[ast.Name(id="matrix")],
                value=ast.Call(
                    func=ast.Attribute(value=ast.Name(id="matrix"), attr="to"), args=[]
                ) as placement,
            ),
            ast.Assign(
                targets=[ast.Name(id="mpo")],
                value=ast.IfExp(
                    test=ast.Compare(
                        left=ast.Name(id="mpo_shape"),
                        ops=[ast.Is()],
                        comparators=[ast.Constant(None)],
                    ),
                    body=ast.Name(id="matrix"),
                ),
            ),
            ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(value=ast.Name(id="Gate"), attr="__init__"),
                    args=[ast.Name(id="self"), ast.Name(id="matrix"), ast.Name(id="mpo")],
                    keywords=[],
                )
            ),
        ] if placement.keywords and _gate_keywords_only(placement):
            return None
    return "single-site _assemble is not a pass-through: " + " | ".join(map(ast.unparse, code))


def _semantic_parameter_passes_through(facts: Facts, _thetas: tuple[float, ...]) -> str | None:
    function = _function(facts["XR-SEMPARAM"])
    value = function.args.args[-1].arg
    code = _code(function)
    match code:
        case [
            ast.Assign(
                targets=[ast.Name(id=result)],
                value=ast.Call(
                    func=ast.Attribute(value=ast.Name(id="self"), attr="_as_tensor"),
                    args=[ast.Name(id=argument)],
                    keywords=[],
                ),
            ),
            *rest,
        ] if argument == value:
            # 重新赋值或在它上面调方法（如 neg_()）都可能改掉角度。
            touched = any(
                (
                    isinstance(node, ast.Name)
                    and node.id == result
                    and isinstance(node.ctx, ast.Store)
                )
                or (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == result
                )
                for statement in rest
                for node in ast.walk(statement)
            )
            returns = [node for node in ast.walk(function) if isinstance(node, ast.Return)]
            if (
                returns
                and not touched
                and all(
                    isinstance(ret.value, ast.Name) and ret.value.id == result for ret in returns
                )
            ):
                return None
    return "_semantic_parameter is not a pass-through: " + " | ".join(map(ast.unparse, code))


def _mps_contracts_the_gate_input(facts: Facts, _thetas: tuple[float, ...]) -> str | None:
    match _parse(facts["XR-APPLY-MPS"]).body:
        case [ast.Assign(value=ast.Constant(value=str() as subscripts))] if (
            subscripts.count(",") == 1 and subscripts.count("->") == 1
        ):
            pass
        case _:
            raise UnsupportedEvidenceError("XR-APPLY-MPS: expected one einsum string assignment")
    inputs, output = subscripts.split("->")
    gate, state = inputs.split(",")
    # M[out, in]：门的第二个下标与态收缩，第一个下标原位替换它出现在输出里。
    if (
        len(gate) == 2
        and gate[1] in state
        and gate[0] not in state
        and output == state.replace(gate[1], gate[0])
    ):
        return None
    return f"MPS contraction {subscripts!r} does not apply the gate as M[out, in]"


def _state_vector_left_multiplies(facts: Facts, _thetas: tuple[float, ...]) -> str | None:
    calls = [
        node
        for node in ast.walk(_parse(facts["XR-APPLY-SV"]))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "matmul"
    ]
    if len(calls) != 1:
        raise UnsupportedEvidenceError(f"XR-APPLY-SV: expected 1 matmul, found {len(calls)}")
    match calls[0].args:
        case [ast.Name(id="matrix"), _]:
            return None
    return f"state-vector update is {ast.unparse(calls[0])}"


def _lands_on(matrix: Matrix2, source: str) -> str:
    column = [matrix[row][_inverse(conventions.OPTICS_INDEX_TO_PHYSICAL)[source]] for row in (0, 1)]
    hits = [row for row in (0, 1) if abs(column[row]) > DEFAULT_TOLERANCE]
    return (
        conventions.OPTICS_INDEX_TO_PHYSICAL[hits[0]] if len(hits) == 1 else f"{len(hits)} states"
    )


def _sigma_plus(facts: Facts, _thetas: tuple[float, ...]) -> str | None:
    landed = _lands_on(gate_matrix(facts["XR-SP"]), "ground")
    return None if landed == "excited" else f"Sp applied to ground lands on {landed}"


def _sigma_minus(facts: Facts, _thetas: tuple[float, ...]) -> str | None:
    landed = _lands_on(gate_matrix(facts["XR-SM"]), "excited")
    return None if landed == "ground" else f"Sm applied to excited lands on {landed}"


def _z_is_the_commutator(facts: Facts, _thetas: tuple[float, ...]) -> str | None:
    sp, sm, z = (gate_matrix(facts[fact_id]) for fact_id in ("XR-SP", "XR-SM", "XR-Z"))
    forward, backward = conventions._matmul(sp, sm), conventions._matmul(sm, sp)
    commutator = tuple(
        tuple(f - b for f, b in zip(f_row, b_row, strict=True))
        for f_row, b_row in zip(forward, backward, strict=True)
    )
    if conventions._close(z, commutator, DEFAULT_TOLERANCE):
        return None
    return f"[Sp, Sm] = {commutator} but Z = {z}"


def _z_is_positive_on_excited(facts: Facts, _thetas: tuple[float, ...]) -> str | None:
    z = gate_matrix(facts["XR-Z"])
    index = _inverse(conventions.OPTICS_INDEX_TO_PHYSICAL)
    on_excited, on_ground = (
        z[index["excited"]][index["excited"]],
        z[index["ground"]][index["ground"]],
    )
    if abs(on_excited - 1) <= DEFAULT_TOLERANCE and abs(on_ground + 1) <= DEFAULT_TOLERANCE:
        return None
    return f"Z is {on_excited} on excited and {on_ground} on ground"


def is_degenerate(theta: float) -> bool:
    """判断 θ 是否让 RZ(θ) 过于接近 ±I，以至于看不出下标翻转。"""
    return 2 * abs(math.sin(theta / 2)) < 0.1


def _require_informative(thetas: tuple[float, ...]) -> None:
    degenerate = [theta for theta in thetas if is_degenerate(theta)]
    assert thetas and not degenerate, f"theta samples cannot expose a basis flip: {thetas}"


def _rz_formula_at(facts: Facts, theta: float) -> str | None:
    z = gate_matrix(facts["XR-Z"])
    expected: Matrix2 = (
        (cmath.exp(-1j * theta * z[0][0] / 2), 0j),
        (0j, cmath.exp(-1j * theta * z[1][1] / 2)),
    )
    derived = gate_matrix(facts["XR-RZ"], theta=theta)
    if conventions._close(derived, expected, DEFAULT_TOLERANCE):
        return None
    return f"RZ({theta}) = {derived} but exp(-i*theta*Z/2) = {expected}"


def _in_physical_basis(matrix: Matrix2, index_map: Mapping[int, str]) -> Matrix2:
    index = _inverse(index_map)
    ground, excited = index["ground"], index["excited"]
    return (
        (matrix[ground][ground], matrix[ground][excited]),
        (matrix[excited][ground], matrix[excited][excited]),
    )


def _rz_coupling_at(facts: Facts, theta: float) -> str | None:
    # 光学下标下 Z 的物理含义反号，所以同一物理作用对应本仓的 RZ(-theta)。
    theirs = _in_physical_basis(
        gate_matrix(facts["XR-RZ"], theta=theta), conventions.OPTICS_INDEX_TO_PHYSICAL
    )
    ours = _in_physical_basis(conventions._rz(-theta), conventions.QASM3_INDEX_TO_PHYSICAL)
    if conventions._close(theirs, ours, DEFAULT_TOLERANCE):
        return None
    return (
        f"in the (ground, excited) basis their RZ({theta}) = {theirs} but ours RZ(-theta) = {ours}"
    )


def _rz_formula(facts: Facts, thetas: tuple[float, ...]) -> str | None:
    _require_informative(thetas)
    return next(filter(None, (_rz_formula_at(facts, theta) for theta in thetas)), None)


def _rz_coupling(facts: Facts, thetas: tuple[float, ...]) -> str | None:
    _require_informative(thetas)
    return next(filter(None, (_rz_coupling_at(facts, theta) for theta in thetas)), None)


def _initial_claim(facts: Facts, _thetas: tuple[float, ...]) -> str | None:
    text = facts["XR-INIT"].verbatim
    missing = [
        phrase for phrase in ("all ground state", "all 1's = all spin down") if phrase not in text
    ]
    return f"initial-state comment lacks {missing}" if missing else None


def _spin_parse(facts: Facts, _thetas: tuple[float, ...]) -> str | None:
    generators = [
        node
        for node in ast.walk(_parse(facts["XR-INIT-PARSE"]))
        if isinstance(node, ast.GeneratorExp)
    ]
    if len(generators) != 1:
        raise UnsupportedEvidenceError(
            f"XR-INIT-PARSE: expected 1 generator, found {len(generators)}"
        )
    (generator,) = generators
    match generator.elt, generator.generators:
        case ast.Call(func=ast.Name(id="int"), args=[ast.Name(id=name)], keywords=[]), [
            ast.comprehension(target=ast.Name(id=target), ifs=[])
        ] if name == target:
            return None
    return f"spin character becomes an index via {ast.unparse(generator.elt)}"


def _initial_spin_is_ground(facts: Facts, _thetas: tuple[float, ...]) -> str | None:
    match _parse(facts["XR-INIT"]).body:
        case [
            ast.Assign(value=ast.BinOp(left=ast.Constant(value=str() as spin), op=ast.Mult()))
        ] if spin in {"0", "1"}:
            pass
        case _:
            raise UnsupportedEvidenceError("XR-INIT: expected '<spin>' * <sites>")
    state = conventions.OPTICS_INDEX_TO_PHYSICAL[int(spin)]
    return None if state == "ground" else f"initial spin {spin!r} is index {spin} = {state}"


_CHECKS: dict[str, dict[str, Check]] = {
    "R0": {
        "asm": _assemble_passes_through,
        "sem": _semantic_parameter_passes_through,
        "mps": _mps_contracts_the_gate_input,
        "sv": _state_vector_left_multiplies,
    },
    "R1": {"Sp": _sigma_plus, "Sm": _sigma_minus},
    "R2": {"alg": _z_is_the_commutator, "attr": _z_is_positive_on_excited},
    "R3a": {"formula": _rz_formula},
    "R3b": {"coupling": _rz_coupling},
    "R4": {"claim": _initial_claim, "parse": _spin_parse, "map": _initial_spin_is_ground},
}

CLAUSES = {rule: tuple(checks) for rule, checks in _CHECKS.items()}
"""每个判据的合取子句名。"""


def clause_failures(
    rule: str, facts: Facts, thetas: tuple[float, ...] = NON_DEGENERATE_THETAS
) -> dict[str, str]:
    """对一个判据逐子句求值，只返回失败的子句及其观察值。

    Args:
        rule: 判据名，``CLAUSES`` 的键之一。
        facts: 按 ID 索引的事实。
        thetas: R3 使用的角度样本。

    Returns:
        ``{子句名: 观察值}``；判据成立时为空字典。求值器异常不捕获。
    """
    observed = {clause: check(facts, thetas) for clause, check in _CHECKS[rule].items()}
    return {clause: text for clause, text in observed.items() if text is not None}


def _verdict(
    rule: str, facts: Facts, thetas: tuple[float, ...] = NON_DEGENERATE_THETAS
) -> str | None:
    failures = clause_failures(rule, facts, thetas)
    return "; ".join(f"{clause}: {observed}" for clause, observed in failures.items()) or None


def r0_application_order(facts: Facts) -> str | None:
    """判定对方把门矩阵按 M[out, in] 原样作用于态（R1–R3 的前提）。"""
    return _verdict("R0", facts)


def r1_sigma_direction(facts: Facts) -> str | None:
    """判定 Sp 把 ground 升到 excited、Sm 把 excited 降到 ground。"""
    return _verdict("R1", facts)


def r2_sigma_z(facts: Facts) -> str | None:
    """判定 Z = [Sp, Sm] 且 Z 在 excited 上为 +1。"""
    return _verdict("R2", facts)


def r3_rz_formula(facts: Facts, thetas: tuple[float, ...] = NON_DEGENERATE_THETAS) -> str | None:
    """判定对方 RZ 在其自身 Z 下满足 exp(-i*theta*Z/2)；样本退化时抛 ``AssertionError``。"""
    return _verdict("R3a", facts, thetas)


def r3_rz_coupling(facts: Facts, thetas: tuple[float, ...] = NON_DEGENERATE_THETAS) -> str | None:
    """判定物理基下对方 RZ(theta) 等于本仓 RZ(-theta)；样本退化时抛 ``AssertionError``。"""
    return _verdict("R3b", facts, thetas)


def r4_initial_state(facts: Facts) -> str | None:
    """判定对方默认初态（全 '1' 自旋串）是全 ground 态。"""
    return _verdict("R4", facts)


def mismatch_report(
    rule: str, ours_name: str, ours_value: object, fact: Fact, observed: str
) -> str:
    """渲染中立的差异报告：不预设哪一侧有误。

    Args:
        rule: 失败的判据名。
        ours_name: 本仓约定常量名。
        ours_value: 该常量当前的值。
        fact: 被对照的对方事实。
        observed: 判据返回的观察值。

    Returns:
        五段式纯 ASCII 多行文本。
    """
    lo, hi = fact.lines
    return (
        f"cross-repo falsification {rule} failed; attribution undecided (do not edit either side)\n"
        f"  ours    : {ours_name} = {ours_value!r} (src/qaiji/core/conventions.py)\n"
        f"  theirs  : {fact.fact_id}: {fact.physical_claim}\n"
        f"            {fact.source_path}:{lo}-{hi} @ {fact.commit} (extracted {fact.extracted_on})\n"
        f"  observed: {observed}\n"
        "  next    : record a divergence report and ask the convention owner to decide"
    )


# 防腐：G1 保鲜与 G2 实时重核。消息面向看不到计划文档的 CI 读者，因此内嵌刷新步骤、保持纯 ASCII。

MAX_SNAPSHOT_AGE_DAYS = 180
OPTICS_ROOT_ENV = "QAIJI_QUANTEMPO_ROOT"

REFRESH_STEPS = f"""
refresh the snapshot:
  1. confirm the counterpart checkout and its commit:
       git -C "${OPTICS_ROOT_ENV}" log -1 --format=%h
  2. for each class fact, re-locate the ClassDef block and check its line range (example: Sp):
       uv run python -c "import ast,sys;t=open(sys.argv[1]).read();\\
n=[c for c in ast.walk(ast.parse(t)) if isinstance(c,ast.ClassDef) and c.name==sys.argv[2]];\\
assert len(n)==1;print(n[0].lineno,n[0].end_lineno)" \\
         "${OPTICS_ROOT_ENV}/src/quantempo/domain/quantum/gates/single_qubit.py" Sp
  3. re-check the action convention (all 15 str1 entries must read M[out,in]):
       grep -o 'self.str1\\[[0-9]*\\] = "[^"]*"' "${OPTICS_ROOT_ENV}/src/quantempo/core/constants.py" \\
         | awk -F'"' '{{split($2,a,",");print (substr(a[1],2,1)=="x")?"OK":"CHECK", $2}}' | sort | uniq -c
  4. spot-check the trust boundary: these must still only convert dtype/device or store as-is:
       base.py: _as_tensor and the self._matrix/self._mpo assignments in Gate.__init__;
       mps_strategy.py: _ensure_device; statevector_strategy.py: _match_state_precision
  5. spot-check the recorded divergences: has the counterpart QASM loader or the
     alternative-backend naming changed?
  6. update verbatim / lines / commit / extracted_on in tests/core/_optics_snapshot.py
  7. run the live re-check and confirm every fact matches exactly once:
       {OPTICS_ROOT_ENV}=... uv run pytest tests/core/test_conventions_crossrepo.py --no-cov -rfEs"""


def freshness_problems(facts: Iterable[Fact], today: date) -> list[str]:
    """逐条计龄：超过保鲜期或提取日期在未来的事实各报一行。

    Args:
        facts: 待检查的快照事实。
        today: 注入的当前日期（生产测试传 ``date.today()``）。

    Returns:
        ``"<ID>: stale|future: <说明>"`` 形式的问题行；全部新鲜时为空。
    """
    problems = []
    for fact in facts:
        age = (today - fact.extracted_on).days
        if age > MAX_SNAPSHOT_AGE_DAYS:
            problems.append(
                f"{fact.fact_id}: stale: {age} days old (limit {MAX_SNAPSHOT_AGE_DAYS})"
            )
        elif age < 0:
            # 写错成未来日期会让门控长期不触发，必须和超龄一样失败。
            problems.append(
                f"{fact.fact_id}: future: extracted_on {fact.extracted_on} is after {today}"
            )
    return problems


def assert_fresh(facts: Iterable[Fact], today: date) -> None:
    """快照有任何过期或未来日期的事实时让测试失败，并在消息中给出刷新步骤。"""
    problems = freshness_problems(facts, today)
    if problems:
        lines = "\n".join(f"  {problem}" for problem in problems)
        pytest.fail(f"optics snapshot is not fresh:\n{lines}\n{REFRESH_STEPS}", pytrace=False)


class Discovery(enum.Enum):
    """对方仓库的发现结果：显式配置严格，隐式默认宽松。"""

    FOUND = "found"
    MISCONFIGURED = "misconfigured"
    UNCONFIGURED = "unconfigured"


def _is_checkout(root: Path) -> bool:
    return (root / "src" / "quantempo").is_dir()


def discover_optics_repo(env: Mapping[str, str], repo_root: Path) -> tuple[Discovery, Path]:
    """定位对方仓库：先看环境变量，未设置时才看本仓的兄弟目录。

    Args:
        env: 环境变量映射（生产测试传 ``os.environ``）。
        repo_root: 本仓根目录。

    Returns:
        发现状态与被检查的路径。设了变量却无效为 ``MISCONFIGURED``，不回退到兄弟目录；
        未设变量且兄弟目录无效为 ``UNCONFIGURED``。
    """
    configured = env.get(OPTICS_ROOT_ENV)
    if configured is not None:
        root = Path(configured)
        return (Discovery.FOUND if _is_checkout(root) else Discovery.MISCONFIGURED), root
    root = repo_root.parent / "QuanTempo"
    return (Discovery.FOUND if _is_checkout(root) else Discovery.UNCONFIGURED), root


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def live_problems(facts: Iterable[Fact], root: Path) -> list[str]:
    """逐条比对快照与对方检出：每条 verbatim 必须按整行在源文件中恰好出现一次，且其后没有续写。

    行号漂移不算问题；文件缺失、原文不再出现、原文出现多次、原文之后紧跟更深缩进的行
    （同一个类或语句块被续写）各报一行。

    Returns:
        ``"<ID>: missing|drift|not unique|grown: <说明>"`` 形式的问题行；全部一致时为空。
    """
    problems = []
    for fact in facts:
        path = root / fact.source_path
        if not path.is_file():
            problems.append(f"{fact.fact_id}: missing: {fact.source_path}")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        target = fact.verbatim.splitlines()
        # 按整行比对：子串匹配会放过同一行首尾的追加（如整行被注释掉、返回值被再加工）。
        starts = [
            i for i in range(len(lines) - len(target) + 1) if lines[i : i + len(target)] == target
        ]
        if not starts:
            problems.append(f"{fact.fact_id}: drift: verbatim no longer in {fact.source_path}")
        elif len(starts) > 1:
            problems.append(f"{fact.fact_id}: not unique: verbatim appears {len(starts)} times")
        else:
            rest = (line for line in lines[starts[0] + len(target) :] if line.strip())
            if _indent(next(rest, "")) > _indent(target[0]):
                problems.append(f"{fact.fact_id}: grown: code is indented under the verbatim")
    return problems


# 证伪状态标注：属性 docstring 在运行时不存在，只能从源码的 AST 读取。

CONTRACTED_CONSTANTS = frozenset(
    {
        "QASM3_INDEX_TO_PHYSICAL",
        "OPTICS_INDEX_TO_PHYSICAL",
        "QASM3_TO_OPTICS_BIT",
        "RZ_PHASE_CONVENTION",
    }
)
STATUS_VOCABULARY = ("已跨库证伪", "参照系定义", "推导成立")
_CROSS_REPO = STATUS_VOCABULARY[0]
_STATUS = re.compile(r"证伪状态：([^（。]*)")
_FACT_REF = re.compile(r"XR-[A-Z0-9]+(?:-[A-Z0-9]+)*")
_TEST_PATH = re.compile(r"``(tests/core/[^`]+)``")


def _assigned_names(node: ast.stmt) -> list[str]:
    """语句绑定的全部名字；链式赋值与元组 / 列表解包逐个展开。"""
    if isinstance(node, ast.AnnAssign):
        targets = [node.target]
    elif isinstance(node, ast.Assign):
        targets = node.targets
    else:
        return []
    names = []
    for target in targets:
        elements = target.elts if isinstance(target, ast.Tuple | ast.List) else [target]
        names += [element.id for element in elements if isinstance(element, ast.Name)]
    return names


def _public_constants(tree: ast.Module) -> set[str]:
    names = (name for node in tree.body for name in _assigned_names(node))
    return {name for name in names if name.isupper() and not name.startswith("_")}


def attribute_docstrings(source: str) -> dict[str, str]:
    """提取模块级赋值紧随其后的属性 docstring。

    Returns:
        ``{被赋值的名字: docstring}``；没有紧跟字符串表达式的赋值不出现。
    """
    body = ast.parse(source).body
    docs = {}
    for node, following in itertools.pairwise(body):
        names = _assigned_names(node)
        # 只认单名字赋值：链式或解包赋值后的字符串归属不明。
        if (
            len(names) == 1
            and isinstance(following, ast.Expr)
            and isinstance(following.value, ast.Constant)
            and isinstance(following.value.value, str)
        ):
            docs[names[0]] = following.value.value
    return docs


def docstring_problems(source: str, facts: Iterable[Fact], repo_root: Path) -> list[str]:
    """按链接规则 L1–L5 检查约定常量的证伪状态标注。

    Args:
        source: ``conventions.py`` 的源码。
        facts: 快照事实。
        repo_root: 本仓根目录，用于核对 docstring 中的测试路径。

    Returns:
        ``"L<n>: <说明>"`` 形式的问题行；标注与快照一致时为空。
    """
    public = _public_constants(ast.parse(source))
    docs = attribute_docstrings(source)
    known = {fact.fact_id for fact in facts}
    problems = []
    if public != CONTRACTED_CONSTANTS:
        problems.append(f"L1: public constants {sorted(public)} differ from the contracted four")
    problems += [f"L1: {name} has no attribute docstring" for name in sorted(public - docs.keys())]
    cited_anywhere: set[str] = set()
    for name in sorted(public & docs.keys()):
        doc = docs[name]
        statuses = _STATUS.findall(doc)
        if len(statuses) != 1 or statuses[0] not in STATUS_VOCABULARY:
            problems.append(
                f"L2: {name} must state exactly one status from the vocabulary, got {statuses}"
            )
        cited = set(_FACT_REF.findall(doc))
        cited_anywhere |= cited
        if (statuses == [_CROSS_REPO]) != bool(cited):
            problems.append(
                f"L3: {name} status {statuses} is inconsistent with cited facts {sorted(cited)}"
            )
        if cited - known:
            problems.append(f"L3: {name} cites unknown facts {sorted(cited - known)}")
        problems += [
            f"L5: {name} refers to missing path {path}"
            for path in _TEST_PATH.findall(doc)
            if not (repo_root / path).exists()
        ]
    if known - cited_anywhere:
        problems.append(f"L4: facts cited by no constant: {sorted(known - cited_anywhere)}")
    return problems
