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


def _label_rank(label: ApplicabilityLabel) -> int:
    return {
        ApplicabilityLabel.OVERRIDDEN: 4,
        ApplicabilityLabel.IRRELEVANT: 3,
        ApplicabilityLabel.APPLY: 2,
        ApplicabilityLabel.UNCERTAIN: 1,
    }[label]


def _query_specifies_origin(query: str) -> bool:
    return any(
        token in query
        for token in (
            "từ hà nội",
            "từ hn",
            "from han",
            "từ đà nẵng",
            "from dad",
            "từ sgn",
            "từ tp.hcm",
            "từ hồ chí minh",
            "origin=",
        )
    )


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
                token in query for token in ("từ hà nội", "from han", "bay từ hn", "origin han")
            ):
                label = ApplicabilityLabel.OVERRIDDEN
                reason = "departure airport overridden by current request"
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
            elif ("ngân sách" in text or "triệu" in text) and any(
                token in query
                for token in ("dưới 1 triệu", "dưới 1 trieu", "1 triệu/đêm", "1 trieu/dem")
            ):
                label = ApplicabilityLabel.OVERRIDDEN
                reason = "stored budget overridden by explicit lower cap in query"
            elif domain == "hotel" and domain_action == "search_hotels":
                if "ngân sách" in text or "triệu" in text:
                    label = ApplicabilityLabel.APPLY
                    reason = "budget preference applies to hotel search"
                elif ("biển" in text or "gần biển" in text or "resort" in text) and (
                    "công tác" in query or "business" in query or "trung tâm" in query
                ):
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "beach preference irrelevant for business search"
                elif "biển" in text or "gần biển" in text:
                    label = ApplicabilityLabel.APPLY
                    reason = "beach preference applies to leisure hotel search"
                elif "yên tĩnh" in text or "quiet" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "quiet preference has no API field; trade-off at display"
                elif "bồn tắm" in text or "bathtub" in text:
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "room amenity irrelevant for search action"
                elif "đoàn" in text and "tránh" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "group avoidance is soft preference at search"
            elif domain == "hotel" and domain_action == "get_hotel_details":
                if "bồn tắm" in text or "bathtub" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "room amenity uncertain at hotel details"
            elif domain == "hotel" and domain_action == "get_reviews":
                if "bồn tắm" in text or "ngân sách" in text:
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "room prefs irrelevant for reviews"
            elif domain == "flight" and domain_action in {
                "search_one_way",
                "search_round_trip",
            }:
                if any(
                    token in text
                    for token in ("phổ thông", "economy", "hạng phổ thông")
                ) and any(
                    token in query for token in ("business", "thương gia", "business class")
                ):
                    label = ApplicabilityLabel.OVERRIDDEN
                    reason = "economy preference overridden by business class request"
                elif any(
                    token in text
                    for token in ("phổ thông", "economy", "hạng phổ thông")
                ):
                    label = ApplicabilityLabel.APPLY
                    reason = "cabin class preference applies to flight search"
                elif any(
                    token in text
                    for token in ("bay thẳng", "thẳng", "direct", "tránh nối", "nối chuyến")
                ):
                    label = ApplicabilityLabel.APPLY
                    reason = "direct-flight preference applies to search"
                elif "sgn" in text or "tp.hcm" in text or "hồ chí minh" in text:
                    if _query_specifies_origin(query):
                        label = ApplicabilityLabel.OVERRIDDEN
                        reason = "origin preference overridden by explicit origin in query"
                    else:
                        label = ApplicabilityLabel.APPLY
                        reason = "departure origin preference applies when query omits origin"
                elif any(token in text for token in ("ghế", "cửa sổ", "seat")):
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "seat preference irrelevant before search"
                elif "rẻ nhất" in text or "cheapest" in text:
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
                if "tự động" in text or "automatic" in text:
                    label = ApplicabilityLabel.APPLY
                    reason = "transmission preference applies to car search"
                elif "7 chỗ" in text or "bảy chỗ" in text or "tối thiểu 7" in text:
                    label = ApplicabilityLabel.APPLY
                    reason = "seat capacity preference applies to car search"
                elif "phụ phí" in text or "surcharge" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "surcharge avoidance soft until tool payload has breakdown"
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
                if (
                    ("nghìn" in text or "ngân sách" in text)
                    and ("người" in text or "mỗi người" in text or "/người" in text)
                    and any(
                        token in query
                        for token in (
                            "700 nghìn",
                            "700 nghin",
                            "tối đa 700",
                            "700 nghìn/người",
                        )
                    )
                ):
                    label = ApplicabilityLabel.OVERRIDDEN
                    reason = "per-person budget overridden by explicit higher cap"
                elif any(
                    token in text
                    for token in ("thiên nhiên", "nature", "trek", "rừng", "núi")
                ):
                    label = ApplicabilityLabel.APPLY
                    reason = "nature preference applies to attraction search"
                elif any(
                    token in text
                    for token in ("đông", "crowded", "crowd", "tránh điểm")
                ):
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "crowd avoidance soft until tool has crowd signal"
                elif "văn hóa" in text or "culture" in text:
                    label = ApplicabilityLabel.APPLY
                    reason = "culture tour applies at search"
                elif "biển" in text and "văn hóa" not in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "beach tour soft preference at search"
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
                "- apply: relevant constraint for this action — use when preference maps to "
                "tool/API fields (budget, beach, economy, direct flight, origin, car seats, nature)\n"
                "- overridden: conflicts with the current user request\n"
                "- irrelevant: not relevant to the current action\n"
                "- uncertain: preference cannot be verified from tool data alone "
                "(e.g. quiet hotel, crowd avoidance without crowd field) — still rank/trade-off\n"
                "Current user request has priority over stored memories.\n"
                "Do NOT mark budget/beach/economy/direct/origin/seats/nature as uncertain just "
                "because the user query omits them — apply when the action is a domain search.\n"
                "\nExamples (search actions):\n"
                "- hotel search_hotels + 'Ngân sách 1–2 triệu' + 'Tìm KS Phú Quốc' → apply\n"
                "- hotel search_hotels + 'Thích gần biển' + leisure query → apply\n"
                "- hotel search_hotels + 'Thích yên tĩnh' → uncertain (no quiet field)\n"
                "- flight search_one_way + economy/direct/SGN prefs + 'Bay HN sáng thứ Hai' → apply\n"
                "- car search_cars + automatic/7-seat prefs → apply; phụ phí avoidance → uncertain\n"
                "- excursion search_attractions + nature pref → apply; avoid crowded → uncertain\n"
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


async def reconcile_judgments(
    candidates: Sequence[TravelMemory],
    llm_judgments: Sequence[ApplicabilityJudgment],
    *,
    user_query: str,
    domain: str,
    domain_action: str,
    domain_state: dict[str, Any],
) -> list[ApplicabilityJudgment]:
    """Upgrade LLM labels when rule judge is stronger; never downgrade overridden/irrelevant."""
    rule_judge = RuleBasedApplicabilityJudge()
    rule_judgments = await rule_judge.judge_batch(
        user_query=user_query,
        domain=domain,
        domain_action=domain_action,
        domain_state=domain_state,
        candidates=candidates,
    )
    rule_by_id = {item.memory_id: item for item in rule_judgments}
    llm_by_id = {item.memory_id: item for item in llm_judgments}
    reconciled: list[ApplicabilityJudgment] = []
    for memory in candidates:
        memory_id = str(memory.memory_id or "")
        llm = llm_by_id.get(
            memory_id,
            ApplicabilityJudgment(
                memory_id=memory_id,
                label=ApplicabilityLabel.UNCERTAIN,
                confidence=0.5,
                reason="missing judgment",
            ),
        )
        rule = rule_by_id.get(
            memory_id,
            ApplicabilityJudgment(
                memory_id=memory_id,
                label=ApplicabilityLabel.APPLY,
                confidence=0.9,
                reason="default apply",
            ),
        )
        if llm.label in {ApplicabilityLabel.OVERRIDDEN, ApplicabilityLabel.IRRELEVANT}:
            chosen = llm
        elif rule.label in {ApplicabilityLabel.OVERRIDDEN, ApplicabilityLabel.IRRELEVANT}:
            chosen = rule
        elif _label_rank(rule.label) > _label_rank(llm.label):
            chosen = ApplicabilityJudgment(
                memory_id=memory_id,
                label=rule.label,
                confidence=max(llm.confidence, rule.confidence),
                reason=f"reconciled: {rule.reason} (llm: {llm.reason})",
            )
        else:
            chosen = llm
        reconciled.append(chosen)
    return reconciled


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
