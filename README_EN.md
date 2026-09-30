<p align="center">
  <img src="logo.png" alt="Qaiji-IR logo" width="240">
</p>

# Qaiji-IR · 开济IR

**English** | [简体中文](README.md)

> **QaiJiIR** — a cross-layer quantum–classical **digital-twin** intermediate representation.

A cross-layer IR spine for hybrid quantum-classical computing, with **semantic preservation,
feedback runtime, pulse waveform, open-system dynamics, and calibration trace** as first-class
concerns. It spans eight layers (`L5 ProgramIR → L0 WaveformIR`, plus side layers `P DynamicsIR`
and `T TraceIR`) and interoperates with OpenQASM 3, QIR, and MLIR as adapter / target / bridge —
without borrowing semantic authority from them.

## Current status

The eight-layer model is the project's overall direction. The delivered Slice A currently focuses
on the circuit-level front end: 19 `GateType` gate kinds, immutable quantum and classical nodes,
a bidirectional OpenQASM 3 codec, a golden round-trip contract, and executable checks for basis and
RZ phase conventions. OpenQASM 2.0 is accepted as compatibility input and is normalized to 3.0 on
output. Out-of-scope constructs raise a specific `QaijiIRError` subclass instead of being silently
discarded. M-1 adds headerless input, flattening of multiple quantum registers, register
broadcasting, and indexed conditions on one-bit classical registers. Alongside the 14 registered
gate names, the codec accepts 19 additional names through parse-time expansion; these are a
separate set from the 19 `GateType` kinds, whose enumeration is unchanged. See the
[codec documentation](doc/source/api/codec.rst) for equivalence levels, the `cu3` phase difference,
and broadcasting boundaries.

On top of the circuit front end, `qaiji.core.semantics` delivers the L4 semantic authority
layer: it classifies every operation into a morphism bucket, reads first-class measurement/
conditional data flow, produces a structural-identity `sha256` content hash, and runs an R1-R4
preservation-verdict engine that decides — at EXACT or UP_TO_PHASE precision — whether a
transform (position-wise correspondence, a CNOT/CX alias collapse, or folding a whole-turn rotation) still
preserves operator semantics. The layer never imports the OpenQASM parser dependency, enforced
by a double-gated import-purity test. As the domain precondition this verdict engine relies on,
`Gate.canonicalize()`'s whole-turn folding criterion was tightened to fold any exact `2*pi*k`
multiple — previously, very large angles could survive un-folded because the modulo residual
exceeded tolerance.

`qaiji.core.program` provides L5 program descriptions: ordered quantum invocations,
experiment metadata, result outputs, and strict JSON round trips. `compute_kernel_ref`
uses a fixed L4 recipe; `validate_program` authenticates circuits in the supplied table,
checks complete measurement writes for output registers, and reports all problems together.
Calibration and device-model references pass through unchanged. Shot execution and the
feedback runtime are not implemented.
The [L4 tutorial](doc/source/getting-started/semantics.rst) and
[L5 tutorial](doc/source/getting-started/program.rst) show executable examples.

`qaiji.core.native` provides CZ-basis expansion, deterministic L2 scheduling with explicit
timing/resource configuration, strict JSON round trips, and independent source, rule,
matrix, and timing validation. `qubic_mapping` produces neutral operation records;
`qaiji.core.program_native` associates measurement histories and final-bit references
with L5 invocations. The [executable tutorial](doc/source/getting-started/native-schedule.rst)
uses synthetic configuration. These APIs do not emit ISA or waveforms, execute shots,
or establish physical fidelity. Python gates RX90, RX180, ISWAP, and SQISWAP support
native lowering; the existing OpenQASM codec still rejects those four gates.

## Install

```bash
pip install qaiji-ir      # import name: qaiji
```

The package is not yet published on PyPI; until the first release, install from a
clone with `pip install .`.

Qaiji-IR supports Python 3.12–3.14.

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

Build the professional Chinese documentation locally:

```bash
uv sync --group docs && uv run poe docs
```

The generated HTML is written to `doc/build/html/`. Online documentation:
<https://yjmaxpayne.github.io/Qaiji-IR/>.

## License

Apache-2.0
