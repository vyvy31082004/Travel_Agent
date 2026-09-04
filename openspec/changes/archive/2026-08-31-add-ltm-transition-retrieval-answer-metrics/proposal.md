## Why

Extraction metrics already exist. The next gap is measuring transition decisions, supersession lifecycle, retrieval isolation, and memory-grounded answers with gold labels and the formulas already specified for this project.

## What Changes

- Evaluate `calculate_transition(...)` accuracy for `INSERT`, `NOOP`, `SUPERSEDE`, and `REJECT`.
- Evaluate supersession correctness after commit: old memory inactive, `supersedes_memory_id` set, recall excludes the old id.
- Evaluate `Recall@K` and `Precision@K` with `K = LONG_TERM_MEMORY_RECALL_LIMIT`.
- Evaluate cross-user leakage and inactive-memory leakage, target `0`.
- Evaluate memory-grounded answer accuracy (single-hop, multi-hop, temporal, unanswerable) and LoCoMo-style token F1.
- Reuse `src/memory_eval/` and JSONL fixtures. Do not change `/chat` or production commit behavior.
- Do not invent scores. Denominator `0` reports `null`.

## Capabilities

### New Capabilities

- `memory-transition-lifecycle-metrics`: Transition Accuracy and Supersession Correctness.
- `memory-retrieval-metrics`: Recall@K, Precision@K, cross-user leakage, inactive leakage.
- `memory-answer-quality-metrics`: Answer Accuracy and token-level partial F1.

### Modified Capabilities

- None.

## Impact

- Eval code: `src/memory_eval/`, `tests/fixtures/long_term_memory_eval/`, `tests/test_memory_eval_*.py`.
- Measurement surfaces only: `calculate_transition`, `MemoryCommitAdapter`, `mark_memory_superseded`, `TravelMemory.is_active`, `MemoryService.recall`.
- Gold files: `transition_cases.jsonl`, `retrieval_cases.jsonl`, `answer_cases.jsonl`.
- CLI: extend existing `memory_eval` runner with suites `transition`, `retrieval`, `answer`.
- No new runtime dependencies. No LLM judge. No nDCG/MRR in this change.
