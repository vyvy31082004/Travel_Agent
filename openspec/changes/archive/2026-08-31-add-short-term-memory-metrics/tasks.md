## 1. Fixtures

- [x] 1.1 Add `tests/fixtures/short_term_memory_eval/state_cases.jsonl` with per-turn gold state (destination, dates, guests, budget) including a one-slot-wrong case and a normalized-date case, split into `development`/`test`.
- [x] 1.2 Add `reference_cases.jsonl` with ordinal/domain references, one ambiguous-clarification case, and one wrong-item case.
- [x] 1.3 Add `factual_recall_cases.jsonl` with probes labeled by fact position (đầu/giữa/cuối) and before/after summarization, each with gold answer.
- [x] 1.4 Add `success_cases.jsonl` with multi-turn scenarios including a user-changes-mind case and a violated-constraint case.

## 2. State tracking metrics

- [x] 2.1 Implement JGA: full-state match per turn from `requests`/`latest_request_by_domain`/`active_request_id`/`selected_items`; empty denominator → `null`.
- [x] 2.2 Implement Slot F1 with normalized value comparison (ISO dates, numbers, currency); report true/false positive/negative counts.

## 3. Reference resolution metrics

- [x] 3.1 Implement Resolution Accuracy by running `resolve_item_reference(...)`; count `ClarificationNeeded` correct for ambiguous gold; empty denominator → `null`.

## 4. Factual recall metrics

- [x] 4.1 Implement Factual Recall Accuracy scoring probe answers vs gold; group results by fact position and before/after summarization.

## 5. Task success metrics

- [x] 5.1 Implement Success Rate: scenario succeeds only when final action satisfies every active gold constraint; user-changes-mind scored via same metric.

## 6. CLI and tests

- [x] 6.1 Extend `src/memory_eval/cli.py` with `--suite state|reference|factual-recall|success|all` for short-term memory.
- [x] 6.2 Add unit tests for each metric formula, empty-denominator `null`, one-slot-wrong JGA, ambiguous-clarification resolution, position grouping, and violated-constraint success.
- [x] 6.3 Run targeted tests and OpenSpec validation; write `docs/short-term-memory-metrics-implementation.md`.
