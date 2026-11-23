# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""T 层：保持证书检查器，独立重算证书中的每条结论。"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from qaiji.core.trace.codec import _LADDER, dump_trace_log, load_tolerances
from qaiji.core.trace.model import (
    _DECIDABLE_LEVELS,
    Comparison,
    Exclusion,
    PreservationCertificate,
    TraceEvent,
    TraceInputError,
    TraceLog,
    _bits,
    _is_event_id,
    _items,
    numerical_verdict_of,
)

# --- 证书检查 ----------------------------------------------------------------

_FAILURE_CODES = (
    "REF_SOURCE_MISSING",
    "REF_MISSING",
    "REF_KIND_INVALID",
    "EVIDENCE_EMPTY",
    "INPUT_MISMATCH",
    "VERDICT_MISMATCH",
    "EXCLUSION_MISMATCH",
    "SYMBOLIC_LEVEL_UNDECIDABLE",
    "EXPECTED_KEY_MISMATCH",
    "TOLERANCE_SOURCE_MISMATCH",
    "PROGRAM_REF_MISMATCH",
    "EVIDENCE_INCOMPLETE",
    "COMPARISON_SET_MISMATCH",
    "DOCUMENT_MISSING",
    "DOCUMENT_DIGEST_MISMATCH",
    "OBSERVATION_MISMATCH",
    "TRACE_LOG_CONFLICT",
    "SAME_LAYER_TOLERANCE_PRESENT",
)


def _required_evidence(name: str, sides: Iterable[TraceLog]) -> set[tuple[str, str]]:
    """返回跨层比较两侧必须给出的引用。"""
    if name == "branch_weights":
        return {(s.source.digest, e.id) for s in sides for e in s.events if e.kind == "branch"}
    return {(s.source.digest, f"o:{name}") for s in sides}


def _comparison_codes(
    comparison: Comparison,
    logs: Mapping[str, TraceLog],
    program_ref: str,
    verdicts: dict[str, str],
) -> set[str]:
    """返回一项比较的引用、配对、证据与判决失败码。

    重算的判决按比较名写入 ``verdicts``。
    """
    if not comparison.evidence_refs:
        return {"EVIDENCE_EMPTY"}
    codes: set[str] = set()
    cited: set[tuple[str, str]] = set()
    for digest, event_id in comparison.evidence_refs:
        if not _is_event_id(event_id):
            codes.add("REF_KIND_INVALID")
        elif digest not in logs:
            codes.add("REF_SOURCE_MISSING")
        elif event_id not in {event.id for event in logs[digest].events}:
            codes.add("REF_MISSING")
        else:
            cited.add((digest, event_id))
    sides = [logs[digest] for digest in sorted({digest for digest, _ in cited})]
    if not sides:
        return codes
    if any(side.source.program_ref != program_ref for side in sides):
        codes.add("PROGRAM_REF_MISMATCH")
    layers = 1 if comparison.kind == "same_layer" else 2
    programs = {side.source.program_ref for side in sides}
    if len(programs) != 1 or len({side.source.layer for side in sides}) != layers:
        codes.add("INPUT_MISMATCH")
    if comparison.kind == "cross_layer" and cited != _required_evidence(comparison.name, sides):
        codes.add("EVIDENCE_INCOMPLETE")
    if "INPUT_MISMATCH" in codes:
        return codes
    delta = _recomputed_delta(comparison, sides)
    if delta is None:
        return codes | {"VERDICT_MISMATCH"}
    verdicts[comparison.name] = _verdict_of(comparison, delta)
    if delta != comparison.delta or verdicts[comparison.name] != comparison.verdict:
        codes.add("VERDICT_MISMATCH")
    return codes


def _conflict_codes(items: Iterable[TraceLog]) -> set[str]:
    """同一 ``source.digest`` 的日志字节不同时，返回 ``TRACE_LOG_CONFLICT``。"""
    seen: dict[str, bytes] = {}
    for log in items:
        data = dump_trace_log(log)
        if seen.setdefault(log.source.digest, data) != data:
            return {"TRACE_LOG_CONFLICT"}
    return set()


def _same_layer_codes(certificate: PreservationCertificate, items: Iterable[TraceLog]) -> set[str]:
    """返回同层比较的存在、容差与覆盖失败码。

    证书没有同层比较时，返回 ``COMPARISON_SET_MISMATCH``；同层比较写了容差时，
    返回 ``SAME_LAYER_TOLERANCE_PRESENT``。传入日志按 ``(layer, program_ref)`` 分组，
    组内日志按传入份数计（字节相同的副本也计入）；份数 ≥ 2 的组，须有一项同层比较
    引用该组的全部 digest，否则返回 ``EVIDENCE_INCOMPLETE``。各条规则独立判定。
    """
    same = [c for c in certificate.comparisons if c.kind == "same_layer"]
    codes: set[str] = set() if same else {"COMPARISON_SET_MISMATCH"}
    if any(c.tolerance is not None for c in same):
        codes.add("SAME_LAYER_TOLERANCE_PRESENT")
    groups: dict[tuple[str, str], list[str]] = {}
    for log in items:
        groups.setdefault((log.source.layer, log.source.program_ref), []).append(log.source.digest)
    cited = [{digest for digest, _ in c.evidence_refs} for c in same]
    if any(len(g) >= 2 and not any(set(g) <= refs for refs in cited) for g in groups.values()):
        codes.add("EVIDENCE_INCOMPLETE")
    return codes


def _exclusion_codes(
    certificate: PreservationCertificate, logs: Mapping[str, TraceLog], verdicts: dict[str, str]
) -> set[str]:
    """重算的排除项或判决不一致时，返回 ``EXCLUSION_MISMATCH``。"""
    cited = {d for c in certificate.comparisons for d, e in c.evidence_refs if d in logs}
    keys = {(logs[d].source.layer, _dominant_key(logs[d])) for d in cited}
    excluded = {(lay, k) for lay, k in keys if k is not None and k != certificate.expected_key}
    stated = {(e.layer, e.dominant_key) for e in certificate.exclusions}
    rows = [replace(c, verdict=verdicts.get(c.name, c.verdict)) for c in certificate.comparisons]
    verdict = numerical_verdict_of(
        rows, [Exclusion(layer=lay, dominant_key=k) for lay, k in excluded]
    )
    if excluded != stated or verdict != certificate.numerical_verdict:
        return {"EXCLUSION_MISMATCH"}
    return set()


def _recomputed_delta(comparison: Comparison, sides: list[TraceLog]) -> float | None:
    """由比较的两侧计算差值；无法计算时返回 None。"""
    if comparison.kind == "same_layer":
        return 0.0 if len(sides) == 1 else 1.0
    if len(sides) != 2:
        return None
    if comparison.name == "branch_weights":
        weights = [
            {e.id: e.path_weight or 0.0 for e in s.events if e.kind == "branch"} for s in sides
        ]
        keys = set(weights[0]) | set(weights[1])
        return max(
            (abs(weights[0].get(k, 0.0) - weights[1].get(k, 0.0)) for k in keys), default=0.0
        )
    values = [
        next((e.value for e in s.events if e.id == f"o:{comparison.name}"), None) for s in sides
    ]
    if values[0] is None or values[1] is None:
        return None
    return abs(values[0] - values[1])


def _verdict_of(comparison: Comparison, delta: float) -> str:
    """``|delta| <= tolerance`` 时返回 ``within``；同层比较要求差值为 0。"""
    if comparison.tolerance is None:
        return "within" if delta == 0.0 else "exceeded"
    return "within" if abs(delta) <= comparison.tolerance else "exceeded"


def _dominant_key(log: TraceLog) -> str | None:
    """返回路径权重最大的叶分支键；没有分支时返回 None。"""
    keys = {e.id[2:]: e.path_weight or 0.0 for e in log.events if e.kind == "branch"}
    leaves = [k for k in keys if not any(o != k and o.startswith(k) for o in keys)]
    return max(leaves, key=lambda k: (keys[k], k), default=None)


_OBSERVATION_TOLERANCE = 1e-10
_DOCUMENT_ERRORS = (ValueError, KeyError, TypeError, IndexError, struct.error)


def _fetch(digest: str, documents: Mapping[str, bytes]) -> bytes | str:
    """返回 ``digest`` 对应的文档；文档缺失或被改动时返回失败码。"""
    data = documents.get(digest)
    if data is None:
        return "DOCUMENT_MISSING"
    if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        return "DOCUMENT_DIGEST_MISMATCH"
    return data


def _population(definition: Mapping[str, Any], document: bytes) -> float:
    """返回定义的目标在一份结果文档中的末态布居。

    Raises:
        ValueError: 文档与定义不符（阶数、维度或布局）。
    """
    result = json.loads(document)
    order, dims = list(definition["tensor_order"]), list(definition["site_dims"])
    if result["tensor_order"] != order or len(dims) != len(order):
        raise ValueError("tensor_order differs from the result document")
    (state,) = [o for o in result["observations"] if o["kind"] == "full_state"]
    array, dim = state["data"], math.prod(dims)
    density = {"ket": False, "density": True}[state["representation"]]
    shape = array["shape"]
    if array["dtype"] != "c128le" or shape[1:] != [dim] * (1 + density) or shape[0] < 1:
        raise ValueError("site_dims do not give the final-state dimension")
    raw = base64.b64decode(array["data"], validate=True)
    values = struct.unpack(f"<{2 * math.prod(shape)}d", raw)
    position = {label: n for n, label in enumerate(order)}
    wanted = {position[label]: level for label, level in definition["target"]}
    if any(not 0 <= level < dims[n] for n, level in wanted.items()):
        raise ValueError("target level is outside its site")
    offset, total = (shape[0] - 1) * dim ** (1 + density), 0.0
    for index in range(dim):
        digits, rest = [], index
        for size in reversed(dims):
            digits.append(rest % size)
            rest //= size
        if all(digits[len(dims) - 1 - n] == level for n, level in wanted.items()):
            k = 2 * (offset + (index * dim + index if density else index))
            total += values[k] if density else values[k] ** 2 + values[k + 1] ** 2
    return total


def _observation_codes(
    event: TraceEvent, log: TraceLog, documents: Mapping[str, bytes] | None
) -> set[str]:
    """返回一个可观测事件的文档失败码与观测失败码。

    先处理定义，再处理叶文档；每份文档先算哈希，再解析。
    """
    if documents is None:
        return {"DOCUMENT_MISSING"}
    definition = _fetch(event.result_digest or "", documents)
    if isinstance(definition, str):
        return {definition}
    try:
        tree = json.loads(definition)
        leaves = {key: _fetch(digest, documents) for key, digest in tree["leaves"]}
    except _DOCUMENT_ERRORS:
        return {"OBSERVATION_MISMATCH"}
    codes = {data for data in leaves.values() if isinstance(data, str)}
    if codes:
        return codes
    found = {key: data for key, data in leaves.items() if isinstance(data, bytes)}
    # 叶事件缺少分支事件或路径权重时，记为观测不符。
    weights = {
        e.id[2:]: e.path_weight
        for e in log.events
        if e.kind == "branch" and e.path_weight is not None
    }
    if not set(found) <= set(weights):
        return {"OBSERVATION_MISMATCH"}
    try:
        value = math.fsum(weights[k] * _population(tree, data) for k, data in found.items())
    except _DOCUMENT_ERRORS:
        return {"OBSERVATION_MISMATCH"}
    if abs(value - (event.value or 0.0)) > _OBSERVATION_TOLERANCE:
        return {"OBSERVATION_MISMATCH"}
    return set()


def _tolerance_codes(certificate: PreservationCertificate, document: bytes) -> set[str]:
    """返回容差文件与比较集合的失败码；先核对哈希，再解析。"""
    digest = "sha256:" + hashlib.sha256(document).hexdigest()
    if digest != certificate.tolerance_source.digest:
        return {"TOLERANCE_SOURCE_MISMATCH"}
    try:
        table = load_tolerances(document)
    except TraceInputError:
        return {"TOLERANCE_SOURCE_MISMATCH"}
    codes: set[str] = set()
    if table.rule != certificate.tolerance_source.rule:
        codes.add("TOLERANCE_SOURCE_MISMATCH")
    cross = {c.name: c for c in certificate.comparisons if c.kind == "cross_layer"}
    if set(cross) != set(table.comparisons):
        codes.add("COMPARISON_SET_MISMATCH")
    for name, entry in table.comparisons.items():
        level = next((t for t in _LADDER if t >= entry.max_abs_delta), None)
        stated = cross.get(name)
        if entry.tolerance != level or (stated is not None and stated.tolerance != entry.tolerance):
            codes.add("TOLERANCE_SOURCE_MISMATCH")
    return codes


def check_certificate(
    certificate: PreservationCertificate,
    trace_logs: Iterable[TraceLog],
    *,
    expected_key: str,
    tolerance_document: bytes,
    result_documents: Mapping[str, bytes] | None = None,
) -> tuple[str, ...]:
    """用轨迹日志、理想键与容差文件检查一份证书。

    检查每个引用时，依次检查其种类、记录与事件；
    引用有误时，不进入后续检查。

    Args:
        certificate: 待检查的证书。
        trace_logs: 引用所指的轨迹日志，按 ``source.digest`` 查找。同一 digest
            可传多份，各份字节须相同。同层覆盖检查按传入份数计数。
        expected_key: 理想主导键，由调用方计算。
        tolerance_document: 冻结容差文件的字节。
        result_documents: 观测定义与叶结果文档，按 ``sha256:<hex>`` 摘要索引。
            每个被引用的可观测事件都由这些文档重算。

    Returns:
        无重复、顺序固定的失败码；证书成立时为空。

    Raises:
        TraceInputError: 参数类型错误。
    """
    if not isinstance(certificate, PreservationCertificate):
        raise TraceInputError("certificate must be a PreservationCertificate")
    items = _items("trace_logs", trace_logs, TraceLog)
    logs = {log.source.digest: log for log in items}
    _bits("expected_key", expected_key)
    if not isinstance(tolerance_document, bytes):
        raise TraceInputError("tolerance_document must be bytes")
    if result_documents is not None and (
        not isinstance(result_documents, Mapping)
        or not all(isinstance(data, bytes) for data in result_documents.values())
    ):
        raise TraceInputError("result_documents must map digests to bytes")
    codes = _conflict_codes(items) | _same_layer_codes(certificate, items)
    verdicts: dict[str, str] = {}
    observed = {
        (log.source.digest, e.id): (log, e)
        for log in logs.values()
        for e in log.events
        if e.kind == "observable"
    }
    for comparison in certificate.comparisons:
        codes |= _comparison_codes(comparison, logs, certificate.program_ref, verdicts)
        for ref in comparison.evidence_refs:
            if ref in observed:
                codes |= _observation_codes(observed[ref][1], observed[ref][0], result_documents)
    codes |= _exclusion_codes(certificate, logs, verdicts)
    if certificate.symbolic.level not in _DECIDABLE_LEVELS:
        codes.add("SYMBOLIC_LEVEL_UNDECIDABLE")
    if certificate.expected_key != expected_key:
        codes.add("EXPECTED_KEY_MISMATCH")
    codes |= _tolerance_codes(certificate, tolerance_document)
    return tuple(code for code in _FAILURE_CODES if code in codes)
