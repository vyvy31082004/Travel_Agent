"""Evaluate TravelMemory candidate extraction against gold JSONL."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from memory.consolidation import (
    MemoryCandidateExtractor,
    extract_candidate_memories,
    validate_memory_candidate,
)
from memory.long_term import CATEGORY_FAMILY, MemoryCategory, TravelMemory
from memory_eval.semantic_match import (
    CallableSemanticJudge,
    ExactThenLlmSemanticJudge,
    SemanticJudge,
    build_equivalence_matrix,
    maximum_bipartite_matching,
    normalize_match_text,
)


RECOMMENDED_RELEASE_TARGETS: dict[str, float] = {
    "semantic_extraction_precision": 0.85,
    "semantic_extraction_recall": 0.70,
    "evidence_faithfulness_rate": 0.95,
    "no_store_rejection_rate": 0.98,
    "unsafe_rejection_rate": 0.98,
}


@dataclass(frozen=True)
class GoldMemory:
    memory_text: str
    category: str
    domain: str
    family: str
    aliases: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GoldMemory":
        category = str(raw["category"])
        domain = str(raw["domain"])
        family = str(raw.get("family") or CATEGORY_FAMILY[MemoryCategory(category)])
        return cls(
            memory_text=str(raw["memory_text"]),
            category=category,
            domain=domain,
            family=family,
            aliases=tuple(str(value) for value in raw.get("aliases", [])),
        )


@dataclass(frozen=True)
class CandidateExtractionCase:
    case_id: str
    messages: tuple[dict[str, Any], ...]
    gold_memories: tuple[GoldMemory, ...] = ()
    unsafe: bool = False
    expected_store: bool = True
    description: str = ""
    requirement_id: str = "REQ-EXTRACTION"
    risk: str = ""
    split: str = "test"
    code_path: tuple[str, ...] = ()
    metric: tuple[str, ...] = ()
    rationale: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CandidateExtractionCase":
        gold_memories = tuple(
            GoldMemory.from_dict(memory) for memory in raw.get("gold_memories", [])
        )
        if "expected_store" in raw:
            expected_store = bool(raw["expected_store"])
        else:
            # Migration default: empty gold => no-store; non-empty => expect store.
            expected_store = bool(gold_memories)
        return cls(
            case_id=str(raw["case_id"]),
            messages=tuple(dict(message) for message in raw.get("messages", [])),
            gold_memories=gold_memories,
            unsafe=bool(raw.get("unsafe", False)),
            expected_store=expected_store,
            description=str(raw.get("description", "")),
            requirement_id=str(raw.get("requirement_id", "REQ-EXTRACTION")),
            risk=str(raw.get("risk", "")),
            split=str(raw.get("split", "test")),
            code_path=tuple(str(value) for value in raw.get("code_path", [])),
            metric=tuple(str(value) for value in raw.get("metric", [])),
            rationale=str(raw.get("rationale", "")),
        )


@dataclass(frozen=True)
class MetricValue:
    numerator: int
    denominator: int
    value: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
        }


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _case_prf1(
    tp: int, fp: int, fn: int
) -> tuple[float | None, float | None, float | None]:
    """Case-level P/R/F1; null when TP=FP=FN=0 (N/A)."""
    if tp == 0 and fp == 0 and fn == 0:
        return None, None, None
    precision = None if (tp + fp) == 0 else tp / (tp + fp)
    recall = None if (tp + fn) == 0 else tp / (tp + fn)
    return precision, recall, _f1(precision, recall)


@dataclass(frozen=True)
class CaseEvaluation:
    case_id: str
    requirement_id: str
    risk: str
    split: str
    code_path: tuple[str, ...]
    metric: tuple[str, ...]
    rationale: str
    unsafe: bool
    expected_store: bool
    extracted: tuple[dict[str, Any], ...]
    matched_gold_indices: tuple[int, ...]
    true_positives: int
    false_positives: int
    false_negatives: int
    semantic_extraction_precision: float | None
    semantic_extraction_recall: float | None
    semantic_extraction_f1: float | None
    valid_extracted_count: int
    correctly_extracted_count: int
    guardrail_approved_count: int
    faithful_extracted_count: int
    correctly_rejected_no_store: bool | None
    correctly_rejected_unsafe: bool | None
    category_correct: int
    domain_correct: int
    family_correct: int
    matched_pair_count: int
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "requirement_id": self.requirement_id,
            "risk": self.risk,
            "split": self.split,
            "code_path": list(self.code_path),
            "metric": list(self.metric),
            "rationale": self.rationale,
            "unsafe": self.unsafe,
            "expected_store": self.expected_store,
            "extracted": list(self.extracted),
            "matched_gold_indices": list(self.matched_gold_indices),
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "semantic_extraction_precision": self.semantic_extraction_precision,
            "semantic_extraction_recall": self.semantic_extraction_recall,
            "semantic_extraction_f1": self.semantic_extraction_f1,
            "valid_extracted_count": self.valid_extracted_count,
            "correctly_extracted_count": self.correctly_extracted_count,
            "guardrail_approved_count": self.guardrail_approved_count,
            "faithful_extracted_count": self.faithful_extracted_count,
            "correctly_rejected_no_store": self.correctly_rejected_no_store,
            "correctly_rejected_unsafe": self.correctly_rejected_unsafe,
            "category_correct": self.category_correct,
            "domain_correct": self.domain_correct,
            "family_correct": self.family_correct,
            "matched_pair_count": self.matched_pair_count,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class CandidateExtractionReport:
    total_cases: int
    total_extracted_memories: int
    true_positives: int
    false_positives: int
    false_negatives: int
    valid_extracted_memories: int
    correctly_extracted_gold_memories: int
    total_gold_memories: int
    memories_supported_by_user_evidence: int
    approved_memories: int
    category_correct: int
    category_labeled_cases: int
    domain_correct: int
    domain_labeled_cases: int
    family_correct: int
    family_labeled_cases: int
    correctly_rejected_no_store_cases: int
    no_store_cases: int
    correctly_rejected_unsafe_cases: int
    unsafe_gold_cases: int
    cases: tuple[CaseEvaluation, ...] = field(default_factory=tuple)

    @staticmethod
    def ratio(numerator: int, denominator: int) -> float | None:
        return None if denominator == 0 else numerator / denominator

    @property
    def semantic_extraction_precision(self) -> MetricValue:
        denom = self.true_positives + self.false_positives
        return MetricValue(
            self.true_positives,
            denom,
            self.ratio(self.true_positives, denom),
        )

    @property
    def semantic_extraction_recall(self) -> MetricValue:
        denom = self.true_positives + self.false_negatives
        return MetricValue(
            self.true_positives,
            denom,
            self.ratio(self.true_positives, denom),
        )

    @property
    def semantic_extraction_f1(self) -> MetricValue:
        precision = self.semantic_extraction_precision.value
        recall = self.semantic_extraction_recall.value
        value = _f1(precision, recall)
        # Represent F1 as a derived metric; numerator/denominator unused.
        return MetricValue(0, 0, value)

    # Backward-compatible aliases used by older tests / reports.
    @property
    def extraction_precision(self) -> MetricValue:
        return self.semantic_extraction_precision

    @property
    def extraction_recall(self) -> MetricValue:
        return self.semantic_extraction_recall

    @property
    def evidence_faithfulness_rate(self) -> MetricValue:
        return MetricValue(
            self.memories_supported_by_user_evidence,
            self.approved_memories,
            self.ratio(
                self.memories_supported_by_user_evidence, self.approved_memories
            ),
        )

    @property
    def category_accuracy(self) -> MetricValue:
        return MetricValue(
            self.category_correct,
            self.category_labeled_cases,
            self.ratio(self.category_correct, self.category_labeled_cases),
        )

    @property
    def domain_accuracy(self) -> MetricValue:
        return MetricValue(
            self.domain_correct,
            self.domain_labeled_cases,
            self.ratio(self.domain_correct, self.domain_labeled_cases),
        )

    @property
    def family_accuracy(self) -> MetricValue:
        return MetricValue(
            self.family_correct,
            self.family_labeled_cases,
            self.ratio(self.family_correct, self.family_labeled_cases),
        )

    @property
    def no_store_rejection_rate(self) -> MetricValue:
        return MetricValue(
            self.correctly_rejected_no_store_cases,
            self.no_store_cases,
            self.ratio(
                self.correctly_rejected_no_store_cases, self.no_store_cases
            ),
        )

    @property
    def unsafe_rejection_rate(self) -> MetricValue:
        return MetricValue(
            self.correctly_rejected_unsafe_cases,
            self.unsafe_gold_cases,
            self.ratio(
                self.correctly_rejected_unsafe_cases, self.unsafe_gold_cases
            ),
        )

    def metrics(self) -> dict[str, MetricValue]:
        return {
            "semantic_extraction_precision": self.semantic_extraction_precision,
            "semantic_extraction_recall": self.semantic_extraction_recall,
            "semantic_extraction_f1": self.semantic_extraction_f1,
            "extraction_precision": self.extraction_precision,
            "extraction_recall": self.extraction_recall,
            "evidence_faithfulness_rate": self.evidence_faithfulness_rate,
            "category_accuracy": self.category_accuracy,
            "domain_accuracy": self.domain_accuracy,
            "family_accuracy": self.family_accuracy,
            "no_store_rejection_rate": self.no_store_rejection_rate,
            "unsafe_rejection_rate": self.unsafe_rejection_rate,
        }

    def release_gate_results(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        metrics = self.metrics()
        for name, target in RECOMMENDED_RELEASE_TARGETS.items():
            measured = metrics[name].value
            results[name] = {
                "target": target,
                "measured": measured,
                "passed": None if measured is None else measured >= target,
            }
        return results

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "total_extracted_memories": self.total_extracted_memories,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "valid_extracted_memories": self.valid_extracted_memories,
            "correctly_extracted_gold_memories": self.correctly_extracted_gold_memories,
            "total_gold_memories": self.total_gold_memories,
            "memories_supported_by_user_evidence": self.memories_supported_by_user_evidence,
            "approved_memories": self.approved_memories,
            "category_correct": self.category_correct,
            "category_labeled_cases": self.category_labeled_cases,
            "domain_correct": self.domain_correct,
            "domain_labeled_cases": self.domain_labeled_cases,
            "family_correct": self.family_correct,
            "family_labeled_cases": self.family_labeled_cases,
            "correctly_rejected_no_store_cases": self.correctly_rejected_no_store_cases,
            "no_store_cases": self.no_store_cases,
            "correctly_rejected_unsafe_cases": self.correctly_rejected_unsafe_cases,
            "unsafe_gold_cases": self.unsafe_gold_cases,
            "metrics": {
                name: metric.to_dict() for name, metric in self.metrics().items()
            },
            "recommended_release_gates": self.release_gate_results(),
            "cases": [case.to_dict() for case in self.cases],
        }


class CandidateExtractionEvaluator:
    """Evaluate extraction with semantic 1-1 matching and separate faithfulness."""

    def __init__(
        self,
        extractor: MemoryCandidateExtractor | None = None,
        *,
        judge: SemanticJudge | None = None,
        judge_model: str | None = None,
        user_id: str = "eval-user",
        thread_prefix: str = "eval-thread",
    ) -> None:
        self.extractor = extractor
        if judge is not None:
            self.judge = judge
        elif judge_model:
            self.judge = ExactThenLlmSemanticJudge(model=judge_model)
        else:
            # Offline default: exact/normalize match only (no LLM calls).
            self.judge = CallableSemanticJudge()
        self.user_id = user_id
        self.thread_prefix = thread_prefix

    async def evaluate(
        self, cases: Sequence[CandidateExtractionCase]
    ) -> CandidateExtractionReport:
        evaluated: list[CaseEvaluation] = []
        for case in cases:
            if self.extractor is None:
                extracted = extract_candidate_memories(
                    case.messages,
                    user_id=self.user_id,
                    thread_id=f"{self.thread_prefix}:{case.case_id}",
                )
            else:
                extracted = await self.extractor.extract(
                    case.messages,
                    user_id=self.user_id,
                    thread_id=f"{self.thread_prefix}:{case.case_id}",
                )
            evaluated.append(await self._evaluate_case(case, extracted))

        matched_pairs = sum(case.matched_pair_count for case in evaluated)
        return CandidateExtractionReport(
            total_cases=len(evaluated),
            total_extracted_memories=sum(len(case.extracted) for case in evaluated),
            true_positives=sum(case.true_positives for case in evaluated),
            false_positives=sum(case.false_positives for case in evaluated),
            false_negatives=sum(case.false_negatives for case in evaluated),
            valid_extracted_memories=sum(
                case.valid_extracted_count for case in evaluated
            ),
            correctly_extracted_gold_memories=sum(
                case.correctly_extracted_count for case in evaluated
            ),
            total_gold_memories=sum(len(case.gold_memories) for case in cases),
            memories_supported_by_user_evidence=sum(
                case.faithful_extracted_count for case in evaluated
            ),
            approved_memories=sum(
                case.guardrail_approved_count for case in evaluated
            ),
            category_correct=sum(case.category_correct for case in evaluated),
            category_labeled_cases=matched_pairs,
            domain_correct=sum(case.domain_correct for case in evaluated),
            domain_labeled_cases=matched_pairs,
            family_correct=sum(case.family_correct for case in evaluated),
            family_labeled_cases=matched_pairs,
            correctly_rejected_no_store_cases=sum(
                1
                for case in evaluated
                if case.correctly_rejected_no_store is True
            ),
            no_store_cases=sum(1 for case in cases if not case.expected_store),
            correctly_rejected_unsafe_cases=sum(
                1
                for case in evaluated
                if case.correctly_rejected_unsafe is True
            ),
            unsafe_gold_cases=sum(1 for case in cases if case.unsafe),
            cases=tuple(evaluated),
        )

    async def _evaluate_case(
        self,
        case: CandidateExtractionCase,
        extracted: Sequence[TravelMemory],
    ) -> CaseEvaluation:
        errors: list[str] = []
        approved: list[TravelMemory] = []
        for candidate in extracted:
            rule = validate_memory_candidate(candidate)
            if rule.ok:
                approved.append(candidate)
            else:
                errors.extend(rule.reasons)

        guardrail_approved_count = len(approved)
        golds = case.gold_memories

        pred_texts = [candidate.memory_text for candidate in approved]
        gold_texts = [gold.memory_text for gold in golds]
        gold_aliases = [gold.aliases for gold in golds]

        if approved and golds:
            matrix = await build_equivalence_matrix(
                pred_texts,
                gold_texts,
                self.judge,
                gold_aliases=gold_aliases,
            )
            pairs = maximum_bipartite_matching(matrix)
        else:
            pairs = []

        matched_pred = {pi for pi, _ in pairs}
        matched_gold = {gi for _, gi in pairs}
        true_positives = len(pairs)
        false_positives = sum(
            1 for index in range(len(approved)) if index not in matched_pred
        )
        false_negatives = sum(
            1 for index in range(len(golds)) if index not in matched_gold
        )

        for index, candidate in enumerate(approved):
            if index not in matched_pred:
                errors.append("candidate did not match a gold atomic memory")

        category_correct = 0
        domain_correct = 0
        family_correct = 0
        matched_gold_indices: list[int] = []
        for pred_index, gold_index in sorted(pairs):
            matched_gold_indices.append(gold_index)
            candidate = approved[pred_index]
            gold = golds[gold_index]
            category_correct += int(str(candidate.category) == gold.category)
            domain_correct += int(str(candidate.domain) == gold.domain)
            family_correct += int(str(candidate.family) == gold.family)

        # Semantic extraction TP does not require label correctness.
        valid_count = true_positives
        correctly_extracted_count = true_positives

        faithful_count = 0
        for candidate in approved:
            span_ok = _supported_by_user_message(candidate, case.messages)
            if not span_ok:
                continue
            if await self.judge.evidence_supports(
                candidate.evidence_text, candidate.memory_text
            ):
                faithful_count += 1

        has_approved = guardrail_approved_count > 0
        rejected_no_store: bool | None = None
        if not case.expected_store:
            rejected_no_store = not has_approved
            if has_approved:
                errors.append("no-store case produced a guardrail-approved candidate")

        rejected_unsafe: bool | None = None
        if case.unsafe:
            rejected_unsafe = not has_approved
            if has_approved:
                errors.append("unsafe case produced a guardrail-approved candidate")

        precision, recall, f1 = _case_prf1(
            true_positives, false_positives, false_negatives
        )

        return CaseEvaluation(
            case_id=case.case_id,
            requirement_id=case.requirement_id,
            risk=case.risk,
            split=case.split,
            code_path=case.code_path,
            metric=case.metric,
            rationale=case.rationale,
            unsafe=case.unsafe,
            expected_store=case.expected_store,
            extracted=tuple(candidate.to_record() for candidate in extracted),
            matched_gold_indices=tuple(matched_gold_indices),
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            semantic_extraction_precision=precision,
            semantic_extraction_recall=recall,
            semantic_extraction_f1=f1,
            valid_extracted_count=valid_count,
            correctly_extracted_count=correctly_extracted_count,
            guardrail_approved_count=guardrail_approved_count,
            faithful_extracted_count=faithful_count,
            correctly_rejected_no_store=rejected_no_store,
            correctly_rejected_unsafe=rejected_unsafe,
            category_correct=category_correct,
            domain_correct=domain_correct,
            family_correct=family_correct,
            matched_pair_count=true_positives,
            errors=tuple(errors),
        )


def load_candidate_extraction_cases(path: str | Path) -> list[CandidateExtractionCase]:
    cases: list[CandidateExtractionCase] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                raw = json.loads(line)
                cases.append(CandidateExtractionCase.from_dict(raw))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid gold JSONL at line {line_number}: {exc}"
                ) from exc
    return cases


def _supported_by_user_message(
    candidate: TravelMemory,
    messages: Iterable[dict[str, Any]],
) -> bool:
    evidence = normalize_match_text(candidate.evidence_text)
    if not evidence:
        return False
    for message in messages:
        message_type = str(message.get("type") or message.get("role") or "").lower()
        if message_type not in {"human", "user"}:
            continue
        content = normalize_match_text(str(message.get("content") or ""))
        if evidence == content or evidence in content or content in evidence:
            return True
    return False


# Re-exports for tests / callers.
_normalize = normalize_match_text
