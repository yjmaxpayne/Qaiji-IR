# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L0 采样波形层：实值实验室系样本的不可修改记录、参考采样、严格编解码与内容身份。

包根 ``qaiji`` 与 ``qaiji.core`` 不导出本包。只依赖标准库、``qaiji.exceptions``、
``qaiji.core._codec`` 与 L1 脉冲层。
"""

from .codec import dump_waveform, load_waveform, sample_digests, waveform_id
from .errors import WaveformContractError, WaveformDiagnostic
from .model import WAVEFORM_SCHEMA, Channel, Segment, TransformRecord, WaveformIR
from .sampling import sample_count, sample_envelope, sample_play

__all__ = [
    "WAVEFORM_SCHEMA",
    "Channel",
    "Segment",
    "TransformRecord",
    "WaveformContractError",
    "WaveformDiagnostic",
    "WaveformIR",
    "dump_waveform",
    "load_waveform",
    "sample_count",
    "sample_digests",
    "sample_envelope",
    "sample_play",
    "waveform_id",
]
