## Why

VietTrip AI đã có bộ đo long-term memory (extraction, transition, retrieval, answer) nhưng chưa có cách đo **short-term memory** trong phạm vi một hội thoại (`thread_id`). Không có bộ đo này, ta không biết agent có theo dõi đúng yêu cầu đang hiệu lực, giải đúng tham chiếu tới kết quả đã hiển thị, giữ đúng dữ kiện sau khi nén hội thoại, và hoàn thành đúng tác vụ đa lượt hay không. Kế hoạch trong `ke-hoach-danh-gia-short-term-memory-viettrip-ai.md` đã chốt bộ metric rút gọn cần triển khai.

## What Changes

- Thêm bộ đánh giá offline, gold-labeled cho short-term memory, tách khỏi `/chat` hot path.
- Triển khai **năm metric cốt lõi** theo kế hoạch, mỗi metric gắn một thành phần STM thật:
  - **Joint Goal Accuracy (JGA)** và **Slot F1** cho structured state (`src/agents/primary/state.py`).
  - **Resolution Accuracy** cho reference resolver (`src/services/reference_resolver.py`).
  - **Factual Recall Accuracy** cho summary + messages (`src/services/summarize.py`).
  - **Success Rate** cho kịch bản đa lượt (toàn bộ STM).
- Thêm fixtures gold tiếng Việt cho từng nhóm case: state turns, reference cases, summary-recall probes, kịch bản đa lượt (bao gồm case đổi ý).
- Mở rộng CLI đánh giá hiện có (`src/memory_eval_cli.py`) với suite short-term memory.
- Mọi metric report gồm `numerator`, `denominator`, `value`; `denominator = 0` → `value = null`. Không bịa số.
- Tách `development` và `held-out test`; chỉ held-out test dùng để kết luận cuối.

## Capabilities

### New Capabilities

- `stm-state-tracking-metrics`: Đo JGA và Slot F1 bằng cách so structured state của agent (`requests`, `latest_request_by_domain`, `active_request_id`, `selected_items`) với gold state theo từng lượt.
- `stm-reference-resolution-metrics`: Đo Resolution Accuracy của `resolve_item_reference(...)` trên tham chiếu thứ tự/domain, tính cả trường hợp gold là mơ hồ phải trả `ClarificationNeeded`.
- `stm-factual-recall-metrics`: Đo Factual Recall Accuracy — sau khi summary kích hoạt, agent còn trả lời/áp dụng đúng dữ kiện gold từ lịch sử; case chia theo vị trí dữ kiện và trước/sau nén.
- `stm-task-success-metrics`: Đo Success Rate của kịch bản đa lượt; kịch bản chỉ thành công khi hành động/phản hồi cuối thỏa toàn bộ ràng buộc gold đang hiệu lực.

### Modified Capabilities

<!-- Không thay đổi requirement của capability hiện có. -->

## Impact

- Thành phần đọc (không sửa hành vi runtime): `src/agents/primary/state.py`, `src/services/summarize.py`, `src/services/reference_resolver.py`, `src/repositories/result_store.py`.
- Thành phần thêm mới: fixtures `tests/fixtures/short_term_memory_eval/`, module evaluator trong `src/memory_eval/`, mở rộng `src/memory_eval/cli.py` với `--suite`, unit tests trong `tests/`.
- Tài liệu: `docs/short-term-memory-evaluation-metrics-plan.md` (đã có), thêm doc implementation khi apply.
- Không đổi `/chat` API contract; không thêm LLM-as-judge làm metric chính; không training/RL.
