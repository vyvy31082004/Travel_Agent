## ADDED Requirements

### Requirement: Factual Recall Accuracy after summarization

The evaluator SHALL compute Factual Recall Accuracy by asking gold probe questions after the conversation summary is triggered and counting a probe correct when the agent's answer matches the gold fact taken from the original messages. Probe answers SHALL be scored against gold answers, not by free-form LLM judgement alone. The report SHALL include `numerator`, `denominator`, and `value`; when `denominator` is `0`, `value` SHALL be `null`.

#### Scenario: Fact retained after compression
- **WHEN** the user stated "tôi không muốn chuyến transit quá 3 giờ" before summarization, and later the probe asks the transit limit
- **THEN** the probe counts as correct only if the agent answers or applies the 3-hour limit

#### Scenario: Fact lost after compression
- **WHEN** the summarized history drops a required fact and the agent answers the probe incorrectly
- **THEN** the probe contributes `0` to the numerator

#### Scenario: Position-labeled probes
- **WHEN** probes are labeled by fact position (đầu, giữa, cuối) and by before/after summarization
- **THEN** the report groups accuracy by these labels so position bias is visible

#### Scenario: No probes
- **WHEN** the gold set contains no summary-recall probes
- **THEN** Factual Recall Accuracy `value` is `null`
