# Annotation Guideline — Domain Recall (`retrieval_cases.jsonl`)

Gold cho eval **SQL candidate pool** + **applicability judge**. Hai gold độc lập.

## 1. Phạm vi

Mỗi case mô phỏng một lần `recall_domain_with_applicability` sau khi action đã được xác định.

Không gán nhãn semantic top-K. Không dùng `relevant: true/false`.

## 2. Schema bắt buộc

- `scenario_type`: key ổn định trong taxonomy (parity dev/test)
- `memory_store`: toàn bộ memory seed (active/inactive, multi-user, multi-domain)
- `expected_sql_pool`: memory_id **phải** có trong `fetch_active_domain_memories`
- `expected_applicability`: nhãn trên từng candidate trong pool
- `expected_presented_constraints`: constraint + `strength` cho memory xuất hiện trong final context

## 3. Nhãn applicability

| Nhãn | Ý nghĩa |
|------|---------|
| `apply` | Liên quan trực tiếp quyết định hiện tại → vào hard context |
| `uncertain` | Có thể hỗ trợ ranking → vào soft context |
| `overridden` | Liên quan nhưng user hiện tại phủ định/ghi đè |
| `irrelevant` | Không thuộc action/state hiện tại |

**OVERRIDDEN** ≠ **IRRELEVANT**:
- OVERRIDDEN: memory vốn liên quan (cùng chiều quyết định) nhưng bị query hiện tại bác bỏ
- IRRELEVANT: memory không thuộc quyết định/action hiện tại

## 4. SQL pool

Pool = mọi `travel_preferences` **active** đúng `user_id` + `domain`. Không semantic filter.

Memory trong pool nhưng `irrelevant`/`overridden` là **pass** cho SQL — lỗi nằm ở judge nếu final context vẫn chứa chúng.

## 5. Final context

`final_context` = memory có nhãn `apply` hoặc `uncertain` sau judge.

Metric chất lượng:

- `context_recall` = `apply` trong final / toàn bộ gold `apply`
- `allowed_context_precision` = (`apply` + `uncertain`) trong final / toàn bộ final
- `uncertain_recall` = `uncertain` trong final / toàn bộ gold `uncertain`
- `irrelevant_leakage_rate` = `irrelevant` trong final / toàn bộ gold `irrelevant`
- `overridden_leakage_rate` = `overridden` trong final / toàn bộ gold `overridden`
- `context_case_pass_rate`: case pass khi không thiếu gold `apply` và không có
  gold `irrelevant`/`overridden` trong final; `uncertain` là optional

Metric composition (chỉ để chẩn đoán, không dùng làm KPI chất lượng):

- `context_precision` = tỷ trọng gold `apply` trong final
- `uncertain_context_rate` = tỷ trọng gold `uncertain` trong final

Hai tỷ trọng trên phản ánh final context gồm hard hay soft preference nhiều hơn;
`uncertain` không phải lỗi precision.

## 6. Presented constraints

```json
{"memory_id": "h-quiet", "constraint": "prefer_quiet", "strength": "soft_preference"}
```

- `apply` → `hard_preference` hoặc `soft_preference` tùy case
- `uncertain` → luôn `soft_preference`

## 7. Split

- `development` (65): tune + CI gate scope/leakage
- `test` (85): held-out variants, cùng `scenario_type` coverage

Mỗi `scenario_type` ≥ 1 case ở **cả hai** split.

## 8. Gán nhãn độc lập

Không sửa gold theo output model. Evidence nằm trong `rationale`.
