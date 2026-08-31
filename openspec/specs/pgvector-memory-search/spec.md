# pgvector-memory-search Specification

## Purpose
TBD - created by archiving change add-pgvector-memory-embeddings. Update Purpose after archive.
## Requirements
### Requirement: Vector search is scoped by memory ownership and lifecycle
The system SHALL perform pgvector semantic memory search only within deterministic ownership and lifecycle filters.

#### Scenario: Authenticated user recalls memories
- **WHEN** vector recall searches memories for a user request
- **THEN** the SQL query filters by the current user id, requested memory families, active status, and validity window
- **AND** it orders only the filtered candidates by vector distance

#### Scenario: Another user has semantically similar memories
- **WHEN** another user has memories close to the query embedding
- **THEN** those memories are not returned because user id filtering is mandatory

### Requirement: Vector recall is feature-flagged
The system SHALL allow pgvector recall to be enabled or disabled independently from deterministic recall and memory writes.

#### Scenario: Vector search disabled
- **WHEN** `LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED` is false
- **THEN** recall uses the existing deterministic retrieval path
- **AND** no query embedding call is made

#### Scenario: Vector search enabled
- **WHEN** `LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED` is true and embedding/index setup is healthy
- **THEN** recall embeds the latest user query and searches pgvector for active memories
- **AND** returns results through the existing recall response contract

### Requirement: Deterministic fallback on vector failure
The system SHALL fall back to deterministic retrieval when vector search cannot run and fallback is enabled.

#### Scenario: Embedding provider fails
- **WHEN** query embedding generation fails and `LONG_TERM_MEMORY_VECTOR_FALLBACK_ENABLED` is true
- **THEN** the system logs the vector error
- **AND** returns deterministic recall results instead of failing the chat flow

#### Scenario: pgvector query fails
- **WHEN** PostgreSQL vector search raises an operational error and fallback is enabled
- **THEN** the system logs the failure
- **AND** returns deterministic recall results

#### Scenario: Fallback disabled
- **WHEN** vector search fails and `LONG_TERM_MEMORY_VECTOR_FALLBACK_ENABLED` is false
- **THEN** recall returns no vector results and surfaces a controlled internal error path suitable for tests/operations
- **AND** it does not leak provider or database internals to the user response

### Requirement: Vector result threshold and limit
The system SHALL apply configured distance threshold and result limit to vector recall.

#### Scenario: Similarity below threshold
- **WHEN** a memory is outside the configured `LONG_TERM_MEMORY_VECTOR_DISTANCE_THRESHOLD`
- **THEN** that memory is excluded from recalled memory context

#### Scenario: More vector results than limit
- **WHEN** more matching memories exist than the configured recall limit
- **THEN** the system returns only the highest-ranked memories up to the limit
- **AND** records only those ids in `recalled_memory_ids`

### Requirement: Recall contract remains stable
The system SHALL keep the same memory recall output shape regardless of deterministic or vector retrieval.

#### Scenario: Vector recall returns results
- **WHEN** vector recall succeeds
- **THEN** `MemoryService.recall` still returns `memory_context`, `recalled_memory_ids`, and memory objects in the existing format
- **AND** primary graph code does not need storage-specific changes
