Feature: P-v1 bound continuous-evolution contract
  Qaiji-IR specifies a portable problem and a deterministic result contract.
  These scenarios are implementation requirements, not completed tests.
  The analytic checker validates only the reference values and discrimination.

  Background:
    Given the P-v1 contract in QAIJI-PRD-008
    And numerical comparisons use absolute tolerance 1e-10 and relative tolerance 0 unless exact comparison is required

  @must @planned
  Scenario: AC-01 Restore a bound problem without a device registry
    Given a complete artifact with fixed operator and signal values
    And no device registry or calibration database is available
    When a consumer restores the physical problem
    Then every physical value equals the artifact value
    And no mutable external configuration is read
    When the restoration mechanism substitutes a default calibration scale
    Then the independent content comparison fails on that physical value

  @must @planned
  Scenario: AC-02 Apply an operator in an explicit asymmetric tensor order
    Given tensor order [a, b] and local dimensions [2, 3]
    And the dimensionless operator X acts only on site a
    When each consumer applies the operator to basis index 2
    Then the output has value 1 at index 5 and zero at every other index
    When consumer A assembles the factors in the reversed tensor order
    Then the element comparison fails at the declared tensor order

  @must @planned
  Scenario Outline: AC-03 Preserve units, phase, and Hermitian sums
    Given the signed analytic fixtures V-02 and V-03
    And a Hermitian operator expressed as two non-Hermitian terms
    When the correct consumer restores and interprets the fixtures
    Then both phase fixtures match their analytic density matrices
    And the Hermitian sum passes physical checking
    When its operator or unit mechanism applies <mutation>
    Then the phase or operator comparison fails

    Examples:
      | mutation                         |
      | an additional factor of 2*pi      |
      | the opposite sign of Y           |
      | an incorrect Hamiltonian sign    |

  @must @planned
  Scenario: AC-04 Treat a Lindblad coefficient as a rate
    Given initial state |1> and L = |0><1|
    And the rate is 0.02 per ns for 50 ns
    When each consumer interprets the Lindblad term
    Then the excited population equals exp(-1)
    When the collapse-operator mechanism uses 0.02 instead of sqrt(0.02)
    Then the population comparison fails because the effective rate is squared

  @must @planned
  Scenario: AC-05 Keep signal intervals and output times independent
    Given signal edges [0, 1, 3] ns and values [0.2, 0.4] rad/ns
    And H(t) = u(t) X with initial state |0>
    And output times [0, 0.5, 1, 3] ns
    When the consumer interprets the signal
    Then u(1) is 0.4 rad/ns
    And the signal area through 3 ns is 1 rad
    And the result contains exactly the four requested times
    And the excited populations at those times are [0, sin(0.1)^2, sin(0.2)^2, sin(1)^2]
    When the boundary mechanism uses the preceding interval at time 1
    Then the boundary-value comparison fails
    When the output mechanism snaps time 0.5 to a signal edge
    Then the time comparison fails
    When the output mechanism uses an edge state but keeps the time label 0.5
    Then the population comparison fails at time 0.5

  @must @planned
  Scenario: AC-05 Interpret a sampled rate on the same intervals
    Given edges [0, 1, 3] ns and rates [0.1, 0.3] per ns
    And initial state |1> with L = |0><1|
    When the consumer interprets the dissipator
    Then the excited population at 3 ns equals exp(-0.7)
    And no terminal rate sample is consumed
    When the rate mechanism extends the first rate through the last interval
    Then the population comparison fails

  @must @planned
  Scenario: AC-06 Reject an omitted local initial state
    Given a product state for two declared sites
    And the local factor for one site is absent
    When structural checking examines the state
    Then it reports INVALID_REQUEST at the missing factor
    When the state mechanism supplies a ground state instead
    Then the omission-rejection check fails

  @must @planned
  Scenario: AC-06 Return explicit zero-duration observations
    Given one signal edge [7] ns and no sampled interval values
    And output times [7] ns
    And an explicit normalized initial state with requested observations
    When the zero-duration mechanism produces the result
    Then all requested values equal their initial-state values
    And the time axis has one entry
    And no evolution solver is invoked
    When that mechanism returns zero output entries
    Then the result cardinality check fails

  @must @planned
  Scenario: AC-07 Keep partial trace distinct from subspace projection
    Given a Bell state with one retained subsystem
    And a separate qutrit state diag(0.5, 0.25, 0.25)
    And the qutrit projection retains levels [0, 1]
    When both observation mechanisms produce their outputs
    Then the Bell reduced state is I/2
    And the qutrit block is diag(0.5, 0.25)
    And the qutrit input trace is 1, trace error is 0, and leakage is 0.25
    And physical checking accepts the block trace 0.75
    When the projection mechanism normalizes the qutrit block
    Then the block, trace, and leakage comparisons fail

  @must @planned
  Scenario: AC-07 Use a conjugate transpose for a complex isometry
    Given v = (1, i, 0)^T/sqrt(2), V = v, and rho = v v-dagger
    When the projection mechanism computes V-dagger rho V
    Then the projected block is [1] and the raw leakage estimate is 0
    When that mechanism replaces V-dagger with V-transpose
    Then the block and leakage comparisons fail

  @must @planned
  Scenario: AC-07 Preserve the raw leakage estimate when input trace has numerical error
    Given delta = 2^-35 and rho = diag(1+delta, 0)
    And a zero-duration request with V = I
    When the projection mechanism reports its scalar values
    Then the raw leakage estimate equals -delta exactly
    And the input trace equals 1+delta exactly
    And the trace error equals delta exactly
    When that mechanism subtracts the block trace from the input trace instead of 1
    Then the exact leakage comparison fails
    And the general absolute tolerance 1e-10 is not used for these scalar comparisons

  @must @planned
  Scenario Outline: AC-08 Preserve all core exchange semantics
    Given a valid artifact containing complex matrices and explicit array shapes
    When the codec completes an exchange round trip
    Then all numerical and semantic fields match exactly
    When the codec applies <mutation>
    Then the independent round-trip comparison or strict decoder fails

    Examples:
      | mutation                              |
      | discarding a matrix imaginary part    |
      | replacing a declared tensor axis      |
      | silently accepting an unknown core key |
      | accepting duplicate JSON keys         |

  @must @planned
  Scenario: AC-08 Reject non-finite values and unknown versions
    Given a valid baseline artifact
    When its encoded numerical component is replaced by NaN or Infinity
    Then transport or structural checking reports INVALID_REQUEST
    When its P schema major or unrecognized minor version is changed
    Then decoding reports INVALID_REQUEST with a version diagnostic
    And no best-effort physical interpretation is returned

  @must @planned
  Scenario: AC-09 Separate content identity from provenance and physics equivalence
    Given fixed problem and request identity vectors from the architecture design
    When object key order, attachment path, or provenance changes
    Then problem and request identities remain unchanged
    When phase, target site, rate, or required extension payload changes
    Then both affected content identities change
    When only an observation or execution policy changes
    Then request identity changes and problem identity remains unchanged
    When the identity mechanism omits a required semantic component
    Then the corresponding sensitivity vector fails
    And different operator decompositions are not required to have equal identities

  @must @planned
  Scenario: AC-10 Preserve a required bath extension while refusing interpretation
    Given a bath payload in a versioned required semantic extension envelope
    And every payload byte and referenced array is available
    When an unrecognizing consumer checks and forwards the artifact
    Then transport checking succeeds and the payload survives exactly
    And physical certification and execution report UNSUPPORTED_CAPABILITY
    And the diagnostic identifies the extension namespace and version
    When the loader drops the extension or certifies only the remaining core
    Then the preservation or physical-certification check fails

  @must @planned
  Scenario Outline: AC-11 A report does not authorize a physical transformation
    Given a valid request with no model approximations
    When a consumer reports <transformation> as applied
    Then the result is rejected as INVALID_RESULT
    When the permission mechanism treats the report as authorization
    Then the transformation-permission check fails

    Examples:
      | transformation                    |
      | compression of physical idle time |
      | truncation of physical readout time |
      | quantization of a signal boundary |
      | resampling that changes the ZOH signal |
      | a rotating-wave approximation     |

  @must @planned
  Scenario: AC-11 Resolve only explicitly delegated numerical policy fields
    Given a request that delegates method selection and fixes an error bound
    When a consumer reports its selected method within the bound
    Then that delegated resolution is accepted and reported
    When a consumer changes a nondelegated bound or omits a policy difference
    Then the result is rejected as INVALID_RESULT
    And a policy report alone does not waive the request constraint

  @must @planned
  Scenario Outline: AC-12 Distinguish failures without returning successful empty results
    Given the valid request and checker budget for <condition>
    When the corresponding checking or consumer boundary is exercised
    Then the diagnostic category is <category>
    And its detail code and field path locate the failed condition
    And no successful result is returned
    When the classifier maps that condition to an empty successful result
    Then the failure-classification check fails

    Examples:
      | condition                          | category               |
      | an unknown site in an operator     | INVALID_REQUEST        |
      | an unsupported required extension  | UNSUPPORTED_CAPABILITY |
      | a declared dimension budget excess | RESOURCE_LIMIT         |
      | a numerical execution failure      | SOLVER_FAILURE         |
      | a result with a different request identity | INVALID_RESULT  |

  @must @planned
  Scenario Outline: AC-13 Detect each result-contract mismatch
    Given a result that matches all observations in a valid request
    When the result checker examines the baseline
    Then the result-contract check succeeds
    When the returned <field> is changed inside the result-production path
    Then checking reports INVALID_RESULT at that field
    When the checker omits that comparison
    Then the targeted checker mutation fails the rejection test

    Examples:
      | field                       |
      | request identity            |
      | output time                 |
      | array shape                 |
      | tensor order                |
      | state frame                 |
      | policy difference report    |
      | requested observation set   |

  @must @planned
  Scenario: AC-14 Physical checks do not silently repair inputs
    Given a valid normalized Hermitian state and an adequate explicit budget
    When physical checking uses the declared P-v1 tolerances
    Then that state and a valid projected block pass
    When the state is diag(1.000001, -0.000001)
    Then checking reports INVALID_REQUEST for the negative eigenvalue
    When the state mechanism clips that eigenvalue or normalizes the input
    Then the no-repair and rejection checks fail

  @must @planned
  Scenario: AC-14 Check both sides of the declared PSD numerical boundary
    Given normalized diagonal states rho = diag(1+eps, -eps)
    And an adequate explicit checker budget
    When the PSD mechanism uses the declared tolerance 1e-10
    Then the case eps=1e-10 passes the PSD numerical predicate
    And the cases eps=1.01e-10 and eps=1e-8 fail the PSD numerical predicate
    When that mechanism relaxes the tolerance to 1e-7
    Then the rejection cases detect the incorrect tolerance
    When that mechanism tightens the tolerance to zero
    Then the accepted boundary case detects the incorrect tolerance

  @must @planned
  Scenario: AC-14 A resource limit is not a completed physical check
    Given a valid factored problem whose full matrix exceeds the checker budget
    When structural checking is requested
    Then the global dense-assembly trap is not called
    When physical checking requires work above that budget
    Then it reports RESOURCE_LIMIT with the limited resource
    And it does not claim completed physical certification
    When the budget mechanism silently skips the work and reports success
    Then the check-completeness test fails

  @must @planned
  Scenario: AC-15 Compare two independent consumers with analytic references
    Given the same exchanged asymmetric, phase, decay, and projection fixtures
    And consumers A and B do not share operator or generator construction code
    When each consumer reconstructs operators and deterministic observables
    Then both match every declared analytic reference
    When only consumer A changes the target site during assembly
    Then comparison with consumer B and the analytic reference fails
    And a common serializer is not used as the only semantic reference

  @must @planned
  Scenario: AC-16 Require all six internal negative-control mechanisms
    Given the correct implementation passes the shared contract fixtures
    When each required mutation is injected into its actual mechanism
      | mechanism        | mutation                              |
      | tensor assembly  | exchange tensor factors               |
      | operator assembly | change a phase or target site         |
      | unit interpretation | repeat a unit conversion            |
      | dissipator adaptation | confuse rate with amplitude       |
      | time interpretation | change a ZOH boundary               |
      | codec            | delete or replace a semantic field    |
    Then every mutation fails for its designated contract condition
    And no mutation changes the reference answer or bypasses its mechanism
    When the harness leaves any one mutation undetected
    Then the negative-control completeness gate fails

  @must @planned
  Scenario: AC-17 Preserve existing behavior and keep the contract installation isolated
    Given a package installed with only its declared required dependencies
    And EmuPlat, NumPy, SciPy, QuTiP, and QuanTempo are unavailable
    When the root package is imported in a fresh process
    Then no P numerical container or production solver is loaded implicitly
    And the public P model, codec, and structural checks remain usable explicitly
    And the original L4, L5, and L2 behavior and identity recipes remain compatible
    When the package mechanism adds a numerical dependency or eager solver import
    Then the dependency or fresh-process import gate fails

  @must @planned
  Scenario: AC-18 Keep binding provenance and check every physical attachment
    Given a complete artifact with a fixed physical array attachment
    When only the immutable provenance snapshot identifiers change
    Then the provenance remains available and both content identities are unchanged
    When the required array is absent or one attachment byte is corrupted
    Then restoration reports INVALID_REQUEST at the attachment reference
    When the attachment mechanism skips the content digest check
    Then the corrupted-byte negative control fails
