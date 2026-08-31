## ADDED Requirements

### Requirement: Success Rate for multi-turn scenarios

The evaluator SHALL compute Success Rate over multi-turn scenarios, counting a scenario successful only when the final action or response satisfies every active gold constraint. Scenarios where the user changes their mind SHALL be scored through the same Success Rate, not a separate knowledge-update metric. The report SHALL include `numerator`, `denominator`, and `value`; when `denominator` is `0`, `value` SHALL be `null`.

#### Scenario: Multi-turn booking satisfies all constraints
- **WHEN** a scenario runs search → display list → user picks "khách sạn thứ 2" → change stay dates → confirm
- **THEN** the scenario succeeds only if the system selects the correct item, uses the latest dates, and keeps all still-active constraints

#### Scenario: User changes mind mid-scenario
- **WHEN** the user updates a constraint (e.g., "đổi sang ngày 16") during the scenario
- **THEN** the scenario succeeds only if the final action uses the updated value

#### Scenario: Missing a final constraint
- **WHEN** the final action violates any active gold constraint
- **THEN** the scenario contributes `0` to the numerator

#### Scenario: No scenarios
- **WHEN** the gold set contains no scenarios
- **THEN** Success Rate `value` is `null`
