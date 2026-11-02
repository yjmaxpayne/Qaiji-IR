# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L0 采样波形层的诊断记录与契约错误。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal, NoReturn

from qaiji.exceptions import QaijiIRError

type WaveformCategory = Literal["INVALID_WAVEFORM"]


@dataclass(frozen=True, slots=True, kw_only=True)
class WaveformDiagnostic:
    """一条 L0 诊断。

    ``INVALID_WAVEFORM`` 表示记录、L0 规则、采样参数或编码不合法。``path`` 为 JSON Pointer，
    根为空串。
    """

    category: WaveformCategory
    code: str
    path: str
    message: str
    __hash__: ClassVar[Any] = None


class WaveformContractError(QaijiIRError):
    """L0 契约拒绝，携带不可变的诊断序列。"""

    __slots__ = ("diagnostics",)

    def __init__(self, *, diagnostics: tuple[WaveformDiagnostic, ...]) -> None:
        self.diagnostics = tuple(diagnostics)
        first = self.diagnostics[0]
        super().__init__(f"{first.category}/{first.code} at {first.path or '/'}: {first.message}")


def _fail(code: str, path: str, message: str) -> NoReturn:
    diagnostic = WaveformDiagnostic(
        category="INVALID_WAVEFORM", code=code, path=path, message=message
    )
    raise WaveformContractError(diagnostics=(diagnostic,))
