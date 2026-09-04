# memory-answer-quality-metrics Specification

## Purpose
TBD - created by archiving change add-ltm-transition-retrieval-answer-metrics. Update Purpose after archive.
## Requirements
### Requirement: Memory-grounded answer accuracy
The system SHALL score

```text
Answer Accuracy = correct_answers / total_questions
```

on gold cases in four groups: single-hop, multi-hop, temporal, and adversarial/unanswerable. Each case SHALL include `predicted_answer` and `gold_answer`. The value SHALL be `null` when `total_questions` is `0`.

#### Scenario: Single-hop
- **WHEN** one memory says the user prefers boutique seaside hotels
- **AND** the predicted answer states that preference
- **THEN** the answer is correct

#### Scenario: Multi-hop
- **WHEN** memories distinguish business for work travel and economy for leisure
- **AND** the question is a family holiday
- **THEN** an economy/leisure answer is correct and a business/work answer is incorrect

#### Scenario: Temporal
- **WHEN** a newer active preference superseded an older one
- **THEN** an answer using the active preference is correct
- **AND** an answer using the superseded preference is incorrect

#### Scenario: Unanswerable
- **WHEN** no car preference exists
- **AND** the predicted answer fabricates one
- **THEN** the answer is incorrect

### Requirement: Token-level partial F1
The system SHALL score Vietnamese free-form answers as

```text
Precision = overlapping_tokens / predicted_tokens
Recall = overlapping_tokens / gold_tokens
F1 = 2 * Precision * Recall / (Precision + Recall)
```

Tokens SHALL be lowercased and split on whitespace and punctuation. F1 SHALL be `null` when both predicted and gold token counts are `0`.

#### Scenario: Exact overlap
- **WHEN** predicted tokens equal gold tokens
- **THEN** F1 is `1.0`

#### Scenario: Partial overlap
- **WHEN** gold is `thich khach san boutique gan bien` and predicted is `thich khach san boutique`
- **THEN** Precision is `1.0`, Recall is `4/6`, and F1 is `0.8`
