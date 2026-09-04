## Context

Production already exposes the functions to measure:

- `calculate_transition(...)` / `TransitionAction`
- `mark_memory_superseded(...)`, `status`, `supersedes_memory_id`, `TravelMemory.is_active`
- `MemoryService.recall(...)` / `RecallResult.recalled_memory_ids`

This change only adds offline evaluators and gold JSONL. It does not change `/chat`.

## Goals / Non-Goals

**Goals**

- Score the seven requested metrics with gold fixtures and production functions.
- Run in CI with an in-memory repository.
- Keep gold schema small: `case_id`, input, gold label, optional `rationale`.

**Non-Goals**

- nDCG@K, MRR, semantic lift, LLM-as-judge, Kappa/held-out process, or a generated answerer.
- Changing verifier, embeddings, or `/chat`.
- Graded relevance `2/1/0`.

## Decisions

1. **Reuse `src/memory_eval/`.** Do not add a second eval package.

2. **Call production functions directly.** Transition eval calls `calculate_transition`. Supersession eval commits through `MemoryCommitAdapter`. Retrieval eval calls `MemoryService.recall`. Answer eval scores a fixture `predicted_answer` against `gold_answer`.

3. **In-memory repo for unit eval.** Add one skippable Postgres test that recalled rows are filtered by `m.user_id = %(user_id)s` when `DATABASE_URL` is set.

4. **Binary relevance.** A seeded memory is relevant or not. Recall@K and Precision@K use that bit. `K = LONG_TERM_MEMORY_RECALL_LIMIT`. Precision@K always divides by `K`.

5. **Leakage denominator is recalled count.** Target is `0`. If recall is empty, value is `null`; the isolation test still fails if a wrong-user or inactive id appears.

6. **Answer scoring is fixture-in / score-out.** Each answer case includes `predicted_answer` and `gold_answer`. No deterministic answerer and no `/chat` call.

## Risks / Trade-offs

- [Lexical `calculate_transition` misses paraphrase conflicts] → Gold conflict cases use the signals the function already has.
- [In-memory recall ≠ pgvector ranking] → Unit metrics use a seeded store; SQL isolation is a separate skippable test.
- [Precision@K always `/ K`] → Sparse recall looks low; that matches the specified formula.
- [Scoring fixture answers is not full-agent quality] → Document as memory-QA scoring, not `/chat` E2E.

## Migration Plan

Add evaluators, fixtures, and tests. No schema migration. Rollback is deleting the eval suites.

## Open Questions

None for this change. nDCG/MRR and live `/chat` scoring stay future work.
