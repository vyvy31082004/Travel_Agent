## Why

Lexical `calculate_transition` misses paraphrase duplicates and soft preference conflicts (e.g. economy → business). Transition decisions need a SQL comparison pool, scope/relation judges, and TrustMem as the final write gate—without letting pgvector decide INSERT.

## What Changes

- Add `propose_transition` async orchestration: hard validation → SQL comparison pool → exact normalize fast-path → scope judge → relation judge → `MemoryTransition`.
- Add dedicated `fetch_transition_comparison_pool` (LEFT JOIN embeddings for ranking only; missing vectors stay in pool).
- Keep sync `calculate_transition` as lexical baseline (validate + exact duplicate; no polarity SUPERSEDE).
- Gate INSERT/SUPERSEDE with existing TrustMem verifier; NOOP skips TrustMem mutate path.
- Commit SUPERSEDE in one repository transaction.
- Eval dual-path: `--transition-path lexical|llm|policy-mock`.

## Capabilities

### New Capabilities
- `semantic-memory-transition`: Scope/relation LLM (or mock) policy that maps candidates to REJECT / NOOP / SUPERSEDE / INSERT against an active category/domain comparison pool.

### Modified Capabilities
- `memory-transition-lifecycle-metrics`: Transition accuracy and supersession suites support lexical vs LLM vs policy-mock predictors.

## Impact

- `src/memory/transition.py`, `src/memory/consolidation.py`, `src/memory/worker.py`, `src/memory/commit.py`
- `src/repositories/long_term_memory.py`, `src/settings.py`
- `src/memory_eval/suites.py`, `src/memory_eval/cli.py`
- No required DB schema change for v1 (embedding `is_current` flip on supersede remains optional cleanup).
