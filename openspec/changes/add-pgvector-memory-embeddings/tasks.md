## 1. Environment and Dependency Verification

- [ ] 1.1 Verify target PostgreSQL can enable `vector` extension, and document whether extension setup is app-managed or provisioned out-of-band.
- [ ] 1.2 Verify installed package/API support for `GoogleGenerativeAIEmbeddings`, vector SQL usage, and any required Python `pgvector` helper package if raw SQL is not sufficient.
- [ ] 1.3 Generate a sample embedding with the configured model and confirm actual vector length matches the planned `LONG_TERM_MEMORY_VECTOR_DIMS`.
- [ ] 1.4 Add settings for vector search enabled, fallback enabled, embedding model, vector dimensions, distance threshold, and backfill batch size.

## 2. Database Migration and Indexing

- [ ] 2.1 Add Alembic migration to create/verify PostgreSQL `vector` extension where supported.
- [ ] 2.2 Add `long_term_memory_embeddings` table linked to `long_term_memories` with embedding vector, model, dimensions, content hash, current flag, and timestamps.
- [ ] 2.3 Add uniqueness constraints to prevent duplicate current embeddings for the same memory/model/content hash.
- [ ] 2.4 Add pgvector index for cosine search, preferring HNSW when available and documenting/handling fallback index strategy.
- [ ] 2.5 Add migration downgrade that removes indexes/table without touching source `long_term_memories` records.

## 3. Embedding Service

- [ ] 3.1 Add embedding adapter/service that wraps the configured embedding model and returns a list of floats.
- [ ] 3.2 Validate embedding dimension on every memory/query embedding operation before database write/search.
- [ ] 3.3 Add content hashing helper for stable memory embedding identity based on memory text, condition, category, domain, and model.
- [ ] 3.4 Ensure embedding failures are structured and do not corrupt memory rows or audit records.

## 4. Repository and Recall Integration

- [ ] 4.1 Add repository methods to upsert current memory embeddings and mark outdated embeddings non-current.
- [ ] 4.2 Add repository method to scan active memories missing current embeddings for backfill.
- [ ] 4.3 Add repository method for semantic vector search with user id, family, active status, validity window, limit, and distance threshold filters.
- [ ] 4.4 Update `MemoryService.recall` to use vector search when enabled and healthy, while preserving the existing recall response contract.
- [ ] 4.5 Implement deterministic fallback path when vector search, embedding generation, or pgvector query fails and fallback is enabled.

## 5. Embedding Generation Workflow

- [ ] 5.1 Trigger or enqueue embedding generation after approved memory commits for inserted or updated active memories.
- [ ] 5.2 Ensure rejected/no-op/tool-only memory candidates never create embeddings.
- [ ] 5.3 Add a resumable backfill command or worker mode that embeds active memories missing current embeddings in configured batch sizes.
- [ ] 5.4 Add re-embedding behavior for model/content hash changes without silently mixing incompatible embedding models or dimensions.

## 6. Tests

- [ ] 6.1 Add unit tests for embedding dimension validation, content hashing, and malformed provider outputs.
- [ ] 6.2 Add repository/query construction tests verifying user/family/status filters are mandatory for vector search.
- [ ] 6.3 Add recall service tests for vector-enabled success, vector-disabled deterministic path, and vector failure fallback path.
- [ ] 6.4 Add workflow tests verifying approved memories get embeddings while rejected/no-op candidates do not.
- [ ] 6.5 Add PostgreSQL integration test gated by `DATABASE_URL` that verifies vector extension/table/index migration and a basic semantic search query when pgvector is available.

## 7. Documentation and Verification

- [ ] 7.1 Document vector-related environment variables, rollout order, backfill command, fallback behavior, and re-embedding policy.
- [ ] 7.2 Document operational checks for pgvector extension availability, index existence, embedding dimensions, and fallback status.
- [ ] 7.3 Run `python -m py_compile` or project equivalent on changed Python modules.
- [ ] 7.4 Run targeted pgvector/embedding tests and existing long-term memory tests.
- [ ] 7.5 Run OpenSpec validation for `add-pgvector-memory-embeddings` and resolve all issues.
