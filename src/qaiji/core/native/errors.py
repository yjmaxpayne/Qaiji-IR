# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Native input errors."""


class NativeInputError(ValueError):
    """原生调度的输入或结构不符合要求。"""

    def __init__(self, code: str, path: str, message: str):
        self.code, self.path = code, path
        super().__init__(message)
