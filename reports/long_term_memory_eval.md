# Extraction eval — split=dev

- Extractor: `deterministic`
- Cases: 60
- Generated: 2026-08-23T13:08:05.205329+00:00

## Metrics

| Metric | Value |
|--------|------:|
| Precision | 0.875 |
| Recall | 0.700 |
| Faithfulness | 1.000 |
| Unsafe Rejection | 1.000 |
| Sensitive stored | 0 |

## Gates

- PASS: Precision>=0.85
- PASS: Recall>=0.70
- PASS: Faithfulness>=0.95
- PASS: UnsafeReject>=0.98
- PASS: SensitiveStored=0

## Failures (sample)

- extract_hotel_pref_001: recall miss — missing gold [['gần biển']]; got ['thích khách sạn boutique gần biển']
- extract_hotel_multi_001: recall miss — missing gold [['gần biển'], ['yên tĩnh']]; got ['thích khách sạn boutique gần biển, yên tĩnh']
- extract_flight_multi_001: recall miss — missing gold [['cửa sổ'], ['transit']]; got ['ưu tiên bay thẳng, ghế cửa sổ, không thích transit lâu']
- extract_flight_condition_002: recall miss — missing gold [['cửa sổ']]; got ['ưu tiên ghế cửa sổ khi đi công tác']
- extract_hotel_pref_005: recall miss — missing gold [['view biển']]; got ['thích phòng view biển']
- extract_hotel_pref_009: recall miss — missing gold [['gần sân bay']]; got ['thích khách sạn gần sân bay']
- extract_flight_pref_003: recall miss — missing gold [['Vietnam Airlines']]; got ['ưu tiên hãng Vietnam Airlines']
- extract_flight_pref_009: recall miss — missing gold [['HAN']]; got []
- extract_hotel_multi_002: recall miss — missing gold [['view núi'], ['gần hồ']]; got ['thích khách sạn có ban công, view núi, gần hồ']
- extract_flight_condition_003: recall miss — missing gold [['economy']]; got ['thích economy khi đi du lịch tự túc']
- extract_profile_005: recall miss — missing gold [['lan@example.com']]; got []
- extract_interaction_003: recall miss — missing gold [['tiếng Việt']]; got []
