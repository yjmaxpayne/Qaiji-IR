# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""构造结果检查的合法请求与结果。"""

from __future__ import annotations

import json
import struct
from dataclasses import replace
from pathlib import Path

from qaiji.core.physical.arrays import ArrayData, FrozenJSON
from qaiji.core.physical.codec import load_request
from qaiji.core.physical.identity import request_id
from qaiji.core.physical.model import (
    ExecutionReport,
    MethodChoice,
    Observation,
    ObservationValue,
    OperatorSum,
    Result,
    State,
)


def carray(values, shape):
    return ArrayData.from_values(dtype="c128le", values=values, shape=shape)


def farray(values):
    return ArrayData.from_values(dtype="f64le", values=values, shape=(len(values),))


def bits(value):
    return struct.pack(">d", value).hex()


def policy_values(req, method=None, representation=None):
    return {
        "method": method or req.policy.method.value or req.policy.method.allowed[0],
        "atol": bits(req.policy.atol),
        "rtol": bits(req.policy.rtol),
        "max_step_ns": None if req.policy.max_step_ns is None else bits(req.policy.max_step_ns),
        "representation": representation or req.policy.representation,
    }


def result_request(observations=None):
    data = json.loads((Path(__file__).parent / "physical/data/bath-fixture.json").read_bytes())
    data["problem"]["extensions"] = []
    req = load_request(json.dumps(data).encode())
    site = req.problem.sites[0]
    problem = replace(
        req.problem,
        sites=(site,),
        tensor_order=(site.id,),
        h0=OperatorSum(unit="rad/ns", terms=()),
        drives=(),
        initial_state=State(kind="ket", frame="lab", data=carray([1, 0], (2,))),
    )
    return replace(
        req,
        problem=problem,
        observations=tuple(observations)
        if observations is not None
        else (Observation(id="state", kind="full_state", representation="ket"),),
        policy=replace(
            req.policy,
            representation="ket",
            method=MethodChoice(mode="fixed", value="reference-exact", allowed=()),
        ),
        provenance=replace(req.provenance, basis_mapping=()),
    )


def result_for(req, observations=None, differences=(), transforms=(), actual=None):
    count = req.output_times.shape[0]
    if observations is None:
        observations = (
            ObservationValue(
                id="state",
                kind="full_state",
                representation="ket",
                data=carray([1, 0] * count, (count, 2)),
            ),
        )
    observations = tuple(observations)
    representations = {
        item.id: item.representation if item.kind == "full_state" else "density"
        for item in observations
        if item.kind != "expectation"
    }
    return Result(
        request_id=request_id(req),
        output_times=req.output_times,
        tensor_order=req.problem.tensor_order,
        frame=req.problem.frame,
        observations=observations,
        report=ExecutionReport(
            backend_id="reference",
            backend_version="1",
            actual_policy=FrozenJSON(value=actual if actual is not None else policy_values(req)),
            policy_differences=differences,
            transforms=transforms,
            state_representations=FrozenJSON(value=representations),
            validation_level="transport",
            diagnostics=(),
        ),
    )
