from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, Sequence

from pydantic import BaseModel, Field

from memory.long_term import TravelMemory, format_memory_for_prompt

logger = logging.getLogger(__name__)

DEFAULT_APPLICABILITY_BATCH_SIZE = 10


class ApplicabilityLabel(StrEnum):
    APPLY = "apply"
    OVERRIDDEN = "overridden"
    IRRELEVANT = "irrelevant"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class ApplicabilityJudgment:
    memory_id: str
    label: ApplicabilityLabel
    confidence: float
    reason: str


class ApplicabilityJudge(Protocol):
    async def judge_batch(
        self,
        *,
        user_query: str,
        domain: str,
        domain_action: str,
        domain_state: dict[str, Any],
        candidates: Sequence[TravelMemory],
    ) -> list[ApplicabilityJudgment]:
        """Judge applicability for each candidate memory."""


class _CandidateJudgment(BaseModel):
    memory_id: str
    label: ApplicabilityLabel
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class _BatchJudgmentResponse(BaseModel):
    judgments: list[_CandidateJudgment]


class MockApplicabilityJudge:
    """Deterministic judge for tests; optional per-memory label overrides."""

    def __init__(
        self,
        *,
        default_label: ApplicabilityLabel = ApplicabilityLabel.APPLY,
        overrides: dict[str, ApplicabilityLabel] | None = None,
    ) -> None:
        self._default = default_label
        self._overrides = overrides or {}

    async def judge_batch(
        self,
        *,
        user_query: str,
        domain: str,
        domain_action: str,
        domain_state: dict[str, Any],
        candidates: Sequence[TravelMemory],
    ) -> list[ApplicabilityJudgment]:
        results: list[ApplicabilityJudgment] = []
        for memory in candidates:
            memory_id = str(memory.memory_id or "")
            label = self._overrides.get(memory_id, self._default)
            results.append(
                ApplicabilityJudgment(
                    memory_id=memory_id,
                    label=label,
                    confidence=1.0,
                    reason="mock",
                )
            )
        return results


class RuleBasedApplicabilityJudge:
    """Lightweight heuristic judge used when LLM judge is disabled."""

    async def judge_batch(
        self,
        *,
        user_query: str,
        domain: str,
        domain_action: str,
        domain_state: dict[str, Any],
        candidates: Sequence[TravelMemory],
    ) -> list[ApplicabilityJudgment]:
        query = (user_query or "").lower()
        results: list[ApplicabilityJudgment] = []
        for memory in candidates:
            memory_id = str(memory.memory_id or "")
            text = memory.memory_text.lower()
            label = ApplicabilityLabel.APPLY
            reason = "default apply"
            if domain == "flight" and "sáng" in text and any(
                token in query for token in ("tối", "chiều", "evening", "night")
            ):
                label = ApplicabilityLabel.OVERRIDDEN
                reason = "current request conflicts with morning preference"
            elif domain == "flight" and "sgn" in text and any(
                token in query for token in ("hà nội", "han", "đà nẵng", "dan", "han ")
            ):
                label = ApplicabilityLabel.OVERRIDDEN
                reason = "departure airport overridden by current location"
            elif domain == "car" and ("tự động" in text or "automatic" in text) and any(
                token in query for token in ("số sàn", "sàn", "manual")
            ):
                label = ApplicabilityLabel.OVERRIDDEN
                reason = "transmission preference overridden by manual request"
            elif "ngân sách" in text and any(
                token in query for token in ("5 triệu", "5 trieu", "tối đa 5")
            ):
                label = ApplicabilityLabel.OVERRIDDEN
                reason = "budget preference overridden by explicit higher cap"
            elif domain == "hotel" and domain_action == "search_hotels":
                if "biển" in text or "resort" in text or "gần biển" in text:
                    if "công tác" in query or "business" in query or "trung tâm" in query:
                        label = ApplicabilityLabel.IRRELEVANT
                        reason = "beach preference irrelevant for business search"
                if "bồn tắm" in text or "bathtub" in text:
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "room amenity irrelevant for search action"
                if "đoàn" in text and "tránh" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "group avoidance is soft preference at search"
                if "bồn tắm" in text and any(
                    token in query for token in ("nghỉ dưỡng", "relax")
                ):
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "bathtub may matter for leisure search"
                if (
                    "bồn tắm" in text
                    and not domain_state.get("selected_hotel_id")
                    and domain_state.get("destination") is None
                ):
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "bathtub irrelevant without hotel context"
            elif domain == "hotel" and domain_action == "get_hotel_details":
                if "bồn tắm" in text or "bathtub" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "room amenity uncertain at hotel details"
            elif domain == "hotel" and domain_action == "get_reviews":
                if "bồn tắm" in text or "ngân sách" in text:
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "room prefs irrelevant for reviews"
            elif domain == "flight" and domain_action == "search_one_way":
                if any(token in text for token in ("ghế", "cửa sổ", "seat")):
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "seat preference irrelevant before search"
                if "rẻ nhất" in text or "cheapest" in text:
                    if any(token in query for token in ("đúng giờ", "on time", "schedule")):
                        if "không cần rẻ" in query or "not cheapest" in query:
                            label = ApplicabilityLabel.IRRELEVANT
                            reason = "price pref irrelevant when schedule explicit"
                        else:
                            label = ApplicabilityLabel.UNCERTAIN
                            reason = "price pref uncertain when schedule prioritized"
            elif domain == "flight" and domain_action == "compare_offers":
                if any(token in text for token in ("ghế", "cửa sổ", "seat")):
                    if domain_state.get("visible_results"):
                        label = ApplicabilityLabel.APPLY
                        reason = "seat preference applies when comparing shortlist"
                    else:
                        label = ApplicabilityLabel.UNCERTAIN
                        reason = "seat preference may inform compare"
            elif domain == "car" and domain_action == "search_cars":
                if "7 chỗ" in text or "bảy chỗ" in text:
                    if "tự động" in query or "automatic" in query:
                        label = ApplicabilityLabel.IRRELEVANT
                        reason = "7-seat irrelevant for automatic query"
            elif domain == "car" and domain_action == "select_car":
                if "tự động" in text and any(
                    token in query for token in ("gia đình", "6 người", "7 chỗ")
                ):
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "transmission uncertain when capacity dominates"
                if "7 chỗ" in text or "bảy chỗ" in text:
                    if any(token in query for token in ("gia đình", "6 người")):
                        label = ApplicabilityLabel.APPLY
                        reason = "7-seat applies for family capacity"
            elif domain == "excursion" and domain_action == "search_attractions":
                if "biển" in text and "văn hóa" in text:
                    pass
                if "biển" in text and "văn hóa" not in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "beach tour soft preference at search"
                if "văn hóa" in text:
                    label = ApplicabilityLabel.APPLY
                    reason = "culture tour applies at search"
            elif domain == "excursion" and domain_action == "get_details":
                label = ApplicabilityLabel.UNCERTAIN
                reason = "generic tour prefs uncertain at details"
            elif domain == "hotel" and domain_action == "select_room":
                if "bồn tắm" in text and domain_state.get("selected_hotel_id"):
                    label = ApplicabilityLabel.APPLY
                    reason = "bathtub applies when selecting room"
            results.append(
                ApplicabilityJudgment(
                    memory_id=memory_id,
                    label=label,
                    confidence=0.9,
                    reason=reason,
                )
            )
        return results


class LlmApplicabilityJudge:
    def __init__(self, llm, *, batch_size: int = DEFAULT_APPLICABILITY_BATCH_SIZE) -> None:
        self._llm = llm
        self._batch_size = batch_size

    async def judge_batch(
        self,
        *,
        user_query: str,
        domain: str,
        domain_action: str,
        domain_state: dict[str, Any],
        candidates: Sequence[TravelMemory],
    ) -> list[ApplicabilityJudgment]:
        if not candidates:
            return []
        results: list[ApplicabilityJudgment] = []
        structured = self._llm.with_structured_output(_BatchJudgmentResponse)
        for start in range(0, len(candidates), self._batch_size):
            batch = list(candidates[start : start + self._batch_size])
            payload = [
                {
                    "memory_id": memory.memory_id,
                    "memory_text": memory.memory_text,
                    "condition": memory.condition,
                }
                for memory in batch
            ]
            prompt = (
                "Judge whether each long-term memory applies to the current request.\n"
                "Labels:\n"
                "- apply: relevant hard constraint for this action\n"
                "- overridden: conflicts with the current user request\n"
                "- irrelevant: not relevant to the current action\n"
                "- uncertain: maybe useful as soft priority only\n"
                "Current user request has priority over stored memories.\n"
                f"Domain: {domain}\n"
                f"Action: {domain_action}\n"
                f"User query: {user_query}\n"
                f"Domain state: {json.dumps(domain_state, ensure_ascii=False)}\n"
                f"Candidates: {json.dumps(payload, ensure_ascii=False)}"
            )
            try:
                response = await structured.ainvoke(prompt)
                if isinstance(response, _BatchJudgmentResponse):
                    by_id = {item.memory_id: item for item in response.judgments}
                    for memory in batch:
                        memory_id = str(memory.memory_id or "")
                        item = by_id.get(memory_id)
                        if item is None:
                            results.append(
                                ApplicabilityJudgment(
                                    memory_id=memory_id,
                                    label=ApplicabilityLabel.UNCERTAIN,
                                    confidence=0.5,
                                    reason="missing judgment",
                                )
                            )
                            continue
                        results.append(
                            ApplicabilityJudgment(
                                memory_id=memory_id,
                                label=ApplicabilityLabel(item.label),
                                confidence=item.confidence,
                                reason=item.reason,
                            )
                        )
                    continue
            except Exception as exc:
                logger.warning("applicability judge batch failed: %s", exc)
            fallback = RuleBasedApplicabilityJudge()
            results.extend(
                await fallback.judge_batch(
                    user_query=user_query,
                    domain=domain,
                    domain_action=domain_action,
                    domain_state=domain_state,
                    candidates=batch,
                )
            )
        return results


def build_applicability_judge(
    *,
    llm=None,
    use_llm: bool = True,
    batch_size: int = DEFAULT_APPLICABILITY_BATCH_SIZE,
) -> ApplicabilityJudge:
    if llm is not None and use_llm:
        return LlmApplicabilityJudge(llm, batch_size=batch_size)
    return RuleBasedApplicabilityJudge()


def partition_judgments(
    candidates: Sequence[TravelMemory],
    judgments: Sequence[ApplicabilityJudgment],
) -> tuple[list[TravelMemory], list[TravelMemory], list[ApplicabilityJudgment]]:
    by_id = {str(memory.memory_id): memory for memory in candidates if memory.memory_id}
    apply_memories: list[TravelMemory] = []
    uncertain_memories: list[TravelMemory] = []
    audit = list(judgments)
    for judgment in judgments:
        memory = by_id.get(judgment.memory_id)
        if memory is None:
            continue
        if judgment.label == ApplicabilityLabel.APPLY:
            apply_memories.append(memory)
        elif judgment.label == ApplicabilityLabel.UNCERTAIN:
            uncertain_memories.append(memory)
    return apply_memories, uncertain_memories, audit


def format_applied_context(memories: Sequence[TravelMemory]) -> str:
    return "\n".join(format_memory_for_prompt(memory) for memory in memories)
