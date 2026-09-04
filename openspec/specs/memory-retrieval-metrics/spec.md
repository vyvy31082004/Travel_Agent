# memory-retrieval-metrics Specification

## Purpose
TBD - created by archiving change add-ltm-transition-retrieval-answer-metrics. Update Purpose after archive.
## Requirements
### Requirement: Recall@K
The system SHALL score

```text
Recall@K = relevant_retrieved_in_top_k / total_relevant_memories
```

`K` SHALL be `LONG_TERM_MEMORY_RECALL_LIMIT`. Ranking SHALL use `RecallResult.recalled_memory_ids` from `MemoryService.recall(...)`. Gold relevance is binary. The value SHALL be `null` when `total_relevant_memories` is `0`.

#### Scenario: All relevant ids are in top K
- **WHEN** two memories are gold-relevant and both appear in the top K ids
- **THEN** Recall@K is `1.0`

#### Scenario: One relevant id is missing
- **WHEN** two memories are gold-relevant and only one appears in the top K ids
- **THEN** Recall@K is `0.5`

### Requirement: Precision@K
The system SHALL score

```text
Precision@K = relevant_retrieved_in_top_k / K
```

#### Scenario: Noisy top K
- **WHEN** `K` is `5` and only one of the recalled ids is relevant
- **THEN** Precision@K is `0.2`

### Requirement: Cross-user leakage
The system SHALL score

```text
Cross-user Leakage Rate = memories_from_wrong_user / recalled_memories
```

with target `0`. The value SHALL be `null` when `recalled_memories` is `0`. A case still fails if any recalled id belongs to another user.

#### Scenario: Two users with similar preferences
- **WHEN** user-1 and user-2 both have an active boutique-hotel preference
- **AND** recall runs for user-1
- **THEN** no recalled id belongs to user-2

#### Scenario: User filter
- **WHEN** recall executes
- **THEN** results are scoped to the requesting `user_id`
- **AND** Postgres recall SHALL apply `m.user_id = %(user_id)s`

### Requirement: Inactive memory leakage
The system SHALL score

```text
Inactive Leakage Rate = superseded_or_deleted_or_expired_memories_returned / recalled_memories
```

with target `0`. Inactive means `status` is not `active`, `TravelMemory.is_active` is false, or the validity window is closed. The value SHALL be `null` when `recalled_memories` is `0`.

#### Scenario: Superseded memory returned
- **WHEN** recall returns a superseded memory id
- **THEN** Inactive Leakage Rate is greater than `0`

#### Scenario: Expired memory returned
- **WHEN** recall returns a memory with `valid_to` in the past
- **THEN** that id counts as inactive leakage

#### Scenario: Only active memories returned
- **WHEN** the store has active, superseded, deleted, and expired memories
- **AND** recall returns only active in-window memories
- **THEN** Inactive Leakage Rate is `0`

### Requirement: Retrieval gold coverage
The gold suite SHALL include ranking cases, a two-user isolation case, and inactive/expired/deleted cases. Each case SHALL have `case_id`, `user_id`, query, seeded memories, and binary relevant ids.

#### Scenario: Isolation and inactive cases exist
- **WHEN** the retrieval gold file is loaded
- **THEN** it contains a two-user similar-preference case and at least one superseded or expired memory case
