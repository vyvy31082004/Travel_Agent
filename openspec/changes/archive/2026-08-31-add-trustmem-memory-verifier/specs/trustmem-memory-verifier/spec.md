## ADDED Requirements

### Requirement: Local transition verifier input
The system SHALL evaluate memory writes using a local transition object equivalent to `z_t = (chunk, M_old, actions, M_new)` before committing changes.

#### Scenario: Insert transition is evaluated
- **WHEN** a memory worker proposes an insert transition for a completed turn
- **THEN** the verifier receives the bounded message chunk, relevant active memories before the transition, the proposed insert action, and the projected memory state after insert

#### Scenario: Supersession transition is evaluated
- **WHEN** a candidate conflicts with an existing active memory
- **THEN** the verifier receives the existing memory as part of `M_old`
- **AND** receives the projected `M_new` state showing the old memory superseded and the candidate active

### Requirement: Coverage scoring
The system SHALL score coverage in `[0, 1]` to measure whether important durable information from the chunk is sufficiently represented by the proposed memory transition.

#### Scenario: Candidate omits a durable condition
- **WHEN** the user says they prefer business class for work travel and economy for leisure travel
- **AND** the candidate only stores business class preference without the leisure condition
- **THEN** the coverage score is below the approval threshold
- **AND** the verifier reason explains the missing durable condition

#### Scenario: Candidate preserves all important durable facts
- **WHEN** the candidate stores both work-travel and leisure-travel flight preferences with their conditions
- **THEN** the coverage score meets or exceeds the configured threshold

### Requirement: Preservation scoring
The system SHALL score preservation in `[0, 1]` to measure whether valid existing memories are not incorrectly deleted, distorted, over-generalized, or merged with lost conditions.

#### Scenario: Update over-generalizes an existing conditional memory
- **WHEN** `M_old` contains economy preference for leisure travel
- **AND** the proposed transition changes the user to always prefer business class
- **THEN** the preservation score is below the approval threshold
- **AND** the transition is not approved for commit

#### Scenario: Supersession preserves unrelated memories
- **WHEN** a hotel preference is superseded
- **THEN** unrelated flight, car, profile, and interaction-rule memories remain preserved in `M_new`
- **AND** the preservation score is not penalized for those unrelated memories

### Requirement: Faithfulness scoring
The system SHALL score faithfulness in `[0, 1]` to measure whether new or changed memory content is supported by user evidence in the chunk or by valid previous memory.

#### Scenario: Tool result is converted into user preference
- **WHEN** a tool result returns hotels near a train station
- **AND** the candidate states that the user likes hotels near train stations without user confirmation
- **THEN** the faithfulness score is below the approval threshold
- **AND** the transition is rejected or retried rather than committed

#### Scenario: User explicitly confirms a tool-derived option
- **WHEN** a tool result suggests hotels near a train station
- **AND** the user explicitly says they prefer hotels near the train station
- **THEN** the candidate can meet the faithfulness threshold if the memory text is supported by that user statement

### Requirement: Threshold-gated verifier decision
The system SHALL approve TrustMem-inspired verifier results only when deterministic validation passes and coverage, preservation, and faithfulness scores meet configured thresholds.

#### Scenario: One dimension below threshold
- **WHEN** coverage and preservation pass but faithfulness is below threshold
- **THEN** the verifier decision is not approve
- **AND** no active memory change is committed

#### Scenario: All dimensions pass
- **WHEN** deterministic validation passes and all TrustMem-inspired scores meet thresholds
- **THEN** the commit adapter can commit the approved transition atomically
- **AND** writes audit metadata with scores and reasons

### Requirement: Verifier modes and fallback
The system SHALL support deterministic, TrustMem-gated, and TrustMem dry-run verifier modes.

#### Scenario: Deterministic mode selected
- **WHEN** `LONG_TERM_MEMORY_VERIFIER=deterministic`
- **THEN** the existing deterministic verifier behavior is used
- **AND** no LLM TrustMem verifier call is required

#### Scenario: TrustMem dry-run mode selected
- **WHEN** `LONG_TERM_MEMORY_VERIFIER=trustmem-dry-run`
- **THEN** TrustMem-inspired scores are computed and written to audit
- **AND** commit gating still follows the deterministic verifier decision

#### Scenario: TrustMem verifier fails or times out
- **WHEN** `LONG_TERM_MEMORY_VERIFIER=trustmem` and the verifier call fails, times out, or returns malformed output
- **THEN** the system records the failure in verifier audit metadata
- **AND** the commit decision falls back to the deterministic verifier

### Requirement: Structured verifier audit output
The system SHALL persist TrustMem-inspired verifier output in structured audit metadata.

#### Scenario: Audit record is written for scored transition
- **WHEN** a transition is evaluated by the TrustMem-inspired verifier
- **THEN** `verifier_result` includes verifier mode, model, prompt version, coverage score/reason, preservation score/reason, faithfulness score/reason, thresholds, final decision, and reasons

#### Scenario: Malformed score is returned
- **WHEN** verifier output contains a score outside `[0, 1]` or missing required dimensions
- **THEN** the output is treated as malformed
- **AND** the transition decision falls back to the deterministic verifier with `fallback_reason` recorded

### Requirement: Travel-specific verifier fixtures
The system SHALL include tests or fixtures for travel-memory-specific verifier failures and approvals.

#### Scenario: Conditional flight preference coverage fixture
- **WHEN** a fixture contains both work-travel business preference and leisure-travel economy preference
- **THEN** the test detects low coverage if one condition is omitted

#### Scenario: Existing memory preservation fixture
- **WHEN** a fixture attempts to replace conditional preferences with an unconditional memory
- **THEN** the test detects low preservation

#### Scenario: Tool-only faithfulness fixture
- **WHEN** a fixture candidate stores a tool result as a user preference without user confirmation
- **THEN** the test detects low faithfulness
