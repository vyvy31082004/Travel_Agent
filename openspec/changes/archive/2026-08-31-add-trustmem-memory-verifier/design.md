## Context

The long-term memory pipeline already has deterministic validation, dry-run transition calculation, audit, and a `MemoryVerifier` interface. Current implementation is a conservative deterministic baseline: it can approve/reject/no-op based on transition action, but it does not evaluate the full local transition `z_t = (chunk, M_old, actions, M_new)` with TrustMem-style dimensions.

The PDF design describes a TrustMem-inspired verifier that scores local transitions on coverage, preservation, and faithfulness. This change should implement that idea at inference time only. It must not introduce TrustMem training, RL, or direct memory writes outside the existing commit adapter.

## Goals / Non-Goals

**Goals:**

- Add a verifier contract that evaluates a proposed local memory transition using the current chunk, previous active memories, proposed actions, and proposed new memory state.
- Score coverage, preservation, and faithfulness independently in `[0, 1]`.
- Gate commits using configurable thresholds and structured reasons.
- Persist verifier dimensions/scores/reasons in existing audit output.
- Keep deterministic validation, dry-run transition calculation, and repository commit adapter mandatory.
- Provide deterministic/fake verifier tests and fixture cases for travel-specific examples.
- Keep fallback behavior safe when LLM verifier is disabled, times out, or returns malformed output.

**Non-Goals:**

- Do not implement RL, training, reward modeling, or candidate ranking for model training.
- Do not let the verifier directly insert/update/delete memory records.
- Do not run verifier on the `/chat` response hot path before final answer.
- Do not replace deterministic validation; TrustMem-inspired verification is an additional gate.
- Do not require a UI console for reviewing verifier output in this change.

## Decisions

### Use inference-time verifier only

The original TrustMem concept uses a frozen LLM to judge local transitions and produce scores that can supervise/rank candidates during training. This project will reuse only the inference-time verifier idea: evaluate each proposed transition before commit and write structured audit metadata.

Rationale:

- Keeps implementation aligned with the current worker/outbox architecture.
- Avoids unnecessary RL/training complexity.
- Preserves auditability and deterministic fallback.

### Evaluate local transition object

The verifier input should include:

```text
z_t = {
  chunk: bounded completed-turn message chunk,
  M_old: relevant active memories before transition,
  actions: proposed action/transition metadata,
  M_new: candidate memory state after applying proposed action in dry-run form
}
```

Mapping to current code:

- `chunk`: memory job messages / serialized final turn context.
- `M_old`: active memories loaded before transition calculation.
- `actions`: `MemoryTransition.action`, reasons, existing memory id.
- `M_new`: candidate `TravelMemory` and projected active memory state after insert/supersede/noop/reject.

### Score three dimensions

The verifier must return:

```json
{
  "coverage": {"score": 0.0, "reason": "..."},
  "preservation": {"score": 0.0, "reason": "..."},
  "faithfulness": {"score": 0.0, "reason": "..."},
  "decision": "approve|reject|retry|noop",
  "reasons": ["..."]
}
```

Dimension meaning for travel memory:

- **Coverage**: important durable information in the chunk is sufficiently preserved in proposed memory changes.
- **Preservation**: valid old memories are not incorrectly deleted, distorted, over-generalized, or merged with lost conditions.
- **Faithfulness**: new/changed memory content is supported by user evidence in chunk or by valid `M_old`; tool/API facts alone are not treated as user preference.

### Threshold-gated decision

Default thresholds should be conservative:

```text
coverage >= 0.80
preservation >= 0.90
faithfulness >= 0.95
```

A transition is approved only if deterministic rules pass and all verifier dimensions meet threshold. Faithfulness should be the strictest threshold because unsupported memory creates lasting user-profile corruption.

### Preserve deterministic verifier as fallback

Add settings to select verifier mode:

```text
LONG_TERM_MEMORY_VERIFIER=deterministic|trustmem|trustmem-dry-run
LONG_TERM_MEMORY_TRUSTMEM_MODEL=<model>
LONG_TERM_MEMORY_TRUSTMEM_TIMEOUT_SECONDS=<seconds>
LONG_TERM_MEMORY_TRUSTMEM_COVERAGE_THRESHOLD=0.80
LONG_TERM_MEMORY_TRUSTMEM_PRESERVATION_THRESHOLD=0.90
LONG_TERM_MEMORY_TRUSTMEM_FAITHFULNESS_THRESHOLD=0.95
```

Modes:

- `deterministic`: current baseline behavior.
- `trustmem`: TrustMem-inspired scores gate commits.
- `trustmem-dry-run`: run scorer and audit scores, but commit decision still follows deterministic verifier until quality is accepted.

### Audit everything

`memory_audit_records.verifier_result` should include model, prompt version, dimension scores, threshold comparison, raw/normalized decision, and failure/fallback reason. No additional audit table is required unless current JSONB audit becomes insufficient.

## Risks / Trade-offs

- **Risk: LLM verifier rejects too many useful memories** → Mitigation: dry-run mode, thresholds configurable, fixture-based calibration.
- **Risk: LLM verifier hallucinates score/reasons** → Mitigation: structured schema validation, malformed output causes retry/fallback rather than commit.
- **Risk: Added worker latency/cost** → Mitigation: worker-side only, timeout setting, deterministic fallback.
- **Risk: Over-generalization still slips through** → Mitigation: preservation prompt/examples focus on conditions such as business vs leisure, family vs solo travel.
- **Risk: Faithfulness misses tool-output pollution** → Mitigation: explicitly include tool/API examples and require user evidence for preferences.

## Migration Plan

1. Add config and verifier result data structures.
2. Add TrustMem-inspired prompt/schema and parser behind `MemoryVerifier`.
3. Pass enough context into verifier to evaluate `chunk`, `M_old`, `actions`, and projected `M_new`.
4. Write dimension scores into existing `verifier_result` audit JSONB.
5. Add dry-run mode and tests before enabling commit gating.
6. Roll out with `LONG_TERM_MEMORY_VERIFIER=trustmem-dry-run` in staging.
7. Enable `trustmem` mode only after score calibration passes fixture benchmarks.

## Open Questions

- Which LLM provider/model should be the default frozen verifier in this project environment?
- Should supersession transitions require higher preservation threshold than insert transitions?
- Should coverage failures block commits or only trigger retry when the extracted candidate is incomplete but not harmful?
