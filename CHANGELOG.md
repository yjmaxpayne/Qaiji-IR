# Changelog

All notable changes to this project are documented here. The format follows
[Conventional Commits](https://www.conventionalcommits.org/) and versions are derived from
git tags via `poetry-dynamic-versioning`.

## [Unreleased]

### Feat

- Add `qaiji.codec.parse_qasm3`: one parse returns the circuit together with a source-origin
  table aligned one-to-one with `circuit.gates`, including conditional bodies. `from_qasm3`
  keeps its signature and accepts and rejects exactly the same sources (L7-01).
- Add `qaiji.codec.ParsedQasm3`, a frozen, unhashable record of `circuit`, `origins` and
  `declared_version` (header text, `None` when absent); its equality compares circuit and
  origins (L7-02).
- Add `qaiji.codec.OperationOrigin`, a frozen per-operation record: statement index, raw
  spelling, 1-based inclusive line/column span in code points, broadcast and expansion
  indices, and conditional body origins. Circuit equality, summaries, canonical form and
  `to_qasm3` never read it (L7-03).
- Ship an empty PEP 561 `py.typed` marker inside the package and every built wheel, so type
  checkers use qaiji's annotations (L7-06).

- Accept headerless OpenQASM input while retaining explicit version validation (L6-01).
- Expand 19 additional gate names into existing serializable gates, with documented
  equivalence levels and the official OQ2 interpretation of `cu3` (L6-02).
- Broadcast register-level gate operands in index order; all register operands must have
  equal width, including width-one registers (L6-03).
- Broadcast measurements between equal-width sources and targets; mixed register/indexed
  forms require the register side to have width one (L6-04).
- Flatten multiple quantum registers in declaration order (L6-05).
- Accept indexed equality conditions on one-bit classical registers for values 0 and 1;
  indexed conditions on multi-bit registers remain unsupported (L6-06).

- Add `qaiji.core.native`: explicit timing/resource configuration, CZ-basis lowering,
  deterministic native schedules, strict `qaiji.native_schedule.v0` JSON, independent
  source/rule/matrix/timing validation, and neutral `qubic_mapping` projections.
- Add `qaiji.core.program_native`: authenticate each L5 invocation and associate
  measurement histories and final-bit references with declared outputs. These records
  do not execute shots, emit hardware instructions/waveforms, or establish physical fidelity.
- Document native and bridge APIs, supported domains and integer budgets, with an
  executable synthetic-configuration JSON → validation → projection → bridge tutorial.

- Add `qaiji.core.program`: frozen L5 program records, strict JSON round trips, a fixed
  L4 kernel-reference recipe, and ordered validation of referenced circuits and output
  measurement coverage through `validate_program` and `ProgramValidationError`.
- Deliver the slice-A typed front-end model, classical core, bidirectional OpenQASM 3 codec,
  conventions self-check, golden round-trip contract, and
  `IR_SCHEMA_VERSION = "qaiji.ir.v0"` schema marker.
- Add the `qaiji.core.semantics` L4 semantic authority layer: operation classification
  (`MorphismType`/`EquivLevel`/`CartanRole`/`ConditionModel`, `classify_operation`,
  `annotate_circuit`), data-flow reads (`MeasurementHandle`, `ClassicalEdge`,
  `build_dataflow_summary`), a canonical structural-identity hash (`build_semantic_summary`,
  `canonical_summary_hash`, `SUMMARY_SCHEMA_VERSION = "qaiji.semantic_summary.v0"`), an
  R1-R4 preservation-verdict pipeline (`PreservationSummary`, `check_preservation`,
  `UnsupportedEquivLevelError`), and a frozen handshake handle (`SemanticIRHandle`,
  `HandleStatus`, `freeze_summary`, `schema_version = "qaiji.semantic_ir_handle.v0"`).
  `Circuit.canonicalize()` performs the circuit-level structural normalization the
  preservation pipeline judges against. The layer is a codec/OpenQASM/numpy-free leaf,
  enforced by a double-gated import-purity test.

### Fix

- A decimal integer literal longer than the interpreter's integer string conversion limit
  now raises `Qasm3ParseError` (`source at 1:1:` plus the interpreter's message, original
  `ValueError` as the cause) instead of a bare `ValueError`. Only the `openqasm3.parse` step
  is wrapped (L7-04).
- An integer gate parameter outside the float range now evaluates to infinity and raises
  `Qasm3UnsupportedConstructError` (`Gate parameters must be finite`) instead of a bare
  `OverflowError`, whether written alone, negated, parenthesised or inside an expression that
  stays infinite. `1/N` now underflows to `0.0` and is accepted; `1/(1/N)` raises
  `Qasm3ParseError` (`division by zero`); `N-N` and `N/N` are not finite; `N**2` and `N%2`
  still report `unsupported binary expression` (L7-05).
- Hexadecimal, binary and octal literals no longer bypass the conversion limit. Every integer
  literal that is read (register widths, indices, condition values, parameters) and the
  running total qubit count must be convertible to decimal; otherwise `Qasm3ParseError`
  reports `<construct> at L:C:` plus the interpreter's message, with the original cause.
  Per case: an oversized qubit index was a bare `ValueError`; an oversized classical bit
  index or bit condition value was `Qasm3UnsupportedConstructError` at the statement and is
  now `Qasm3ParseError` at the literal; an oversized register width (reported at `[`),
  whole-register condition value or total qubit count (reported at the crossing
  declaration) was accepted and then broke `to_qasm3`. Values within the limit keep their
  previous outcome; the total number of classical bits is not limited (L7-08).
- Reject quantum/classical register name collisions in either declaration order (L6-07).
- Wrap recursion overflow during parsing or evaluation in `Qasm3ParseError`, reporting
  `expression nesting exceeds parser limit` (L6-08).
- Reject empty, whitespace-only and comment-only input as having no qubit declaration;
  wrap other parser-call `AttributeError` failures in `Qasm3ParseError` (L6-09).
- Choose the first output quantum register name from `q`, `q0`, `q1`, … not occupied by
  a classical register, preserving the existing output when `q` is available (L6-10).

### Changed

- Rotation folding in `Gate.canonicalize()` now decides "is this a whole turn?" through the
  shared `_tau_multiple_exponent` predicate applied to the angle as authored, instead of a
  tolerance test on `theta % tau`. Angles at large whole turns (measured from `1e6 * tau`)
  previously survived as rotations because the modulo residual exceeded the tolerance; they
  now fold to `I`, which is the physically correct reading. Normalization of surviving
  rotations is unchanged.
- Pytest `addopts` now includes `-rfEs`, so skip reasons are listed next to failures in the
  short summary (the live cross-repo re-check reports why it was skipped).

### Tests

- Add cross-repo falsification of the basis conventions: ten frozen source facts from the
  optics adapter's domain layer are judged by criteria R0-R4 through an eval-free AST
  evaluator. "Falsification passed" is the expected outcome, not a no-op.
- K-1: flipping `OPTICS_INDEX_TO_PHYSICAL` and `QASM3_TO_OPTICS_BIT` together still passes
  `self_check()`; the cross-repo criteria now catch this consistent silent flip.
- The snapshot expires: once any fact is more than 180 days old the suite fails without any
  code change. The failure message lists the stale facts and the inline refresh steps.

### Contract

- Any change that breaks the golden OpenQASM round trip must bump `IR_SCHEMA_VERSION` and be
  recorded in this changelog.
- Any change to the semantic-summary hash input domain, its 14-key stable-key set, or a
  `qaiji.core.semantics.types` literal that flows into a summary key must bump
  `SUMMARY_SCHEMA_VERSION` and be recorded here.

### Docs

- Each convention constant's docstring now states its falsification status (cross-repo
  falsified / reference frame / derived), linked to the snapshot facts by rules L1-L5.
- Add a locally reproducible Chinese Sphinx documentation site and align the bilingual README
  quick start with the delivered Slice A API.
- Docstrings in five modules state their facts without milestone codes or status wording;
  code with bare strings stripped is unchanged (L7-07).
- Document the codec metadata API (`parse_qasm3`, `ParsedQasm3`, `OperationOrigin`) with an
  executable example, the integer-limit failures and their messages in the codec reference
  and troubleshooting pages, and the shipped `py.typed` marker.
