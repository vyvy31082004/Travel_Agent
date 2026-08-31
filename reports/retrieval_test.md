# Retrieval evaluation

- Suite: `retrieval`
- Split: `test`
- Cases: `85`
- Gold: `E:\Travel Agent\customer-support-agent\tests\fixtures\long_term_memory_eval\retrieval_cases.jsonl`
- Applicability judge: `rule`

> Rule-based judge uses fixture-aligned heuristics and runs quickly in CI.
> Use `--applicability-judge llm` for production-like Gemini judging.

## Metrics

| Metric | Value |
|--------|-------|
| SQL candidate pool completeness | 1.0000 |
| Cross-user candidate leakage | 0.0000 |
| Cross-domain candidate leakage | 0.0000 |
| Inactive candidate leakage | 0.0000 |
| Context recall (apply) | 1.0000 |
| Context precision | 0.8172 |
| Uncertain in final context | 0.1613 |
| Overridden leakage | 0.0000 |
| Applicability macro-F1 | 0.9352 |
| Cross-user context leakage | 0.0000 |
| Cross-domain context leakage | 0.0000 |
| Inactive context leakage | 0.0000 |
