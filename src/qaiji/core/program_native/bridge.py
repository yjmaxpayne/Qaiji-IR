# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Authenticate every invocation before associating declared output events."""

from collections.abc import Mapping

from qaiji.core.circuit import Circuit
from qaiji.core.native import (
    CheckResult,
    NativeInputError,
    NativeIssue,
    NativeScheduleIR,
    NativeValidationReport,
)
from qaiji.core.native.model import _copy, _fail
from qaiji.core.native.source import _capture_source
from qaiji.core.native.validation import _validate_snapshot
from qaiji.core.program import ProgramIR, validate_program

from .model import (
    FinalBitBinding,
    InvocationEventRef,
    NativeBinding,
    OutputMeasurementBinding,
    ProgramNativeIssue,
    ProgramNativeMap,
    ProgramNativeValidationError,
)


def _wrong_source() -> NativeValidationReport:
    """The source must still belong to the invocation after legacy validation."""
    absent = CheckResult(status="not_run", issues=())
    return NativeValidationReport(
        source=CheckResult(
            status="fail",
            issues=(
                NativeIssue(
                    code="source_ref",
                    path="$.source_kernel_ref",
                    source=None,
                    operation_index=None,
                    message="Source does not match the invocation reference.",
                ),
            ),
        ),
        rules=absent,
        hp=absent,
        schedule=absent,
        groups=(),
        all_results_ready_ns=None,
    )


def bridge_program_native(
    program: ProgramIR, kernels: Mapping[str, Circuit], bindings: Mapping[int, NativeBinding]
) -> ProgramNativeMap:
    """保留 L5 校验错误，汇总 L2 错误，再映射认证后的测量事件。

    不执行采样或解析元数据引用。可以检测 L5 与 L2 校验之间的来源变更；
    不支持并发修改。
    """
    validate_program(program, kernels)
    for name, value in (("kernels", kernels), ("bindings", bindings)):
        if not isinstance(value, Mapping):
            _fail("container", "$." + name, "Expected a mapping.")
    for key in bindings:
        if type(key) is not int:
            _fail("integer", "$.bindings", "Binding keys must be built-in integers.")
    issues = []
    authenticated: dict[int, NativeScheduleIR] = {}
    for index, invocation in enumerate(program.quantum_invocations):
        if index not in bindings:
            issues.append(
                ProgramNativeIssue(
                    invocation_index=index,
                    code="binding_missing",
                    native_report=None,
                    input_code=None,
                    input_path=None,
                    message="Invocation has no native binding.",
                )
            )
            continue
        try:
            snapshot = _capture_source(kernels[invocation.kernel_ref])
            binding = _copy(bindings[index], NativeBinding, "$")
            report = (
                _wrong_source()
                if snapshot.source_kernel_ref != invocation.kernel_ref
                else _validate_snapshot(snapshot, binding.schedule, binding.config)
            )
        except NativeInputError as error:
            issues.append(
                ProgramNativeIssue(
                    invocation_index=index,
                    code="native_input",
                    native_report=None,
                    input_code=error.code,
                    input_path=error.path,
                    message=str(error),
                )
            )
            continue
        if not report.valid:
            issues.append(
                ProgramNativeIssue(
                    invocation_index=index,
                    code="native_invalid",
                    native_report=report,
                    input_code=None,
                    input_path=None,
                    message="Native authentication failed.",
                )
            )
        else:
            authenticated[index] = binding.schedule
    if issues:
        raise ProgramNativeValidationError(issues)
    return _map_outputs(program, authenticated)


def _map_outputs(
    program: ProgramIR, authenticated: dict[int, NativeScheduleIR]
) -> ProgramNativeMap:
    histories: dict[tuple[int, str], list[InvocationEventRef]] = {}
    latest: dict[tuple[int, str], dict[int, InvocationEventRef]] = {}
    for index, schedule in authenticated.items():
        for event in schedule.events:
            key = (index, event.register_name)
            ref = InvocationEventRef(invocation_index=index, event_id=event.event_id)
            histories.setdefault(key, []).append(ref)
            latest.setdefault(key, {})[event.bit_index] = ref
    outputs = []
    for output in program.result_outputs:
        key = (output.invocation_index, output.register_name)
        outputs.append(
            OutputMeasurementBinding(
                invocation_index=output.invocation_index,
                register_name=output.register_name,
                history=tuple(histories[key]),
                # B0 requires every output bit to be measured, and B1 preserves
                # that same source: latest therefore has contiguous bit indices.
                final_bits=tuple(
                    FinalBitBinding(bit_index=bit, event=latest[key][bit])
                    for bit in range(len(latest[key]))
                ),
            )
        )
    return ProgramNativeMap(outputs=tuple(outputs))
