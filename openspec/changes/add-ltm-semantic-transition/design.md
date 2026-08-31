## Context

Lexical transition cannot detect paraphrase duplicates or soft value conflicts. Production needs SQL completeness, LLM semantic judgment, and TrustMem as the final write gate.

## Decisions

1. **Dual API**: keep sync `calculate_transition` for offline lexical tests; add async `propose_transition` for production.
2. **Separate judges**: scope then relation for auditable partitions; policy code overrides LLM `selected_action`.
3. **No polarity lexical SUPERSEDE** in v1; relation judge owns conflicts.
4. **Ranking-only pgvector**: LEFT JOIN; null distances last; never filter pool by distance.
5. **Early-exit**: only high-confidence NOOP/SUPERSEDE; INSERT after full pool scan.
6. **Transactional SUPERSEDE** via `commit_supersede`.
7. **Eval paths**: `lexical` | `llm` | `policy-mock` (gold-derived or fixture judgments).

## Non-goals (v1)

- Flipping embedding `is_current` on supersede
- REVIEW queue for ambiguous targets
- Merging scope+relation into one LLM call
