## Why

Current long-term memory verification is still a deterministic baseline and does not implement the TrustMem-inspired verifier described in `thiet_ke_toan_bo_long_term_memory.pdf`. This creates risk that approved memory transitions miss important durable details, distort existing valid memories, or add unsupported facts from tool output.

## What Changes

- Add an inference-time TrustMem-inspired verifier for local memory transitions `z_t = (chunk, M_old, actions, M_new)`.
- Score each proposed transition on three dimensions in `[0, 1]`: coverage, preservation, and faithfulness.
- Gate memory commits using score thresholds, structured reasons, and deterministic validation/audit before repository writes.
- Preserve the current deterministic verifier as fallback; do not add RL, training, or direct hot-path memory writes.
- Add structured verifier output to audit records so memory quality can be reviewed offline.
- Add tests and evaluation fixtures for travel-memory-specific failure modes such as missing conditional preferences, incorrect supersession, and unsupported tool-derived memories.

## Capabilities

### New Capabilities
- `trustmem-memory-verifier`: Inference-time verifier that evaluates long-term memory transitions by coverage, preservation, and faithfulness before commit.

### Modified Capabilities

## Impact

- Affects memory verification design around `src/memory/verifier.py`, `src/memory/consolidation.py`, `src/memory/commit.py`, and `memory_audit_records`.
- Adds verifier settings for provider/model, thresholds, timeout/fallback behavior, and prompt version.
- Adds tests for verifier scoring, commit gating, fallback behavior, malformed verifier output, and audit persistence.
- Does not change `/chat` API, MCP domain servers, pgvector recall, LangMem candidate extraction boundaries, or repository source-of-truth semantics.
- Does not implement TrustMem training/RL; only reuses the verifier idea at inference time.
