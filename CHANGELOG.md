# Changelog

All notable changes to this project are documented here. The format follows
[Conventional Commits](https://www.conventionalcommits.org/) and versions are derived from
git tags via `poetry-dynamic-versioning`.

## [Unreleased]

### Added

- 新增 `two_body_drive` 端口角色，允许非零载频，CZ 目标必须恰为比特对。
- 新增独立 `PortResourceMap`、严格编解码、内容身份与逐 Play 资源覆盖检查。

- Add `ProgramIRV1` with an authoritative conditional tree and strict `qaiji.program.v1` exchange.
- Bind invariant checks to explicit program kernels, saved circuit hashes, and scheduling inputs.
- Compare waveform leaf events with L1 Acquire events.

### Changed

- L1 保持 `qaiji.pulse/0.1`。旧 L1 字段、规范字节与身份保持不变。

- Replace waveform segment `condition` with ordered `branch` histories in `qaiji.waveform/0.2`.
- Reject waveform 0.1 bytes with `SCHEMA` and validate complete binary trees.
- Preserve program v0 exchange and L1 identities. Reject conditional v1 programs at the native bridge.

## [0.4.1] - 2026-11-03

This release changes only the documentation, one docstring and the citation metadata. The
behavior, the dependencies and the lock file are the same as in 0.4.0.

### Documentation

- Remove the statements that L1 and L0 have no public interface or no source. The start page,
  the code map and the contributing page now list the L1 pulse and L0 waveform layers. The start
  page states that the package does not lower L2 to L1 and does not materialize a whole L1
  program as L0 waveforms.
- The exception page lists `PulseContractError` and `WaveformContractError`.
- The layer relations page lists every check that `check_pulse_program` runs. It states that
  `WaveformIR` checks only the sha256 format of `source_pulse_ref` and does not compare it with
  a `pulse_program_id`.
- The L1 and L0 API pages give the full dependencies of each package and the `sha256:` prefix of
  the identities.
- Fix the sample time in the waveform page and in the `sample_play` docstring:
  `t_k = start_ns + k·1e9 / f_s` in ns.
- The scope statements say "measurement sampling (shots)", because L0 samples waveforms.

### Changed

- `CITATION.cff` lists the version-specific DOIs of v0.3.1 and v0.4.0.

## [0.4.0] - 2026-11-03

### Added

- The L1 pulse layer `qaiji.core.pulse`. It has immutable `Port`, `Frame`, `Envelope`, `Play`,
  `ShiftPhase` and `Acquire` records and a `PulseProgramIR` record that checks its invariants at
  construction. `frame_phase` and `carrier_phase` give the phases of a `Play`. `phases_equal`
  compares two phases modulo 2π. A strict codec gives canonical bytes and the `pulse_program_id`
  identity. `check_pulse_program` checks that a program agrees with the L2 schedule it comes from.
- The L0 sampled-waveform layer `qaiji.core.waveform`. It has immutable `Channel`, `Segment`,
  `TransformRecord` and `WaveformIR` records and checks the L0 rules at construction.
  `sample_envelope` samples an L1 envelope at the interval midpoints. `sample_play` mixes one
  `Play` with its frame carrier into real-valued lab-frame samples. A strict codec gives canonical
  bytes, the `waveform_id` identity and a SHA-256 digest of the samples of each channel.
- Both packages use only the standard library. The package root and `qaiji.core` do not export
  them. The required-only wheel gate now imports each of their modules and `qaiji.core._codec`
  in a fresh process that blocks numpy.
- API pages for the two layers. The core-concepts pages for L1 and L0 give their records, rules
  and boundaries.

### Changed

- **Breaking:** the native rule set is now v1. `NATIVE_RULESET_VERSION` is `qaiji.cz_basis.v1`
  and every `rule_id` starts with `cz.v1.`. `NativeScheduleIR` rejects schedules with the v0 rule
  set version, so 0.4.0 cannot read an L2 JSON document from 0.3.x. Lower the circuit again with
  `lower_to_native`.
- **Breaking:** the L2 identity changes for every program. Each L2 JSON document contains the rule
  set version, so a digest of `NativeScheduleIR.to_json()` changes even when the operations do not
  change. The operations change only for programs that use one of the templates below.
- RX, RY and U3 use short templates when the angle is bitwise ±0.0 or ±π/2. U3 omits the RZ slots
  that have a bitwise zero angle. `sx` and `sxdg` lower to one RX90. `sdg`, `tdg`, `p` and `u1`
  lower to RZ only.
- Conditional bodies have no frame changes. RZ and Z slots move into the phases of later RX90
  slots. Each qubit with a nonzero net frame F gets RX90(π), RX90(π), RX90(w), RX90(w), with
  w = remainder(F/2, 2π). The group phase of a conditional Z is −π/2.
- The encoding primitives and the strict JSON parser are in the private module
  `qaiji.core._codec`. It adds `parse_json`, `json_pointer` and `CodecFault`. The module is
  private: it is not in the `__all__` of `qaiji` or `qaiji.core`. The P-layer codec calls the
  primitives, and its canonical bytes do not change.

### Fixed

- L1 text fields reject strings with lone surrogates. The error is a `PulseContractError` with
  code `UNICODE`, as in L0. Before, such a record could be built, and canonical serialization
  then raised a raw `UnicodeEncodeError`.

## [0.3.1] - 2026-10-30

This release changes only the documentation. The code, the dependencies and the lock file are
the same as in 0.3.0.

### Documentation

- Restructure the documentation. The conventions and native-schedule pages move under
  `core-concepts/`. The core-concepts section now has a page for each layer (L0 to L5 and P),
  an architecture page, a layer relations page and an IR family topology figure. A code map is
  added for contributors.
- Update the index, getting-started, API and development pages to the new structure. The start
  page and the README feature lists give the circuit front end first, then the layers from L2
  up to L5.
- Revise the wording of `README.md`, `README_EN.md` and `doc/`: use one term for each concept
  and remove ambiguous phrases.

## [0.3.0] - 2026-10-29

### Added

- P schema 1.1. `Problem.rotation_freqs` gives the rotation frequency of each site in rad/ns,
  in `tensor_order`; it must be empty when `frame="lab"` and must cover all sites when
  `frame="rotating"`. Capability and requirement profiles carry `approximations`. A request
  matches a profile only when the frames are equal and the requested approximations are a
  subset of the allowed ones.
- The `qaiji.p.bath` extension, version `1.0`, with a public schema: coupling operator,
  spectral density (`drude_lorentz`, `one_over_f`, `tabulated`), temperature and a required
  PSD convention. A consumer must declare `("qaiji.p.bath", "1.0")` in `required_extensions`.
- `request_id`, `problem_id`, `canonical_request_bytes`, `canonical_problem_bytes` and
  `extract_requirements` accept a keyword-only `budget`. A consumer that raises the check
  budget for a large request or problem can identify it and extract its requirements. The
  budget limits resources only; it does not change the identity, the bytes or the requirements.
- The physical guide states the rotating-frame state convention:
  `psi_r(t) = U_r(t) psi(t)` with `U_r(t) = exp(+i sum_k w_k n_k t)` on the absolute problem
  time axis. Rotating-frame and bath requests are certified to the `structure` level only.

### Changed

- **Breaking:** all five P document kinds (problem, request, result, requirements,
  capabilities) use schema version `/1.1`. This release reads and writes only `/1.1`; it
  rejects `/1.0` documents, and 0.2.0 readers reject `/1.1` documents.
- The documentation site is rebuilt on `main` after a release is published.
- `CITATION.cff` lists the version-specific DOI of v0.2.0.

### Security

- Development dependencies are relocked: certifi 2026.10.23, virtualenv 21.15.1, packaging
  26.3 (required by virtualenv 21.15.1) and filelock 4.2.4. The package's runtime dependencies
  do not change.

## [0.2.0] - 2026-10-23

### Added

- P 层公开不可变记录、严格交换、内容身份与分级检查。
  新增标准库可执行教程和 API 文档。
  最小 wheel 验收检查必需依赖、安装路径与逐模块导入。
  CI 在独立环境执行该入口。

- Link the arXiv preprint (2609.29305) from both READMEs, the documentation homepage,
  package URLs, and citation metadata. Keep the software DOI as the default code citation.

- A `Publish to PyPI` workflow builds a release tag and uploads its wheel and sdist to PyPI
  through Trusted Publishing with attestations. It runs when a GitHub Release is published
  (provided the tagged commit already contains the workflow), and on manual dispatch for an
  existing tag. Before uploading it requires a `vX.Y.Z` tag on a commit reachable from `main`,
  passing metadata checks, a wheel whose installed `qaiji.__version__` equals the tag, and, when the
  Release already has package files or a `SHA256SUMS` asset, a byte-for-byte match with them; if any
  check fails, nothing is uploaded. Releases marked as pre-releases are not published. On a Release,
  the files and their `SHA256SUMS` are then attached to it.

### Changed

- Building or installing the package from a git checkout now requires a reachable tag matching the
  release pattern (`vX.Y.Z`) and full history: the build backend runs in strict mode and only reads the tag
  nearest to `HEAD`. Each case, before → after:
  - no tag reachable from `HEAD`: built as `0.0.0.postN.dev0+<commit>` → fails with
    `No tags available and fallbacks disabled by strict mode`;
  - only non-matching tags reachable: built as `0.0.0.postN.dev0+<commit>` → fails with
    `The pattern did not match the latest tag '<tag>'`;
  - a non-matching tag nearer to `HEAD` than a matching one: built as a `.postN` version of the
    older matching tag → fails with the same message;
  - shallow clone whose history contains the matching tag: built with the correct version and
    a warning → fails with `This is a shallow repository, so Dunamai may not produce the
    correct version.`;
  - shallow clone whose history does not contain a tag: built as `0.0.0.postN.dev0+<commit>` →
    fails with the same message.

  Unchanged: a matching tag on `HEAD` gives `X.Y.Z`, one `N` commits behind gives
  `X.Y.Z.postN.dev0+<commit>`, and sdists carry a fixed version and build without git.
  A new CI job re-checks the git-checkout cases above on pushes to `main` and on pull requests.

## [0.1.0] - 2026-10-02

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
  stays infinite. Each of the following also used to raise that bare `OverflowError`: `1/N`
  and `pi/N` now underflow to `0.0` and are accepted; `1/(1/N)` raises `Qasm3ParseError`
  (`division by zero`); `N-N` and `N/N` are not finite and raise the error above; `N**2` and
  `N%2` raise `Qasm3UnsupportedConstructError` (`unsupported binary expression`), as they
  already did for small operands (L7-05).
- Hexadecimal, binary and octal literals no longer bypass the conversion limit. Every integer
  literal that is read (register widths, indices, condition values, parameters) and the
  running total qubit count must be convertible to decimal; otherwise `Qasm3ParseError`
  reports `<construct> at L:C:` plus the interpreter's message, with the original cause.
  Per case: an oversized qubit index was a bare `ValueError`; an oversized gate parameter
  was a bare `OverflowError`; an oversized classical bit index or bit condition value was
  `Qasm3UnsupportedConstructError` at the statement and is now `Qasm3ParseError` at the
  literal; an oversized register width (reported at `[`),
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
