# Short-term memory evaluation

- Suite: `stm-all`
- Split: `development`
- Cases: `260`
- Gold: `tests\fixtures\short_term_memory_eval`

## Metrics

| Metric | Value | Numerator | Denominator |
|--------|-------|-----------|-------------|
| Joint Goal Accuracy (JGA) | 0.8308 | 54 | 65 |
| Slot F1 | 0.9385 | 252 | 263 |
| Resolution Accuracy | 1.0000 | 65 | 65 |
| Factual Recall Accuracy | 0.7692 | 50 | 65 |
| Task Success Rate | 0.7538 | 49 | 65 |

## state

- `joint_goal_accuracy`: 0.8308 (54/65)
- `slot_f1`: 0.9385 (252/263)

## reference

- `resolution_accuracy`: 1.0000 (65/65)

## factual_recall

- `factual_recall_accuracy`: 0.7692 (50/65)
- By position:
  - `đầu`: 0.7826
  - `giữa`: 0.7727
  - `cuối`: 0.7500
- By phase:
  - `before`: 0.5312
  - `after`: 1.0000

## success

- `success_rate`: 0.7538 (49/65)
