# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""承载 L5 权威控制树，保留 v0 的独立交换契约。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from qaiji.core.program.model import (
    ExperimentMetadata,
    ProgramIR,
    QuantumInvocation,
    ResultOutput,
    _require_object,
    _unique_object,
)


def _index(value: object) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("Expected a non-negative built-in integer")


def _body(value: object) -> tuple[ProgramCall | ProgramIf, ...]:
    if not isinstance(value, (tuple, list)) or any(
        type(node) not in (ProgramCall, ProgramIf) for node in value
    ):
        raise ValueError("Expected a sequence of ProgramCall or ProgramIf")
    return tuple(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgramCall:
    """引用程序调用表中的一个调用。"""

    invocation_index: int

    def __post_init__(self) -> None:
        _index(self.invocation_index)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgramIf:
    """按先前调用的测量寄存器选择一个分支。"""

    invocation_index: int
    register_name: str
    value: int
    then_body: tuple[ProgramCall | ProgramIf, ...]
    else_body: tuple[ProgramCall | ProgramIf, ...]

    def __post_init__(self) -> None:
        _index(self.invocation_index)
        _index(self.value)
        if type(self.register_name) is not str or not self.register_name.isidentifier():
            raise ValueError("Expected a register identifier")
        for name in ("then_body", "else_body"):
            object.__setattr__(self, name, _body(getattr(self, name)))


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgramIRV1:
    """保存完整控制结构。构造期不限制条件深度。"""

    quantum_invocations: tuple[QuantumInvocation, ...]
    experiment_metadata: ExperimentMetadata
    result_outputs: tuple[ResultOutput, ...]
    control_flow: tuple[ProgramCall | ProgramIf, ...]
    schema_version: str = "qaiji.program.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "qaiji.program.v1":
            raise ValueError("schema_version must be qaiji.program.v1")
        base = self._flat_program()
        for name in ("quantum_invocations", "experiment_metadata", "result_outputs"):
            object.__setattr__(self, name, getattr(base, name))
        object.__setattr__(self, "control_flow", _body(self.control_flow))

    def _flat_program(self) -> ProgramIR:
        return ProgramIR(
            quantum_invocations=self.quantum_invocations,
            experiment_metadata=self.experiment_metadata,
            result_outputs=self.result_outputs,
        )

    def to_json(self) -> str:
        """写出含完整控制树的规范 JSON 文本。"""
        payload = json.loads(self._flat_program().to_json())
        payload["schema_version"] = self.schema_version
        payload["control_flow"] = [_encode(node) for node in self.control_flow]
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @classmethod
    def from_json(cls, text: str) -> ProgramIRV1:
        """解析 v1 文本，拒绝未知字段与重复键。"""
        try:
            payload = json.loads(text, object_pairs_hook=_unique_object)
            _require_object(
                payload,
                {
                    "schema_version",
                    "quantum_invocations",
                    "experiment_metadata",
                    "result_outputs",
                    "control_flow",
                },
            )
            if payload["schema_version"] != "qaiji.program.v1":
                raise ValueError("schema_version must be qaiji.program.v1")
            flow = payload.pop("control_flow")
            if type(flow) is not list:
                raise ValueError("control_flow must be a JSON array")
            payload["schema_version"] = "qaiji.program.v0"
            base = ProgramIR.from_json(json.dumps(payload))
            return cls(
                quantum_invocations=base.quantum_invocations,
                experiment_metadata=base.experiment_metadata,
                result_outputs=base.result_outputs,
                control_flow=tuple(_decode(node) for node in flow),
            )
        except RecursionError as error:
            raise ValueError("JSON nested too deeply") from error


def _encode(node: ProgramCall | ProgramIf) -> dict[str, Any]:
    payload: dict[str, Any] = {"invocation_index": node.invocation_index}
    if type(node) is ProgramCall:
        return {"kind": "call", **payload}
    assert isinstance(node, ProgramIf)
    return {
        "kind": "if",
        **payload,
        "register_name": node.register_name,
        "value": node.value,
        "then_body": [_encode(item) for item in node.then_body],
        "else_body": [_encode(item) for item in node.else_body],
    }


def _decode(payload: object) -> ProgramCall | ProgramIf:
    if type(payload) is not dict:
        raise ValueError("Expected a control-flow object")
    if payload.get("kind") == "call":
        _require_object(payload, {"kind", "invocation_index"})
        return ProgramCall(invocation_index=payload["invocation_index"])
    _require_object(
        payload,
        {
            "kind",
            "invocation_index",
            "register_name",
            "value",
            "then_body",
            "else_body",
        },
    )
    if payload["kind"] != "if":
        raise ValueError("Unknown control-flow kind")
    if any(type(payload[name]) is not list for name in ("then_body", "else_body")):
        raise ValueError("Expected JSON branch arrays")
    return ProgramIf(
        invocation_index=payload["invocation_index"],
        register_name=payload["register_name"],
        value=payload["value"],
        then_body=tuple(_decode(n) for n in payload["then_body"]),
        else_body=tuple(_decode(n) for n in payload["else_body"]),
    )


def dump_program(program: ProgramIR | ProgramIRV1) -> bytes:
    """写出对应版本的规范程序字节。"""
    if type(program) not in (ProgramIR, ProgramIRV1):
        raise TypeError("Expected ProgramIR or ProgramIRV1")
    return program.to_json().encode("utf-8")


def load_program(data: bytes) -> ProgramIR | ProgramIRV1:
    """按 schema 解析程序字节，拒绝未知版本。"""
    if type(data) is not bytes:
        raise TypeError("Expected program bytes")
    text = data.decode("utf-8")
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object)
    except RecursionError as error:
        raise ValueError("JSON nested too deeply") from error
    if type(payload) is not dict:
        raise ValueError("Expected a program object")
    if payload.get("schema_version") == "qaiji.program.v1":
        return ProgramIRV1.from_json(text)
    return ProgramIR.from_json(text)
