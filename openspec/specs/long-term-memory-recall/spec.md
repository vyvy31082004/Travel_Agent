# long-term-memory-recall Specification

## Purpose
TBD - created by archiving change add-long-term-memory. Update Purpose after archive.
## Requirements
### Requirement: Per-user memory recall before primary reasoning
The system SHALL retrieve relevant active long-term memories for the current user before the primary agent routes or answers a request.

#### Scenario: Authenticated user starts a new thread
- **WHEN** an authenticated user sends a message in a new thread
- **THEN** the system searches that user's active long-term memories using the latest user message as the recall query
- **AND** the primary agent receives a bounded memory context before deciding whether to answer or delegate

#### Scenario: No user identity is available
- **WHEN** a request has no reliable user id
- **THEN** the system skips long-term memory recall
- **AND** the primary agent continues with the existing short-term/checkpoint behavior

### Requirement: Recall uses active memories only
The system SHALL exclude superseded, revoked, expired, or inactive memories from primary-agent recall.

#### Scenario: Superseded memory exists
- **WHEN** a memory search returns both active and superseded memories
- **THEN** only active memories are included in `memory_context`
- **AND** superseded memory ids are not included in `recalled_memory_ids`

### Requirement: Recall context is bounded and traceable
The system SHALL keep recalled memory context small, structured, and traceable.

#### Scenario: Many memories match a query
- **WHEN** more memories match than the configured recall limit
- **THEN** the system includes only the highest-ranked active memories up to the configured limit
- **AND** records the included memory ids in state as `recalled_memory_ids`

#### Scenario: Memory is injected into prompt context
- **WHEN** memories are injected for primary-agent use
- **THEN** each memory line includes the durable memory text and condition when present
- **AND** the injected context does not expose internal verifier scores as facts

### Requirement: Recall is feature-flagged
The system SHALL allow long-term memory recall to be enabled or disabled without code changes.

#### Scenario: Recall feature flag is disabled
- **WHEN** `LONG_TERM_MEMORY_RECALL_ENABLED` is false
- **THEN** the memory recall node returns empty memory context
- **AND** the rest of the graph behaves as it did before this change

### Requirement: Recall does not replace thread memory
The system SHALL preserve existing LangGraph checkpoint, summary, and Result Store behavior while adding long-term memory recall.

#### Scenario: Thread has short-term summary and recalled memories
- **WHEN** both conversation summary and recalled long-term memories are available
- **THEN** the primary agent receives both contexts with clear separation between thread summary and cross-thread user memory
