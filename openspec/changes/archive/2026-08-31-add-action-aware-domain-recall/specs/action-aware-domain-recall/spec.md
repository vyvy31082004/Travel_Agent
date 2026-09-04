## ADDED Requirements

### Requirement: Domain recall inside sub-agent graph
Each delegated sub-agent graph SHALL run `memory_recall_{domain}` as its first node before `{domain}_chat`.

#### Scenario: Hotel delegation
- **WHEN** primary delegates to hotel
- **THEN** the hotel sub-graph runs `memory_recall_hotel` then `hotel_chat`

### Requirement: SQL candidate pool without semantic search
`memory_recall_{domain}` SHALL fetch active memories via SQL filtered by `user_id` and `domain` only. The user query SHALL NOT be used for vector or ILIKE retrieval.

#### Scenario: Domain candidate lookup
- **WHEN** the hotel sub-agent recalls memories for an authenticated user
- **THEN** it fetches only that user's active hotel-domain candidates without vector or ILIKE query matching

### Requirement: Action-aware applicability judge
After inferring `domain_action`, the system SHALL run an LLM applicability judge on each candidate with labels APPLY, OVERRIDDEN, IRRELEVANT, or UNCERTAIN.

#### Scenario: Conflicting flight preference
- **WHEN** user asks for evening flights and memory says "prefer morning flights"
- **THEN** that memory is labeled OVERRIDDEN and excluded from hard constraints

### Requirement: Sub-agent memory isolation
Sub-agents SHALL NOT receive global `memory_context`, cross-domain state, or raw chat history.

#### Scenario: Flight sub-agent state isolation
- **WHEN** primary delegates a flight request to the flight sub-agent
- **THEN** the sub-agent receives only flight-scoped recalled memories and the current delegated request, not global memory context, cross-domain state, or raw chat history
