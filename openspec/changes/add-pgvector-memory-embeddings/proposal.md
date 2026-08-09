## Why

The long-term memory baseline can recall memories with deterministic filtering, but it still lacks semantic search over meaning-equivalent user preferences. pgvector embeddings are needed so recall can find relevant memories across phrasing differences while staying inside the existing PostgreSQL operational boundary.

## What Changes

- Add pgvector-backed semantic retrieval for long-term memories, scoped to per-user memory families and active lifecycle status.
- Add embedding generation for approved `TravelMemory` records using a configurable embedding model and fixed dimension contract.
- Add migration/setup requirements for PostgreSQL `vector` extension, embedding column/table, vector index, and safe fallback behavior when vector search is unavailable.
- Add recall ranking that combines semantic similarity with deterministic filters; deterministic text retrieval remains the fallback, not a competing source of truth.
- Add backfill/re-embedding workflow for existing memories and future embedding model/dimension changes.
- Add tests and operational checks for vector dimensions, index setup, fallback behavior, and recall quality without over-building a separate vector database service.
- Keep storage application-managed in PostgreSQL for now; do not adopt framework-native `AsyncPostgresStore` as the primary store in this change.

## Capabilities

### New Capabilities
- `pgvector-memory-search`: Semantic search over active long-term memories using PostgreSQL pgvector, with per-user/family/status filters and deterministic fallback.
- `memory-embedding-lifecycle`: Embedding generation, persistence, validation, backfill, and re-embedding policy for `TravelMemory` records.

### Modified Capabilities

## Impact

- Affects long-term memory repository/search logic under `src/repositories/long_term_memory.py` and recall service behavior under `src/services/long_term_memory.py`.
- Adds PostgreSQL migration for `vector` extension and embedding storage/indexing related to `long_term_memories`.
- Adds embedding service/adapter configuration, likely using `langchain-google-genai` embeddings with `models/gemini-embedding-001` unless verified otherwise.
- Adds environment variables for enabling vector search, embedding model, dimensions, distance threshold, backfill batch size, and fallback behavior.
- Adds tests for vector query construction, dimension mismatch protection, fallback path, and migration contract.
- Does not change MCP domain servers, `/chat` API shape, or LangMem candidate extraction semantics.
