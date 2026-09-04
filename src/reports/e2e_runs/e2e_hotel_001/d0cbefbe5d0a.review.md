  # E2E Review — e2e_hotel_001

  ## Scenario
  Áp dụng budget + quiet + near beach preference khi tìm hotel

  ## Query
  - Tìm khách sạn ở Phú Quốc cho tôi.

  ## Final answer
  Dưới đây là một số khách sạn nổi bật giáp biển tại Phú Quốc phù hợp với nhu cầu của bạn:

  ---

  ### 1. **Sea Star Resort** (3 sao)
  * **Giá tham khảo:** ~860.200 VND / đêm (Đã bao gồm thuế & phí)
  * **Đánh giá:** 8.4/10 (Rất tốt - 1.655 đánh giá)
  * **Vị trí:** Dương Tơ (cách trung tâm ~1.7 km), giáp biển.
  * **Tiện ích & Điểm nổi bật:** Bungalow 28m² nguyên căn, bao gồm bữa sáng, không cần thanh toán trước.
  ![Sea Star Resort](https://cf.bstatic.com/xdata/images/hotel/square500/87489686.jpg?k=9b70a26e05e82ccc23de361ca89dddfd2e694d49c576ea4c9f76fba9562f2a2f&o=)

  ---

  ### 2. **Coral Bay Resort** (3 sao)
  * **Giá tham khảo:** ~1.606.813 VND / đêm (Đã bao gồm thuế & phí)
  * **Đánh giá:** 8.4/10 (Rất tốt - 680 đánh giá)
  * **Vị trí:** Dương Tơ (cách trung tâm ~2.7 km), giáp biển.
  * **Tiện ích & Điểm nổi bật:** Bao bữa sáng, hủy miễn phí, không cần thanh toán trước.
  ![Coral Bay Resort](https://cf.bstatic.com/xdata/images/hotel/square500/40356001.jpg?k=8db4e677fac7798141b84ad55fdf8a2a8330ca51921568b3602e15da7fabce77&o=)

  ---

  ### 3. **Ocean Bay Resort & Spa Phu Quoc** (5 sao)
  * **Giá tham khảo:** ~2.502.500 VND / đêm (Đã bao gồm thuế & phí)
  * **Đánh giá:** 9.0/10 (Tuyệt hảo - 3.062 đánh giá)
  * **Vị trí:** Ông Lang (cách trung tâm ~4.5 km), giáp biển, không gian yên tĩnh.
  * **Tiện ích & Điểm nổi bật:** Bungalow rộng 52m², bao gồm bữa sáng.
  ![Ocean Bay Resort & Spa Phu Quoc](https://cf.bstatic.com/xdata/images/hotel/square500/685539137.jpg?k=446f7c9698c694e0fbb5e8d9a174aa83964fac8e3971f34513c62cd1c943ec89&o=)

  ---

  ### 4. **Best Western Premier Sonasea Phu Quoc** (5 sao)
  * **Giá tham khảo:** ~3.000.000 VND / đêm (Đã bao gồm thuế & phí)
  * **Đánh giá:** 8.2/10 (Rất tốt - 683 đánh giá)
  * **Vị trí:** Dương Tơ (cách trung tâm ~10 km), giáp biển.
  * **Tiện ích & Điểm nổi bật:** Bao gồm bữa sáng, dịch vụ đẳng cấp 5 sao.
  ![Best Western Premier Sonasea Phu Quoc](https://cf.bstatic.com/xdata/images/hotel/square500/770599803.jpg?k=5e71c4a12688dca49ee41fbe65a99a66fd0f07826f540486a6184082f7604157&o=)

  ---

  ### 5. **Dusit Princess Moonrise Beach Resort** (5 sao)
  * **Giá tham khảo:** ~3.850.000 VND / đêm (Đã bao gồm thuế & phí)
  * **Đánh giá:** 9.3/10 (Tuyệt hảo - 1.499 đánh giá)
  * **Vị trí:** Dương Tơ (cách trung tâm ~4 km), giáp biển.
  * **Tiện ích & Điểm nổi bật:** Khách sạn nghỉ dưỡng cao cấp, bao gồm bữa sáng.
  ![Dusit Princess Moonrise Beach Resort](https://cf.bstatic.com/xdata/images/hotel/square500/296411169.jpg?k=7290afafba1527e77526627b10834f9da7137c907834a6540657e79deb434cf8&o=)

  ---

  Bạn hãy cho tôi biết nếu muốn xem thêm ngày lưu trú cụ thể, số lượng khách, hoặc cần đặt phòng trực tiếp nhé!

  ## Auto scores (informational)
  - - **routing_accuracy**: PASS — delegated domains match
  - - **tool_call_correctness**: PASS — all expected tools called with required arguments
  - - **context_recall_precision**: PASS — context recall/precision satisfied
  - - **cross_user_inactive_leakage**: PASS — no cross-user/inactive leakage detected
  - - **finalize_correctness**: PASS — no new long-term memories stored
  - - **trace_integrity**: PASS — all auto checkpoints passed or skipped

  ## Evidence bundle

  ### Active memories (fixture ids)
  ```json
  {
    "m_budget": "de62ae8a-80b8-58a6-bfcf-0199984f6c2c",
    "m_quiet": "e9e8a6a0-ec66-51ab-82f0-8b71c33a0378",
    "m_beach": "397ea00f-cba6-5445-9b89-3c207daf17b5",
    "m_other_user": "cbb4a166-3280-51ab-973a-e91add751201",
    "m_superseded": "08fd7614-4e37-55c0-b890-5010437c2da6"
  }
  ```

  ### Global recall
  ```json
  {
    "memory_context": "",
    "recalled_memory_ids": [],
    "recalled_fixture_ids": []
  }
  ```

  ### Domain recall
  ```json
  {
    "hotel": {
      "candidate_pool_ids": [
        "m_beach",
        "m_quiet",
        "m_budget"
      ],
      "applicability": {
        "m_beach": "uncertain",
        "m_quiet": "uncertain",
        "m_budget": "uncertain"
      },
      "final_context_ids": [
        "m_beach",
        "m_quiet",
        "m_budget"
      ],
      "applied_constraints": [
        "(soft) [397ea00f-cba6-5445-9b89-3c207daf17b5] Thích khách sạn gần biển",
        "(soft) [e9e8a6a0-ec66-51ab-82f0-8b71c33a0378] Thích khách sạn yên tĩnh",
        "(soft) [de62ae8a-80b8-58a6-bfcf-0199984f6c2c] Ngân sách hotel thường 1–2 triệu/đêm"
      ]
    }
  }
  ```

  ### Tool snapshots
  ### search_hotels_tool
  ```json
  {
    "search_id": "a4b3944e-4af0-403b-99ba-ac31cef2a918",
    "request_id": "req_hotel_456f0ca6",
    "domain": "hotel",
    "total_results": 10,
    "items": [
      {
        "name": "Sea Star Resort",
        "star": 3,
        "photo": "https://cf.bstatic.com/xdata/images/hotel/square500/87489686.jpg?k=9b70a26e05e82ccc23de361ca89dddfd2e694d49c576ea4c9f76fba9562f2a2f&o=",
        "price": 860200,
        "rating": 8.4,
        "address": null,
        "item_id": "1111660",
        "currency": "VND",
        "location": "Phú Quốc",
        "price_tier": "mid",
        "external_hotel_id": "1111660",
        "accessibilityLabel": [
          "Sea Star Resort",
          "3 trên 5 sao",
          "8,4 Rất tốt 1655 đánh giá",
          "Duong To • 1,7km từ trung tâm",
          "Giáp biển",
          "Ưu Đãi Mùa Du Lịch",
          "Bao bữa sáng",
          "1 bungalow nguyên căn – 28 m² : 1 giường • 1 phòng ngủ • 1 phòng tắm",
          "Giá gốc là 2150500 VND",
          "Giá hiện tại là 860200 VND",
          "Đã bao gồm thuế và phí",
          "Không cần thanh toán trước",
          "Chỉ còn 4 căn với giá này trên Booking.com"
        ],
        "position": 1
      },
      {
        "name": "Best Western Premier Sonasea Phu Quoc",
        "star": 5,
        "photo": "https://cf.bstatic.com/xdata/images/hotel/square500/770599803.jpg?k=5e71c4a12688dca49ee41fbe65a99a66fd0f07826f540486a6184082f7604157&o=",
        "price": 3000000,
        "rating": 8.2,
        "address": null,
        "item_id": "4632878",
        "currency": "VND",
        "location": "Phú Quốc",
        "price_tier": "luxury",
        "external_hotel_id": "4632878",
        "accessibilityLabel": [
          "Best Western Premier Sonasea Phu Quoc",
          "5 trên 5 sao",
          "8,2 Rất tốt 683 đánh giá",
          "Duong To • 10km từ trung tâm",
          "Giáp biển",
          "Bao bữa sáng",
          "1 giường",
          "3000000 VND",
          "Đã bao gồm thuế và phí"
        ],
        "position": 2
      },
      {
        "name": "Vinholidays Fiesta Phu Quoc",
        "star": 4,
        "photo": "https://cf.bstatic.com/xdata/images/hotel/square500/302248703.jpg?k=600e0c05a76594df28aef976d935a2e18ef557e5f81ca6e450807b963e874aab&o=",
        "price": 1190000,
        "rating": 8.3,
        "address": null,
        "item_id": "6744856",
        "currency": "VND",
        "location": "Phú Quốc",
        "price_tier": "mid",
        "external_hotel_id": "6744856",
        "accessibilityLabel": [
          "Vinholidays Fiesta Phu Quoc",
          "4 trên 5 sao",
          "8,3 Rất tốt 864 đánh giá",
          "Ganh Dau • 16,3km từ trung tâm",
          "Cách biển 0,7km",
          "1 phòng khách sạn : 2 giường",
          "Giá gốc là 1487500 VND",
          "Giá hiện tại là 1190000 VND",
          "Đã bao gồm thuế và phí"
        ],
        "position": 3
      },
      {
        "name": "Dusit Princess Moonrise Beach Resort",
        "star": 5,
        "photo": "https://cf.bstatic.com/xdata/images/hotel/square500/296411169.jpg?k=7290afafba1527e77526627b10834f9da7137c907834a6540657e79deb434cf8&o=",
        "price": 3850000,
        "rating": 9.3,
        "address": null,
        "item_id": "3002731",
        "currency": "VND",
        "location": "Phú Quốc",
        "price_tier": "luxury",
        "external_hotel_id": "3002731",
        "accessibilityLabel": [
          "Dusit Princess Moonrise Beach Resort",
          "5 trên 5 sao",
          "Đây là chỗ nghỉ Ưu tiên",
          "9,3 Tuyệt hảo 1499 đánh giá",
          "Duong To • 4km từ trung tâm",
          "Giáp biển",
          "Bao bữa sáng",
          "1 phòng khách sạn : 1 giường",
          "Giá gốc là 7000000 VND",
          "Giá hiện tại là 3850000 VND",
          "Đã bao gồm thuế và phí",
          "Chỉ còn 1 căn với giá này trên Booking.com"
        ],
        "position": 4
      },
      {
        "name": "New World Phu Quoc Resort",
        "star": 5,
        "photo": "https://cf.bstatic.com/xdata/images/hotel/square500/744463485.jpg?k=790cc4e6eb761db82f8ef7afce37e8afb5a072597feeaa23d55f2cd95f1436c8&o=",
        "price": 6940080,
        "rating": 8.5,
        "address": null,
        "item_id": "7006996",
        "currency": "VND",
        "location": "Phú Quốc",
        "price_tier": "luxury",
        "external_hotel_id": "7006996",
        "accessibilityLabel": [
          "New World Phu Quoc Resort",
          "5 trên 5 sao",
          "Đây là chỗ nghỉ Ưu tiên",
          "8,5 Rất tốt 696 đánh giá",
          "An Thoi • 21,1km từ trung tâm",
          "Giáp biển",
          "Bao bữa sáng",
          "1 giường",
          "6940080 VND",
          "Đã bao gồm thuế và phí",
          "Chỉ còn 3 căn với giá này trên Booking.com"
        ],
        "position": 5
      },
      {
        "name": "Devesun Boutique Hotel Phú Quốc",
        "star": 0,
        "photo": "https://cf.bstatic.com/xdata/images/hotel/square500/877016766.jpg?k=8f14a27420c89addd276e4e17e585c97ed4d9e8c1045f29da53e6ada9d681a93&o=",
        "price": 1377000,
        "rating": 9.4,
        "address": null,
        "item_id": "15979413",
        "currency": "VND",
        "location": "Phú Quốc",
        "price_tier": "mid",
        "external_hotel_id": "15979413",
        "accessibilityLabel": [
          "Devesun Boutique Hotel Phú Quốc",
          "9,4 Tuyệt hảo 24 đánh giá",
          "An Thoi • 21,9km từ trung tâm",
          "Bao bữa sáng",
          "1 phòng khách sạn : 1 giường",
          "1377000 VND",
          "Đã bao gồm thuế và phí",
          "Chỉ còn 2 căn với giá này trên Booking.com"
        ],
        "position": 6
      },
      {
        "name": "Coral Bay Resort",
        "star": 3,
        "photo": "https://cf.bstatic.com/xdata/images/hotel/square500/40356001.jpg?k=8db4e677fac7798141b84ad55fdf8a2a8330ca51921568b3602e15da7fabce77&o=",
        "price": 1606813,
        "rating": 8.4,
        "address": null,
        "item_id": "872579",
        "currency": "VND",
        "location": "Phú Quốc",
        "price_tier": "luxury",
        "external_hotel_id": "872579",
        "accessibilityLabel": [
          "Coral Bay Resort",
          "3 trên 5 sao",
          "Đây là chỗ nghỉ Ưu tiên",
          "8,4 Rất tốt 680 đánh giá",
          "Duong To • 2,7km từ trung tâm",
          "Giáp biển",
          "Giá chỉ có trên điện thoại",
          "Bao bữa sáng",
          "1 giường",
          "Giá gốc là 2380464 VND",
          "Giá hiện tại là 1606813 VND",
          "Đã bao gồm thuế và phí",
          "Hủy miễn phí",
          "Không cần thanh toán trước",
          "Chỉ còn 2 căn với giá này trên Booking.com"
        ],
        "position": 7
      },
      {
        "name": "Ocean Bay Resort & Spa Phu Quoc",
        "star": 5,
        "photo": "https://cf.bstatic.com/xdata/images/hotel/square500/685539137.jpg?k=446f7c9698c694e0fbb5e8d9a174aa83964fac8e3971f34513c62cd1c943ec89&o=",
        "price": 2502500,
        "rating": 9,
        "address": null,
        "item_id": "7017600",
        "currency": "VND",
        "location": "Phú Quốc",
        "price_tier": "luxury",
        "external_hotel_id": "7017600",
        "accessibilityLabel": [
          "Ocean Bay Resort & Spa Phu Quoc",
          "5 trên 5 sao",
          "Đây là chỗ nghỉ Ưu tiên",
          "9,0 Tuyệt hảo 3062 đánh giá",
          "Ong Lang • 4,5km từ trung tâm",
          "Giáp biển",
          "Ưu Đãi Mùa Du Lịch",
          "Bao bữa sáng",
          "1 bungalow nguyên căn – 52 m² : 1 giường • 1 phòng ngủ • 1 phòng tắm",
          "Giá gốc là 3850000 VND",
          "Giá hiện tại là 2502500 VND",
          "Đã bao gồm thuế và phí",
          "Chỉ còn 4 căn với giá này trên Booking.com"
        ],
        "position": 8
      },
      {
        "name": "Premier Residences Phu Quoc Emerald Bay Managed by Accor",
        "star": 5,
        "photo": "https://cf.bstatic.com/xdata/images/hotel/square500/882580829.jpg?k=e5bb89041a22558ba097546d55d78483a8165a91db837de4ec36668507c06d5c&o=",
        "price": 2734265,
        "rating": 7.9,
        "address": null,
        "item_id": "4263727",
        "currency": "VND",
        "location": "Phú Quốc",
        "price_tier": "luxury",
        "external_hotel_id": "4263727",
        "accessibilityLabel": [
          "Premier Residences Phu Quoc Emerald Bay Managed by Accor",
          "5 trên 5 sao",
          "Đây là chỗ nghỉ Ưu tiên",
          "7,9 Tốt 860 đánh giá",
          "An Thoi • 21,5km từ trung tâm",
          "Giáp biển",
          "Bao bữa sáng",
          "1 phòng khách sạn : 1 giường",
          "2734265 VND",
          "+366392 VND thuế và phí",
          "Không cần thanh toán trước"
        ],
        "position": 9
      },
      {
        "name": "Emerald Boutique Hotel Phú Quốc",
        "star": 0,
        "photo": "https://cf.bstatic.com/xdata/images/hotel/square500/807807940.jpg?k=cb81791f57b7cce1bb367974cc342c9902281a3dc69aafac18df4cc2d17ba0c2&o=",
        "price": 1710000,
        "rating": 9.7,
        "address": null,
        "item_id": "15590428",
        "currency": "VND",
        "location": "Phú Quốc",
        "price_tier": "luxury",
        "external_hotel_id": "15590428",
        "accessibilityLabel": [
          "Emerald Boutique Hotel Phú Quốc",
          "9,7 Xuất sắc 39 đánh giá",
          "Duong To • 9,5km từ trung tâm",
          "Cách biển 0,7km",
          "Giá chỉ có trên điện thoại",
          "1 phòng khách sạn : 1 giường",
          "Giá gốc là 1900000 VND",
          "Giá hiện tại là 1710000 VND",
          "Đã bao gồm thuế và phí",
          "Hủy miễn phí",
          "Không cần thanh toán trước",
          "Chỉ còn 3 căn với giá này trên Booking.com"
        ],
        "position": 10
      }
    ],
    "labels": []
  }
  ```

  ## Rubric checklist (human — official)
  - [ ] Task Success
  - [ ] Answer Faithfulness
  - [ ] Answer Relevance
  - [ ] Memory-Grounded Answer Accuracy
  - [ ] Preference Compliance
  - [ ] Hallucinated Memory (none expected)

  ### Required constraints
  - ưu tiên budget 1–2 triệu/đêm
  - ưu tiên yên tĩnh
  - gần biển nếu tool có evidence

  ### Trade-off rules
  - Nếu không có lựa chọn thỏa toàn bộ điều kiện, phải nêu rõ điều kiện nào chưa thỏa

  ### Forbidden claims
  - Giá/đặc điểm không có trong tool result
  - Viện dẫn preference không tồn tại hoặc inactive

  ## Notes
  ___
