# Short-term memory evaluation

- Suite: `stm-all`
- Split: `test`
- Cases: `340`
- Gold: `tests\fixtures\short_term_memory_eval`

## Metrics

| Metric | Value | Numerator | Denominator |
|--------|-------|-----------|-------------|
| Joint Goal Accuracy (JGA) | 0.8353 | 71 | 85 |
| Slot F1 | 0.9380 | 325 | 339 |
| Resolution Accuracy | 1.0000 | 85 | 85 |
| Factual Recall Accuracy | 0.7529 | 64 | 85 |
| Task Success Rate | 0.7529 | 64 | 85 |

## state

- `joint_goal_accuracy`: 0.8353 (71/85)
- `slot_f1`: 0.9380 (325/339)

## reference

- `resolution_accuracy`: 1.0000 (85/85)

## factual_recall

- `factual_recall_accuracy`: 0.7529 (64/85)
- By position:
  - `cuối`: 0.7586
  - `giữa`: 0.7143
  - `đầu`: 0.7857
- By phase:
  - `after`: 0.9773
  - `before`: 0.5122

## success

- `success_rate`: 0.7529 (64/85)
