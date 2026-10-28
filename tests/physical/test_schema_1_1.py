# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""检查 P schema 1.1：旋转系频率、近似能力与 bath 扩展。"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from qaiji.core.physical import FrozenJSON, PContractError
from qaiji.core.physical.capabilities import extract_requirements, match_capabilities
from qaiji.core.physical.codec import (
    dump_problem,
    dump_request,
    load_capabilities,
    load_problem,
    load_request,
)
from qaiji.core.physical.model import (
    Capabilities,
    LocalFactor,
    OperatorSum,
    OperatorTerm,
    RequiredExtension,
    Result,
    Site,
    State,
)
from qaiji.core.physical.validation import check_request

TWO_PI = 2 * math.pi
# anyon_2q_CZ 平台两个比特的驱动频率（GHz）；换成 rad/ns 才是契约单位。
GHZ = {"q0": 5.52845, "q1": 5.6752}
BATH = ("qaiji.p.bath", "1.0")
BATH_CONTENT_TYPE = "application/vnd.qaiji.p.bath+json"
PSD = {"frequency_axis": "rad/ns", "sides": "one_sided", "fourier_measure": "1/pi"}


def _hex(value: float) -> str:
    return struct.pack(">d", value).hex()


def _lab_request():
    data = json.loads((Path(__file__).parent / "data/bath-fixture.json").read_bytes())
    data["problem"]["extensions"] = []
    return load_request(json.dumps(data).encode())


def _state(state, frame, data=None):
    # State 按 kind 分支，dataclasses.replace 会传入其他分支的字段，所以显式构造。
    return State(kind=state.kind, frame=frame, data=state.data if data is None else data)


def _two_site_request(tensor_order=("q1", "q0")):
    # tensor_order 与 sites 的顺序不同，才能区分「按 tensor_order 排序」与「按 sites 排序」。
    base = _lab_request()
    sites = (Site(id="q0", dim=2, basis=("0", "1")), Site(id="q1", dim=2, basis=("0", "1")))
    state = base.problem.initial_state
    ket = replace(state.data, shape=(4,), data=state.data.data[:64])
    problem = replace(
        base.problem,
        sites=sites,
        tensor_order=tensor_order,
        h0=OperatorSum(unit="rad/ns", terms=()),
        drives=(),
        initial_state=_state(state, state.frame, ket),
    )
    return replace(base, problem=problem)


def _rotating(req, freqs, *, approximations=("rwa",)):
    problem = req.problem
    return replace(
        req,
        problem=replace(
            problem,
            frame="rotating",
            initial_state=_state(problem.initial_state, "rotating"),
            rotation_freqs=tuple(freqs),
            approximations=approximations,
        ),
    )


def _rad(site: str) -> tuple[str, float]:
    return (site, TWO_PI * GHZ[site])


def _details(diagnostic):
    from qaiji.core.physical.capabilities import _plain

    return _plain(diagnostic.details)


def _codes(report, path=None):
    return [d.code for d in report.diagnostics if path is None or d.path == path]


# --- 版本：5 类 P 文档同属 1.1，0.3.0 不读 1.0 文档（U-T4a-1、U-T4a-2） ---


def test_every_p_document_declares_schema_1_1():
    """5 类文档共用一个版本；漏改任何一类，混用 1.0 与 1.1 的消费者会静默接受旧文档。"""
    req = _lab_request()
    requirements = extract_requirements(req)
    capabilities = Capabilities(
        consumer_id="t",
        consumer_version="1",
        profiles=requirements.profiles,
        max_dimension=4,
        precision=FrozenJSON(
            value={"dtype": "binary64", "min_atol": _hex(0.0), "min_rtol": _hex(0.0)}
        ),
        required_extensions=(),
        output_kinds=requirements.output_kinds,
        methods=requirements.methods,
    )
    assert json.loads(dump_request(req).document)["schema"] == "qaiji.p.request/1.1"
    assert req.problem.schema == "qaiji.p.problem/1.1"
    assert requirements.schema == "qaiji.p.requirements/1.1"
    assert capabilities.schema == "qaiji.p.capabilities/1.1"
    assert Result.__dataclass_fields__["schema"].default == "qaiji.p.result/1.1"


def test_reader_rejects_a_1_0_problem_document_by_its_missing_field():
    """严格单版本：1.0 problem 先以字段集失败，诊断列出缺少的 rotation_freqs。"""
    doc = json.loads(dump_problem(_lab_request().problem).document)
    del doc["rotation_freqs"]
    doc["schema"] = "qaiji.p.problem/1.0"
    with pytest.raises(PContractError) as caught:
        load_problem(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())
    (diagnostic,) = caught.value.diagnostics
    assert diagnostic.code == "KEYS"
    assert _details(diagnostic)["missing"] == ["rotation_freqs"]


def test_reader_rejects_a_1_0_capabilities_document_by_version():
    """字段集不变的文档类以 VERSION 拒收 1.0，不会被当成 1.1 读入。"""
    req = _lab_request()
    requirements = extract_requirements(req)
    doc = {
        "consumer_id": "t",
        "consumer_version": "1",
        "profiles": [json.loads(json.dumps(_profile_dict(requirements)))],
        "max_dimension": 4,
        "precision": {"dtype": "binary64", "min_atol": _hex(0.0), "min_rtol": _hex(0.0)},
        "required_extensions": [],
        "output_kinds": list(requirements.output_kinds),
        "methods": list(requirements.methods),
        "schema": "qaiji.p.capabilities/1.0",
    }
    with pytest.raises(PContractError) as caught:
        load_capabilities(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())
    assert [d.code for d in caught.value.diagnostics] == ["VERSION"]


def _profile_dict(requirements):
    from qaiji.core.physical.capabilities import _plain

    profile = _plain(requirements.profiles[0])
    profile["state_representations"] = ["density", "ket"]
    return profile


# --- rotation_freqs 的编码与结构规则 ---


def test_rotation_freqs_round_trip_as_site_and_binary64_pairs():
    """频率按 [站点, binary64 十六进制] 编码；往返逐位相同，才能参与身份哈希。"""
    req = _rotating(_two_site_request(), [_rad("q1"), _rad("q0")])
    doc = json.loads(dump_problem(req.problem).document)
    assert doc["rotation_freqs"] == [["q1", _hex(TWO_PI * 5.6752)], ["q0", _hex(TWO_PI * 5.52845)]]
    assert load_request(dump_request(req).document) == req


def test_lab_problem_has_no_rotation_freqs():
    """实验室系的合法值是空表；重冻的 1.1 夹具显式写出空表。"""
    assert _lab_request().problem.rotation_freqs == ()
    assert check_request(_lab_request(), level="structure").complete


@pytest.mark.parametrize(
    ("frame", "freqs"),
    [
        ("lab", [_rad("q1"), _rad("q0")]),  # 实验室系不得带旋转频率
        ("rotating", []),  # 旋转系缺全部站点
        ("rotating", [_rad("q1")]),  # 旋转系缺 1 个站点
        ("rotating", [_rad("q0"), _rad("q1")]),  # 按 sites 排序，不按 tensor_order
        ("rotating", [_rad("q1"), _rad("q1")]),  # 重复站点
        ("rotating", [_rad("q1"), _rad("q0"), ("qx", 1.0)]),  # 多出未知站点
    ],
    ids=["lab-nonempty", "rotating-empty", "missing-site", "sites-order", "duplicate", "extra"],
)
def test_rotation_freqs_must_follow_the_tensor_order(frame, freqs):
    """每条规则单独可破：只查长度、只查集合或只查 sites 顺序的实现各放过其中一格。"""
    req = _rotating(_two_site_request(), freqs)
    if frame == "lab":
        req = replace(
            req,
            problem=replace(
                req.problem,
                frame="lab",
                initial_state=_state(req.problem.initial_state, "lab"),
                approximations=(),
            ),
        )
    report = check_request(req, level="structure")
    assert _codes(report) == ["ROTATION_FREQS"]
    assert report.diagnostics[0].path == "/problem/rotation_freqs"


@pytest.mark.parametrize(
    ("value", "code"),
    [((("q0", float("nan")),), "NONFINITE"), ((("q0", "34.7"),), "NUMBER"), ((("q0",),), "KEYS")],
    ids=["nan", "text", "one-item"],
)
def test_rotation_freqs_entries_are_site_number_pairs(value, code):
    """模型层只接受（站点, 有限实数）二元组。"""
    with pytest.raises(PContractError) as caught:
        replace(_lab_request().problem, rotation_freqs=value)
    assert caught.value.diagnostics[0].code == code


# --- 认证级别：旋转系只认证到 structure（S4_CERT，U-T4a-3） ---


def test_rotating_requests_are_certified_only_to_structure():
    """physical 级没有检查能区分按 GHz 写入的频率（少乘 2π）：两份请求的检查结果相同。

    若以后加入能区分它们的物理检查，本测试失败，physical.rst 的认证级别说明须同步修改。
    """
    order = ("q1", "q0")
    right = _rotating(_two_site_request(order), [_rad(s) for s in order])
    ghz = _rotating(_two_site_request(order), [(s, GHZ[s]) for s in order])
    for req in (right, ghz):
        assert check_request(req, level="structure").complete
        physical = check_request(req, level="physical")
        assert not physical.complete
        assert _codes(physical) == ["PROFILE"]
        assert _details(physical.diagnostics[0])["missing"] == ["frame", "approximations"]


# --- 能力：profile 的近似键与旋转系匹配（AC-13(c)） ---


def _consumer(**changes):
    req = _lab_request()
    profile = _profile_dict(extract_requirements(req))
    profile.update(changes)
    return Capabilities(
        consumer_id="t",
        consumer_version="1",
        profiles=(FrozenJSON(value=profile),),
        max_dimension=64,
        precision=FrozenJSON(
            value={"dtype": "binary64", "min_atol": _hex(0.0), "min_rtol": _hex(0.0)}
        ),
        required_extensions=(),
        output_kinds=tuple(profile["output_kinds"]),
        methods=(profile["method"],),
    )


def _rotating_lab_site_request():
    req = _lab_request()
    return _rotating(req, [(site, TWO_PI * 5.0) for site in req.problem.tensor_order])


def test_requirements_carry_frame_and_approximations():
    """旋转系 + RWA 请求不再在提取时拒收；需求 profile 记下参考系与近似。"""
    requirements = extract_requirements(_rotating_lab_site_request())
    (profile,) = [p.value for p in requirements.profiles]
    assert dict(profile.items)["frame"] == "rotating"
    assert list(dict(profile.items)["approximations"].items) == ["rwa"]


@pytest.mark.parametrize(
    ("changes", "missing"),
    [
        (dict(frame="rotating", approximations=["rwa"]), []),
        (dict(frame="lab", approximations=["rwa"]), ["frame"]),
        (dict(frame="rotating", approximations=[]), ["approximations"]),
    ],
    ids=["declares-both", "lab-only", "no-rwa"],
)
def test_rotating_requests_match_only_declared_consumers(changes, missing):
    """只声明实验室系的消费者拒收旋转系请求（AC-13(c)）；未声明 rwa 的消费者拒收 RWA 请求。"""
    report = match_capabilities(
        extract_requirements(_rotating_lab_site_request()), _consumer(**changes)
    )
    assert report.complete is (not missing)
    if missing:
        assert _details(report.diagnostics[0])["missing"] == [
            f"profiles/0/capabilities/0/{field}" for field in missing
        ]


def test_lab_requests_still_match_a_consumer_that_also_allows_rwa():
    """允许 rwa 的消费者仍接受不要求近似的实验室系请求。"""
    report = match_capabilities(
        extract_requirements(_lab_request()), _consumer(approximations=["rwa"])
    )
    assert report.complete


@pytest.mark.parametrize(
    "approximations", [None, ["magnus"], ["rwa", "rwa"]], ids=["missing", "unknown", "duplicate"]
)
def test_capability_profiles_require_known_approximations(approximations):
    """profile 键集合含 approximations，取值只允许已知近似名。"""
    from qaiji.core.physical.capabilities import _plain

    consumer = _consumer()
    profile = _plain(consumer.profiles[0])
    if approximations is None:
        del profile["approximations"]
    else:
        profile["approximations"] = approximations
    report = match_capabilities(
        extract_requirements(_lab_request()),
        replace(consumer, profiles=(FrozenJSON(value=profile),)),
    )
    assert not report.complete
    assert [(d.code, d.path) for d in report.diagnostics] == [
        ("KEYS", "/profiles/0" if approximations is None else "/profiles/0/approximations")
    ]


# --- bath 扩展 qaiji.p.bath/1.0（U-T4a-4） ---


def _coupling(unit="1", site=None, dim=2):
    req = _lab_request()
    site = site or req.problem.sites[0].id
    matrix = req.problem.initial_state.data
    # 对角阵 diag(0, …, 0, 1)：最高能级的数算符。
    data = bytes(16 * (dim * dim - 1)) + struct.pack("<dd", 1.0, 0.0)
    number = replace(matrix, shape=(dim, dim), data=data)
    op = OperatorSum(
        unit=unit,
        terms=(OperatorTerm(coefficient=1, factors=(LocalFactor(site=site, matrix=number),)),),
    )
    probe = replace(req.problem, h0=op)
    return json.loads(dump_problem(probe).document)["h0"]


def _array(values):
    import base64

    data = struct.pack(f"<{len(values)}d", *values)
    return {"dtype": "f64le", "shape": [len(values)], "data": base64.b64encode(data).decode()}


DENSITIES = {
    "drude_lorentz": {"kind": "drude_lorentz", "lam": _hex(3.14159e-4), "gamma": _hex(0.314159)},
    "one_over_f": {"kind": "one_over_f", "eta": _hex(1e-3), "w_lc": _hex(1e-3), "w_hc": _hex(10.0)},
    "tabulated": {
        "kind": "tabulated",
        "omega": _array([0.0, 1.0, 2.0]),
        "J": _array([0.0, 0.5, 0.2]),
    },
}


def _bath_payload(**changes):
    payload = {
        "coupling": _coupling(),
        "spectral_density": DENSITIES["drude_lorentz"],
        "temperature": _hex(0.15707963267948966),
        "psd": dict(PSD),
    }
    payload.update(changes)
    return payload


def _bath_request(payload=None, *, content_type=BATH_CONTENT_TYPE, version="1.0"):
    req = _lab_request()
    extension = RequiredExtension(
        namespace=BATH[0],
        version=version,
        content_type=content_type,
        required=True,
        affects_physics=True,
        payload=FrozenJSON(value=_bath_payload() if payload is None else payload),
    )
    return replace(req, problem=replace(req.problem, extensions=(extension,)))


@pytest.mark.parametrize("kind", sorted(DENSITIES))
def test_bath_payloads_pass_structure_and_stop_at_physical(kind):
    """3 种谱密度都能表达；Qaiji 没有 bath 求解器，所以只认证到 structure。"""
    req = _bath_request(_bath_payload(spectral_density=DENSITIES[kind]))
    assert load_request(dump_request(req).document) == req
    assert check_request(req, level="structure").complete
    physical = check_request(req, level="physical")
    assert _codes(physical) == ["REQUIRED_EXTENSION"]
    assert extract_requirements(req).required_extensions == (BATH,)


def _density(kind, **changes):
    return {**DENSITIES[kind], **changes}


BAD_BATHS = {
    "missing-psd": ({k: v for k, v in _bath_payload().items() if k != "psd"}, "KEYS"),
    "unknown-kind": (_bath_payload(spectral_density={"kind": "ohmic"}), "BATH"),
    "density-keys": (
        _bath_payload(spectral_density={"kind": "drude_lorentz", "lam": _hex(1.0)}),
        "KEYS",
    ),
    "integer-number": (_bath_payload(temperature=1), "BINARY64"),
    "lam-zero": (_bath_payload(spectral_density=_density("drude_lorentz", lam=_hex(0.0))), "BATH"),
    "gamma-negative": (
        _bath_payload(spectral_density=_density("drude_lorentz", gamma=_hex(-1.0))),
        "BATH",
    ),
    "eta-zero": (_bath_payload(spectral_density=_density("one_over_f", eta=_hex(0.0))), "BATH"),
    "cutoffs-reversed": (
        _bath_payload(spectral_density=_density("one_over_f", w_lc=_hex(10.0), w_hc=_hex(1.0))),
        "BATH",
    ),
    "omega-decreasing": (
        _bath_payload(spectral_density=_density("tabulated", omega=_array([0.0, 2.0, 1.0]))),
        "BATH",
    ),
    "omega-negative": (
        _bath_payload(spectral_density=_density("tabulated", omega=_array([-1.0, 1.0, 2.0]))),
        "BATH",
    ),
    "j-negative": (
        _bath_payload(spectral_density=_density("tabulated", J=_array([0.0, -0.5, 0.2]))),
        "BATH",
    ),
    "j-nonzero-at-zero": (
        _bath_payload(spectral_density=_density("tabulated", J=_array([0.1, 0.5, 0.2]))),
        "BATH",
    ),
    "length-mismatch": (
        _bath_payload(spectral_density=_density("tabulated", J=_array([0.0, 0.5]))),
        "SHAPE",
    ),
    "single-sample": (
        _bath_payload(spectral_density=_density("tabulated", omega=_array([1.0]), J=_array([0.5]))),
        "SHAPE",
    ),
    "temperature-zero": (_bath_payload(temperature=_hex(0.0)), "BATH"),
    "psd-two-sided": (_bath_payload(psd={**PSD, "sides": "two_sided"}), "BATH"),
    "psd-axis": (_bath_payload(psd={**PSD, "frequency_axis": "GHz"}), "BATH"),
    "psd-measure": (_bath_payload(psd={**PSD, "fourier_measure": "1/(2pi)"}), "BATH"),
    "coupling-unit": (_bath_payload(coupling=_coupling(unit="rad/ns")), "UNIT"),
    "coupling-site": (_bath_payload(coupling=_coupling(site="zz")), "SITE"),
    "j-empty": (
        _bath_payload(
            spectral_density=_density("tabulated", omega=_array([0.0, 1.0]), J=_array([]))
        ),
        "SHAPE",
    ),
    "w-lc-negative": (
        _bath_payload(spectral_density=_density("one_over_f", w_lc=_hex(-1.0), w_hc=_hex(10.0))),
        "BATH",
    ),
    "arrays-2d": (
        _bath_payload(
            spectral_density=_density(
                "tabulated",
                omega={**_array([0.0, 1.0, 2.0, 3.0]), "shape": [2, 2]},
                J={**_array([0.0, 1.0, 2.0, 3.0]), "shape": [2, 2]},
            )
        ),
        "SHAPE",
    ),
    "temperature-negative": (_bath_payload(temperature=_hex(-0.1)), "BATH"),
    "kind-list": (_bath_payload(spectral_density={"kind": ["drude_lorentz"]}), "BATH"),
    "coupling-matrix-shape": (_bath_payload(coupling=_coupling(dim=3)), "FACTOR_SHAPE"),
    "coupling-not-record": (_bath_payload(coupling={"unit": "1"}), "KEYS"),
    "extra-top-key": (_bath_payload(statistics="bosonic"), "KEYS"),
    "density-extra-key": (
        _bath_payload(spectral_density=_density("drude_lorentz", cutoff=_hex(1.0))),
        "KEYS",
    ),
    "psd-extra-key": (_bath_payload(psd={**PSD, "normalized": "yes"}), "KEYS"),
    "omega-complex": (
        # omega 与 J 都是复数：长度相同，只有 dtype 检查能拦下它。
        _bath_payload(
            spectral_density=_density(
                "tabulated",
                omega={**_array([0.0, 0.0, 1.0, 0.0, 2.0, 0.0]), "dtype": "c128le", "shape": [3]},
                J={**_array([0.0, 0.0, 0.5, 0.0, 0.2, 0.0]), "dtype": "c128le", "shape": [3]},
            )
        ),
        "SHAPE",
    ),
    "omega-repeated": (
        _bath_payload(spectral_density=_density("tabulated", omega=_array([0.0, 1.0, 1.0]))),
        "BATH",
    ),
    "cutoffs-equal": (
        _bath_payload(spectral_density=_density("one_over_f", w_lc=_hex(1.0), w_hc=_hex(1.0))),
        "BATH",
    ),
}


@pytest.mark.parametrize("name", sorted(BAD_BATHS))
def test_bath_payload_rules_reject_each_violation(name):
    """每条 payload 规则配一个只违反它的输入；诊断位于该扩展的 payload 之下。"""
    payload, code = BAD_BATHS[name]
    report = check_request(_bath_request(payload), level="structure")
    assert not report.complete
    assert _codes(report)[0] == code
    assert report.diagnostics[0].path.startswith("/problem/extensions/0/payload")


def test_bath_extension_requires_its_content_type():
    """命名空间与版本相同但内容类型不同的扩展不按 bath 解读，结构检查拒收。"""
    report = check_request(_bath_request(content_type="application/json"), level="structure")
    assert _codes(report) == ["BATH"]
    assert report.diagnostics[0].path == "/problem/extensions/0/content_type"


def test_other_bath_versions_stay_opaque():
    """未知版本不按 1.0 规则校验，仍走通用扩展路径：structure 通过，physical 报缺解释器。"""
    req = _bath_request({"anything": "goes"}, version="2.0")
    assert check_request(req, level="structure").complete
    assert _codes(check_request(req, level="physical")) == ["REQUIRED_EXTENSION"]


def test_tabulated_density_may_start_above_zero_with_a_positive_value():
    """J(0)=0 只约束 omega=0 处的样本；从正频率开始的表可以取正值。"""
    density = _density("tabulated", omega=_array([0.5, 1.0]), J=_array([0.3, 0.2]))
    assert check_request(
        _bath_request(_bath_payload(spectral_density=density)), level="structure"
    ).complete


def test_bath_rules_apply_to_every_extension_position():
    """bath 扩展不在第 0 位时同样校验；诊断路径指向它自己的下标。"""
    req = _bath_request(_bath_payload(temperature=_hex(0.0)))
    opaque = json.loads((Path(__file__).parent / "data/bath-fixture.json").read_bytes())
    other = load_request(json.dumps(opaque).encode()).problem.extensions[0]
    req = replace(req, problem=replace(req.problem, extensions=(other, *req.problem.extensions)))
    report = check_request(req, level="structure")
    assert [(d.code, d.path) for d in report.diagnostics] == [
        ("BATH", "/problem/extensions/1/payload/temperature")
    ]


def test_bath_diagnostics_use_the_problem_root_when_checking_a_problem():
    """单独检查 problem 时，codec 与值域两类诊断都不带 /problem 前缀。"""
    from qaiji.core.physical.validation import check_problem

    bad_shape = _bath_request(_bath_payload(temperature=1)).problem
    bad_value = _bath_request(_bath_payload(temperature=_hex(0.0))).problem
    assert [d.path for d in check_problem(bad_shape, level="structure").diagnostics] == [
        "/extensions/0/payload/temperature"
    ]
    assert [d.path for d in check_problem(bad_value, level="structure").diagnostics] == [
        "/extensions/0/payload/temperature"
    ]


@pytest.mark.parametrize(
    ("entry", "code"),
    [(["q1"], "KEYS"), (["q1", "34.7"], "BINARY64"), ([1, _hex(1.0)], "JSON_TYPE")],
    ids=["one-item", "decimal-text", "site-number"],
)
def test_rotation_freqs_decoding_rejects_bad_pairs(entry, code):
    """codec 按 [文本, binary64] 解码每一项；十进制文本在 codec 层就以 BINARY64 失败。"""
    req = _rotating(_two_site_request(), [_rad("q1"), _rad("q0")])
    doc = json.loads(dump_problem(req.problem).document)
    doc["rotation_freqs"][0] = entry
    with pytest.raises(PContractError) as caught:
        load_problem(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())
    first = caught.value.diagnostics[0]
    assert (first.code, first.path) == (
        code,
        "/rotation_freqs/0"
        if code == "KEYS"
        else f"/rotation_freqs/0/{0 if code == 'JSON_TYPE' else 1}",
    )


def test_rotation_freqs_survive_the_attachment_layout():
    """附件布局只外置数组；旋转频率仍内联，往返后相等。"""
    req = _rotating(_two_site_request(), [_rad("q1"), _rad("q0")])
    artifact = dump_problem(req.problem, layout="attachments")
    doc = json.loads(artifact.document)
    assert doc["rotation_freqs"] == [["q1", _hex(TWO_PI * 5.6752)], ["q0", _hex(TWO_PI * 5.52845)]]
    restored = load_problem(artifact.document, attachments=dict(artifact.attachments))
    assert restored == req.problem


@pytest.mark.parametrize("kind", ["request", "result", "requirements", "capabilities"])
def test_each_document_kind_rejects_schema_1_0(kind):
    """字段集不变的 4 类文档各自以 VERSION 拒收 1.0；只放宽某一类的实现会被对应参数拦下。"""
    from qaiji.core.physical import codec

    fields = json.loads((Path(__file__).parent / "data/schema-fields.json").read_bytes())
    doc = dict(fields["examples"][kind], schema=f"qaiji.p.{kind}/1.0")
    load = getattr(codec, f"load_{kind}")
    with pytest.raises(PContractError) as caught:
        load(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())
    assert [(d.code, d.path) for d in caught.value.diagnostics] == [("VERSION", "/schema")]


def test_a_problem_may_carry_several_baths():
    """每个 bath 扩展独立描述一个库（对应 EmuPlat 的 baths 元组）；两个合法 bath 都通过结构检查。"""
    first = _bath_request().problem.extensions[0]
    second = _bath_request(_bath_payload(temperature=_hex(2.0))).problem.extensions[0]
    req = _lab_request()
    req = replace(req, problem=replace(req.problem, extensions=(first, second)))
    assert check_request(req, level="structure").complete
    assert extract_requirements(req).required_extensions == (BATH, BATH)
    # 第 2 个 bath 非法时同样被检出：只校验第 1 个 bath 的实现会放过它。
    bad = _bath_request(_bath_payload(temperature=_hex(0.0))).problem.extensions[0]
    req = replace(req, problem=replace(req.problem, extensions=(first, bad)))
    report = check_request(req, level="structure")
    assert [(d.code, d.path) for d in report.diagnostics] == [
        ("BATH", "/problem/extensions/1/payload/temperature")
    ]


@pytest.mark.parametrize(
    ("frame", "approximations", "codes"),
    [
        ("lab", ("rwa",), ["APPROXIMATION"]),
        ("rotating", ("rwa",), []),
        ("rotating", (), []),
        ("lab", (), []),
    ],
    ids=["lab-rwa", "rotating-rwa", "rotating-exact", "lab-exact"],
)
def test_rwa_needs_a_rotating_frame(frame, approximations, codes):
    """RWA 在旋转系中丢弃反旋项；实验室系下没有定义，结构检查拒收。"""
    req = _rotating(_two_site_request(), [_rad("q1"), _rad("q0")], approximations=approximations)
    if frame == "lab":
        problem = req.problem
        req = replace(
            req,
            problem=replace(
                problem,
                frame="lab",
                rotation_freqs=(),
                initial_state=_state(problem.initial_state, "lab"),
            ),
        )
    report = check_request(req, level="structure")
    assert _codes(report) == codes
    if codes:
        assert report.diagnostics[0].path == "/problem/approximations"
