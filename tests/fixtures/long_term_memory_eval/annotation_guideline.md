# Annotation Guideline — Candidate Extraction

Tài liệu này khóa quy tắc gán nhãn cho `extraction_cases.jsonl`. Không sửa gold label theo output của hệ thống.

## 1. Phạm vi

Chỉ gán nhãn Long-Term Memory: preference, profile fact hoặc interaction rule do user xác nhận và có giá trị qua nhiều hội thoại.

Không gán nhãn LTM cho:

- context tạm thời trong một `thread_id`;
- tool/API output, giá hiện tại, booking token, `search_id`, payload;
- yêu cầu chỉ đúng cho một chuyến;
- passport, CVV, password, số thẻ;
- assistant suggestion chưa được user xác nhận;
- claim mơ hồ như “có thể”, “chưa chắc”.

## 2. Valid memory

Một gold memory hợp lệ phải:

1. được user xác nhận trực tiếp;
2. có giá trị tái sử dụng qua nhiều phiên;
3. atomic: một memory chứa một durable fact;
4. có evidence từ user message;
5. có category/domain/family đúng enum.

Ví dụ:

- “Tôi thích khách sạn boutique gần biển” → valid LTM.
- “Tìm khách sạn Đà Nẵng ngày 15/9 giá dưới 2 triệu” → không phải LTM.
- Tool trả “khách sạn X 1,5 triệu” → reject.

## 3. Atomicity

Nếu một câu có nhiều durable fact độc lập, gán nhiều gold memories:

```text
“Tôi thích khách sạn boutique gần biển, yên tĩnh”
→ thích khách sạn boutique
→ thích khách sạn gần biển
→ thích khách sạn yên tĩnh
```

Không bỏ condition. Ví dụ business khi công tác và economy khi du lịch phải giữ đủ cả hai phạm vi.

## 4. Enum labels

- khách sạn/resort/homestay → `hotel_preference`, `hotel`;
- flight/bay/chuyến bay/sân bay → `flight_preference`, `flight`;
- thuê xe/tài xế → `car_preference`, `car`;
- tour/tham quan/hoạt động → `excursion_preference`, `excursion`;
- preference lịch trình chung → `general_preference`, `general`;
- tên/xưng hô → `profile_fact`, `general`;
- quy tắc trả lời/tương tác → `interaction_rule`, `general`.

Family suy ra từ `CATEGORY_FAMILY`.

## 5. Schema truy vết

Mỗi dòng JSONL phải có:

- `case_id`;
- `requirement_id`;
- `risk`;
- `split` (`development` hoặc `test`);
- `messages`;
- `gold_memories`;
- `code_path`;
- `metric`;
- `rationale`.

## 6. Gán nhãn độc lập

Theo `plan.pdf`:

1. Hai annotator gán nhãn độc lập trên ít nhất 20–30% dataset.
2. Annotator không xem output model.
3. Tính Cohen’s Kappa cho valid/invalid và category/domain.
4. Kappa ≥ 0,80: đồng thuận tốt.
5. Kappa 0,60–0,79: sửa guideline và làm rõ case.
6. Kappa < 0,60: không dùng nhãn đó để kết luận.
7. Bất đồng được adjudication sau khi gán độc lập.

## 7. Split policy

- `development`: dùng sửa rule/prompt/threshold.
- `test`: khóa trước khi tune; chỉ dùng báo cáo cuối.

Nếu đã sửa logic dựa trên output của test, case đó phải chuyển về development và tạo held-out mới.

## 8. Trạng thái dataset hiện tại

Bộ 57 case hiện tại là **pilot gold draft do một annotator tạo**. Chưa có annotator thứ hai, Cohen’s Kappa hoặc adjudication. Vì vậy số đo hiện tại chỉ là **pilot diagnostic**, chưa phải kết quả held-out chính thức để kết luận trước hội đồng.
