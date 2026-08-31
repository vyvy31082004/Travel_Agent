# Annotation Guideline — Memory Transition

Tài liệu này khóa quy tắc gán nhãn cho `transition_cases.jsonl`. Không sửa gold label theo output của `calculate_transition` hoặc model.

## 1. Phạm vi

Mỗi case gồm `existing` (active memories đã có) và một `candidate` memory mới. Annotator gán đúng một `gold_action` trong:

`insert` | `noop` | `supersede` | `reject`

Gold gán theo **policy ý nghĩa**, không theo output `calculate_transition`.

- `development`: case rõ nghĩa (exact duplicate, polarity / soft conflict, sensitive/ambiguous, insert) — dùng iterate policy và `policy-mock` / LLM transition path.
- `test` (held-out, 85 cases): **cân bằng** ~một nửa lexical-easy (exact dup / reject / plain insert) và ~một nửa policy-hard (paraphrase NOOP, value-swap SUPERSEDE, hedge). Gold không đổi theo hệ thống. Split: development 65 / held-out 85.

Lexical path (`--transition-path lexical`) chỉ validate + exact normalize duplicate (cùng condition); **không** polarity SUPERSEDE. Paraphrase / soft conflict là target của `--transition-path llm` (hoặc `policy-mock` để regression policy mapping offline).

## 2. Quy tắc từng action

### `reject`

Gán khi evidence của candidate không được phép ghi LTM:

- chứa dữ liệu nhạy cảm: mật khẩu/password, passport/số hộ chiếu, thẻ tín dụng/credit card, CVV;
- evidence là tool/API output (`search_id`, `item_id`, `total_results`, …);
- claim mơ hồ: “có thể”, “maybe”, “perhaps”, “không chắc”.

Reject có ưu tiên cao hơn mọi action khác (không insert/supersede dù text có preference).

Held-out có thể dùng paraphrase credential (PIN, OTP, hộ chiếu, thẻ ATM) hoặc hedge (`hình như`, `tôi nghĩ`, `có lẽ`, `chắc là`) — vẫn `reject` dù thiếu exact token trong rule hiện tại.

### `noop`

Gán khi candidate **cùng durable fact** với một memory active (kể cả paraphrase), cùng user. Không tạo bản ghi mới.

Exact lexical match là đủ nhưng không bắt buộc trên held-out.

### `supersede`

Gán khi candidate hợp lệ và:

1. **Conflict / value swap**: cùng `category` + `domain`, preference đổi ý hoặc đổi giá trị trên cùng chủ đề (thích ↔ không thích, economy → business, boutique → chuỗi lớn, …); hoặc
2. **Updated condition**: điều kiện áp dụng đổi, hoặc preference trong cùng condition đổi.

Sau supersede, memory cũ phải inactive và memory mới liên kết `supersedes_memory_id`.

### `insert`

Gán khi candidate hợp lệ (có evidence user, không sensitive/ambiguous/tool-only), **không** trùng memory active nào, và **không** conflict cùng category/domain với memory active.

Ví dụ: chưa có memory hotel → insert preference hotel mới; đã có flight preference khác chủ đề → vẫn có thể insert hotel.

## 3. Enum category / domain

Giống extraction:

- khách sạn/resort/homestay → `hotel_preference`, `hotel`
- flight/bay → `flight_preference`, `flight`
- thuê xe → `car_preference`, `car`
- tour/tham quan → `excursion_preference`, `excursion`
- lịch trình chung → `general_preference`, `general`
- tên/xưng hô → `profile_fact`, `general`
- quy tắc tương tác → `interaction_rule`, `general`

## 4. Schema truy vết

Mỗi dòng JSONL phải có:

- `case_id`
- `requirement_id` (`REQ-TRANS-DUP` | `REQ-TRANS-CONFLICT` | `REQ-TRANS-CONDITION` | `REQ-TRANS-SENSITIVE` | `REQ-TRANS-AMBIGUOUS` | `REQ-TRANS-INSERT`)
- `risk`
- `split` (`development` hoặc `test`)
- `existing`
- `candidate`
- `gold_action`
- `code_path`
- `metric`
- `rationale`

Case `gold_action=supersede` nên liệt kê cả `transition_accuracy` và `supersession_correctness` trong `metric`.

## 5. Gán nhãn độc lập

1. Hai annotator gán độc lập trên ít nhất 20–30% dataset.
2. Annotator không xem output hệ thống.
3. Tính Cohen’s Kappa trên `gold_action`.
4. Kappa ≥ 0,80: đồng thuận tốt.
5. Kappa 0,60–0,79: sửa guideline và làm rõ case.
6. Kappa < 0,60: không dùng nhãn đó để kết luận.
7. Bất đồng được adjudication sau khi gán độc lập.

## 6. Split policy

- `development`: dùng sửa rule / threshold.
- `test`: khóa trước khi tune; chỉ dùng báo cáo cuối (held-out).

Nếu đã sửa logic dựa trên output của test, case đó phải chuyển về development và tạo held-out mới.

## 7. Trạng thái dataset hiện tại

Bộ **100 case** (`development`=65, `test`/held-out=35) là **pilot gold draft do một annotator tạo**. Chưa có annotator thứ hai, Cohen’s Kappa hoặc adjudication. Số đo hiện tại chỉ là **pilot diagnostic**, chưa phải kết quả held-out chính thức để kết luận trước hội đồng.
