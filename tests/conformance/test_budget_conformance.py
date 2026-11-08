# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""81 维请求与结果须在默认预算内通过物理检查。"""

from dataclasses import replace

from physical_result_factories import carray, farray, result_for, result_request
from qaiji.core.invariants import check_invariants
from qaiji.core.physical import (
    CheckBudget,
    Observation,
    ObservationValue,
    Site,
    State,
    check_request,
    check_result,
    dump_request,
    request_id,
)


def density_request(dimension=81):
    req = result_request()
    sites = tuple(Site(id=f"q{i}", dim=3, basis=("0", "1", "2")) for i in range(4))
    density = [1] + [0] * (dimension * dimension - 1)
    req = replace(
        req,
        problem=replace(
            req.problem,
            sites=sites,
            tensor_order=tuple(s.id for s in sites),
            initial_state=State(
                kind="density", frame="lab", data=carray(density, (dimension, dimension))
            ),
        ),
        output_times=farray([0, 1]),
        observations=(Observation(id="state", kind="full_state", representation="density"),),
        policy=replace(req.policy, representation="density"),
    )
    res = result_for(
        req,
        observations=(
            ObservationValue(
                id="state",
                kind="full_state",
                representation="density",
                data=carray(density * 2, (2, dimension, dimension)),
            ),
        ),
    )
    return req, res


def test_dimension_81_request_and_result_pass_default_and_reject_old_dimension():
    req, res = density_request()
    assert not check_request(req, level="physical").diagnostics
    assert not check_result(req, res, level="physical").diagnostics
    from qaiji.core.invariants import PInvariantInput

    assert check_invariants(PInvariantInput(request=req, result=res), layer="P").ok
    rejected = check_request(req, level="physical", budget=CheckBudget(max_dense_dimension=64))
    assert [(d.category, d.code, d.path) for d in rejected.diagnostics] == [
        ("RESOURCE_LIMIT", "DENSE_DIMENSION", "/problem/sites")
    ]
    assert request_id(req, budget=CheckBudget(max_dense_dimension=64)) == request_id(req)


def test_dimension_81_result_exceeds_old_shared_rational_budget():
    req, res = density_request()
    old = CheckBudget(max_rational_ops=1000000)
    assert not check_request(req, level="physical", budget=old).diagnostics
    rejected = check_result(req, res, level="physical", budget=old)
    assert any(
        d.category == "RESOURCE_LIMIT" and d.code == "RATIONAL_OPS" for d in rejected.diagnostics
    )


def test_wire_budget_refuses_actual_encoded_request_bytes():
    req, _ = density_request()
    size = len(dump_request(req).document)
    report = check_request(req, level="physical", budget=CheckBudget(max_wire_bytes=size - 1))
    assert any(d.category == "RESOURCE_LIMIT" and d.code == "BYTES" for d in report.diagnostics)
