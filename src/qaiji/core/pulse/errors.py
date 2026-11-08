# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""L1 脉冲层的诊断记录与契约错误。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal, NoReturn

from qaiji.exceptions import QaijiIRError

type PulseCategory = Literal["INVALID_PROGRAM", "SCHEDULE_MISMATCH", "resources"]


@dataclass(frozen=True, slots=True, kw_only=True)
class PulseDiagnostic:
    """一条 L1 诊断。

    ``INVALID_PROGRAM`` 表示记录、不变量或编码不合法。``SCHEDULE_MISMATCH`` 表示程序与
    L2 调度不一致。``resources`` 表示独立端口资源映射不一致。
    ``path`` 为 JSON Pointer，根为空串。
    """

    category: PulseCategory
    code: str
    path: str
    message: str
    __hash__: ClassVar[Any] = None


class PulseContractError(QaijiIRError):
    """L1 契约拒绝，携带不可变的诊断序列。"""

    __slots__ = ("diagnostics",)

    def __init__(self, *, diagnostics: tuple[PulseDiagnostic, ...]) -> None:
        self.diagnostics = tuple(diagnostics)
        first = self.diagnostics[0]
        super().__init__(f"{first.category}/{first.code} at {first.path or '/'}: {first.message}")


def _fail(
    code: str, path: str, message: str, category: PulseCategory = "INVALID_PROGRAM"
) -> NoReturn:
    diagnostic = PulseDiagnostic(category=category, code=code, path=path, message=message)
    raise PulseContractError(diagnostics=(diagnostic,))
