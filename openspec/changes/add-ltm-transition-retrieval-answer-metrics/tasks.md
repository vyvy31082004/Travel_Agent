## 1. Fixtures

- [x] 1.1 Add `transition_cases.jsonl` with duplicate, conflict, updated condition, sensitive reject, ambiguous reject, and insert.
- [x] 1.2 Add `retrieval_cases.jsonl` with binary relevant ids, two-user similar preferences, and superseded/expired/deleted memories.
- [x] 1.3 Add `answer_cases.jsonl` with single-hop, multi-hop, temporal, and unanswerable items, each having `predicted_answer` and `gold_answer`.

## 2. Transition and lifecycle

- [x] 2.1 Score Transition Accuracy from `calculate_transition(...)` vs gold action.
- [x] 2.2 Score Supersession Correctness after commit: old inactive, `supersedes_memory_id` set, recall omits old id.

## 3. Retrieval and leakage

- [x] 3.1 Score Recall@K and Precision@K from `MemoryService.recall` with `K = LONG_TERM_MEMORY_RECALL_LIMIT`.
- [x] 3.2 Score cross-user and inactive leakage; target `0`. Add one skippable Postgres test for `m.user_id = %(user_id)s`.

## 4. Answer quality

- [x] 4.1 Score Answer Accuracy by question group and LoCoMo-style token F1 on fixture answers. Do not generate answers.

## 5. CLI and tests

- [x] 5.1 Extend the existing CLI with `--suite transition|retrieval|answer|all`.
- [x] 5.2 Add unit tests for formulas, empty-denominator `null`, leakage isolation, and supersession failures.
- [x] 5.3 Run targeted tests and OpenSpec validation.
