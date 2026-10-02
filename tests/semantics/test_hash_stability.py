# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""全新进程下、贯穿完整语义链路的端到端哈希稳定性（I-Q4.3）。"""

import textwrap

from _fresh_process import run_fresh_process
from qaiji.codec.qasm3 import from_qasm3
from qaiji.core.semantics.registry import annotate_circuit
from qaiji.core.semantics.summary import build_semantic_summary, canonical_summary_hash

_QASM3_SOURCE = textwrap.dedent(
    """\
    OPENQASM 3.0;
    include "stdgates.inc";
    qubit[2] source;
    bit outcome;
    h source[0];
    cx source[0], source[1];
    outcome[0] = measure source[0];
    if (outcome == 1) {
      x source[1];
    }
    """
)


def _parent_process_digest() -> str:
    circuit = from_qasm3(_QASM3_SOURCE)
    annotations = annotate_circuit(circuit)
    summary = build_semantic_summary(circuit=circuit, annotations=annotations)
    return canonical_summary_hash(summary)


def test_fresh_process_digest_matches_parent_process_digest() -> None:
    """完整链路必须跨进程边界给出一致结果（AC-Q2）。

    一个碰巧依赖于字符串驻留、dict 迭代的偶然顺序，或任何其他同进程副产物的哈希，
    能通过所有进程内单元测试，却依然会打破下游的跨会话"regime identity"承诺 ——
    这是唯一一个真能捕获该类缺陷的测试，因此它在一个真正独立的解释器里跑完整条
    链路，而不是把进程边界 mock 掉。
    """
    script = textwrap.dedent(
        f"""
        from qaiji.codec.qasm3 import from_qasm3
        from qaiji.core.semantics.registry import annotate_circuit
        from qaiji.core.semantics.summary import build_semantic_summary, canonical_summary_hash

        source = {_QASM3_SOURCE!r}
        circuit = from_qasm3(source)
        annotations = annotate_circuit(circuit)
        summary = build_semantic_summary(circuit=circuit, annotations=annotations)
        print(canonical_summary_hash(summary))
        """
    )
    child_digest = run_fresh_process(script).strip()

    assert child_digest.startswith("sha256:")
    assert child_digest == _parent_process_digest()
