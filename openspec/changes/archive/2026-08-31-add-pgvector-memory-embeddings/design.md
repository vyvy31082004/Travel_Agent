## Context

The `add-long-term-memory` change introduced application-managed PostgreSQL tables, deterministic recall fallback, memory jobs, audit, and LangMem candidate extraction. It intentionally deferred vector search: memory recall can work, but it does not yet find memories that are semantically relevant when the user's wording differs from the stored memory text.

The PDF design recommends PostgreSQL + pgvector with `gemini-embedding-001` and a 3072-dimensional embedding as the likely baseline. This change adds that missing semantic search layer while keeping the existing architecture: PostgreSQL remains the operational source of truth, memory writes still go through the commit adapter, and deterministic retrieval remains the fallback.

## Goals / Non-Goals

**Goals:**

- Add pgvector-backed semantic search for active per-user long-term memories.
- Generate and persist embeddings for approved `TravelMemory` records.
- Keep vector search scoped by user id, memory family, lifecycle status, and result limit.
- Validate embedding dimensions and model identity before writes/search.
- Provide deterministic fallback when pgvector, embeddings, or the embedding provider is unavailable.
- Support backfill/re-embedding for existing memories and model changes.
- Keep integration small enough for the current PostgreSQL/FastAPI app; avoid introducing a separate vector database service.

**Non-Goals:**

- Replace application-managed `long_term_memories` as the memory source of truth.
- Adopt framework-native `AsyncPostgresStore` as the primary store in this change.
- Implement multi-vector per memory, cross-user global search, or advanced learning-to-rank.
- Require vector search for `/chat` to work.
- Automatically change embedding dimensions on an existing index without an explicit re-embedding/migration plan.

## Decisions

### Use pgvector in the same PostgreSQL cluster

Use the existing PostgreSQL cluster and add pgvector support for memory embeddings. This keeps operational complexity lower than adding Qdrant or another vector service, and matches the PDF recommendation that checkpoint, application tables, audit, outbox, and vector index can live in PostgreSQL while remaining separated by table responsibility.

Alternative considered: use existing `qdrant-client` dependency. It is powerful, but would add another runtime service and data consistency problem before the application needs it.

### Store embeddings in a separate application table

Create a `long_term_memory_embeddings` table linked to `long_term_memories` rather than adding many embedding-specific columns directly to the memory table.

Planned shape:

```sql
long_term_memory_embeddings (
  embedding_id uuid primary key,
  memory_id uuid not null references long_term_memories(memory_id) on delete cascade,
  embedding vector(<dims>) not null,
  embedding_model text not null,
  embedding_dims integer not null,
  content_hash text not null,
  is_current boolean not null default true,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  unique(memory_id, embedding_model, content_hash)
)
```

Rationale:

- Memory lifecycle remains independent from embedding lifecycle.
- Re-embedding can create/replace embedding rows without rewriting memory facts.
- Audit/outbox logic remains unchanged.
- A future model migration can be planned explicitly.

### Use one configured embedding model/dimension at a time

Default planned model:

```text
models/gemini-embedding-001
```

Default planned dimensions:

```text
3072
```

The implementation must verify the actual returned vector length in the local environment before inserting. If returned length does not match configured `LONG_TERM_MEMORY_VECTOR_DIMS`, the system must fail the embedding write/search safely and fall back to deterministic retrieval.

Changing embedding model or dimensions requires a deliberate re-embedding flow. Do not silently reuse an old vector index with a different model/dimension.

### Keep semantic search behind repository/service interfaces

`MemoryService.recall(...)` should not know whether results came from vector search or deterministic text fallback. The repository should expose a semantic search method that accepts user/family/status filters, query embedding, limit, and threshold.

Recall order:

1. If vector search is disabled, use deterministic retrieval.
2. If vector search is enabled, embed the query.
3. Search pgvector with deterministic filters: user id, family, active status, validity window.
4. Apply configured similarity/distance threshold.
5. Return bounded memories and ids in the same `RecallResult` contract.
6. On embedding/vector errors, log and fall back to deterministic retrieval if fallback is enabled.

### Generate memory embeddings after approved commits

Embeddings should be created after a memory is approved and committed, not before verifier/audit. The worker/commit path can enqueue or perform embedding generation for newly inserted/updated memories. Tool-only or rejected candidate memories never get embeddings.

### Backfill existing memories in batches

Add a backfill command/worker mode that finds active memories without current embeddings, generates embeddings in batches, and records progress. It must be idempotent and safe to resume.

### Use feature flags and explicit fallback

Add independent settings:

- `LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED`
- `LONG_TERM_MEMORY_VECTOR_FALLBACK_ENABLED`
- `LONG_TERM_MEMORY_EMBEDDING_MODEL`
- `LONG_TERM_MEMORY_VECTOR_DIMS`
- `LONG_TERM_MEMORY_VECTOR_DISTANCE_THRESHOLD`
- `LONG_TERM_MEMORY_EMBEDDING_BACKFILL_BATCH_SIZE`

This lets teams enable embedding writes/backfill before enabling vector recall.

## Risks / Trade-offs

- **Risk: pgvector extension unavailable** → Mitigation: migration/setup detects failure; app falls back to deterministic retrieval when configured.
- **Risk: embedding dimension mismatch** → Mitigation: verify returned vector length before write/search; block embedding usage and log clear error.
- **Risk: embedding provider latency/cost** → Mitigation: embed memories in worker/backfill, keep query embedding bounded to recall path, and use feature flags.
- **Risk: stale embeddings after memory updates** → Mitigation: content hash and `is_current` lifecycle determine whether embedding needs refresh.
- **Risk: vector results ignore ownership/lifecycle** → Mitigation: SQL query must filter by user id, family, status, and validity before/alongside vector ordering.
- **Risk: over-engineering** → Mitigation: one embedding table, one configured model/dimension, no separate vector DB, no advanced ranking in this change.

## Migration Plan

1. Verify PostgreSQL supports `CREATE EXTENSION vector` in the target environment.
2. Add migration for pgvector extension and `long_term_memory_embeddings` table.
3. Add vector index for cosine search, preferring HNSW if available; otherwise document fallback/index alternative.
4. Add embedding service adapter with dimension verification.
5. Add repository methods for embedding upsert, missing-embedding scan, and semantic memory search.
6. Add backfill command/worker mode for existing memories.
7. Enable embedding generation in development with vector recall still disabled.
8. Run backfill and verify index/search behavior.
9. Enable vector recall with deterministic fallback on.
10. Roll back by disabling vector search; deterministic recall remains available and embedding rows can stay inert.

## Open Questions

- Does the deployed PostgreSQL image allow `CREATE EXTENSION vector`, or must the extension be provisioned out-of-band?
- Which pgvector index type/version is available in the target environment: HNSW or IVFFLAT?
- Does `models/gemini-embedding-001` return 3072 dimensions in this exact environment, or should an output dimension override be configured?
- What distance threshold is acceptable after testing real travel memory examples?
