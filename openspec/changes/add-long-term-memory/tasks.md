## 1. Baseline and Dependency Decisions

- [x] 1.1 Review current primary graph flow, state schema, checkpoint/store setup, and Result Store integration points.
- [x] 1.2 Decide and document the first implementation storage adapter: framework-native LangGraph Store or application-managed PostgreSQL tables behind the same service interface.
- [x] 1.3 Pin or verify required package versions for LangMem, LangGraph Store/Postgres, embeddings, and PostgreSQL vector support.
- [x] 1.4 Add feature flags and settings for recall, write consolidation, sync finalize mode, recall limit, worker retry limit, and embedding/store configuration.

## 2. Memory Schema and Storage

- [x] 2.1 Add `TravelMemory` schema with memory text, category, domain, condition, evidence text, source thread id, status, validity metadata, and timestamps.
- [x] 2.2 Add namespace helper functions for per-user memory families: travel preferences, profile facts, and interaction rules.
- [x] 2.3 Add repository/service interfaces that hide storage implementation details from graph code.
- [x] 2.4 Add PostgreSQL migration for memory jobs, memory audit records, and any application-managed memory tables/indexes selected in task 1.2.
- [x] 2.5 Add storage setup or migration verification for semantic search/index support, with deterministic filtered retrieval fallback when embeddings are unavailable.

## 3. Recall Path

- [x] 3.1 Implement `MemoryService.recall` with feature-flag handling, no-user fallback, namespace filtering, active-status filtering, and bounded result limits.
- [x] 3.2 Extend primary graph state with `memory_context` and `recalled_memory_ids` without breaking existing state consumers.
- [x] 3.3 Add `memory_recall` node before `primary_assistant` in the primary graph.
- [x] 3.4 Update the primary assistant prompt/context assembly so recalled memories are clearly separated from thread summary and tool results.
- [x] 3.5 Ensure domain subgraphs continue to use existing config/state and do not independently query long-term memory in this change.

## 4. Consolidation Outbox

- [x] 4.1 Implement idempotency key generation from user id, thread id, and final message/checkpoint identity.
- [x] 4.2 Add `MemoryService.enqueue_final_turn` that creates one memory job per completed final answer when write consolidation is enabled.
- [x] 4.3 Add graph finalize integration after final answers that enqueues the memory job without blocking response generation.
- [x] 4.4 Add sync finalize mode only for local tests/prototypes, guarded by configuration and disabled by default.
- [x] 4.5 Ensure summarize/end routing still behaves correctly when memory enqueue is skipped, disabled, or fails non-fatally.

## 5. Candidate Extraction and Verification

- [x] 5.1 Implement candidate extraction using LangMem or an equivalent adapter that emits atomic `TravelMemory` candidates from bounded turn context.
- [x] 5.2 Add deterministic validation rules that reject tool-only facts, missing evidence, ambiguous claims, unsafe sensitive data, and oversized memories.
- [x] 5.3 Implement dry-run transition calculation for inserts, updates, supersessions, rejects, and no-ops against existing active memories.
- [x] 5.4 Implement optional verifier evaluation for non-trivial transitions using a stable prompt/model configuration.
- [x] 5.5 Implement commit adapter that applies approved transitions atomically and writes audit records for approved, rejected, retried, and failed decisions.

## 6. Worker and Operations

- [x] 6.1 Add a memory worker entrypoint or background runner that processes pending memory jobs with retry limits and terminal failure states.
- [x] 6.2 Add structured logging for recall count, recalled ids, job id, transition decision, verifier decision, and failure summaries.
- [x] 6.3 Add lightweight debug/admin access for developers to inspect memory jobs and audit records without building a full UI console.
- [x] 6.4 Add safe rollback behavior: disabling feature flags stops recall and/or write processing without requiring schema rollback.

## 7. Testing

- [x] 7.1 Add unit tests for `TravelMemory` validation, namespace helpers, and active/superseded lifecycle behavior.
- [x] 7.2 Add unit tests for recall filtering by user id, memory family, active status, and recall limit.
- [x] 7.3 Add primary graph tests verifying recalled memories are injected before primary reasoning and existing `/chat` behavior remains compatible.
- [x] 7.4 Add consolidation tests for idempotent job enqueue, duplicate finalization, and disabled write flag behavior.
- [x] 7.5 Add candidate extraction/validation tests for stable preferences, tool-only temporary results, ambiguous evidence, and conflicting memories.
- [x] 7.6 Add worker tests for approve, reject, retry, failure, and atomic commit/audit behavior.
- [x] 7.7 Add integration test against PostgreSQL for migration, memory insert/search, job processing, and active memory recall when database configuration is available.

## 8. Documentation and Verification

- [x] 8.1 Document environment variables, feature flags, worker command, and rollout order for long-term memory.
- [x] 8.2 Document examples of what should and should not become durable travel memory.
- [x] 8.3 Run `python -m py_compile` or project equivalent on changed Python modules.
- [x] 8.4 Run targeted memory tests and existing primary graph/chat tests.
- [x] 8.5 Run OpenSpec validation for `add-long-term-memory` and resolve all issues.
