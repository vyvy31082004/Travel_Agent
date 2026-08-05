## ADDED Requirements

### Requirement: Atomic travel memory schema
The system SHALL store long-term memories as atomic travel memory records with typed category, domain, condition, evidence, source thread, lifecycle status, and timestamps.

#### Scenario: Memory is stored
- **WHEN** an approved memory is committed
- **THEN** the stored record includes memory text, category, domain, optional condition, evidence text, source thread id, status, and created/updated timestamps

#### Scenario: Category and domain are assigned
- **WHEN** a memory is committed
- **THEN** it is assigned a category such as flight preference, hotel preference, car preference, excursion preference, general preference, profile fact, or interaction rule
- **AND** it is assigned a domain such as flight, hotel, car, excursion, planner, or general

### Requirement: Per-user namespace isolation
The system SHALL isolate long-term memories by user id and memory family.

#### Scenario: Two users have similar preferences
- **WHEN** two users state similar travel preferences
- **THEN** each user's memories are stored and recalled only from that user's namespace

#### Scenario: Searching one memory family
- **WHEN** recall searches travel preferences
- **THEN** the system does not mix unrelated profile facts or interaction rules unless explicitly configured to search multiple families

### Requirement: Memory lifecycle preserves history
The system SHALL preserve memory lifecycle history instead of destructively overwriting prior facts.

#### Scenario: Memory is superseded
- **WHEN** a new approved memory replaces an older active memory
- **THEN** the older memory is marked superseded
- **AND** the new memory is stored as the active version with a relationship to the prior memory when supported

#### Scenario: Memory is deleted or forgotten
- **WHEN** a memory is explicitly removed by policy or future user action
- **THEN** it is excluded from recall
- **AND** the system preserves enough audit metadata to explain the change unless policy requires hard deletion

### Requirement: Semantic and filtered search
The system SHALL support bounded semantic search with deterministic filters for user id, memory family, status, category, and domain.

#### Scenario: Recall query is executed
- **WHEN** the system searches memories for a user request
- **THEN** search results are limited to the user's namespace, active status, configured memory families, and configured result limit

#### Scenario: Embeddings are unavailable
- **WHEN** the embedding/vector index is unavailable or disabled
- **THEN** the system degrades to deterministic filtered retrieval or returns empty memory context without breaking the chat flow

### Requirement: Auditability
The system SHALL record enough audit information to review why a memory was inserted, rejected, updated, or superseded.

#### Scenario: Memory transition is processed
- **WHEN** a consolidation job evaluates a memory transition
- **THEN** the system records the proposed transition, decision, rule result or verifier summary, affected memory ids, and source job id

### Requirement: Storage implementation is abstracted
The system SHALL hide the underlying memory storage implementation behind service/repository interfaces.

#### Scenario: Store implementation changes
- **WHEN** the project switches between framework-native LangGraph Store and application-managed PostgreSQL tables
- **THEN** primary graph code continues calling the same memory service interface
- **AND** graph-level behavior remains unchanged
