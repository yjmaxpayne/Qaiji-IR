# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""给出独立解析值。"""

import math


def y_density(theta):
    c, s = math.cos(theta), math.sin(theta)
    return [[c * c, c * s], [c * s, s * s]]


def x_density(theta):
    c, s = math.cos(theta), math.sin(theta)
    return [[c * c, 1j * c * s], [-1j * c * s, s * s]]


def z_plus_density(theta):
    return [
        [0.5, complex(math.cos(2 * theta), -math.sin(2 * theta)) / 2],
        [complex(math.cos(2 * theta), math.sin(2 * theta)) / 2, 0.5],
    ]


def decay_density(exponent):
    p = math.exp(-exponent)
    return [[1 - p, 0], [0, p]]


def drive_angle(time):
    return 0.2 * min(time, 1) + 0.4 * max(time - 1, 0)


def decay_exponent(time):
    return 0.1 * min(time, 1) + 0.3 * max(time - 1, 0)
