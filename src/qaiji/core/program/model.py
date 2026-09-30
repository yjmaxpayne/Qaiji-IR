# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L5 程序的不可变数据声明。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

PROGRAM_SCHEMA_VERSION = "qaiji.program.v0"


@dataclass(frozen=True, slots=True)
class QuantumInvocation:
    """一次量子内核调用。

    Example:
        >>> QuantumInvocation("sha256:" + "a" * 64).kernel_ref.startswith("sha256:")
        True
    """

    kernel_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.kernel_ref, str):
            raise ValueError("kernel_ref must be a str")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.kernel_ref) is None:
            raise ValueError("kernel_ref must contain 64 lowercase hex digits after sha256:")


@dataclass(frozen=True, slots=True)
class ExperimentMetadata:
    """实验参数及透传的不透明字符串引用，本仓不校验引用内容。

    Example:
        >>> ExperimentMetadata(100).shot_count
        100
    """

    shot_count: int
    calibration_set_ref: str | None = None
    device_profile_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.shot_count) is not int:
            raise ValueError("shot_count must be a positive int")
        if self.shot_count < 1:
            raise ValueError("shot_count must be a positive int")
        for name in ("calibration_set_ref", "device_profile_ref"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(f"{name} must be a non-empty str or None")
                if not value:
                    raise ValueError(f"{name} must be a non-empty str or None")


@dataclass(frozen=True, slots=True)
class ResultOutput:
    """一次调用的经典寄存器输出。

    Example:
        >>> ResultOutput(0, "c").register_name
        'c'
    """

    invocation_index: int
    register_name: str

    def __post_init__(self) -> None:
        if type(self.invocation_index) is not int:
            raise ValueError("invocation_index must be a non-negative int")
        if self.invocation_index < 0:
            raise ValueError("invocation_index must be a non-negative int")
        if not isinstance(self.register_name, str):
            raise ValueError("register_name must be an identifier")
        if not self.register_name.isidentifier():
            raise ValueError("register_name must be an identifier")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgramIR:
    """以调用、实验参数及结果输出表达的 L5 程序。

    Example:
        >>> program = ProgramIR(
        ...     quantum_invocations=[QuantumInvocation("sha256:" + "a" * 64)],
        ...     experiment_metadata=ExperimentMetadata(100),
        ...     result_outputs=[ResultOutput(0, "c")],
        ... )
        >>> program.schema_version
        'qaiji.program.v0'
    """

    schema_version: str = PROGRAM_SCHEMA_VERSION
    quantum_invocations: tuple[QuantumInvocation, ...]
    experiment_metadata: ExperimentMetadata
    result_outputs: tuple[ResultOutput, ...]

    def __post_init__(self) -> None:
        if self.schema_version != PROGRAM_SCHEMA_VERSION:
            raise ValueError("schema_version must be qaiji.program.v0")
        for name in ("quantum_invocations", "result_outputs"):
            if not isinstance(getattr(self, name), (list, tuple)):
                raise ValueError(f"{name} must be a list or tuple")
        object.__setattr__(self, "quantum_invocations", tuple(self.quantum_invocations))
        object.__setattr__(self, "result_outputs", tuple(self.result_outputs))
        if not all(isinstance(item, QuantumInvocation) for item in self.quantum_invocations):
            raise ValueError("quantum_invocations must contain only QuantumInvocation")
        if not isinstance(self.experiment_metadata, ExperimentMetadata):
            raise ValueError("experiment_metadata must be ExperimentMetadata")
        if not all(isinstance(item, ResultOutput) for item in self.result_outputs):
            raise ValueError("result_outputs must contain only ResultOutput")
        if not self.quantum_invocations:
            raise ValueError("ProgramIR requires at least one quantum invocation")
        if not self.result_outputs:
            raise ValueError("ProgramIR requires at least one result output")
        if any(
            item.invocation_index >= len(self.quantum_invocations) for item in self.result_outputs
        ):
            raise ValueError("result output points past quantum_invocations")
        if len(
            {(item.invocation_index, item.register_name) for item in self.result_outputs}
        ) != len(self.result_outputs):
            raise ValueError("result_outputs must not repeat")

    def to_json(self) -> str:
        """写出键序固定、纯 ASCII 且无额外空白的规范 JSON。

        Returns:
            包含每层全部字段的 JSON 文本，序列顺序保持不变。

        Raises:
            ValueError: 超大整数超过标准库的整数转字符串位数限制。
        """
        payload = {
            "schema_version": self.schema_version,
            "quantum_invocations": [
                {"kernel_ref": item.kernel_ref} for item in self.quantum_invocations
            ],
            "experiment_metadata": {
                "shot_count": self.experiment_metadata.shot_count,
                "calibration_set_ref": self.experiment_metadata.calibration_set_ref,
                "device_profile_ref": self.experiment_metadata.device_profile_ref,
            },
            "result_outputs": [
                {"invocation_index": item.invocation_index, "register_name": item.register_name}
                for item in self.result_outputs
            ],
        }
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )

    @classmethod
    def from_json(cls, text: str) -> ProgramIR:
        """解析任意空白与键序的 JSON，逐层检查对象、键集和数组。

        Args:
            text: 程序 JSON 文本。

        Returns:
            通过构造期校验的不可变程序。

        Raises:
            ValueError: 畸形 JSON 文本仅抛此异常族，含解析错误和嵌套过深。
            TypeError: 不支持的非文本实参由标准库 json.loads 拒收。
        """
        try:
            payload = json.loads(text, object_pairs_hook=_unique_object)
        except RecursionError as error:
            raise ValueError("JSON nested too deeply") from error
        _require_object(
            payload,
            {"schema_version", "quantum_invocations", "experiment_metadata", "result_outputs"},
        )
        for name in ("quantum_invocations", "result_outputs"):
            if not isinstance(payload[name], list):
                raise ValueError(f"{name} must be a JSON array")
        for item in payload["quantum_invocations"]:
            _require_object(item, {"kernel_ref"})
        _require_object(
            payload["experiment_metadata"],
            {"shot_count", "calibration_set_ref", "device_profile_ref"},
        )
        for item in payload["result_outputs"]:
            _require_object(item, {"invocation_index", "register_name"})
        return cls(
            schema_version=payload["schema_version"],
            quantum_invocations=tuple(
                QuantumInvocation(**item) for item in payload["quantum_invocations"]
            ),
            experiment_metadata=ExperimentMetadata(**payload["experiment_metadata"]),
            result_outputs=tuple(ResultOutput(**item) for item in payload["result_outputs"]),
        )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """在标准库解析对象时拒收重复键。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object keys")
        result[key] = value
    return result


def _require_object(value: object, expected_keys: set[str]) -> None:
    """检查 JSON 对象及其严格键集。"""
    if not isinstance(value, dict):
        raise ValueError("must be a JSON object")
    if set(value) != expected_keys:
        raise ValueError(f"must have exactly keys {sorted(expected_keys)}")
