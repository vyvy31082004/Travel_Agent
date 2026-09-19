# Retrieval evaluation

- Suite: `retrieval`
- Split: `development`
- Cases: `65`
- Gold: `E:\Travel Agent\customer-support-agent\tests\fixtures\long_term_memory_eval\retrieval_cases.jsonl`
- Applicability judge: `rule`

> Rule-based judge uses fixture-aligned heuristics and runs quickly in CI.
> Use `--applicability-judge llm` for production-like Gemini judging.

## Quality metrics

| Metric | Value |
|--------|-------|
| SQL candidate pool completeness | 1.0000 |
| Apply recall | 1.0000 |
| Allowed context precision | 1.0000 |
| Uncertain recall | 1.0000 |
| Irrelevant leakage | 0.0000 |
| Overridden leakage | 0.0000 |
| Context case pass rate | 1.0000 |
| Applicability macro-F1 | 0.9742 |

## Isolation metrics

| Metric | Value |
|--------|-------|
| Cross-user candidate leakage | 0.0000 |
| Cross-domain candidate leakage | 0.0000 |
| Inactive candidate leakage | 0.0000 |
| Cross-user context leakage | 0.0000 |
| Cross-domain context leakage | 0.0000 |
| Inactive context leakage | 0.0000 |

## Context composition diagnostics

| Metric | Value |
|--------|-------|
| Apply-only share in final context (diagnostic) | 0.4872 |
| Uncertain share in final context (diagnostic) | 0.5128 |
