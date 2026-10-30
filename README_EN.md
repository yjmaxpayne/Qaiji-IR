<p align="center">
  <img src="logo.png" alt="Qaiji-IR logo" width="240">
</p>

# Qaiji-IR · 开济 IR

**English** | [简体中文](README.md)

[![Python 3.12–3.14](https://img.shields.io/badge/python-3.12%E2%80%933.14-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![CI](https://github.com/yjmaxpayne/Qaiji-IR/actions/workflows/ci.yml/badge.svg)](https://github.com/yjmaxpayne/Qaiji-IR/actions/workflows/ci.yml)
[![Documentation](https://github.com/yjmaxpayne/Qaiji-IR/actions/workflows/docs.yml/badge.svg)](https://github.com/yjmaxpayne/Qaiji-IR/actions/workflows/docs.yml)
[![Docs](https://img.shields.io/badge/docs-latest-blue)](https://yjmaxpayne.github.io/Qaiji-IR/)
[![codecov](https://codecov.io/gh/yjmaxpayne/Qaiji-IR/graph/badge.svg?token=M9NQqTSx08)](https://codecov.io/gh/yjmaxpayne/Qaiji-IR)
[![OpenQASM 3](https://img.shields.io/badge/OpenQASM-3.0-6929C4)](https://openqasm.com/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23118964.svg)](https://doi.org/10.5281/zenodo.23118964)

> **Qaiji-IR** — a cross-layer quantum–classical **digital-twin** intermediate representation.

Qaiji-IR is designed as a cross-layer IR spine for hybrid quantum–classical computing, with
**semantic preservation, feedback runtime, pulse waveform, open-system dynamics, and calibration
trace** as first-class concerns. The overall design spans eight layers
(`L5 ProgramIR → L0 WaveformIR`, plus side layers `P DynamicsIR` and `T TraceIR`) and interoperates
with OpenQASM 3, QIR, and MLIR as adapter / target / bridge — without borrowing semantic authority
from them.

## Features

- **Circuit model and conventions**: 19 `GateType` kinds, immutable quantum and classical nodes,
  and a mutable `Circuit` container; executable checks for basis and RZ phase conventions.
- **OpenQASM codec**: reads OpenQASM 2.0 and 3.0 (the version header is optional) and normalizes
  output to 3.0; text round trips preserve circuit equality. It supports 14 registered gate names,
  and expands 19 further standard gate names at parse time into serializable gates without adding
  `GateType` kinds. Register broadcasting, flattening of multiple quantum registers, and indexed
  conditions on one-bit classical registers are supported. Out-of-scope constructs raise a
  specific `QaijiIRError` subclass instead of being silently discarded. See the
  [codec documentation](doc/source/api/codec.rst) for equivalence levels, the `cu3` phase
  difference, and broadcasting boundaries.
- **L2 native schedules** (`qaiji.core.native`, `qaiji.core.program_native`): CZ-basis expansion
  and deterministic scheduling under explicit timing and resource configuration, strict JSON
  round trips, and independent source, rule, matrix, and timing validation. `qubic_mapping`
  produces neutral operation records, and the program bridge associates measurement histories and
  final-bit references with L5 invocations. Python-built RX90, RX180, ISWAP, and SQISWAP gates take
  part in native scheduling; the OpenQASM codec does not support these four gates.
- **L4 semantics** (`qaiji.core.semantics`): classifies every operation into a morphism category,
  extracts measurement and conditional data flow, produces a structural-identity `sha256` content
  hash, and runs an R1–R4 verdict engine that decides whether position-wise correspondence, a
  CNOT/CX alias collapse, or folding a whole-turn rotation preserves operator semantics (`EXACT`
  or `UP_TO_PHASE`). The layer does not depend on the OpenQASM parser.
- **L5 programs** (`qaiji.core.program`): ordered quantum invocations, experiment metadata, result
  outputs, and strict JSON round trips. `compute_kernel_ref` derives kernel references with a fixed
  L4 recipe; `validate_program` authenticates circuits in the supplied table, checks measurement
  writes for output registers, and reports all problems together.
- **P continuous-evolution contract** (`qaiji.core.physical`): immutable problems, requests, and
  results; strict exchange with explicit array attachments; content identities for physical fields
  and execution policy; tiered checks for structure, capabilities, numerical conditions, and resource
  budgets. The P layer uses only the standard library and does not execute time evolution.

Executable tutorials: [L2 native scheduling](doc/source/getting-started/native-schedule.rst),
[L4 semantic summaries](doc/source/getting-started/semantics.rst),
[L5 program validation](doc/source/getting-started/program.rst), and
[P continuous-evolution contracts](doc/source/getting-started/physical.rst).

**Scope**: the package does not execute shots or time evolution, provide a feedback runtime,
emit ISA or waveforms, or claim physical fidelity. Calibration and device-model references are
passed through. The pulse (L1), waveform (L0), and trace (T) layers have no public interfaces yet.
The P layer provides exchange and checking contracts. Consumers implement solvers and hardware
adapters themselves.

## Installation

```bash
pip install qaiji-ir   # import name: qaiji
# unreleased changes on main: pip install "git+https://github.com/yjmaxpayne/Qaiji-IR.git"
```

Qaiji-IR supports Python 3.12–3.14. See the
[installation guide](doc/source/getting-started/installation.rst) for a development setup.

## Quick start

```python
from qaiji import from_qasm3, to_qasm3

source = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
h q[0];
cx q[0], q[1];
"""

circuit = from_qasm3(source)
canonical = to_qasm3(circuit)
assert from_qasm3(canonical) == circuit
print(canonical)
```

## Documentation

Build the Chinese documentation locally:

```bash
uv sync --group docs && uv run poe docs
```

The generated HTML is written to `doc/build/html/`. The online documentation is at
<https://yjmaxpayne.github.io/Qaiji-IR/>.

## Paper and citation

Related preprint: [arXiv:2609.29305](https://arxiv.org/abs/2609.29305) (Jun Ye, 2026).
The paper's integration evidence and this package's public API have separate scopes; for the scope
of the public API, see **Scope** above. If you use the software, cite the version-specific DOI in
[CITATION.cff](CITATION.cff). If you discuss the IR architecture, also cite the preprint.

## License

Apache-2.0
