## Why

The current Travel Agent has short-term thread memory, summaries, and Result Store references, but it does not persist durable user preferences across conversations. Long-term memory is needed so the primary travel agent can remember stable travel preferences, profile facts, and interaction rules across threads while avoiding unsafe or noisy writes from transient tool results.

## What Changes

- Add a scoped long-term memory layer for persisted per-user travel preferences, profile facts, and interaction rules.
- Add memory recall before primary-agent reasoning so relevant active memories can influence routing and answers across threads.
- Add memory consolidation after final answers using a controlled background/outbox flow instead of writing memories directly on the hot path.
- Add an atomic `TravelMemory` schema with category, domain, condition, evidence, source thread, lifecycle status, and timestamps.
- Add storage/audit structures for memory jobs, proposed transitions, verifier decisions, and active/superseded memory lifecycle.
- Add guardrails so tool/API search results are not stored as preferences unless supported by user evidence.
- Add tests and observability hooks to validate recall, consolidation, idempotency, verification, and auditability.
- Keep the design sufficiently complete for production evolution, but avoid over-engineering: no multi-tenant org layer, no real-time memory writes for every tool call, and no UI-heavy memory management console in the first implementation.

## Capabilities

### New Capabilities
- `long-term-memory-recall`: Per-user memory retrieval that injects relevant active memories into the primary agent before routing and response generation.
- `long-term-memory-consolidation`: Post-response outbox/worker pipeline that extracts durable memories from completed turns, verifies transitions, and commits approved memories.
- `travel-memory-store`: Storage model, namespace strategy, lifecycle, audit, and semantic search for atomic travel memories.

### Modified Capabilities

## Impact

- Affected primary graph construction in `src/agents/primary/agent.py` to add recall/finalize memory nodes without disrupting current delegation flow.
- New memory schema/service/repository modules under `src/memory/` or `src/services/` for recall, consolidation, verification, and store access.
- New PostgreSQL migrations for memory jobs/audit metadata and potentially pgvector/LangGraph Store setup depending on final implementation approach.
- Dependency impact may include `langmem`, `langgraph-store-postgres`/store support, and embedding configuration if not already available.
- Runtime impact includes an optional background worker for memory consolidation and feature flags to enable recall/write independently.
- No changes are expected to MCP domain servers; domain agents should receive memory only through primary-agent context and existing user/thread config.
