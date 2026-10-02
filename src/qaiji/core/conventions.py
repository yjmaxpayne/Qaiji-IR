# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""与物理适配器共享的基组下标映射与相位约定。"""

import cmath
from typing import Final

from qaiji.constants import DEFAULT_TOLERANCE
from qaiji.exceptions import ConventionViolationError

QASM3_INDEX_TO_PHYSICAL: Final = {0: "ground", 1: "excited"}
"""将 OpenQASM 计算基标签映射到物理态名称。

证伪状态：参照系定义。其余约定都以本表为参照，语义权威在本仓；
外部实现对 OpenQASM 比特另有物理解释时，以差异报告处理，不据此改写本表。
其变动由 ``self_check`` 与跨库判据 R3b 共同看守。
"""

OPTICS_INDEX_TO_PHYSICAL: Final = {0: "excited", 1: "ground"}
"""将光学适配器的存储下标映射到物理态名称。

证伪状态：已跨库证伪（判据 R0–R4，范围限于光学适配器的门、电路与原生后端层）。
快照事实 XR-SP、XR-SM、XR-Z、XR-ASSEMBLE、XR-SEMPARAM、XR-APPLY-MPS、XR-APPLY-SV、
XR-INIT、XR-INIT-PARSE，见源码仓库 ``tests/core/_optics_snapshot.py``。
"""

QASM3_TO_OPTICS_BIT: Final = {0: 1, 1: 0}
"""将 OpenQASM 基组标签翻译为光学适配器的存储下标。

证伪状态：推导成立。由 ``QASM3_INDEX_TO_PHYSICAL`` 与 ``OPTICS_INDEX_TO_PHYSICAL``
经 ``self_check`` 推出。注意：光学适配器自带的 OpenQASM 加载路径不做这次翻转
（比特 b 直接作为下标 b），不在本契约覆盖范围内，二者不可混用。
"""

RZ_PHASE_CONVENTION: Final = "exp(-i*theta*Z/2)"
"""Z 轴旋转的规范符号约定。

证伪状态：已跨库证伪（判据 R3a、R3b）。快照事实 XR-RZ、XR-Z，
见源码仓库 ``tests/core/_optics_snapshot.py``。跨到光学适配器的存储下标时 Z 的物理含义反号，
因此同一角度的物理作用相反：RZ_optics(θ) ≡ RZ_qasm(−θ)。
"""

type _Matrix2 = tuple[tuple[complex, complex], tuple[complex, complex]]

_IDENTITY: Final[_Matrix2] = ((1 + 0j, 0j), (0j, 1 + 0j))
_MINUS_IDENTITY: Final[_Matrix2] = ((-1 + 0j, 0j), (0j, -1 + 0j))
_RZ_PI: Final[_Matrix2] = ((-1j, 0j), (0j, 1j))


def _rz(theta: float) -> _Matrix2:
    return (
        (cmath.exp(-1j * theta / 2), 0j),
        (0j, cmath.exp(1j * theta / 2)),
    )


def _matmul(left: _Matrix2, right: _Matrix2) -> _Matrix2:
    return (
        (
            left[0][0] * right[0][0] + left[0][1] * right[1][0],
            left[0][0] * right[0][1] + left[0][1] * right[1][1],
        ),
        (
            left[1][0] * right[0][0] + left[1][1] * right[1][0],
            left[1][0] * right[0][1] + left[1][1] * right[1][1],
        ),
    )


def _close(left: _Matrix2, right: _Matrix2, atol: float) -> bool:
    return all(
        abs(left[row][column] - right[row][column]) <= atol
        for row in range(2)
        for column in range(2)
    )


def self_check(atol: float = DEFAULT_TOLERANCE) -> None:
    """当声明的基组约定与 RZ 约定不自洽时抛出异常。"""
    try:
        checks = (
            all(QASM3_TO_OPTICS_BIT[QASM3_TO_OPTICS_BIT[bit]] == bit for bit in (0, 1)),
            all(
                QASM3_INDEX_TO_PHYSICAL[bit] == OPTICS_INDEX_TO_PHYSICAL[QASM3_TO_OPTICS_BIT[bit]]
                for bit in (0, 1)
            ),
            _close(_rz(0.0), _IDENTITY, atol),
            _close(_matmul(_rz(0.7), _rz(1.1)), _rz(1.8), atol),
            _close(_rz(2 * cmath.pi), _MINUS_IDENTITY, atol),
            _close(_rz(cmath.pi), _RZ_PI, atol),
        )
    except (KeyError, TypeError) as error:
        raise ConventionViolationError("conventions self-check failed") from error

    if not all(checks):
        raise ConventionViolationError("conventions self-check failed")
