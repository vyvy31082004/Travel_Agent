from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from memory.consolidation import (
    MemoryCandidateExtractor,
    extract_candidate_memories,
    validate_memory_candidate,
)
from memory.long_term import CATEGORY_FAMILY, MemoryCategory, TravelMemory


RECOMMENDED_RELEASE_TARGETS: dict[str, float] = {
    "extraction_precision": 0.85,
    "evidence_faithfulness_rate": 0.95,
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
    description: str = ""
    requirement_id: str = "REQ-EXTRACTION"
    risk: str = ""
    split: str = "test"
    code_path: tuple[str, ...] = ()
    metric: tuple[str, ...] = ()
    rationale: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CandidateExtractionCase":
        return cls(
            case_id=str(raw["case_id"]),
            messages=tuple(dict(message) for message in raw.get("messages", [])),
            gold_memories=tuple(
                GoldMemory.from_dict(memory)
                for memory in raw.get("gold_memories", [])
            ),
            unsafe=bool(raw.get("unsafe", False)),
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
    extracted: tuple[dict[str, Any], ...]
    matched_gold_indices: tuple[int, ...]
    valid_extracted_count: int
    correctly_extracted_count: int
    guardrail_approved_count: int
    faithful_extracted_count: int
    correctly_rejected_unsafe: bool | None
    category_correct: int
    domain_correct: int
    family_correct: int
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
            "extracted": list(self.extracted),
            "matched_gold_indices": list(self.matched_gold_indices),
            "valid_extracted_count": self.valid_extracted_count,
            "correctly_extracted_count": self.correctly_extracted_count,
            "guardrail_approved_count": self.guardrail_approved_count,
            "faithful_extracted_count": self.faithful_extracted_count,
            "correctly_rejected_unsafe": self.correctly_rejected_unsafe,
            "category_correct": self.category_correct,
            "domain_correct": self.domain_correct,
            "family_correct": self.family_correct,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class CandidateExtractionReport:
    total_cases: int
    total_extracted_memories: int
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
    correctly_rejected_unsafe_cases: int
    unsafe_gold_cases: int
    cases: tuple[CaseEvaluation, ...] = field(default_factory=tuple)

    @staticmethod
    def ratio(numerator: int, denominator: int) -> float | None:
        # A missing denominator is undefined, not a measured zero.
        return None if denominator == 0 else numerator / denominator

    @property
    def extraction_precision(self) -> MetricValue:
        return MetricValue(
            self.valid_extracted_memories,
            self.total_extracted_memories,
            self.ratio(self.valid_extracted_memories, self.total_extracted_memories),
        )

    @property
    def extraction_recall(self) -> MetricValue:
        return MetricValue(
            self.correctly_extracted_gold_memories,
            self.total_gold_memories,
            self.ratio(
                self.correctly_extracted_gold_memories, self.total_gold_memories
            ),
        )

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
            "extraction_precision": self.extraction_precision,
            "extraction_recall": self.extraction_recall,
            "evidence_faithfulness_rate": self.evidence_faithfulness_rate,
            "category_accuracy": self.category_accuracy,
            "domain_accuracy": self.domain_accuracy,
            "family_accuracy": self.family_accuracy,
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
            "correctly_rejected_unsafe_cases": self.correctly_rejected_unsafe_cases,
            "unsafe_gold_cases": self.unsafe_gold_cases,
            "metrics": {
                name: metric.to_dict() for name, metric in self.metrics().items()
            },
            "recommended_release_gates": self.release_gate_results(),
            "cases": [case.to_dict() for case in self.cases],
        }


class CandidateExtractionEvaluator:
    """Evaluate extraction against a human-authored JSONL gold set.

    Matching is conservative and one-to-one: each extracted memory can match at
    most one gold memory. A match requires normalized memory text equality or an
    explicit gold alias; classification fields must also agree for the memory
    to count as correctly extracted.
    """

    def __init__(
        self,
        extractor: MemoryCandidateExtractor | None = None,
        *,
        user_id: str = "eval-user",
        thread_prefix: str = "eval-thread",
    ) -> None:
        self.extractor = extractor
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
            evaluated.append(self._evaluate_case(case, extracted))

        return CandidateExtractionReport(
            total_cases=len(evaluated),
            total_extracted_memories=sum(len(case.extracted) for case in evaluated),
            valid_extracted_memories=sum(
                case.valid_extracted_count for case in evaluated
            ),
            correctly_extracted_gold_memories=sum(
                case.correctly_extracted_count for case in evaluated
            ),
            total_gold_memories=sum(
                len(case.gold_memories) for case in cases
            ),
            memories_supported_by_user_evidence=sum(
                case.faithful_extracted_count for case in evaluated
            ),
            approved_memories=sum(
                case.guardrail_approved_count for case in evaluated
            ),
            category_correct=sum(case.category_correct for case in evaluated),
            category_labeled_cases=sum(
                len(case.gold_memories) for case in cases
            ),
            domain_correct=sum(case.domain_correct for case in evaluated),
            domain_labeled_cases=sum(
                len(case.gold_memories) for case in cases
            ),
            family_correct=sum(case.family_correct for case in evaluated),
            family_labeled_cases=sum(
                len(case.gold_memories) for case in cases
            ),
            correctly_rejected_unsafe_cases=sum(
                bool(case.correctly_rejected_unsafe)
                for case in evaluated
                if case.correctly_rejected_unsafe is not None
            ),
            unsafe_gold_cases=sum(1 for case in cases if case.unsafe),
            cases=tuple(evaluated),
        )

    def _evaluate_case(
        self,
        case: CandidateExtractionCase,
        extracted: Sequence[TravelMemory],
    ) -> CaseEvaluation:
        matched: list[int] = []
        used: set[int] = set()
        valid_count = 0
        correctly_extracted_count = 0
        guardrail_approved_count = 0
        faithful_count = 0
        category_correct = 0
        domain_correct = 0
        family_correct = 0
        errors: list[str] = []

        for candidate in extracted:
            rule = validate_memory_candidate(candidate)
            if rule.ok:
                guardrail_approved_count += 1
            match_index = _find_gold_text_match(candidate, case.gold_memories, used)
            is_gold_text = match_index is not None
            labels_correct = False
            if match_index is not None:
                gold = case.gold_memories[match_index]
                labels_correct = (
                    str(candidate.category) == gold.category
                    and str(candidate.domain) == gold.domain
                    and str(candidate.family) == gold.family
                )
            # Precision is intentionally strict: valid means guardrails pass,
            # the candidate matches a gold atomic memory, and all enum labels
            # are correct. An unlabelled extraction is not silently counted as
            # valid merely because it has evidence_text.
            if rule.ok and is_gold_text and labels_correct:
                valid_count += 1
                correctly_extracted_count += 1
            elif not rule.ok:
                errors.extend(rule.reasons)
            elif not is_gold_text:
                errors.append("candidate did not match a gold atomic memory")
            else:
                errors.append("candidate matched gold text but classification was wrong")
            if (
                rule.ok
                and is_gold_text
                and _supported_by_user_message(candidate, case.messages)
            ):
                # Merely copying a user sentence into evidence_text is not
                # sufficient: the candidate claim itself must match a
                # human-labelled supported memory (or explicit alias).
                faithful_count += 1
            if match_index is None:
                continue
            used.add(match_index)
            matched.append(match_index)
            gold = case.gold_memories[match_index]
            category_correct += int(str(candidate.category) == gold.category)
            domain_correct += int(str(candidate.domain) == gold.domain)
            family_correct += int(str(candidate.family) == gold.family)

        rejected = None
        if case.unsafe:
            # The evaluated pipeline includes validate_memory_candidate(...),
            # as specified by the metric's code mapping. A raw deterministic
            # candidate is still correctly rejected if no candidate passes the
            # guardrail.
            rejected = not extracted or all(
                not validate_memory_candidate(candidate).ok
                for candidate in extracted
            )
            if not rejected:
                errors.append("unsafe case produced a guardrail-approved candidate")

        return CaseEvaluation(
            case_id=case.case_id,
            requirement_id=case.requirement_id,
            risk=case.risk,
            split=case.split,
            code_path=case.code_path,
            metric=case.metric,
            rationale=case.rationale,
            unsafe=case.unsafe,
            extracted=tuple(candidate.to_record() for candidate in extracted),
            matched_gold_indices=tuple(matched),
            valid_extracted_count=valid_count,
            correctly_extracted_count=correctly_extracted_count,
            guardrail_approved_count=guardrail_approved_count,
            faithful_extracted_count=faithful_count,
            correctly_rejected_unsafe=rejected,
            category_correct=category_correct,
            domain_correct=domain_correct,
            family_correct=family_correct,
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
                raise ValueError(f"invalid gold JSONL at line {line_number}: {exc}") from exc
    return cases


def _find_gold_text_match(
    candidate: TravelMemory,
    gold_memories: Sequence[GoldMemory],
    used: set[int],
) -> int | None:
    candidate_text = _normalize(candidate.memory_text)
    for index, gold in enumerate(gold_memories):
        if index in used:
            continue
        accepted = {gold.memory_text, *gold.aliases}
        if candidate_text in {_normalize(text) for text in accepted}:
            return index
    return None


def _supported_by_user_message(
    candidate: TravelMemory,
    messages: Iterable[dict[str, Any]],
) -> bool:
    evidence = _normalize(candidate.evidence_text)
    if not evidence:
        return False
    for message in messages:
        message_type = str(message.get("type") or message.get("role") or "").lower()
        if message_type not in {"human", "user"}:
            continue
        content = _normalize(str(message.get("content") or ""))
        if evidence == content or evidence in content or content in evidence:
            return True
    return False


def _normalize(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[\s:,.!?;\-]+$", "", value)
    return value
