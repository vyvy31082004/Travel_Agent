## 1. Configuration and Contracts

- [ ] 1.1 Add verifier mode settings for `deterministic`, `trustmem`, and `trustmem-dry-run`.
- [ ] 1.2 Add TrustMem verifier model, timeout, prompt version, and coverage/preservation/faithfulness threshold settings.
- [ ] 1.3 Extend verifier result structures to include per-dimension score, reason, threshold, and pass/fail status.
- [ ] 1.4 Define the local transition payload shape for `chunk`, `M_old`, `actions`, and projected `M_new` without changing repository write semantics.

## 2. TrustMem-Inspired Verifier

- [ ] 2.1 Implement a `TrustMemInspiredMemoryVerifier` behind the existing `MemoryVerifier` interface.
- [ ] 2.2 Build a structured prompt/schema that asks only for coverage, preservation, faithfulness, decision, and reasons.
- [ ] 2.3 Validate verifier output strictly: required dimensions, numeric scores in `[0, 1]`, allowed decisions, and non-empty reasons on failure.
- [ ] 2.4 Convert malformed, timed-out, or provider-failed verifier calls into safe retry/reject results.
- [ ] 2.5 Implement threshold-gated approval logic where every dimension must pass before commit approval.

## 3. Pipeline Integration

- [ ] 3.1 Pass bounded job message chunk and relevant active `M_old` memories into verifier evaluation.
- [ ] 3.2 Compute projected `M_new` for insert, no-op, supersede, and reject transitions without mutating database state.
- [ ] 3.3 Keep deterministic validation and dry-run transition calculation mandatory before TrustMem verification.
- [ ] 3.4 Add `trustmem-dry-run` mode that audits TrustMem scores while preserving deterministic commit decisions.
- [ ] 3.5 Ensure verifier never commits directly; only the existing commit adapter can apply approved transitions.

## 4. Audit and Observability

- [ ] 4.1 Persist verifier mode, model, prompt version, dimension scores/reasons, thresholds, final decision, and fallback reason in `memory_audit_records.verifier_result`.
- [ ] 4.2 Add structured logs for TrustMem verifier decisions, low dimension scores, fallback, timeout, and malformed output.
- [ ] 4.3 Update debug/audit documentation to show how to inspect TrustMem verifier metadata.

## 5. Travel-Specific Tests and Fixtures

- [ ] 5.1 Add fixtures for coverage failures: business class for work plus economy for leisure where candidate omits leisure condition.
- [ ] 5.2 Add fixtures for preservation failures: existing conditional economy memory is over-generalized to always business.
- [ ] 5.3 Add fixtures for faithfulness failures: tool hotel result near station is stored as user preference without confirmation.
- [ ] 5.4 Add approval fixture where user explicitly confirms a tool-derived option and candidate remains faithful.
- [ ] 5.5 Add tests for deterministic mode, TrustMem gated mode, TrustMem dry-run mode, and fallback on verifier failure.
- [ ] 5.6 Add tests that malformed scores outside `[0, 1]` cannot approve transitions.

## 6. Documentation and Validation

- [ ] 6.1 Document TrustMem-inspired verifier behavior, settings, dimensions, thresholds, and non-goals in long-term memory docs.
- [ ] 6.2 Document that this change does not implement RL/training and does not add hot-path memory writes.
- [ ] 6.3 Run targeted memory verifier tests and existing long-term memory tests.
- [ ] 6.4 Run OpenSpec validation for `add-trustmem-memory-verifier` and resolve issues.
