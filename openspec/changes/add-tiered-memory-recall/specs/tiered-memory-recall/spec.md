## ADDED Requirements

### Requirement: Global recall before primary routing
The system SHALL recall profile facts, interaction rules, and general preferences before the primary assistant routes or answers.

#### Scenario: User starts a turn
- **WHEN** an authenticated user sends a message
- **THEN** `memory_recall_global` runs once with the user message as query
- **AND** recalled context excludes domain-specific travel preferences (hotel/flight/car/excursion)

### Requirement: Domain recall on delegated branches only
The system SHALL run domain recall only for domains the primary assistant delegates in that turn.

#### Scenario: Single-domain hotel request
- **WHEN** primary delegates only to hotel
- **THEN** only the hotel domain recall branch runs

#### Scenario: Trip plan request
- **WHEN** primary recognizes a multi-day trip plan request
- **THEN** it delegates in parallel to flight, hotel, excursion, and car
- **AND** each delegated branch runs its own domain recall with `delegated_request` as query

### Requirement: Branch-local delegation state
The system SHALL keep `delegated_request`, `turn_constraints`, and `domain_memory_context` on each parallel Send copy, not on shared parent state with last-write reducers.

#### Scenario: Parallel delegation isolation
- **WHEN** hotel and flight branches execute in parallel
- **THEN** each branch retains its own delegated request, constraints, and domain memory context without overwriting the other branch

### Requirement: Structured domain branch results
Each domain wrapper SHALL return a `DomainBranchResult` object via state update with domain, options, applied_constraints, warnings, and summary.

#### Scenario: Parallel branches join
- **WHEN** multiple domain branches complete
- **THEN** `join_results` merges `domain_branch_results` and `recalled_memory_ids` via reducers
- **AND** primary synthesizes the final itinerary without calling MCP tools or delegating again

### Requirement: Per-domain turn constraints
The primary assistant SHALL assign turn constraints per domain and pass only the relevant list to each delegation tool.

#### Scenario: Hotel-only constraints
- **WHEN** a turn includes hotel and flight constraints
- **THEN** the hotel delegation receives only hotel-relevant constraints and the flight delegation receives only flight-relevant constraints

### Requirement: Memory finalize scope
`memory_finalize` SHALL enqueue durable preference extraction only and SHALL NOT persist MCP results, prices, IDs, search refs, or temporary itineraries.

#### Scenario: Finalize after tool results
- **WHEN** a turn contains MCP results and temporary itinerary data
- **THEN** memory finalization enqueues only durable preference extraction and excludes tool results, prices, IDs, search references, and temporary itinerary data
