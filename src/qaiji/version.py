# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""包版本号的唯一真相来源。

下面的字面量只是兜底值；``poetry-dynamic-versioning`` 会在构建时用最新 git tag
推导出的版本号覆盖它。
"""

__version__ = "0.0.0"
"""已安装发行版的版本号，构建时由最近的 Git tag 推导而来。"""
