## Context

VietTrip AI có bốn thành phần short-term memory thật trong một hội thoại `thread_id`: structured state (`src/agents/primary/state.py`), conversation summary (`src/services/summarize.py`, `KEEP_COUNT=8`, `MAX_MESSAGES=12`, `30_000` chars), Result Store TTL (`src/repositories/result_store.py`), và reference resolver (`src/services/reference_resolver.py`). Change này thêm bộ đo offline cho bốn thành phần đó theo kế hoạch đã chốt (`ke-hoach-danh-gia-short-term-memory-viettrip-ai.md`), tái dùng khung `src/memory_eval/` đã có cho long-term memory.

## Goals / Non-Goals

Goals:
- Triển khai 5 metric: JGA, Slot F1, Resolution Accuracy, Factual Recall Accuracy, Success Rate.
- Gold-labeled, deterministic, chạy được trong CI với in-memory fixtures.
- Report chuẩn: `numerator`/`denominator`/`value`, `denominator=0` → `null`.
- Tái dùng CLI `src/memory_eval_cli.py` với `--suite`.

Non-Goals:
- Không sửa hành vi runtime của `/chat`, state, summarize, resolver.
- Không dùng LLM-as-judge làm metric chính; không ROUGE làm metric chính.
- Không training/RL; không benchmark long-term (đã có change riêng).
- Không đo TTL/expiry của Result Store như metric riêng ở giai đoạn này (payload-refs được dùng gián tiếp qua reference/success cases).

## Decisions

- **Tái dùng `src/memory_eval/`**: thêm module STM (ví dụ `src/memory_eval/short_term.py`) thay vì tạo package mới, để một CLI/一 khung report. Alternative: package riêng — bị loại vì trùng lặp scaffolding.
- **Chấm deterministic bằng gold**: Slot value so sánh sau chuẩn hóa (ngày ISO, số, tiền tệ). Alternative: so sánh chuỗi thô — bị loại vì phạt paraphrase đúng.
- **Resolution Accuracy thay vì MUC/B³/CEAF**: mỗi tham chiếu VietTrip thường một `item_id` đích; Resolution Accuracy trực tiếp, dễ audit. Nguồn phương pháp vẫn dẫn Pradhan et al. (2014). Alternative: bộ coreference đầy đủ — quá nặng, chưa tương xứng.
- **Factual Recall thay ROUGE/QAGS đầy đủ**: chấm hành vi cuối (trả lời probe đúng gold), kế thừa tinh thần QAGS + Needle-in-a-Haystack + Lost-in-the-Middle. Alternative: ROUGE — bị loại vì overlap không đo factuality; QAGS pipeline đầy đủ — nặng.
- **Case đổi ý gộp vào JGA + Success Rate**: không tách metric knowledge-update riêng, giữ bộ metric gọn. Nguồn: Budzianowski et al. (2018), chuẩn hóa rule theo Nekvinda & Dušek (2021).
- **Gold schema JSONL tối thiểu** cho từng suite; mỗi case có `case_id`, split (`development`/`test`), input, gold, và điều kiện kích hoạt summary khi cần.
- **Factual Recall và Success Rate cần agent chạy**: dùng fixture-in/score-out khi có thể (probe answer/agent action đã ghi sẵn trong gold) để giữ deterministic; nếu cần chạy agent thật thì đặt sau cờ và ngoài CI mặc định.

## Risks / Trade-offs

- [Gold nhỏ, một annotator] → Đánh dấu pilot diagnostic; cần double annotation + Cohen's Kappa + adjudication trước khi làm benchmark hội đồng.
- [Factual Recall/Success cần agent] → Ưu tiên fixture-in/score-out; nếu chạy agent, tách khỏi CI mặc định để tránh phụ thuộc model/mạng.
- [Slot normalization phức tạp] → Giới hạn tập slot chuẩn hóa (ngày, số khách, ngân sách, item) và ghi rõ quy tắc.
- [JGA quá khắt khe] → Luôn báo cáo kèm Slot F1 để tránh hiểu nhầm.

## Migration Plan

- Thêm module + fixtures + tests; không có migration DB.
- Rollback: xóa module/fixtures/tests và nhánh CLI `--suite` mới; không ảnh hưởng runtime.

## Open Questions

- Factual Recall/Success có chạy agent thật trong một chế độ tùy chọn không, hay chỉ fixture-in/score-out? Mặc định chọn fixture-in/score-out cho CI.
- Có cần đo riêng Result Store TTL/expiry không? Hiện để ngoài phạm vi; có thể mở change sau nếu cần.
