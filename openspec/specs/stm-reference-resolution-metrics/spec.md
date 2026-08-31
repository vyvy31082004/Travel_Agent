# stm-reference-resolution-metrics Specification

## Purpose
TBD - created by archiving change add-short-term-memory-metrics. Update Purpose after archive.
## Requirements
### Requirement: Resolution Accuracy for item references

The evaluator SHALL compute Resolution Accuracy by running `resolve_item_reference(...)` over gold reference cases and counting a case correct when the resolver returns the gold `item_id`, or returns `ClarificationNeeded` when the gold label marks the reference as ambiguous. The report SHALL include `numerator`, `denominator`, and `value`; when `denominator` is `0`, `value` SHALL be `null`.

#### Scenario: Ordinal reference resolves to correct item
- **WHEN** the user says "khách sạn thứ 2" and `visible_results` lists hotels in order
- **THEN** the resolver returns the second displayed `item_id` and the case counts as correct

#### Scenario: Ambiguous reference requires clarification
- **WHEN** the gold label marks a reference as ambiguous because multiple domains match
- **THEN** the case counts as correct only if the resolver returns `ClarificationNeeded` instead of guessing an item

#### Scenario: Wrong item resolved
- **WHEN** the resolver returns an `item_id` different from the gold `item_id`
- **THEN** the case contributes `0` to the numerator

#### Scenario: No labeled references
- **WHEN** the gold set contains no reference cases
- **THEN** Resolution Accuracy `value` is `null`
