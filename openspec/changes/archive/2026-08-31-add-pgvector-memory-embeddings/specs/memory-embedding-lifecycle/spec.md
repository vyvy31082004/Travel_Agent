## ADDED Requirements

### Requirement: Approved memories receive embeddings
The system SHALL generate embeddings only for approved and committed long-term memories.

#### Scenario: Memory insert approved
- **WHEN** the commit adapter inserts an approved active memory
- **THEN** the system creates or enqueues creation of an embedding for that memory
- **AND** stores embedding metadata including model, dimensions, content hash, and current status

#### Scenario: Candidate rejected
- **WHEN** a memory candidate is rejected by validation or verifier
- **THEN** no embedding is generated for that rejected candidate

### Requirement: Embedding dimensions are validated
The system SHALL verify embedding vector dimensions before writing or querying pgvector.

#### Scenario: Embedding model returns configured dimensions
- **WHEN** the embedding provider returns a vector whose length equals `LONG_TERM_MEMORY_VECTOR_DIMS`
- **THEN** the vector can be written to pgvector or used for search

#### Scenario: Embedding model returns wrong dimensions
- **WHEN** the provider returns a vector whose length differs from `LONG_TERM_MEMORY_VECTOR_DIMS`
- **THEN** the system rejects that embedding operation
- **AND** records a clear operational error without corrupting existing embeddings

### Requirement: Embedding storage tracks model and content hash
The system SHALL track embedding model, embedding dimensions, content hash, and current status for each memory embedding.

#### Scenario: Memory text unchanged
- **WHEN** a memory already has a current embedding with the same model, dimensions, and content hash
- **THEN** the embedding generation step is idempotent and does not create a duplicate current embedding

#### Scenario: Memory content changes
- **WHEN** a memory's embedded content hash changes
- **THEN** the previous embedding is marked not current or superseded
- **AND** a new current embedding is generated for the new content

### Requirement: Backfill existing memories
The system SHALL provide a resumable backfill workflow for active memories missing current embeddings.

#### Scenario: Backfill runs with active memories missing embeddings
- **WHEN** the backfill command runs
- **THEN** it selects active memories without current embeddings for the configured model/dimensions
- **AND** processes them in batches no larger than `LONG_TERM_MEMORY_EMBEDDING_BACKFILL_BATCH_SIZE`

#### Scenario: Backfill is interrupted
- **WHEN** backfill stops before all memories are embedded
- **THEN** rerunning backfill resumes from remaining missing/outdated embeddings without duplicating current embeddings

### Requirement: Model or dimension changes require explicit re-embedding
The system SHALL not silently reuse embeddings from a different model or dimension.

#### Scenario: Configured embedding model changes
- **WHEN** `LONG_TERM_MEMORY_EMBEDDING_MODEL` changes
- **THEN** existing embeddings from the old model are not considered current for the new model
- **AND** re-embedding/backfill is required before vector recall uses the new model

#### Scenario: Configured dimensions change
- **WHEN** `LONG_TERM_MEMORY_VECTOR_DIMS` changes
- **THEN** implementation requires an explicit migration/re-index plan before enabling vector recall
- **AND** the system must not write vectors into an incompatible pgvector column

### Requirement: pgvector setup is verifiable
The system SHALL include checks/tests to verify pgvector extension, embedding table, vector index, and query behavior.

#### Scenario: Migration verification runs
- **WHEN** database migration verification is executed against PostgreSQL
- **THEN** it confirms the `vector` extension exists, embedding table exists, and vector index can be used or inspected

#### Scenario: pgvector unavailable
- **WHEN** the target database cannot enable pgvector
- **THEN** the system leaves vector recall disabled
- **AND** deterministic recall remains operational
