## Why

Domain memory recall must run after the sub-agent knows its current action, using SQL candidate pools and an LLM applicability judge. Recall nodes belong inside each sub-agent graph, not on the primary graph.

## What Changes

- Move `memory_recall_{domain}` into hotel/flight/car/excursion sub-agent graphs.
- Remove `*_domain_recall` nodes from the primary graph; primary `Send`s directly to `*_assistant`.
- SQL fetch all active memories for user+domain (no semantic search on query).
- LLM applicability judge: APPLY, OVERRIDDEN, IRRELEVANT, UNCERTAIN.
- Sub-agents do not receive global memory or cross-domain state.

## Capabilities

### New Capabilities
- `action-aware-domain-recall`: Action inference, SQL candidate pool, applicability judge, sub-agent isolation.

## Impact

- `src/memory/domain_actions.py`, `src/memory/task_router.py`, `src/memory/applicability.py`
- `src/memory/recall_nodes.py`, `src/services/long_term_memory.py`, `src/repositories/long_term_memory.py`
- `src/agents/primary/agent.py`, `src/agents/primary/domain_scope.py`
- `src/agents/{hotel,flight,car,excursion}/agent.py`
- `src/memory/domain_runtime.py`, `src/settings.py`
