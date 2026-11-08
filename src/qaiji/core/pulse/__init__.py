# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1 脉冲层：不可修改的帧、端口与绝对时间指令，帧相位函数，严格编解码与内容身份。

包根 ``qaiji`` 与 ``qaiji.core`` 不导出本包。只依赖标准库与本仓的 L2 原生层。
"""

from .check import check_pulse_program
from .codec import dump_pulse_program, load_pulse_program, native_schedule_ref, pulse_program_id
from .errors import PulseContractError, PulseDiagnostic
from .model import (
    PULSE_SCHEMA,
    Acquire,
    Envelope,
    Frame,
    Play,
    Port,
    PulseProgramIR,
    ShiftPhase,
)
from .phase import PHASE_ATOL, carrier_phase, frame_phase, phases_equal
from .resources import (
    PORT_RESOURCES_SCHEMA,
    PortResourceEntry,
    PortResourceMap,
    check_port_resources,
    dump_port_resources,
    load_port_resources,
    port_resources_id,
)

__all__ = [
    "PHASE_ATOL",
    "PORT_RESOURCES_SCHEMA",
    "PULSE_SCHEMA",
    "Acquire",
    "Envelope",
    "Frame",
    "Play",
    "Port",
    "PortResourceEntry",
    "PortResourceMap",
    "PulseContractError",
    "PulseDiagnostic",
    "PulseProgramIR",
    "ShiftPhase",
    "carrier_phase",
    "check_port_resources",
    "check_pulse_program",
    "dump_port_resources",
    "dump_pulse_program",
    "frame_phase",
    "load_port_resources",
    "load_pulse_program",
    "native_schedule_ref",
    "phases_equal",
    "port_resources_id",
    "pulse_program_id",
]
