# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""P 层分级结构与物理检查。"""

from __future__ import annotations

import math
import struct
from itertools import pairwise
from typing import Any, cast

from . import codec
from ._numeric import _NumericContext
from .arrays import ArrayData, FrozenJSON
from .diagnostics import (
    CheckBudget,
    CheckReport,
    Diagnostic,
    PContractError,
    _Category,
    _Level,
)
from .model import OperatorSum, Problem, Request, RequiredExtension

_DEFAULT_BUDGET = CheckBudget()


def _diagnostic(
    code: str, path: str, message: str, *, category: _Category = "INVALID_REQUEST", **details: Any
) -> Diagnostic:
    return Diagnostic(
        category=category,
        code=code,
        path=path,
        message=message,
        details=FrozenJSON(value=cast(Any, details)),
    )


def _values(array: ArrayData) -> tuple[float, ...]:
    return tuple(value for (value,) in struct.iter_unpack("<d", array.data))


class _Structure:
    def __init__(self, problem: Problem, prefix: str):
        self.problem = problem
        self.prefix = prefix
        self.diagnostics: list[Diagnostic] = []
        self.dims = {site.id: site.dim for site in problem.sites}
        self.dimension = math.prod(site.dim for site in problem.sites)

    def expect(self, condition: bool, code: str, path: str, message: str) -> None:
        if not condition:
            self.diagnostics.append(_diagnostic(code, self.prefix + path, message))

    def reference(self, site: str, path: str) -> None:
        self.expect(site in self.dims, "SITE", path, "Unknown site reference.")

    def references(self, sites: tuple[str, ...], path: str) -> None:
        for index, site in enumerate(sites):
            self.reference(site, f"{path}/{index}")

    def operator(self, operator: OperatorSum, unit: str, path: str) -> None:
        self.expect(operator.unit == unit, "UNIT", path + "/unit", "Unexpected operator unit.")
        for i, term in enumerate(operator.terms):
            for j, factor in enumerate(term.factors):
                item_path = f"{path}/terms/{i}/factors/{j}"
                self.reference(factor.site, item_path + "/site")
                if factor.site in self.dims:
                    dim = self.dims[factor.site]
                    self.expect(
                        factor.matrix.shape == (dim, dim),
                        "FACTOR_SHAPE",
                        item_path + "/matrix",
                        "Local matrix shape must match its site.",
                    )

    def signal(self, signal: Any, unit: str, path: str, *, drive: bool = False) -> None:
        self.expect(signal.unit == unit, "UNIT", path + "/unit", "Unexpected signal unit.")
        if drive:
            self.expect(
                signal.kind == "zoh", "SIGNAL_TIME", path + "/kind", "Drive signals must use zoh."
            )
        if signal.kind == "zoh":
            self.expect(
                signal.values.shape == (len(_values(self.problem.signal_edges)) - 1,),
                "SHAPE",
                path + "/values",
                "Zoh values must match the interval count.",
            )
        if not drive:
            values = (signal.value,) if signal.kind == "constant" else _values(signal.values)
            self.expect(
                all(value >= 0 for value in values), "NUMBER", path, "Rates must be nonnegative."
            )

    def bath(self, extension: RequiredExtension, path: str) -> None:
        if extension.content_type != codec._BATH_CONTENT_TYPE:
            self.expect(False, "BATH", path + "/content_type", "Unexpected bath content type.")
            return
        path += "/payload"
        try:
            bath = codec._bath_payload(extension.payload, self.prefix + path)
        except PContractError as error:
            self.diagnostics.extend(error.diagnostics)
            return
        self.operator(bath["coupling"], "1", path + "/coupling")
        density, at = bath["spectral_density"], path + "/spectral_density"
        if density["kind"] == "tabulated":
            arrays = (density["omega"], density["J"])
            shaped = all(a.dtype == "f64le" and len(a.shape) == 1 for a in arrays)
            omega, values = (_values(a) if shaped else () for a in arrays)
            sampled = shaped and len(omega) == len(values) >= 2
            self.expect(
                sampled,
                "SHAPE",
                at,
                "Tabulated omega and J must be equal-length real vectors of at least two samples.",
            )
            # 形状不合格时不查值域：空数组或长度不等时没有可比较的样本。
            if sampled:
                self.expect(
                    omega[0] >= 0 and all(a < b for a, b in pairwise(omega)),
                    "BATH",
                    at + "/omega",
                    "Tabulated omega must start at zero or above and increase strictly.",
                )
                self.expect(
                    all(v >= 0 for v in values) and not (omega[0] == 0 and values[0] != 0),
                    "BATH",
                    at + "/J",
                    "Tabulated J must be nonnegative and zero at omega = 0.",
                )
        else:
            for name, value in density.items():
                if name != "kind":
                    self.expect(value > 0, "BATH", f"{at}/{name}", "Expected a positive value.")
            if density["kind"] == "one_over_f":
                self.expect(
                    density["w_lc"] < density["w_hc"],
                    "BATH",
                    at,
                    "The low cutoff must be below the high cutoff.",
                )
        self.expect(
            bath["temperature"] > 0, "BATH", path + "/temperature", "Expected a positive value."
        )
        psd = bath["psd"]
        self.expect(
            (psd["frequency_axis"], psd["sides"], psd["fourier_measure"])
            == ("rad/ns", "one_sided", "1/pi"),
            "BATH",
            path + "/psd",
            "Unsupported spectral density convention.",
        )

    def problem_fields(self) -> None:
        p = self.problem
        ids = [site.id for site in p.sites]
        self.expect(len(ids) == len(set(ids)), "SITE", "/sites", "Site IDs must be unique.")
        self.expect(
            set(p.tensor_order) == set(ids) and len(p.tensor_order) == len(ids),
            "TENSOR_ORDER",
            "/tensor_order",
            "Tensor order must contain every site exactly once.",
        )
        self.expect(
            p.initial_state.frame == p.frame,
            "KEYS",
            "/initial_state/frame",
            "State and problem frames must match.",
        )
        self.expect(
            all(a == "rwa" for a in p.approximations),
            "KEYS",
            "/approximations",
            "Unknown approximation.",
        )
        self.expect(
            p.frame == "rotating" or "rwa" not in p.approximations,
            "APPROXIMATION",
            "/approximations",
            "The rwa approximation needs a rotating frame.",
        )
        # 一次比较覆盖四条规则：实验室系为空、旋转系覆盖全部站点、按 tensor_order 排列、无重复。
        self.expect(
            [site for site, _ in p.rotation_freqs]
            == (list(p.tensor_order) if p.frame == "rotating" else []),
            "ROTATION_FREQS",
            "/rotation_freqs",
            "Rotation frequencies must follow the tensor order in a rotating frame "
            "and be empty in the lab frame.",
        )
        for i, extension in enumerate(p.extensions):
            if (extension.namespace, extension.version) == codec._BATH:
                self.bath(extension, f"/extensions/{i}")
        edges = _values(p.signal_edges)
        self.expect(
            bool(edges) and all(a < b for a, b in pairwise(edges)),
            "SIGNAL_TIME",
            "/signal_edges",
            "Signal edges must be nonempty and strictly increasing.",
        )
        self.operator(p.h0, "rad/ns", "/h0")
        groups: tuple[tuple[str, Any], ...] = (
            ("drives", p.drives),
            ("environment/jumps", p.environment.jumps),
        )
        for field, records in groups:
            record_ids = [record.id for record in records]
            self.expect(
                len(record_ids) == len(set(record_ids)),
                "DUPLICATE",
                "/" + field,
                "Record IDs must be unique.",
            )
            for i, record in enumerate(records):
                path = f"/{field}/{i}"
                self.operator(record.operator, "1", path + "/operator")
                drive = field == "drives"
                self.signal(
                    record.signal if drive else record.rate,
                    "rad/ns" if drive else "1/ns",
                    path + ("/signal" if drive else "/rate"),
                    drive=drive,
                )
        state = p.initial_state
        if state.kind == "product":
            factors = state.factors or ()
            self.expect(
                {f.site for f in factors} == set(ids) and len(factors) == len(ids),
                "PRODUCT_COVERAGE",
                "/initial_state/factors",
                "Product factors must cover every site exactly once.",
            )
            for i, factor in enumerate(factors):
                self.reference(factor.site, f"/initial_state/factors/{i}/site")
                if factor.site in self.dims:
                    dim = self.dims[factor.site]
                    shape = (dim,) if factor.kind == "ket" else (dim, dim)
                    self.expect(
                        factor.data.shape == shape,
                        "SHAPE",
                        f"/initial_state/factors/{i}/data",
                        "Product factor shape must match its site.",
                    )
        else:
            shape = (self.dimension,) if state.kind == "ket" else (self.dimension, self.dimension)
            self.expect(
                state.data is not None and state.data.shape == shape,
                "SHAPE",
                "/initial_state/data",
                "State shape must match the Hilbert dimension.",
            )

    def request_fields(self, request: Request) -> None:
        # 请求字段使用交换根路径。
        prefix = self.prefix
        self.prefix = ""
        times = _values(request.output_times)
        edges = _values(self.problem.signal_edges)
        self.expect(
            bool(times) and all(a < b for a, b in pairwise(times)),
            "OUTPUT_TIME",
            "/output_times",
            "Output times must be nonempty and strictly increasing.",
        )
        if edges:
            self.expect(
                all(edges[0] <= t <= edges[-1] for t in times),
                "OUTPUT_TIME",
                "/output_times",
                "Output times must stay within signal edges.",
            )
            if len(edges) == 1:
                self.expect(
                    times == edges,
                    "ZERO_DURATION",
                    "/output_times",
                    "A zero-duration request must observe its sole edge.",
                )
        ids = [o.id for o in request.observations]
        self.expect(
            len(ids) == len(set(ids)),
            "OBSERVATION_ID",
            "/observations",
            "Observation IDs must be unique.",
        )
        for i, observation in enumerate(request.observations):
            path = f"/observations/{i}"
            if observation.kind == "expectation":
                assert observation.operator is not None
                self.operator(observation.operator, "1", path + "/operator")
            elif observation.kind in ("partial_trace", "projection"):
                sites = (
                    observation.keep_sites
                    if observation.kind == "partial_trace"
                    else observation.input_sites
                )
                assert sites is not None
                self.references(
                    sites,
                    path
                    + ("/keep_sites" if observation.kind == "partial_trace" else "/input_sites"),
                )
                if observation.kind == "projection" and all(site in self.dims for site in sites):
                    assert observation.isometry is not None
                    rows, columns = observation.isometry.shape
                    self.expect(
                        rows == math.prod(self.dims[site] for site in sites)
                        and 0 < columns <= rows,
                        "SHAPE",
                        path + "/isometry",
                        "Projection shape must match its input sites.",
                    )
        mappings = request.provenance.basis_mapping
        bits = [mapping.logical_bit for mapping in mappings]
        mapped_sites = [mapping.site for mapping in mappings]
        self.expect(
            len(bits) == len(set(bits)) and len(mapped_sites) == len(set(mapped_sites)),
            "PROVENANCE",
            "/provenance/basis_mapping",
            "Basis mappings must be unique.",
        )
        basis = {site.id: site.basis for site in self.problem.sites}
        for i, mapping in enumerate(mappings):
            path = f"/provenance/basis_mapping/{i}"
            self.reference(mapping.site, path + "/site")
            if mapping.site in basis:
                self.expect(
                    mapping.zero_label in basis[mapping.site]
                    and mapping.one_label in basis[mapping.site]
                    and mapping.zero_label != mapping.one_label,
                    "PROVENANCE",
                    path,
                    "Basis labels must identify distinct site states.",
                )
        self.prefix = prefix


def _remaining_stages(level: _Level, failed: str) -> tuple[str, ...]:
    stages = (
        ("transport", "structure", "capability", "physical")
        if level == "physical"
        else ("transport", "structure")
        if level == "structure"
        else ("transport",)
    )
    return stages[stages.index(failed) :]


def _check(
    value: Problem | Request,
    level: _Level,
    budget: CheckBudget,
    cls: type[Problem] | type[Request],
    *,
    context: _NumericContext | None = None,
) -> CheckReport:
    if level not in ("transport", "structure", "physical"):
        from .diagnostics import _fail

        _fail("KEYS", "/level", "Unknown validation level.")
    request = cls is Request
    try:
        if request:
            codec.dump_request(cast(Request, value), budget=budget)
        else:
            codec.dump_problem(cast(Problem, value), budget=budget)
    except PContractError as error:
        return CheckReport(
            level=level,
            complete=False,
            diagnostics=error.diagnostics,
            checked=(),
            unchecked=_remaining_stages(level, "transport"),
        )
    problem = cast(Request, value).problem if request else cast(Problem, value)
    unchecked = tuple(
        f"{'/problem' if request else ''}/extensions/{i}/physics"
        for i in range(len(problem.extensions))
    )
    checked: tuple[str, ...] = ("transport",)
    if level == "transport":
        return CheckReport(
            level=level, complete=True, diagnostics=(), checked=checked, unchecked=unchecked
        )
    structure = _Structure(problem, "/problem" if request else "")
    structure.problem_fields()
    if request:
        structure.request_fields(cast(Request, value))
    if structure.diagnostics:
        return CheckReport(
            level=level,
            complete=False,
            diagnostics=tuple(structure.diagnostics),
            checked=checked,
            unchecked=(*unchecked, *_remaining_stages(level, "structure")),
        )
    checked += ("structure",)
    if level == "structure":
        return CheckReport(
            level=level, complete=True, diagnostics=(), checked=checked, unchecked=unchecked
        )
    diagnostics = []
    prefix = "/problem" if request else ""
    for i, extension in enumerate(problem.extensions):
        diagnostics.append(
            _diagnostic(
                "REQUIRED_EXTENSION",
                f"{prefix}/extensions/{i}",
                "Required extension has no physical interpreter.",
                category="UNSUPPORTED_CAPABILITY",
                missing=[{"namespace": extension.namespace, "version": extension.version}],
                namespace=extension.namespace,
                version=extension.version,
            )
        )
    unsupported = []
    if problem.frame != "lab":
        unsupported.append("frame")
    if problem.approximations:
        unsupported.append("approximations")
    if unsupported:
        diagnostics.append(
            _diagnostic(
                "PROFILE",
                prefix,
                "The requested semantics are unsupported.",
                category="UNSUPPORTED_CAPABILITY",
                missing=unsupported,
            )
        )
    if request:
        from .capabilities import _initial_kind, _representation_missing, _request_representations

        requested = cast(Request, value)
        missing = _representation_missing(
            problem.environment.kind,
            _initial_kind(problem),
            _request_representations(requested),
            {"ket", "density"},
        )
        if missing:
            diagnostics.append(
                _diagnostic(
                    "PROFILE",
                    "/observations",
                    "Full-state representations have no supported common value.",
                    category="UNSUPPORTED_CAPABILITY",
                    missing=missing,
                )
            )
    if diagnostics:
        unchecked = (*unchecked, "capability")
    else:
        checked += ("capability",)
    if not diagnostics:
        from ._numeric import _check_physical

        try:
            _check_physical(value, context if context is not None else _NumericContext(budget))
        except PContractError as error:
            diagnostics.extend(error.diagnostics)
        else:
            return CheckReport(
                level=level,
                complete=True,
                diagnostics=(),
                checked=(*checked, "physical"),
                unchecked=unchecked,
            )
    return CheckReport(
        level=level,
        complete=False,
        diagnostics=tuple(diagnostics),
        checked=checked,
        unchecked=(*unchecked, "physical"),
    )


def check_problem(
    problem: Problem, *, level: _Level, budget: CheckBudget = _DEFAULT_BUDGET
) -> CheckReport:
    """检查问题在指定级别的契约。

    Args:
        problem: 待检查的问题。
        level: 请求的检查级别。
        budget: 传输与检查的资源上限。

    Returns:
        检查报告。未执行项保留在 unchecked。
        未知扩展不得通过 physical 认证。
        physical 检查数值条件与资源预算。

    Raises:
        PContractError: level 不是已知检查级别。
    """
    return _check(problem, level, budget, Problem)


def check_request(
    request: Request, *, level: _Level, budget: CheckBudget = _DEFAULT_BUDGET
) -> CheckReport:
    """检查请求在指定级别的契约。

    Args:
        request: 待检查的请求。
        level: 请求的检查级别。
        budget: 传输与检查的资源上限。

    Returns:
        检查报告。领域拒绝写入 diagnostics。
        未知扩展不得通过 physical 认证。
        physical 检查数值条件与资源预算。

    Raises:
        PContractError: level 不是已知检查级别。
    """
    return _check(request, level, budget, Request)


def require_valid(report: CheckReport) -> None:
    """拒绝失败或未完成的检查报告。

    Args:
        report: 待检查的报告。

    Raises:
        PContractError: 报告包含诊断或未完成检查。
    """
    if report.diagnostics:
        raise PContractError(diagnostics=report.diagnostics)
    if not report.complete:
        raise PContractError(
            diagnostics=(_diagnostic("KEYS", "", "The requested validation is incomplete."),)
        )
