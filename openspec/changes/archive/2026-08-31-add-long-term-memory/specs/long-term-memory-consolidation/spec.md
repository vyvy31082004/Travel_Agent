## ADDED Requirements

### Requirement: Final-turn memory job enqueue
The system SHALL enqueue a memory consolidation job after a completed final answer instead of performing durable memory writes directly in the chat hot path.

#### Scenario: Final answer is produced
- **WHEN** the primary graph produces a final user-facing answer
- **THEN** the system creates a `memory_jobs` entry containing user id, thread id, final message id or checkpoint id, and enough bounded turn context for consolidation
- **AND** the chat response is not blocked on candidate extraction or verification

#### Scenario: Duplicate finalize event occurs
- **WHEN** the same final turn is processed more than once
- **THEN** the system uses an idempotency key based on user id, thread id, and final message/checkpoint identity
- **AND** it does not create duplicate memory jobs for the same turn

### Requirement: Candidate extraction uses durable evidence only
The system SHALL extract candidate memories only from durable user evidence and relevant assistant context.

#### Scenario: User states a stable preference
- **WHEN** a user says a reusable preference such as preferring boutique hotels or direct flights
- **THEN** the consolidation pipeline may propose a corresponding atomic memory with evidence text and source thread id

#### Scenario: Tool result contains temporary facts
- **WHEN** a hotel, flight, car, weather, or tour tool returns temporary search results
- **THEN** the consolidation pipeline does not store those results as user preferences unless the user explicitly asks to remember them or confirms they represent a preference

### Requirement: LangMem candidate extraction adapter
The system SHALL support `langmem==0.0.30` as a worker-side candidate extraction adapter behind the existing extraction interface.

#### Scenario: LangMem adapter is enabled
- **WHEN** the memory worker processes a completed final-turn job and LangMem extraction is configured
- **THEN** the worker uses LangMem to propose structured candidate memories from bounded conversation context
- **AND** the candidates are normalized into the system `TravelMemory` schema before validation

#### Scenario: LangMem is unavailable or disabled
- **WHEN** LangMem is not available, fails initialization, or the LangMem extractor flag is disabled
- **THEN** the worker falls back to the deterministic extractor or records a safe skipped/failed job according to worker retry rules
- **AND** the chat hot path continues unaffected

#### Scenario: LangMem proposes memory changes
- **WHEN** LangMem proposes inserts, updates, deletions, or no-op memory changes
- **THEN** the system treats them only as proposed candidates
- **AND** deterministic validation, dry-run transition calculation, verifier/audit, and repository commit adapter remain mandatory before active memory changes

#### Scenario: LangMem must not write directly
- **WHEN** LangMem extraction runs
- **THEN** it must not write directly to `long_term_memories` or any framework store
- **AND** it must not bypass audit records or feature flags

### Requirement: Dry-run transition before commit
The system SHALL compute proposed memory inserts, updates, supersessions, or no-ops before committing changes.

#### Scenario: Candidate duplicates existing memory
- **WHEN** a proposed memory is semantically equivalent to an existing active memory
- **THEN** the dry-run transition marks it as no-op or update instead of inserting an unbounded duplicate

#### Scenario: Candidate conflicts with existing memory
- **WHEN** a proposed memory conflicts with an existing active memory
- **THEN** the transition records the conflict and requires verification before superseding existing memory

### Requirement: Verification gate for memory writes
The system SHALL commit only approved memory transitions.

#### Scenario: Deterministic rules reject a transition
- **WHEN** a proposed transition lacks user evidence, is tool-only, contains unsafe sensitive data, or is too ambiguous
- **THEN** the system rejects the transition and writes an audit record without changing active memory

#### Scenario: Verifier approves a transition
- **WHEN** deterministic rules and the verifier approve a proposed transition
- **THEN** the system commits the memory changes atomically
- **AND** writes an audit record containing decision, reasons, and affected memory ids

### Requirement: Consolidation is feature-flagged
The system SHALL allow memory write consolidation to be disabled independently from recall.

#### Scenario: Write feature flag is disabled
- **WHEN** `LONG_TERM_MEMORY_WRITE_ENABLED` is false
- **THEN** the system does not enqueue or process memory write jobs
- **AND** memory recall can still operate on existing memories if enabled

### Requirement: Worker retry and failure state
The system SHALL track job attempts and terminal states for consolidation failures.

#### Scenario: Worker processing fails transiently
- **WHEN** extraction, verification, or commit fails with a retryable error
- **THEN** the job records the attempt and remains available for retry until the configured attempt limit

#### Scenario: Worker exhausts retry attempts
- **WHEN** a job exceeds the configured retry limit
- **THEN** the job is marked failed with an error summary suitable for operations review
