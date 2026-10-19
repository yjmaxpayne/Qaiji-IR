# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查物理判据与请求级资源预算。"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from qaiji.core.physical import (
    ArrayData,
    CheckBudget,
    LocalFactor,
    Observation,
    OperatorSum,
    OperatorTerm,
    ProductFactor,
    Site,
    State,
)
from qaiji.core.physical.codec import dump_request, load_request
from qaiji.core.physical.validation import check_problem, check_request


def array(values, shape):
    return ArrayData.from_values(dtype="c128le", values=values, shape=shape)


def request():
    data = json.loads((Path(__file__).parent / "data/bath-fixture.json").read_bytes())
    data["problem"]["extensions"] = []
    req = load_request(json.dumps(data).encode())
    site = req.problem.sites[0]
    problem = replace(
        req.problem,
        sites=(site,),
        tensor_order=(site.id,),
        h0=OperatorSum(unit="rad/ns", terms=()),
        drives=(),
        initial_state=State(kind="ket", frame="lab", data=array([1, 0], (2,))),
    )
    return replace(
        req, problem=problem, observations=(), provenance=replace(req.provenance, basis_mapping=())
    )


def density(values):
    req = request()
    return replace(
        req,
        problem=replace(
            req.problem,
            initial_state=State(kind="density", frame="lab", data=array(values, (2, 2))),
        ),
    )


def product_request(count=2, value=1.0, dim=1):
    req = request()
    sites = tuple(
        Site(id=f"s{i}", dim=dim, basis=tuple(str(j) for j in range(dim))) for i in range(count)
    )
    problem = replace(
        req.problem,
        sites=sites,
        tensor_order=tuple(s.id for s in sites),
        h0=OperatorSum(unit="rad/ns", terms=()),
        drives=(),
        initial_state=State(
            kind="product",
            frame="lab",
            factors=tuple(
                ProductFactor(
                    site=s.id,
                    kind="density",
                    data=array([value] + [0] * (dim * dim - 1), (dim, dim)),
                )
                for s in sites
            ),
        ),
    )
    return replace(
        req, problem=problem, observations=(), provenance=replace(req.provenance, basis_mapping=())
    )


@pytest.mark.parametrize("case", ["ket", "density", "product", "nonhermitian_terms"])
def test_p_tiered_physical_budget(case):
    req = request()
    if case == "density":
        req = density([0.5, -0.5j, 0.5j, 0.5])
    elif case == "product":
        req = product_request()
    elif case == "nonhermitian_terms":
        site = req.problem.sites[0].id
        terms = tuple(
            OperatorTerm(coefficient=1, factors=(LocalFactor(site=site, matrix=array(v, (2, 2))),))
            for v in ([0, 1j, 0, 0], [0, 0, -1j, 0])
        )
        req = replace(req, problem=replace(req.problem, h0=OperatorSum(unit="rad/ns", terms=terms)))
    assert check_request(req, level="structure").complete
    before = dump_request(req).document
    report = check_request(req, level="physical")
    assert report.complete, report.diagnostics
    assert not report.diagnostics
    assert not report.unchecked
    assert dump_request(req).document == before
    assert check_problem(req.problem, level="physical").complete


@pytest.mark.parametrize(
    "minimum,accepted",
    [
        (-0.5e-10, True),
        (-1e-10, True),
        (math.nextafter(-1e-10, -math.inf), False),
        (-1.01e-10, False),
        (-1e-8, False),
        (-1e-6, False),
        (-2e-10, False),
    ],
)
def test_psd_boundary_uses_exact_binary64(minimum, accepted):
    req = density([minimum, 0, 0, 1 - minimum])
    report = check_request(req, level="physical")
    assert report.complete is accepted
    assert (not report.diagnostics) is accepted
    if not accepted:
        assert report.diagnostics[0].code == "PSD"


@pytest.mark.parametrize(
    "variant,code",
    [
        ("nonhermitian_total", "HERMITIAN"),
        ("unnormalized_ket", "NORMALIZATION"),
        ("imaginary_trace", "NORMALIZATION"),
        ("complex_non_psd", "PSD"),
        ("negative_pivot", "PSD"),
        ("zero_pivot_column", "PSD"),
        ("global_normalization", "NORMALIZATION"),
        ("dense_dimension", "DENSE_DIMENSION"),
        ("numeric_elements", "NUMERIC_ELEMENTS"),
        ("rational_ops", "RATIONAL_OPS"),
        ("rational_bits", "RATIONAL_BITS"),
        ("numeric_range", "NUMERIC_RANGE"),
        ("isometry", "ISOMETRY"),
    ],
)
def test_physical_invalid_request_and_resource_diagnostics(variant, code):
    req = request()
    assert check_request(req, level="physical").complete
    budget = CheckBudget()
    if variant == "nonhermitian_total":
        req = replace(
            req,
            problem=replace(
                req.problem,
                h0=OperatorSum(unit="rad/ns", terms=(OperatorTerm(coefficient=1j, factors=()),)),
            ),
        )
    elif variant == "unnormalized_ket":
        req = replace(
            req,
            problem=replace(
                req.problem, initial_state=State(kind="ket", frame="lab", data=array([1, 1], (2,)))
            ),
        )
    elif variant == "imaginary_trace":
        req = density([0.5 + 1e-8j, 0, 0, 0.5])
    elif variant == "complex_non_psd":
        req = density([0.5, -1j, 1j, 0.5])
    elif variant == "negative_pivot":
        req = density([-2e-10, 0, 0, 1 + 2e-10])
    elif variant == "zero_pivot_column":
        req = density([-1e-10, 1e-5, 1e-5, 1 + 1e-10])
    elif variant == "global_normalization":
        req = product_request(3, 1 + 0.75e-10)
    elif variant == "dense_dimension":
        budget = replace(budget, max_dense_dimension=1)
    elif variant == "numeric_elements":
        budget = replace(budget, max_numeric_elements=0)
    elif variant == "rational_ops":
        req = product_request()
        budget = replace(budget, max_rational_ops=1)
    elif variant == "rational_bits":
        req = density([0.5, 0, 0, 0.5])
        budget = replace(budget, max_rational_bits=8)
    elif variant == "numeric_range":
        req = replace(
            req,
            problem=replace(
                req.problem,
                h0=OperatorSum(
                    unit="rad/ns", terms=(OperatorTerm(coefficient=1e308, factors=()),) * 2
                ),
            ),
        )
    elif variant == "isometry":
        req = replace(
            req,
            observations=(
                Observation(
                    id="p",
                    kind="projection",
                    input_sites=(req.problem.sites[0].id,),
                    isometry=array([1, 1], (2, 1)),
                ),
            ),
        )
    assert check_request(req, level="structure").complete
    before = dump_request(req).document
    report = check_request(req, level="physical", budget=budget)
    assert not report.complete
    assert code in {d.code for d in report.diagnostics}, report.diagnostics
    assert dump_request(req).document == before
    if code in {
        "DENSE_DIMENSION",
        "NUMERIC_ELEMENTS",
        "RATIONAL_OPS",
        "RATIONAL_BITS",
        "NUMERIC_RANGE",
    }:
        d = next(d for d in report.diagnostics if d.code == code)
        assert d.category == "RESOURCE_LIMIT"
        assert {"resource", "required", "limit"} <= dict(d.details.value.items).keys()
    if variant == "rational_ops":
        assert report.diagnostics[0].path == "/problem/initial_state/factors/1/data"


def test_p_request_budget_is_cumulative():
    budget = CheckBudget(max_rational_ops=1)
    assert check_request(
        product_request(1), level="physical", budget=CheckBudget(max_rational_ops=2)
    ).complete
    report = check_request(product_request(2), level="physical", budget=budget)
    assert not report.complete
    assert report.diagnostics[0].code == "RATIONAL_OPS"
    assert report.diagnostics[0].path == "/problem/initial_state/factors/1/data"


@pytest.mark.parametrize(
    "variant",
    [
        "psd-loose-1e-7",
        "psd-tight-zero",
        "psd-diagonal-only",
        "skip-budget",
        "reset-cumulative-counter",
        "repair-input",
        "skip-global-product-normalization",
        "skip-zero-pivot-offdiagonal",
        "unchecked-integer-product",
    ],
)
def test_p_rejects_physical_budget_or_psd(variant):
    from qaiji.core.physical._numeric import _NumericContext

    req = density([0.5, 0, 0, 0.5])
    assert check_request(req, level="physical").complete
    budget = CheckBudget()
    code = "PSD"
    if variant == "psd-tight-zero":
        req = density([1 + 1e-10, 0, 0, -1e-10])
        assert check_request(req, level="physical").complete
        return
    if variant == "psd-loose-1e-7":
        req = density([1 + 1.01e-10, 0, 0, -1.01e-10])
    elif variant == "psd-diagonal-only":
        req = density([0.5, 1j, -1j, 0.5])
    elif variant == "skip-budget":
        budget = CheckBudget(max_numeric_elements=0)
        code = "NUMERIC_ELEMENTS"
    elif variant == "reset-cumulative-counter":
        req = product_request(2)
        budget = CheckBudget(max_rational_ops=1)
        code = "RATIONAL_OPS"
    elif variant == "repair-input":
        req = density([1.000001, 0, 0, -0.000001])
    elif variant == "skip-global-product-normalization":
        req = product_request(2, 1 + 0.75e-10, dim=2)
        code = "NORMALIZATION"
    elif variant == "skip-zero-pivot-offdiagonal":
        req = density([-1e-10, 1e-5, 1e-5, 1 + 1e-10])
    elif variant == "unchecked-integer-product":

        class CheckedInteger(int):
            def __mul__(self, other):
                raise AssertionError("Integer multiplication ran before its budget check.")

        from qaiji.core.physical import PContractError

        context = _NumericContext(CheckBudget(max_rational_bits=8))
        assert context.integer_product(2, 3, "") == 6
        with pytest.raises(PContractError) as error:
            context.integer_product(CheckedInteger(255), CheckedInteger(255), "")
        assert error.value.diagnostics[0].code == "RATIONAL_BITS"
        return
    assert check_request(req, level="structure").complete
    before = dump_request(req).document
    report = check_request(req, level="physical", budget=budget)
    assert not report.complete
    assert report.diagnostics[0].code == code
    assert dump_request(req).document == before


def test_dimension_and_slots_refuse_before_assembly(monkeypatch):
    from qaiji.core.physical import _numeric

    req = request()
    assert check_request(req, level="physical").complete

    def trap(*args, **kwargs):
        raise AssertionError("Dense assembly ran before its budget check.")

    monkeypatch.setattr(_numeric, "_values", trap)
    for budget in (CheckBudget(max_dense_dimension=0), CheckBudget(max_numeric_elements=0)):
        assert check_request(req, level="structure", budget=budget).complete
        report = check_request(req, level="physical", budget=budget)
        assert report.diagnostics[0].category == "RESOURCE_LIMIT"
        assert not report.complete


def test_schur_counts_across_multiple_states():
    from qaiji.core.physical import PContractError
    from qaiji.core.physical._numeric import _NumericContext, _psd

    for _ in range(2):
        context = _NumericContext(CheckBudget(max_rational_ops=1))
        _psd([1 + 0j], 1, context, "/state")
        assert context.operations == 1
    with pytest.raises(PContractError) as error:
        _psd([1 + 0j], 1, context, "/next")
    assert error.value.diagnostics[0].code == "RATIONAL_OPS"
    assert error.value.diagnostics[0].path == "/next"


def test_fraction_cross_cancellation_precedes_products():
    from fractions import Fraction

    from qaiji.core.physical._numeric import _NumericContext

    context = _NumericContext(CheckBudget(max_rational_bits=8))
    assert context.multiply(Fraction(127, 128), Fraction(128, 127), "") == 1
    assert context.add(Fraction(1, 128), Fraction(127, 128), "") == 1


def test_operator_assembly_respects_tensor_order_and_identity():
    from qaiji.core.physical._numeric import _assemble_operator, _NumericContext

    req = request()
    a = req.problem.sites[0]
    b = Site(id="b", dim=3, basis=("0", "1", "2"))
    operator = OperatorSum(
        unit="rad/ns",
        terms=(
            OperatorTerm(
                coefficient=2,
                factors=(
                    LocalFactor(site=a.id, matrix=array([0, -1j, 1j, 0], (2, 2))),
                    LocalFactor(site=b.id, matrix=array([1, 0, 0, 0, 2, 0, 0, 0, 3], (3, 3))),
                ),
            ),
            OperatorTerm(coefficient=3, factors=()),
        ),
    )
    problem = replace(req.problem, sites=(a, b), tensor_order=(b.id, a.id))
    result = _assemble_operator(operator, problem, _NumericContext(CheckBudget()), "/h0")
    expected = [0j] * 36
    for i in range(6):
        expected[6 * i + i] = 3
    for i, value in ((0, 2), (2, 4), (4, 6)):
        expected[6 * i + i + 1] = -value * 1j
        expected[6 * (i + 1) + i] = value * 1j
    assert result == expected


def test_operator_releases_local_workspace_between_terms(monkeypatch):
    from qaiji.core.physical import _numeric

    req = request()
    factor = LocalFactor(site=req.problem.sites[0].id, matrix=array([1, 0, 0, 1], (2, 2)))
    operator = OperatorSum(
        unit="rad/ns", terms=(OperatorTerm(coefficient=1, factors=(factor,)),) * 2
    )
    active = 0
    peak = 0
    original = _numeric._values

    class Workspace(list):
        def __init__(self, values):
            nonlocal active, peak
            super().__init__(values)
            active += 1
            peak = max(peak, active)

        def __del__(self):
            nonlocal active
            active -= 1

    monkeypatch.setattr(_numeric, "_values", lambda a: Workspace(original(a)))
    matrix = _numeric._assemble_operator(
        operator, req.problem, _numeric._NumericContext(CheckBudget()), "/h0"
    )
    assert matrix == [2, 0, 0, 2]
    assert active == 0
    assert peak == 1


@pytest.mark.parametrize("variant", ["reset-request-result-counter"])
def test_p_request_and_result_share_budget(variant):
    from physical_result_factories import carray, farray, result_for, result_request
    from qaiji.core.physical._numeric import _check_physical, _NumericContext
    from qaiji.core.physical.model import ObservationValue
    from qaiji.core.physical.results import _physical_observation, check_result

    req = result_request((Observation(id="state", kind="full_state", representation="density"),))
    req = replace(
        req,
        output_times=farray([0.0]),
        policy=replace(req.policy, representation="density"),
        problem=replace(
            req.problem,
            initial_state=State(kind="density", frame="lab", data=carray([1, 0, 0, 0], (2, 2))),
        ),
    )
    value = ObservationValue(
        id="state",
        kind="full_state",
        representation="density",
        data=carray([1, 0, 0, 0], (1, 2, 2)),
    )
    result = result_for(req, (value,))
    context = _NumericContext(CheckBudget())
    _check_physical(req, context)
    request_count = context.operations
    _physical_observation(value, context, "/observations/0")
    total_count = context.operations
    # 每个四阶实嵌入矩阵需要 6 + 3 + 1 次 Schur 更新。
    assert request_count == 10
    assert total_count == 20
    assert check_result(
        req, result, level="physical", budget=CheckBudget(max_rational_ops=total_count)
    ).complete
    budget = CheckBudget(max_rational_ops=request_count)
    assert check_request(req, level="physical", budget=budget).complete
    result_context = _NumericContext(budget)
    _physical_observation(value, result_context, "/observations/0")
    assert result_context.operations == request_count
    report = check_result(req, result, level="physical", budget=budget)
    assert not report.complete
    item = report.diagnostics[0]
    assert (item.category, item.code) == ("RESOURCE_LIMIT", "RATIONAL_OPS")
    assert item.path == "/observations/0/data"
    assert item.details.value.items == (
        ("limit", request_count),
        ("required", request_count + 1),
        ("resource", "RATIONAL_OPS"),
    )


def test_result_numeric_budget_precedes_array_materialization(monkeypatch):
    from physical_result_factories import carray, result_for, result_request
    from qaiji.core.physical import results
    from qaiji.core.physical.model import ObservationValue

    req = result_request((Observation(id="state", kind="full_state", representation="density"),))
    req = replace(req, policy=replace(req.policy, representation="density"))
    count = req.output_times.shape[0]
    value = ObservationValue(
        id="state",
        kind="full_state",
        representation="density",
        data=carray([1, 0, 0, 0] * count, (count, 2, 2)),
    )
    result = result_for(req, (value,))
    assert results.check_result(req, result, level="physical").complete

    def forbidden(array):
        raise AssertionError("Result values must not be materialized above the budget.")

    monkeypatch.setattr(results, "_values", forbidden)
    report = results.check_result(
        req, result, level="physical", budget=CheckBudget(max_numeric_elements=32)
    )
    assert not report.complete
    assert any(
        d.category == "RESOURCE_LIMIT"
        and d.code == "NUMERIC_ELEMENTS"
        and d.path == "/observations/0/data"
        for d in report.diagnostics
    )
