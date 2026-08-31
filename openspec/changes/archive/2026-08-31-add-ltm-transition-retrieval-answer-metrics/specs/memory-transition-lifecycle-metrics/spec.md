## ADDED Requirements

### Requirement: Transition decision accuracy
The system SHALL score

```text
Transition Accuracy = correct_transition_decisions / labeled_transition_cases
```

by comparing `calculate_transition(...)`.action to a gold label in `{INSERT, NOOP, SUPERSEDE, REJECT}`. The value SHALL be `null` when the denominator is `0`.

#### Scenario: Duplicate preference
- **WHEN** the candidate matches an existing active memory
- **THEN** the predicted action is `NOOP`

#### Scenario: Preference conflict
- **WHEN** the candidate conflicts with an existing active memory in the same category and domain
- **THEN** the predicted action is `SUPERSEDE`

#### Scenario: Updated condition
- **WHEN** the candidate changes a durable condition of an existing active preference
- **THEN** the predicted action is `SUPERSEDE`

#### Scenario: Sensitive reject
- **WHEN** evidence contains passport, card, CVV, or password data
- **THEN** the predicted action is `REJECT`

#### Scenario: Ambiguous reject
- **WHEN** evidence is ambiguous
- **THEN** the predicted action is `REJECT`

#### Scenario: New preference insert
- **WHEN** the candidate is valid and does not match or conflict with existing active memories
- **THEN** the predicted action is `INSERT`

### Requirement: Transition gold coverage
The gold suite SHALL include duplicate, conflict, updated condition, sensitive reject, and ambiguous reject cases. Each case SHALL have `case_id`, existing memories, candidate, and gold action.

#### Scenario: Required case types are present
- **WHEN** the transition gold file is loaded
- **THEN** it contains at least one case for each of duplicate, conflict, updated condition, sensitive reject, and ambiguous reject

### Requirement: Supersession correctness
The system SHALL score

```text
Supersession Correctness = correct_supersede_cases / conflict_cases
```

A conflict case is correct only after commit if:

1. the old memory is not active (`status` superseded or `TravelMemory.is_active` is false);
2. the new memory `supersedes_memory_id` equals the old memory id;
3. `MemoryService.recall(...)` does not return the old memory id.

#### Scenario: Old memory still active
- **WHEN** the old memory remains active after the new preference is stored
- **THEN** the case is incorrect

#### Scenario: Missing supersedes_memory_id
- **WHEN** the new memory does not set `supersedes_memory_id`
- **THEN** the case is incorrect

#### Scenario: Recall returns old and new
- **WHEN** recall returns both the superseded id and the new id
- **THEN** the case is incorrect

#### Scenario: Correct supersession
- **WHEN** commit uses `mark_memory_superseded(...)` and inserts the linked new memory
- **THEN** the old memory is inactive, the new memory links the old id, recall excludes the old id, and the case is correct
