# Short-term memory evaluation

- Suite: `stm-all`
- Split: `all`
- Cases: `600`
- Gold: `tests\fixtures\short_term_memory_eval`

## Metrics

| Metric | Value | Numerator | Denominator |
|--------|-------|-----------|-------------|
| Joint Goal Accuracy (JGA) | 0.8333 | 125 | 150 |
| Slot F1 | 0.9382 | 577 | 602 |
| Resolution Accuracy | 1.0000 | 150 | 150 |
| Factual Recall Accuracy | 0.7600 | 114 | 150 |
| Task Success Rate | 0.7533 | 113 | 150 |

## state

- `joint_goal_accuracy`: 0.8333 (125/150)
- `slot_f1`: 0.9382 (577/602)

## reference

- `resolution_accuracy`: 1.0000 (150/150)

## factual_recall

- `factual_recall_accuracy`: 0.7600 (114/150)
- By position:
  - `đầu`: 0.7843
  - `giữa`: 0.7400
  - `cuối`: 0.7551
- By phase:
  - `before`: 0.5205
  - `after`: 0.9870

## success

- `success_rate`: 0.7533 (113/150)
