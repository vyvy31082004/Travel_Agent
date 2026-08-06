## Context

The current system already has several memory-like mechanisms, each with a different scope:

- LangGraph checkpointing provides short-term thread state by `thread_id`.
- Conversation summaries compress long thread histories.
- Result Store persists large tool/search payloads and returns compact references.
- `user_id` and `thread_id` are already propagated through primary/domain graph config, which gives a basis for separating user identity from conversation identity.

What is missing is durable, cross-thread user memory: stable travel preferences, profile facts, and interaction rules that should help future travel planning conversations. The PDF design proposes a LangGraph/LangMem-style architecture with recall before primary-agent reasoning and consolidation after final answers. This design keeps that direction but scopes the first implementation to a practical baseline: enough safety, auditability, and extensibility without building a full memory operations platform.

## Goals / Non-Goals

**Goals:**

- Persist durable per-user travel memories across threads.
- Recall relevant active memories before the primary agent routes or answers.
- Store atomic memories rather than large free-form profiles.
- Separate transient tool/API results from durable user preferences.
- Consolidate memories after final answers through an outbox/worker path rather than blocking every chat turn.
- Verify memory transitions before committing writes.
- Maintain audit records for proposed, approved, rejected, and superseded memory changes.
- Keep read/write behavior feature-flagged so recall can be enabled before writes.
- Fit the current FastAPI + LangGraph + PostgreSQL architecture.

**Non-Goals:**

- Build a full UI memory management console in the first implementation.
- Add organization/multi-tenant namespaces beyond per-user isolation.
- Store every tool result as a memory.
- Write memory on every MCP tool call.
- Require user-visible real-time memory updates in the same request.
- Replace LangGraph checkpointing, summaries, or Result Store.
- Implement complex RL-style memory ranking beyond simple semantic search plus deterministic filters.

## Decisions

### Use per-user namespaces, not thread namespaces

Long-term memory must follow a user across conversations, so namespaces will be based on `user_id`, not `thread_id`.

Initial namespaces:

```python
("users", user_id, "travel_preferences")
("users", user_id, "profile_facts")
("users", user_id, "interaction_rules")
```

Alternatives considered:
- **Include `thread_id` in namespace**: simpler for ownership, but prevents cross-thread reuse.
- **Single flat namespace per user**: simpler, but harder to filter lifecycle and recall by memory family.
- **Org/user namespace**: useful later, but not needed until the app has organization accounts.

### Use atomic `TravelMemory` records

Each memory will be a small durable statement with category, domain, condition, evidence, source thread, status, and validity metadata. This avoids overwriting a user's full profile and preserves context such as “business travel” versus “family vacation”.

Confidence or verifier score is metadata for ranking/audit, not user-facing truth. Recall should expose memory text, condition, and enough provenance for traceability, not raw scoring details.

### Add recall before primary-agent reasoning

The primary graph should perform memory recall before `primary_assistant`. Recalled active memories become bounded context that can influence routing and response generation. Domain subgraphs should not independently query long-term memory in the first implementation; they receive user memory through primary context and existing state/config.

Initial flow:

```text
START -> memory_recall -> primary_assistant -> existing delegation/join flow
```

### Consolidate after final answers via outbox

Memory writes should not block the main chat response. After final answer, the system should enqueue a `memory_jobs` row with idempotency key and turn metadata. A worker processes the job, extracts candidate memory transitions, verifies them, and commits approved changes.

A synchronous finalize node may be allowed only for local prototypes/tests behind a feature flag, but the production-oriented path is outbox/worker.

### Use manager + adapter + verifier, not direct hot-path writes

The PDF compares `create_memory_store_manager`, `create_memory_manager + adapter`, and hot-path `manage_memory_tool`. This change adopts a manager + adapter + verifier approach:

1. Candidate extraction proposes desired memory state or transitions.
2. Adapter computes dry-run inserts/updates/deletes against existing memory.
3. Deterministic rules reject obvious unsafe/noisy writes.
4. Optional frozen-LLM verifier reviews ambiguous transitions.
5. Only approved transitions are committed.

This is more work than direct writes, but necessary to avoid polluting long-term memory with temporary tool results or hallucinated facts.

### Store audit and lifecycle metadata in PostgreSQL

PostgreSQL remains the operational source of truth. The first implementation will use application-managed PostgreSQL tables behind a repository/service interface rather than adopting framework-native `AsyncPostgresStore` immediately.

Rationale:

- The project already uses Alembic, SQLAlchemy model metadata, psycopg pools, and a custom `ResultStoreRepository` pattern.
- `langgraph-checkpoint-postgres` is already installed, but LangGraph Store/LangMem package versions are not pinned in the current requirements.
- Application-managed tables make the first implementation deterministic, testable, and easier to migrate in this repo without adding a second storage abstraction prematurely.
- The service boundary keeps a future move to `AsyncPostgresStore` or pgvector-backed semantic search possible.

The first implementation will therefore provide deterministic filtered retrieval and optional lightweight text matching. Embedding/vector search can be added later behind the same repository interface once package versions and database extension availability are confirmed.

The important boundary is the API contract: `MemoryService.recall(...)` and `MemoryService.enqueue_final_turn(...)` hide the storage implementation from primary graph code.

### Feature flags

Use separate flags:

- `LONG_TERM_MEMORY_RECALL_ENABLED`
- `LONG_TERM_MEMORY_WRITE_ENABLED`
- `LONG_TERM_MEMORY_SYNC_FINALIZE`

This allows rollout order: schema/tests → recall read path → write pipeline → verifier strictness.

## Risks / Trade-offs

- **Risk: Memory pollution from transient API/tool results** → Mitigation: require user evidence for durable preferences; reject tool-only results unless user explicitly asks to remember them.
- **Risk: Latency increase** → Mitigation: recall is bounded and write consolidation happens asynchronously through outbox.
- **Risk: Conflicting memories** → Mitigation: atomic memories with conditions and superseded lifecycle; verifier can reject ambiguous updates.
- **Risk: Over-engineering** → Mitigation: defer org namespaces, UI management console, hot-path writes, and complex ranking until there is usage data.
- **Risk: Privacy/user trust** → Mitigation: store evidence/source metadata, make memory writes auditable, and support future delete/forget operations.
- **Risk: Dependency mismatch** → Mitigation: isolate LangMem/LangGraph Store behind adapters and write tests against service interfaces.

## Migration Plan

1. Add feature flags and memory config settings with defaults disabled.
2. Add memory schema types and namespace helpers.
3. Add PostgreSQL migration for memory jobs/audit and storage metadata, or initialize LangGraph Store tables if using framework-native store.
4. Implement `MemoryService.recall` behind a no-op fallback.
5. Add `memory_recall` node before `primary_assistant` and extend state with `memory_context` / `recalled_memory_ids`.
6. Add outbox enqueue after final answer with idempotency key.
7. Implement worker/processor for candidate extraction, dry-run transition, deterministic validation, optional verifier, commit, and audit.
8. Enable recall first in development; enable write consolidation only after tests pass.
9. Rollback by disabling feature flags; data tables can remain inert.

## Verified Dependency Baseline

Current installed versions checked during implementation planning:

- `langgraph==1.2.8`
- `langgraph-checkpoint-postgres==3.1.1`
- `langchain-google-genai==4.2.7`
- `psycopg==3.3.4`
- `sqlalchemy==2.0.51`
- `alembic==1.18.5`
- `pydantic==2.13.4`
- `langmem` is not currently installed.

Because `langmem` is not present, the first implementation will not hard-require it. Candidate extraction will be isolated behind an adapter so a deterministic or LLM-based extractor can ship first, and LangMem can be added later after package/version validation.

## Open Questions

- Which embedding model and vector dimension will be used in the deployed environment if semantic vector search is enabled later?
- Should users get an explicit “forget this” UI in this change or a follow-up change?
- What retention policy applies to rejected memory audit records?
