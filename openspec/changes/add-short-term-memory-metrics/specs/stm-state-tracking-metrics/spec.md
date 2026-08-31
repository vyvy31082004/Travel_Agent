## ADDED Requirements

### Requirement: Joint Goal Accuracy over structured state

The evaluator SHALL compute Joint Goal Accuracy (JGA) by comparing the agent's structured state at each labeled turn against a gold state, where a turn counts as correct only when every gold slot matches. The evaluator SHALL read state from `requests`, `latest_request_by_domain`, `active_request_id`, and `selected_items` in `src/agents/primary/state.py`. The report SHALL include `numerator`, `denominator`, and `value`; when `denominator` is `0`, `value` SHALL be `null`.

#### Scenario: All slots match
- **WHEN** a turn's agent state matches every gold slot (destination, check-in, check-out, guests, budget)
- **THEN** the turn contributes `1` to the JGA numerator

#### Scenario: One slot wrong
- **WHEN** a turn's agent state has the correct destination and dates but the wrong guest count
- **THEN** the turn contributes `0` to the JGA numerator even though other slots are correct

#### Scenario: No labeled turns
- **WHEN** the gold set contains no turns with a gold state
- **THEN** JGA `value` is `null` with `numerator` `0` and `denominator` `0`

### Requirement: Slot F1 over structured state

The evaluator SHALL compute Slot F1 from slot-level true positives, false positives, and false negatives, where a slot is correct only when both the slot name and its normalized value match gold. The report SHALL expose the counts used and a `value`; when there are no predicted and no gold slots, `value` SHALL be `null`.

#### Scenario: Partial slot overlap
- **WHEN** gold has four slots and the agent predicts three of them correctly plus one extra wrong slot
- **THEN** Precision, Recall, and F1 are computed from `true_positive = 3`, `false_positive = 1`, `false_negative = 1`

#### Scenario: Normalized value comparison
- **WHEN** gold `check_in` is `2026-09-15` and the agent stores `15/09/2026`
- **THEN** the slot counts as a match after normalization
