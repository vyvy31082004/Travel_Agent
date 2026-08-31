## Why

Long-term memory recall needs tiered scopes: global profile/rules/general preferences before primary routing, and domain-specific travel preferences only when a domain branch is delegated. Primary orchestrates multi-domain trip planning via parallel domain Send without a separate travel planner subgraph.

## What Changes

- Add `memory_recall_global` before `primary_assistant` (profile, interaction rules, general preference).
- Add `domain_recall` nodes on the primary graph, activated only for delegated domains.
- Branch-local state for `delegated_request`, `turn_constraints`, and `domain_memory_context` on each `Send` copy.
- `DomainBranchResult` returned directly from domain wrappers; `join_results` merges via reducers.
- Remove `travel_planner_assistant` from production primary graph.
- Trip plan requests require parallel delegation to flight, hotel, excursion, and car.

## Capabilities

### New Capabilities
- `tiered-memory-recall`: Global vs domain recall tiers, branch-local state, structured domain branch results, primary synthesis.

## Impact

- `src/repositories/long_term_memory.py`, `src/services/long_term_memory.py`
- `src/memory/recall_nodes.py`, `src/agents/primary/agent.py`, `src/agents/primary/state.py`
- `src/agents/primary/domain_result.py`, `src/prompts/prompt.py`
- `src/memory/domain_runtime.py`
