# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""绑定检查输入与稳定不变量诊断。缺少上下文时拒绝认证。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from qaiji.core.circuit import Circuit
from qaiji.core.native import (
    NativeInputError,
    NativeScheduleIR,
    ScheduleConfig,
    validate_native_schedule,
)
from qaiji.core.physical import (
    CheckBudget,
    PContractError,
    Request,
    Result,
    check_request,
    check_result,
    load_request,
    load_result,
)
from qaiji.core.program import (
    ProgramCall,
    ProgramIR,
    ProgramIRV1,
    ProgramValidationError,
    compute_kernel_ref,
    load_program,
    validate_program,
)
from qaiji.core.pulse import (
    Acquire,
    PortResourceMap,
    PulseContractError,
    PulseProgramIR,
    check_port_resources,
    check_pulse_program,
    load_port_resources,
    load_pulse_program,
)
from qaiji.core.waveform import WaveformContractError, WaveformIR, dump_waveform, load_waveform

type Layer = Literal["L5", "L4", "L2", "L1", "L0", "P", "X"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Invariant:
    """登记不变量与诊断码。"""

    id: str
    layer: Layer
    category: Literal["checked", "convention"]
    statement: str
    codes: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class InvariantResult:
    """保存单项检查结论与 JSON Pointer。"""

    id: str
    layer: Layer
    path: str
    verdict: Literal["pass", "fail"]
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class InvariantReport:
    """保存检查结果。任一失败均拒绝认证。"""

    results: tuple[InvariantResult, ...]

    @property
    def ok(self) -> bool:
        """全部结果通过时返回 True。"""
        return bool(self.results) and all(item.verdict == "pass" for item in self.results)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgramInvariantInput:
    """显式绑定程序与内核解析表。"""

    program: ProgramIR | ProgramIRV1 | bytes | None = None
    kernels: Mapping[str, Circuit] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class L4InvariantInput:
    """绑定电路与先前保存的摘要。"""

    circuit: Circuit | None = None
    recorded_summary_hash: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class L2InvariantInput:
    """绑定时序检查所需的来源、调度与配置。"""

    circuit: Circuit | None = None
    schedule: NativeScheduleIR | bytes | None = None
    config: ScheduleConfig | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class L1InvariantInput:
    """绑定脉冲记录与来源调度。"""

    pulse: PulseProgramIR | bytes | None = None
    schedule: NativeScheduleIR | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PInvariantInput:
    """绑定物理请求、可选结果与共用预算。

    字节字段使用既有 P 记录编码。该载体不增加交换 schema。
    """

    request: Request | bytes | None = None
    result: Result | bytes | None = None
    budget: CheckBudget = field(default_factory=CheckBudget)


_REGISTRY = (
    Invariant(
        id="I-L5.4",
        layer="L5",
        category="checked",
        statement="程序条件深度不超过 4。",
        codes=("DEPTH", "L5_INPUT_MISSING", "L5_INPUT_INVALID"),
    ),
    Invariant(
        id="I-L4.3",
        layer="L4",
        category="checked",
        statement="电路摘要等于记录摘要。",
        codes=("SUMMARY_HASH", "L4_INPUT_MISSING"),
    ),
    Invariant(
        id="I-L2.6",
        layer="L2",
        category="checked",
        statement="操作保持全局串行时序。",
        codes=("resource_overlap", "serial_time", "L2_INPUT_MISSING"),
    ),
    Invariant(
        id="I-L2.7",
        layer="L2",
        category="checked",
        statement="条件操作等待所读结果就绪。",
        codes=("result_not_ready", "L2_INPUT_MISSING"),
    ),
    Invariant(
        id="I-L2.8", layer="L2", category="convention", statement="硬件对齐条件触发时刻。", codes=()
    ),
    Invariant(
        id="I-L1.6",
        layer="L1",
        category="checked",
        statement="端口角色与目标符合来源操作。",
        codes=("TARGET", "L1_INPUT_MISSING"),
    ),
    Invariant(
        id="I-L1.7",
        layer="L1",
        category="checked",
        statement="Acquire 与测量事件一一对应。",
        codes=("EVENT", "EVENT_REF", "EVENT_MISSING", "L1_INPUT_MISSING"),
    ),
    Invariant(
        id="I-L0.5",
        layer="L0",
        category="checked",
        statement="样本有限，通道有序，原点对齐。",
        codes=("NONFINITE", "ORDER", "ALIGN"),
    ),
    Invariant(
        id="I-L0.6",
        layer="L0",
        category="checked",
        statement="分支树完整，事件序列一致。",
        codes=("BRANCH", "BRANCH_EVENTS"),
    ),
    Invariant(
        id="I-P.6",
        layer="P",
        category="checked",
        statement="状态半正定、迹归一且厄米。",
        codes=("PSD", "NORMALIZATION", "HERMITIAN", "P_INPUT_MISSING"),
    ),
    Invariant(
        id="I-P.7",
        layer="P",
        category="checked",
        statement="物理检查不超过显式预算。",
        codes=(
            "DENSE_DIMENSION",
            "RATIONAL_OPS",
            "NUMERIC_ELEMENTS",
            "RATIONAL_BITS",
            "NUMERIC_RANGE",
            "BYTES",
            "DEPTH",
            "ATTACHMENT_BYTES",
            "RESOURCE_LIMIT",
            "P_INPUT_MISSING",
        ),
    ),
    Invariant(
        id="I-X.1",
        layer="X",
        category="checked",
        statement="端口映射资源被来源操作资源覆盖。",
        codes=("RESOURCE_REF", "RESOURCE_PORT", "RESOURCE_MISSING", "RESOURCE_COVERAGE"),
    ),
    Invariant(
        id="I-X.2",
        layer="X",
        category="checked",
        statement="叶路径事件等于 Acquire 序列。",
        codes=("BRANCH_EVENTS",),
    ),
)


def invariant_registry() -> tuple[Invariant, ...]:
    """返回已绑定的不变量，包含只登记的约定。"""
    return _REGISTRY


def _report(
    layer: Layer,
    diagnostics: list[tuple[str, str, str]],
    *,
    ids: tuple[str, ...] | None = None,
) -> InvariantReport:
    specs = [
        s
        for s in invariant_registry()
        if s.layer == layer and s.category == "checked" and (ids is None or s.id in ids)
    ]
    results: list[InvariantResult] = []
    failed: set[str] = set()
    for code, path, message in diagnostics:
        matches = [s.id for s in specs if code in s.codes] or ["UNREGISTERED"]
        for id in matches:
            failed.add(id)
            results.append(
                InvariantResult(
                    id=id,
                    layer=layer,
                    path=path,
                    verdict="fail",
                    message=f"{code}: {message}",
                )
            )
    for spec in specs:
        if spec.id not in failed:
            # 既有检查器在首错后停止。其余检查没有通过证据。
            results.append(
                InvariantResult(
                    id=spec.id,
                    layer=layer,
                    path="",
                    verdict="fail" if diagnostics else "pass",
                    message="前置检查失败，未认证该项。" if diagnostics else "检查通过。",
                )
            )
    return InvariantReport(results=tuple(results))


def _pointer(path: str) -> str:
    parts = re.findall(r"[^.\[\]]+", path.removeprefix("$"))
    return "".join("/" + part.replace("~", "~0").replace("/", "~1") for part in parts)


def _program(source: object) -> list[tuple[str, str, str]]:
    if isinstance(source, (ProgramIR, ProgramIRV1, bytes)):
        source = ProgramInvariantInput(program=source)
    if not isinstance(source, ProgramInvariantInput):
        raise TypeError("L5 requires ProgramInvariantInput or a program record")
    if source.program is None:
        return [("L5_INPUT_MISSING", "/program", "缺少程序。")]
    try:
        program = (
            load_program(source.program) if isinstance(source.program, bytes) else source.program
        )
    except ValueError as error:
        return [("SCHEMA", "/program", str(error))]
    if not isinstance(program, (ProgramIR, ProgramIRV1)):
        raise TypeError("Expected ProgramIR or ProgramIRV1")
    if not isinstance(program, ProgramIRV1):
        return [("L5_INPUT_MISSING", "/program/control_flow", "缺少权威控制树。")]
    if source.kernels is None:
        return [("L5_INPUT_MISSING", "/kernels", "缺少内核解析表。")]
    if not isinstance(source.kernels, Mapping) or any(
        ref in source.kernels and not isinstance(source.kernels[ref], Circuit)
        for ref in (call.kernel_ref for call in program.quantum_invocations)
    ):
        raise TypeError("Expected a mapping from kernel references to Circuit")
    try:
        validate_program(program, source.kernels)
    except ProgramValidationError as error:
        return [
            (error.code or "PROGRAM", "/program" + error.path, str(error)),
            ("L5_INPUT_INVALID", "/program" + error.path, "程序前置检查失败。"),
        ]
    stack = [
        (node, 0, f"/program/control_flow/{i}")
        for i, node in reversed(list(enumerate(program.control_flow)))
    ]
    while stack:
        node, depth, path = stack.pop()
        if isinstance(node, ProgramCall):
            continue
        if depth + 1 > 4:
            return [("DEPTH", path, "条件深度超过 4。")]
        for name in ("else_body", "then_body"):
            body = getattr(node, name)
            stack.extend(
                (child, depth + 1, f"{path}/{name}/{i}")
                for i, child in reversed(list(enumerate(body)))
            )
    return []


def _summary(source: object) -> list[tuple[str, str, str]]:
    if isinstance(source, bytes):
        return [("L4_INPUT_MISSING", "/circuit", "字节输入未绑定电路与独立摘要。")]
    if isinstance(source, Circuit):
        source = L4InvariantInput(circuit=source)
    if not isinstance(source, L4InvariantInput):
        raise TypeError("L4 requires L4InvariantInput or Circuit")
    if source.circuit is None:
        return [("L4_INPUT_MISSING", "/circuit", "缺少电路。")]
    if source.recorded_summary_hash is None:
        return [("L4_INPUT_MISSING", "/recorded_summary_hash", "缺少记录摘要。")]
    if not isinstance(source.circuit, Circuit):
        raise TypeError("Expected Circuit")
    expected = source.recorded_summary_hash
    if (
        type(expected) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", expected) is None
        or compute_kernel_ref(source.circuit) != expected
    ):
        return [("SUMMARY_HASH", "/recorded_summary_hash", "记录摘要与电路摘要不一致。")]
    return []


def _timing(source: object) -> list[tuple[str, str, str]]:
    if isinstance(source, (NativeScheduleIR, bytes)):
        source = L2InvariantInput(schedule=source)
    if not isinstance(source, L2InvariantInput):
        raise TypeError("L2 requires L2InvariantInput or NativeScheduleIR")
    for name in ("circuit", "schedule", "config"):
        if getattr(source, name) is None:
            return [("L2_INPUT_MISSING", "/" + name, "缺少时序检查输入。")]
    if not isinstance(source.circuit, Circuit) or not isinstance(source.config, ScheduleConfig):
        raise TypeError("Expected Circuit and ScheduleConfig")
    if not isinstance(source.schedule, (NativeScheduleIR, bytes)):
        raise TypeError("Expected NativeScheduleIR or schedule bytes")
    try:
        schedule = (
            NativeScheduleIR.from_json(source.schedule.decode())
            if isinstance(source.schedule, bytes)
            else source.schedule
        )
        report = validate_native_schedule(source.circuit, schedule, source.config)
    except NativeInputError as error:
        return [(error.code, "/schedule" + _pointer(error.path), str(error))]
    except UnicodeDecodeError as error:
        return [("SCHEMA", "/schedule", str(error))]
    issues = [
        issue
        for check in (report.source, report.rules, report.hp, report.schedule)
        for issue in check.issues
    ]
    return [(i.code, "/schedule" + _pointer(i.path), i.message) for i in issues]


def _pulse(source: object) -> list[tuple[str, str, str]]:
    if isinstance(source, (PulseProgramIR, bytes)):
        source = L1InvariantInput(pulse=source)
    if not isinstance(source, L1InvariantInput):
        raise TypeError("L1 requires L1InvariantInput or PulseProgramIR")
    for name in ("pulse", "schedule"):
        if getattr(source, name) is None:
            return [("L1_INPUT_MISSING", "/" + name, "缺少脉冲检查输入。")]
    if not isinstance(source.pulse, (PulseProgramIR, bytes)):
        raise TypeError("Expected PulseProgramIR or pulse bytes")
    if not isinstance(source.schedule, NativeScheduleIR):
        raise TypeError("Expected NativeScheduleIR")
    try:
        pulse = (
            load_pulse_program(source.pulse) if isinstance(source.pulse, bytes) else source.pulse
        )
        check_pulse_program(pulse, source.schedule)
    except PulseContractError as error:
        return [(i.code, "/pulse" + i.path, i.message) for i in error.diagnostics]
    return []


def check_invariants(source: object | bytes, *, layer: Layer) -> InvariantReport:
    """检查指定层的绑定输入。违规写入报告，类型不符时抛 TypeError。"""
    checks = {
        "L5": _program,
        "L4": _summary,
        "L2": _timing,
        "L1": _pulse,
        "L0": _waveform,
        "P": _physical,
    }
    if layer not in checks:
        raise ValueError("This layer has no bound checker")
    return _report(layer, checks[layer](source))


def _waveform(source: object) -> list[tuple[str, str, str]]:
    if not isinstance(source, (WaveformIR, bytes)):
        raise TypeError("L0 requires WaveformIR or waveform bytes")
    try:
        load_waveform(dump_waveform(source) if isinstance(source, WaveformIR) else source)
    except WaveformContractError as error:
        return [(i.code, i.path, i.message) for i in error.diagnostics]
    return []


def _physical(source: object) -> list[tuple[str, str, str]]:
    if isinstance(source, (Request, bytes)):
        source = PInvariantInput(request=source)
    if not isinstance(source, PInvariantInput):
        raise TypeError("P requires PInvariantInput or a request record")
    if not isinstance(source.budget, CheckBudget):
        raise TypeError("Expected CheckBudget")
    if source.request is None:
        return [("P_INPUT_MISSING", "/request", "缺少物理请求。")]
    if not isinstance(source.request, (Request, bytes)):
        raise TypeError("Expected Request or request bytes")
    if source.result is not None and not isinstance(source.result, (Result, bytes)):
        raise TypeError("Expected Result or result bytes")
    prefix = "/request" if isinstance(source.request, bytes) else ""
    try:
        request = (
            load_request(source.request, budget=source.budget)
            if isinstance(source.request, bytes)
            else source.request
        )
        report = check_request(request, level="physical", budget=source.budget)
        prefix = ""
        if report.complete and not report.diagnostics and source.result is not None:
            prefix = "/result"
            result = (
                load_result(source.result, budget=source.budget)
                if isinstance(source.result, bytes)
                else source.result
            )
            report = check_result(request, result, level="physical", budget=source.budget)
        diagnostics = report.diagnostics
        if not diagnostics and (not report.complete or report.unchecked):
            return [("P_NOT_RUN", prefix, "物理检查未完成。")]
    except PContractError as error:
        diagnostics = error.diagnostics
    return [
        (
            "RESOURCE_LIMIT" if item.category == "RESOURCE_LIMIT" else item.code,
            prefix + item.path,
            f"{item.category}: {item.code}: {item.message}",
        )
        for item in diagnostics
    ]


def _event_diagnostics(waveform: WaveformIR, pulse: PulseProgramIR) -> list[tuple[str, str, str]]:
    expected = tuple(item.event_id for item in pulse.instructions if isinstance(item, Acquire))
    depth = max(len(segment.branch) for segment in waveform.segments)
    return [
        ("BRANCH_EVENTS", f"/waveform/segments/{index}/branch", "叶路径事件与 Acquire 序列不一致。")
        for index, segment in enumerate(waveform.segments)
        if len(segment.branch) == depth and tuple(e for e, _ in segment.branch) != expected
    ]


def check_waveform_events(*, waveform: WaveformIR, pulse: PulseProgramIR) -> InvariantReport:
    """逐叶比较分支事件与全部 Acquire 事件。只认证 I-X.2。"""
    if not isinstance(waveform, WaveformIR) or not isinstance(pulse, PulseProgramIR):
        raise TypeError("Expected WaveformIR and PulseProgramIR")
    diagnostics = _waveform(waveform)
    if not diagnostics:
        diagnostics = _event_diagnostics(waveform, pulse)
    return _report("X", diagnostics, ids=("I-X.2",))


def check_cross_layer(
    *,
    schedule: NativeScheduleIR | bytes,
    pulse: PulseProgramIR | bytes,
    port_resources: PortResourceMap | bytes,
    waveform: WaveformIR | bytes,
) -> InvariantReport:
    """检查资源覆盖与叶路径事件，返回统一跨层报告。

    输入使用记录对象或既有 JSON 字节。违规写入报告。
    对象类型与对应记录不符时抛 TypeError。
    """
    for value, cls in (
        (schedule, NativeScheduleIR),
        (pulse, PulseProgramIR),
        (port_resources, PortResourceMap),
        (waveform, WaveformIR),
    ):
        if not isinstance(value, (cls, bytes)):
            raise TypeError(f"Expected {cls.__name__} or record bytes")
    prefix = "/schedule"
    try:
        if isinstance(schedule, bytes):
            schedule = NativeScheduleIR.from_json(schedule.decode())
        prefix = "/pulse"
        if isinstance(pulse, bytes):
            pulse = load_pulse_program(pulse)
        check_pulse_program(pulse, schedule)
        prefix = ""
        if isinstance(port_resources, bytes):
            port_resources = load_port_resources(port_resources)
        check_port_resources(schedule, pulse, port_resources)
        prefix = "/waveform"
        waveform = load_waveform(
            dump_waveform(waveform) if isinstance(waveform, WaveformIR) else waveform
        )
    except (PulseContractError, WaveformContractError) as error:
        return _report(
            "X",
            [
                (item.code, prefix + item.path, f"{item.category}: {item.message}")
                for item in error.diagnostics
            ],
        )
    except NativeInputError as error:
        return _report("X", [(error.code, "/schedule" + _pointer(error.path), str(error))])
    except UnicodeDecodeError as error:
        return _report("X", [("SCHEMA", "/schedule", str(error))])
    return _report("X", _event_diagnostics(waveform, pulse))
