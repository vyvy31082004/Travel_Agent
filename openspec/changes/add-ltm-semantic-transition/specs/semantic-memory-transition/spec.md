## ADDED Requirements

### Requirement: Hard validation precedes transition judges
The system SHALL run `validate_memory_candidate` before SQL pooling or LLM judges. Failed candidates SHALL produce `REJECT` with audit and SHALL NOT call scope/relation judges or commit writes.

#### Scenario: Sensitive candidate is rejected
- **WHEN** a candidate evidence contains sensitive credential or payment markers
- **THEN** the transition action is `reject`
- **AND** no comparison-pool query or LLM judge is required for that candidate

### Requirement: SQL comparison pool is complete for category and domain
The system SHALL load the transition comparison set with SQL filtered by `user_id`, `status=active`, matching `category` and `domain`, and validity window. Memories without embeddings SHALL remain in the pool.

#### Scenario: Active memory without embedding stays comparable
- **WHEN** an active same-category/domain memory has no current embedding row
- **THEN** it still appears in the comparison pool
- **AND** ranking places null-distance rows after embedded rows

### Requirement: pgvector ranks but does not decide INSERT
The system SHALL use LEFT JOIN distance only to order memories for LLM batches. Distance thresholds SHALL NOT drop rows from the comparison pool or alone decide `INSERT`.

#### Scenario: Large pool is batched with positive early-exit only
- **WHEN** the comparison pool exceeds the configured batch size
- **THEN** the worker evaluates Top-N batches in rank order
- **AND** may early-exit on high-confidence `NOOP` or `SUPERSEDE` with a valid `existing_memory_id`
- **AND** MAY choose `INSERT` only after scanning the full pool without a positive decision

### Requirement: Scope and relation judges drive semantic actions
The system SHALL partition each batch with a scope judge (`same|different|uncertain`) then run relation judge on `same` survivors without exact-dup plus uncertain/low-confidence items. Policy mapping SHALL prefer equivalent→`NOOP` over supersedes, require a single high-confidence supersede target for `SUPERSEDE`, and fall back to `INSERT` with `ambiguous_target` when multiple supersede targets compete.

#### Scenario: Different conditions are not superseded
- **WHEN** candidate prefers business for work travel and an existing memory prefers economy for family travel
- **THEN** scope is `different` at high confidence
- **AND** the existing memory is dropped from relation input
- **AND** the candidate may `INSERT` without superseding the family preference

#### Scenario: Equivalent wins over concurrent supersedes
- **WHEN** relation judgments include one high-confidence equivalent and one high-confidence supersedes
- **THEN** the selected action is `NOOP` on the best-ranked equivalent id
- **AND** audit records `existing_conflict_detected` for the supersede target
- **AND** the transition does not both noop and supersede

### Requirement: TrustMem remains the write gate
The system SHALL skip TrustMem mutation gating for `NOOP` (audit only). For `INSERT` and `SUPERSEDE`, TrustMem SHALL approve before commit. On TrustMem reject, the proposed action remains in audit while `decision=reject` and no store mutation occurs.

#### Scenario: Approved supersede commits atomically
- **WHEN** TrustMem approves a `SUPERSEDE` with a valid `existing_memory_id`
- **THEN** one transaction marks the old memory superseded and inserts the new active memory with `supersedes_memory_id` set
