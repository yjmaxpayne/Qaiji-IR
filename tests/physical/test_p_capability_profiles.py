# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查完整能力组合与结构边界。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from qaiji.core.physical import (
    ArrayData,
    Capabilities,
    CheckBudget,
    Drive,
    Environment,
    FrozenJSON,
    Jump,
    MethodChoice,
    Observation,
    OperatorSum,
    PContractError,
    ProductFactor,
    Signal,
    Site,
    State,
)
from qaiji.core.physical.capabilities import extract_requirements, match_capabilities
from qaiji.core.physical.codec import dump_requirements, load_request
from qaiji.core.physical.validation import check_problem, check_request


def request():
    data = json.loads((Path(__file__).parent / "data/bath-fixture.json").read_bytes())
    data["problem"]["extensions"] = []
    return load_request(json.dumps(data).encode())


def profile(**changes):
    result = dict(
        environment="closed",
        frame="lab",
        interpolation="zoh",
        determinism="deterministic",
        initial_kind="ket",
        method="reference-exact",
        output_kinds=["full_state"],
        state_representations=["density", "ket"],
    )
    result.update(changes)
    return result


def capabilities(*profiles, **changes):
    profiles = profiles or (profile(),)
    values = dict(
        consumer_id="test",
        consumer_version="1",
        profiles=[FrozenJSON(value=p) for p in profiles],
        max_dimension=64,
        precision=FrozenJSON(
            value={
                "dtype": "binary64",
                "min_atol": "0000000000000000",
                "min_rtol": "0000000000000000",
            }
        ),
        required_extensions=[],
        output_kinds=sorted({k for p in profiles for k in p["output_kinds"]}),
        methods=sorted({p["method"] for p in profiles}),
    )
    values.update(changes)
    return Capabilities(**values)


def test_p_profiles_match_as_whole_combinations():
    req = request()
    assert check_request(req, level="structure").complete
    requirements = extract_requirements(req)
    assert requirements.dimension == 6
    assert type(requirements.dimension) is int
    assert match_capabilities(requirements, capabilities()).complete
    delegated = replace(
        req,
        policy=replace(
            req.policy,
            method=MethodChoice(mode="delegate", value=None, allowed=["a", "reference-exact"]),
        ),
    )
    assert len(extract_requirements(delegated).profiles) == 2
    assert match_capabilities(extract_requirements(delegated), capabilities()).complete


def test_p_profiles_do_not_splice_summaries():
    requirements = extract_requirements(request())
    split = capabilities(
        profile(method="other"), profile(environment="markovian", state_representations=["density"])
    )
    report = match_capabilities(requirements, split)
    assert not report.complete
    assert report.diagnostics
    assert all(d.category == "UNSUPPORTED_CAPABILITY" for d in report.diagnostics)


@pytest.mark.parametrize(
    ("environment", "initial", "representation", "policy", "supported"),
    [
        ("closed", "ket", "ket", "either", True),
        ("closed", "ket", "either", "density", True),
        ("closed", "density", "ket", "either", False),
        ("closed", "density", "density", "either", True),
        ("markovian", "ket", "ket", "either", False),
        ("markovian", "ket", "density", "either", True),
        ("closed", "ket", "density", "ket", False),
    ],
)
def test_p_profile_representation_matrix(environment, initial, representation, policy, supported):
    req = request()
    state = req.problem.initial_state
    if initial == "density":
        state = State(
            kind="density",
            frame="lab",
            data=ArrayData.from_values(dtype="c128le", shape=[6, 6], values=[1] + [0] * 35),
        )
    req = replace(
        req,
        problem=replace(
            req.problem, environment=Environment(kind=environment, jumps=[]), initial_state=state
        ),
        observations=[Observation(id="s", kind="full_state", representation=representation)],
        policy=replace(req.policy, representation=policy),
    )
    assert check_request(req, level="structure").complete
    requirements = extract_requirements(req)
    reps = ["density"] if environment == "markovian" or initial == "density" else ["ket", "density"]
    result = match_capabilities(
        requirements,
        capabilities(
            profile(environment=environment, initial_kind=initial, state_representations=reps)
        ),
    )
    assert result.complete is supported


def test_p_profile_reports_all_missing_requirements():
    req = extract_requirements(request())
    cap = capabilities(
        profile(
            environment="markovian",
            method="other",
            output_kinds=["expectation"],
            state_representations=[],
        ),
        max_dimension=1,
        precision=FrozenJSON(
            value={
                "dtype": "binary64",
                "min_atol": "3ff0000000000000",
                "min_rtol": "3ff0000000000000",
            }
        ),
    )
    report = match_capabilities(req, cap)
    encoded = repr(report.diagnostics)
    for field in [
        "dimension",
        "atol",
        "rtol",
        "environment",
        "method",
        "output_kinds",
        "state_representations",
    ]:
        assert field in encoded
    assert all("missing" in repr(d.details) for d in report.diagnostics)


@pytest.mark.parametrize("change", ["rotating", "rwa"])
def test_p_known_unsupported_semantics_are_not_invalid(change):
    req = request()
    if change == "rotating":
        req = replace(
            req,
            problem=replace(
                req.problem,
                frame="rotating",
                initial_state=State(
                    kind="ket", frame="rotating", data=req.problem.initial_state.data
                ),
            ),
        )
    else:
        req = replace(req, problem=replace(req.problem, approximations=["rwa"]))
    assert check_request(req, level="structure").complete
    report = check_request(req, level="physical")
    assert report.diagnostics
    assert all(d.category == "UNSUPPORTED_CAPABILITY" for d in report.diagnostics)


@pytest.mark.parametrize(
    "change",
    [
        "reference",
        "shape",
        "coverage",
        "units",
        "times",
        "observation-id",
        "projection",
        "unknown-approximation",
    ],
)
def test_structure_rejects_cross_record_mismatch(change):
    req = request()
    assert check_request(req, level="structure").complete
    if change == "reference":
        req = replace(req, problem=replace(req.problem, tensor_order=["a", "unknown"]))
    elif change == "shape":
        req = replace(
            req,
            problem=replace(
                req.problem,
                initial_state=State(
                    kind="ket",
                    frame="lab",
                    data=ArrayData.from_values(dtype="c128le", shape=[2], values=[1, 0]),
                ),
            ),
        )
    elif change == "coverage":
        req = replace(
            req,
            problem=replace(
                req.problem,
                initial_state=State(
                    kind="product",
                    frame="lab",
                    factors=[
                        ProductFactor(
                            site="a",
                            kind="ket",
                            data=ArrayData.from_values(dtype="c128le", shape=[2], values=[1, 0]),
                        )
                    ],
                ),
            ),
        )
    elif change == "units":
        req = replace(req, problem=replace(req.problem, h0=replace(req.problem.h0, unit="1")))
    elif change == "times":
        req = replace(
            req, output_times=ArrayData.from_values(dtype="f64le", shape=[2], values=[1, 0])
        )
    elif change == "observation-id":
        req = replace(req, observations=[req.observations[0], req.observations[0]])
    elif change == "projection":
        req = replace(
            req,
            observations=[
                Observation(
                    id="v",
                    kind="projection",
                    input_sites=["b"],
                    isometry=ArrayData.from_values(dtype="c128le", shape=[2, 1], values=[1, 0]),
                )
            ],
        )
    else:
        req = replace(req, problem=replace(req.problem, approximations=["unknown"]))
    report = check_request(req, level="structure")
    assert not report.complete
    assert report.diagnostics
    assert report.diagnostics[0].category == "INVALID_REQUEST"


def test_structure_dimension_stays_integer_without_global_assembly():
    req = request()
    sites = [Site(id=str(i), dim=2, basis=["0", "1"]) for i in range(60)]
    ket = ArrayData.from_values(dtype="c128le", shape=[2], values=[1, 0])
    state = State(
        kind="product",
        frame="lab",
        factors=[ProductFactor(site=s.id, kind="ket", data=ket) for s in sites],
    )
    problem = replace(
        req.problem,
        sites=sites,
        tensor_order=[s.id for s in sites],
        h0=OperatorSum(unit="rad/ns", terms=[]),
        initial_state=state,
    )
    assert check_problem(
        problem, level="structure", budget=CheckBudget(max_dense_dimension=1)
    ).complete
    requirements = extract_requirements(replace(req, problem=problem))
    assert requirements.dimension == 2**60
    assert type(requirements.dimension) is int


def test_check_revalidates_tampered_fields():
    req = request()
    assert check_request(req, level="transport").complete
    object.__setattr__(req.problem.sites[0], "dim", True)
    report = check_request(req, level="transport")
    assert not report.complete
    assert report.diagnostics


def test_supported_physical_check_completes_numeric_certification():
    report = check_request(request(), level="physical")
    assert report.complete
    assert not report.unchecked


def test_full_state_observations_need_a_common_policy_representation():
    req = request()
    req = replace(
        req,
        policy=replace(req.policy, representation="either"),
        observations=[
            Observation(id="ket", kind="full_state", representation="ket"),
            Observation(id="density", kind="full_state", representation="density"),
        ],
    )
    assert check_request(req, level="structure").complete
    report = match_capabilities(extract_requirements(req), capabilities())
    assert not report.complete
    assert report.diagnostics


def test_zero_duration_at_nonzero_origin_and_empty_zoh():
    req = request()
    edges = ArrayData.from_values(dtype="f64le", shape=[1], values=[7])
    req = replace(req, problem=replace(req.problem, signal_edges=edges), output_times=edges)
    assert check_request(req, level="structure").complete


def test_each_full_state_id_keeps_its_representation_choices():
    req = request()
    req = replace(
        req,
        policy=replace(req.policy, representation="either"),
        observations=[
            Observation(id="first", kind="full_state", representation="either"),
            Observation(id="second", kind="full_state", representation="density"),
        ],
    )
    document = json.loads(dump_requirements(extract_requirements(req)))
    assert document["profiles"][0]["state_representations"] == {
        "first": ["density", "ket"],
        "second": ["density"],
    }


def test_rotating_profile_cannot_override_p_v1_semantics():
    req = request()
    req = replace(
        req,
        problem=replace(
            req.problem,
            frame="rotating",
            initial_state=State(kind="ket", frame="rotating", data=req.problem.initial_state.data),
        ),
    )
    assert check_request(req, level="structure").complete
    report = match_capabilities(extract_requirements(req), capabilities(profile(frame="rotating")))
    assert not report.complete
    assert {d.category for d in report.diagnostics} == {"UNSUPPORTED_CAPABILITY"}
    assert "frame" in repr(report.diagnostics)


def test_rwa_requirements_reject_lost_approximation_semantics():
    req = request()
    assert extract_requirements(req).profiles
    req = replace(req, problem=replace(req.problem, approximations=["rwa"]))
    assert check_request(req, level="structure").complete
    with pytest.raises(PContractError) as error:
        extract_requirements(req)
    assert {d.category for d in error.value.diagnostics} == {"UNSUPPORTED_CAPABILITY"}
    assert error.value.diagnostics[0].path == "/problem/approximations"
    assert "rwa" in repr(error.value.diagnostics[0].details)


def test_mixed_product_requires_density_output():
    req = request()
    factors = [
        ProductFactor(
            site="a",
            kind="ket",
            data=ArrayData.from_values(dtype="c128le", shape=[2], values=[1, 0]),
        ),
        ProductFactor(
            site="b",
            kind="density",
            data=ArrayData.from_values(dtype="c128le", shape=[3, 3], values=[1] + [0] * 8),
        ),
    ]
    req = replace(
        req,
        problem=replace(
            req.problem, initial_state=State(kind="product", frame="lab", factors=factors)
        ),
    )
    requirements = extract_requirements(req)
    document = json.loads(dump_requirements(requirements))
    assert document["profiles"][0]["initial_kind"] == "density"
    assert match_capabilities(
        requirements,
        capabilities(profile(initial_kind="density", state_representations=["density"])),
    ).complete


@pytest.mark.parametrize("field", ["output_kinds", "methods", "profiles"])
def test_capability_summaries_and_profile_fields_are_revalidated(field):
    requirements = extract_requirements(request())
    cap = capabilities()
    assert match_capabilities(requirements, cap).complete
    if field == "profiles":
        bad = profile()
        bad.pop("frame")
        cap = replace(cap, profiles=[FrozenJSON(value=bad)])
    else:
        cap = replace(cap, **{field: ["unsupported"]})
    report = match_capabilities(requirements, cap)
    assert not report.complete
    assert report.diagnostics
    assert {d.category for d in report.diagnostics} == {"INVALID_REQUEST"}


@pytest.mark.parametrize("zero_duration", [False, True])
def test_signal_and_all_observation_structures_have_legal_controls(zero_duration):
    req = request()
    edges = [7] if zero_duration else [7, 8, 9]
    samples = [] if zero_duration else [0, 1]

    def vector(values):
        return ArrayData.from_values(dtype="f64le", shape=[len(values)], values=values)

    identity = OperatorSum(unit="1", terms=[])
    drive = Drive(
        id="drive",
        operator=identity,
        signal=Signal(kind="zoh", unit="rad/ns", values=vector(samples)),
    )
    jump = Jump(
        id="jump", operator=identity, rate=Signal(kind="zoh", unit="1/ns", values=vector(samples))
    )
    problem = replace(
        req.problem,
        signal_edges=vector(edges),
        drives=[drive],
        environment=Environment(kind="markovian", jumps=[jump]),
    )
    observations = [
        Observation(id="expect", kind="expectation", operator=identity),
        Observation(id="trace", kind="partial_trace", keep_sites=["b", "a"]),
        Observation(
            id="project",
            kind="projection",
            input_sites=["b"],
            isometry=ArrayData.from_values(dtype="c128le", shape=[3, 1], values=[1, 0, 0]),
        ),
    ]
    req = replace(
        req,
        problem=problem,
        output_times=vector([7] if zero_duration else [7, 7.5, 9]),
        observations=observations,
    )
    assert check_request(req, level="structure").complete
    requirements = extract_requirements(req)
    assert json.loads(dump_requirements(requirements))["profiles"][0]["state_representations"] == {}
    broken_drive = replace(
        drive,
        signal=Signal(kind="zoh", unit="rad/ns", values=vector([1])),
    )
    broken = replace(req, problem=replace(problem, drives=[broken_drive]))
    assert not check_request(broken, level="structure").complete


def test_requirement_full_state_needs_an_observation_map():
    requirements = extract_requirements(request())
    assert match_capabilities(requirements, capabilities()).complete
    document = json.loads(dump_requirements(requirements))
    document["profiles"][0]["state_representations"] = {}
    forged = replace(requirements, profiles=[FrozenJSON(value=document["profiles"][0])])
    report = match_capabilities(forged, capabilities())
    assert not report.complete
    assert {d.category for d in report.diagnostics} == {"INVALID_REQUEST"}


def test_wrong_check_entry_point_rejects_other_record_type():
    req = request()
    assert check_request(req, level="transport").complete
    assert not check_problem(req, level="transport").complete


@pytest.mark.parametrize(
    "case", ["markovian-ket", "density-ket", "policy-conflict", "observation-conflict"]
)
def test_physical_gate_rejects_incompatible_full_state_representations(case):
    req = request()
    assert not check_request(req, level="physical").diagnostics
    observations = [Observation(id="first", kind="full_state", representation="ket")]
    policy = replace(req.policy, representation="either")
    problem = req.problem
    if case == "markovian-ket":
        problem = replace(problem, environment=Environment(kind="markovian", jumps=[]))
    elif case == "density-ket":
        data = ArrayData.from_values(dtype="c128le", shape=[6, 6], values=[1] + [0] * 35)
        problem = replace(problem, initial_state=State(kind="density", frame="lab", data=data))
    elif case == "policy-conflict":
        policy = replace(policy, representation="density")
    else:
        observations.append(Observation(id="second", kind="full_state", representation="density"))
    req = replace(req, problem=problem, policy=policy, observations=observations)
    assert check_request(req, level="structure").complete
    report = check_request(req, level="physical")
    assert not report.complete
    assert report.diagnostics
    assert {d.category for d in report.diagnostics} == {"UNSUPPORTED_CAPABILITY"}
    details = repr(report.diagnostics)
    for observation in observations:
        assert "state_representations/" + observation.id in details


def test_physical_gate_reports_frame_and_approximation_together():
    req = request()
    assert not check_request(req, level="physical").diagnostics
    problem = replace(
        req.problem,
        frame="rotating",
        approximations=["rwa"],
        initial_state=State(kind="ket", frame="rotating", data=req.problem.initial_state.data),
    )
    req = replace(req, problem=problem)
    assert check_request(req, level="structure").complete
    report = check_request(req, level="physical")
    assert {d.category for d in report.diagnostics} == {"UNSUPPORTED_CAPABILITY"}
    details = repr(report.diagnostics)
    assert "frame" in details
    assert "approximations" in details


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("structure", {"transport", "structure"}),
        ("physical", {"transport", "structure", "capability", "physical"}),
    ],
)
def test_transport_failure_records_all_blocked_stages(monkeypatch, level, expected):
    import qaiji.core.physical.validation as validation

    req = request()
    assert check_request(req, level="transport").complete
    object.__setattr__(req.problem.sites[0], "dim", True)

    def forbidden(*args, **kwargs):
        pytest.fail("Structure executed after transport failure.")

    monkeypatch.setattr(validation._Structure, "problem_fields", forbidden)
    report = check_request(req, level=level)
    assert not report.complete
    assert report.diagnostics
    assert expected <= set(report.unchecked)


def test_structure_failure_records_and_skips_capability(monkeypatch):
    import qaiji.core.physical.capabilities as capability_module

    req = request()
    assert check_request(req, level="structure").complete
    req = replace(req, output_times=ArrayData.from_values(dtype="f64le", shape=[2], values=[1, 0]))

    def forbidden(*args, **kwargs):
        pytest.fail("Capability executed after structure failure.")

    monkeypatch.setattr(capability_module, "_representation_missing", forbidden, raising=False)
    report = check_request(req, level="physical")
    assert not report.complete
    assert report.diagnostics
    assert {"structure", "capability", "physical"} <= set(report.unchecked)
