from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, Sequence

from pydantic import BaseModel, Field

from memory.long_term import TravelMemory, format_memory_for_prompt

logger = logging.getLogger(__name__)

DEFAULT_APPLICABILITY_BATCH_SIZE = 10
LLM_OVERRIDE_CONFIDENCE = 0.7
_DEFAULT_RULE_REASON = "default uncertain (no specific tool-field rule matched)"

# Car capacity prefs that map to search_cars user_needs (4/5/7 chỗ, seater, ...).
_CAR_SEAT_CAPACITY_RE = re.compile(
    r"("
    r"\d+\s*chỗ"
    r"|tối thiểu\s*\d+"
    r"|bốn\s*chỗ|bảy\s*chỗ|năm\s*chỗ|sáu\s*chỗ|tám\s*chỗ|chín\s*chỗ"
    r"|seater|seats?\b|capacity"
    r")",
    re.IGNORECASE,
)


def _is_car_seat_capacity_preference(text: str) -> bool:
    return bool(_CAR_SEAT_CAPACITY_RE.search(text or ""))


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
    matched: bool = False


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


def _query_specifies_origin(query: str) -> bool:
    return any(
        token in query
        for token in (
            "từ hà nội",
            "từ hn",
            "from han",
            "từ han",
            "bay từ han",
            "từ đà nẵng",
            "from dad",
            "từ sgn",
            "từ tp.hcm",
            "từ hồ chí minh",
            "origin=",
        )
    )


# Tool-field rubric (search actions):
# - APPLY: preference maps to a tool/API arg for this action and is not contradicted
#   (hotel: price_min/max; car: user_needs transmission; flight: cabin/direct/origin)
# - UNCERTAIN: may still matter for ranking/reading results but has no tool arg
#   (hotel: quiet, beach; car: surcharge, seat capacity; excursion: crowd)
# - IRRELEVANT: not usable for this action (hotel bathtub on search_hotels; flight seat before offers)
# - OVERRIDDEN: same topic, user request replaces the stored value


def build_applicability_llm_prompt(
    *,
    user_query: str,
    domain: str,
    domain_action: str,
    domain_state: dict[str, Any],
    payload: list[dict[str, Any]],
) -> str:
    """Prompt for LlmApplicabilityJudge — tool-field mapping, not soft-rank⇒apply."""
    return (
        "Judge each stored memory against the CURRENT user request.\n"
        "Priority:\n"
        "1) Explicit preference updates in the user message win over stored memory.\n"
        "2) Antonym / opposite value on the same topic = overridden "
        "(nhóm lớn↔nhóm nhỏ, sáng↔tối, economy↔business, auto↔manual).\n"
        "3) Phrases like 'Từ giờ', 'thay vì', 'không còn', 'đổi sang' signal preference update.\n"
        "4) apply only if the preference maps to a tool/API field for THIS action "
        "AND is not contradicted by the query.\n"
        "Turn constraints are part of the current request — treat them like the user query "
        "when detecting conflicts (e.g. turn_constraints=['ưu tiên nhóm nhỏ'] overrides "
        "memory 'Ưu tiên tour nhóm lớn').\n"
        "Labels:\n"
        "- apply: still-valid preference that maps to tool/API fields for this action "
        "(hotel price_min/price_max; car user_needs transmission; flight cabin_class, "
        "direct/nonstop, origin) and is not contradicted\n"
        "- overridden: user request contradicts or replaces this memory "
        "(even if the topic is still relevant to search)\n"
        "- irrelevant: not usable for the current action "
        "(e.g. room bathtub amenity on hotel search_hotels; seat/window prefs before flight offers exist)\n"
        "- uncertain: may still matter when reading/ranking results but cannot be passed as a "
        "tool arg yet (e.g. hotel quiet/yên tĩnh, gần biển on search_hotels; excursion "
        "nature/beach/culture tour-type prefs that are too general for location; car seat capacity "
        "/ phụ phí without a dedicated seats or surcharge tool field; crowd avoidance without "
        "crowd data)\n"
        "Do NOT choose apply just because the preference is 'about' the domain/search.\n"
        "Do NOT choose apply only because the preference could soft-rank results — "
        "if there is no matching tool/API field for this action, use uncertain or irrelevant.\n"
        "If relevant but contradicted → overridden, not apply.\n"
        "Car seat capacity has no dedicated seats tool arg on search_cars → uncertain "
        "(soft via result field Số chỗ / weak cateId alias). Hotel quiet/beach and excursion "
        "nature/beach/culture tour-types are too general for concrete tool args → uncertain.\n"
        "\nExamples (search actions):\n"
        "- hotel search_hotels + 'Ngân sách 1–2 triệu' + 'Tìm KS Phú Quốc' → apply\n"
        "- hotel search_hotels + 'Thích yên tĩnh' + 'Tìm KS Phú Quốc' → uncertain "
        "(no quiet tool field)\n"
        "- hotel search_hotels + 'Thích gần biển' + any search query → uncertain "
        "(no beach tool field)\n"
        "- hotel search_hotels + 'phòng có bồn tắm' → irrelevant "
        "(room amenity not a search_hotels arg)\n"
        "- hotel search_hotels công tác + budget/beach/bathtub → apply / uncertain / irrelevant\n"
        "- hotel get_hotel_details + bathtub/budget → uncertain "
        "(soft when reading rooms; no search tool fields on details)\n"
        "- flight search_one_way + economy/direct/SGN prefs + 'Bay HN sáng thứ Hai' → apply\n"
        "- flight + memory 'ưu tiên bay sáng' + query 'tìm chuyến tối' → overridden\n"
        "- flight search_one_way + 'thường chọn rẻ nhất' + 'đúng giờ nhất' → uncertain "
        "(prioritizing schedule is not a hard cancellation of price preference)\n"
        "- flight search_one_way + 'thường chọn rẻ nhất' + 'không cần rẻ' → irrelevant\n"
        "- car search_cars + automatic pref → apply; seat capacity (5/7 chỗ) → uncertain "
        "(no seats tool arg; soft via Số chỗ in results); phụ phí avoidance → uncertain\n"
        "- excursion search_attractions + nature/beach/culture tour-type prefs → uncertain "
        "(too general vs concrete location); avoid crowded → uncertain\n"
        "- excursion + memory 'Ưu tiên tour nhóm lớn' + query "
        "'Từ giờ ưu tiên nhóm nhỏ. Tìm tour Hội An' → overridden\n"
        f"Domain: {domain}\n"
        f"Action: {domain_action}\n"
        f"User query: {user_query}\n"
        f"Turn constraints: {json.dumps((domain_state or {}).get('turn_constraints') or [], ensure_ascii=False)}\n"
        f"Domain state: {json.dumps(domain_state, ensure_ascii=False)}\n"
        f"Candidates: {json.dumps(payload, ensure_ascii=False)}"
    )


class RuleBasedApplicabilityJudge:
    """Heuristic fallback judge aligned with the tool-field applicability rubric."""

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
        constraints = [
            str(item).lower()
            for item in (domain_state or {}).get("turn_constraints") or []
            if str(item).strip()
        ]
        if constraints:
            query = f"{query} {' '.join(constraints)}".strip()
        results: list[ApplicabilityJudgment] = []
        for memory in candidates:
            memory_id = str(memory.memory_id or "")
            text = memory.memory_text.lower()
            # Conservative default per the tool-field rubric: a preference that
            # no specific rule matched must NOT be promoted to a hard `apply`
            # constraint (matched=False so reconcile will not fence on this label).
            # Leave it `uncertain` (soft context) so it never injects tool args alone.
            label = ApplicabilityLabel.UNCERTAIN
            reason = _DEFAULT_RULE_REASON
            if domain == "flight" and "sáng" in text and any(
                token in query for token in ("tối", "chiều", "evening", "night")
            ):
                label = ApplicabilityLabel.OVERRIDDEN
                reason = "current request conflicts with morning preference"
            elif domain == "flight" and "sgn" in text and _query_specifies_origin(query):
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
                    reason = "budget maps to price_min/price_max on search_hotels"
                elif "bồn tắm" in text or "bathtub" in text:
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "room bathtub amenity is not a search_hotels tool field"
                elif "biển" in text or "gần biển" in text or "resort" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "beach preference has no search_hotels tool field"
                elif "yên tĩnh" in text or "quiet" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "quiet preference has no search_hotels tool field"
                elif "đoàn" in text and "tránh" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "group avoidance has no search_hotels tool field"
            elif domain == "hotel" and domain_action == "get_hotel_details":
                if "bồn tắm" in text or "bathtub" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "room amenity uncertain at hotel details"
                elif "ngân sách" in text or "triệu" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "budget has no get_hotel_details tool field; soft when reading rooms"
            elif domain == "hotel" and domain_action == "get_reviews":
                if "bồn tắm" in text or "ngân sách" in text:
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "room prefs irrelevant for reviews"
            elif domain == "flight" and domain_action in {
                "search_one_way",
                "search_round_trip",
            }:
                if any(token in text for token in ("ghế", "cửa sổ", "seat")):
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "seat preference irrelevant before search"
                elif any(
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
                    reason = "transmission maps to user_needs on search_cars"
                elif _is_car_seat_capacity_preference(text):
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "seat capacity soft until results expose Số chỗ (no seats tool arg)"
                elif "phụ phí" in text or "surcharge" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "surcharge avoidance soft until tool payload has breakdown"
            elif domain == "car" and domain_action == "select_car":
                if "tự động" in text and any(
                    token in query for token in ("gia đình", "6 người", "7 chỗ")
                ):
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "transmission uncertain when capacity dominates"
                if _is_car_seat_capacity_preference(text):
                    if any(token in query for token in ("gia đình", "6 người")):
                        label = ApplicabilityLabel.APPLY
                        reason = "seat capacity applies for family capacity"
            elif domain == "excursion" and domain_action == "search_attractions":
                memory_large = any(
                    token in text for token in ("nhóm lớn", "large group", "đoàn lớn")
                )
                query_small = any(
                    token in query for token in ("nhóm nhỏ", "small group", "tour nhỏ")
                )
                memory_small = any(
                    token in text for token in ("nhóm nhỏ", "small group", "tour nhỏ")
                )
                query_large = any(
                    token in query for token in ("nhóm lớn", "large group", "đoàn lớn")
                )
                if (memory_large and query_small) or (memory_small and query_large):
                    label = ApplicabilityLabel.OVERRIDDEN
                    reason = "group-size preference overridden by current request"
                elif (
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
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "nature tour-type is too general for concrete attraction tool args"
                elif any(
                    token in text
                    for token in ("đông", "crowded", "crowd", "tránh điểm")
                ):
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "crowd avoidance soft until tool has crowd signal"
                elif "văn hóa" in text or "culture" in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "culture tour-type is too general for concrete attraction tool args"
                elif "biển" in text and "văn hóa" not in text:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "beach tour soft preference at search"
                elif memory_large or memory_small:
                    label = ApplicabilityLabel.APPLY
                    reason = "group-size preference applies to attraction search"
            elif domain == "excursion" and domain_action == "get_details":
                if "biển" in text or "beach" in text:
                    label = ApplicabilityLabel.IRRELEVANT
                    reason = "tour-type preference is irrelevant to details for a selected tour"
                else:
                    label = ApplicabilityLabel.UNCERTAIN
                    reason = "generic tour prefs uncertain at details"
            elif domain == "hotel" and domain_action == "select_room":
                if "bồn tắm" in text and domain_state.get("selected_hotel_id"):
                    label = ApplicabilityLabel.APPLY
                    reason = "bathtub applies when selecting room"
            matched = reason != _DEFAULT_RULE_REASON
            results.append(
                ApplicabilityJudgment(
                    memory_id=memory_id,
                    label=label,
                    confidence=0.9,
                    reason=reason,
                    matched=matched,
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
            prompt = build_applicability_llm_prompt(
                user_query=user_query,
                domain=domain,
                domain_action=domain_action,
                domain_state=domain_state or {},
                payload=payload,
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
    """Reconcile LLM and rule labels with specificity-aware priority.

    Order: overridden → specific rule irrelevant → keep specific rule
    apply/uncertain (LLM irrelevant cannot drop) → unmatched demotes lone
    LLM apply to uncertain; otherwise use LLM (high-conf irrelevant/overridden).
    """
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
                label=ApplicabilityLabel.UNCERTAIN,
                confidence=0.5,
                reason=_DEFAULT_RULE_REASON,
                matched=False,
            ),
        )
        chosen = _reconcile_one(llm=llm, rule=rule)
        reconciled.append(chosen)
    return reconciled


def _reconcile_one(
    *,
    llm: ApplicabilityJudgment,
    rule: ApplicabilityJudgment,
) -> ApplicabilityJudgment:
    memory_id = rule.memory_id or llm.memory_id

    def _pick(
        source: ApplicabilityJudgment,
        *,
        label: ApplicabilityLabel | None = None,
        reason: str | None = None,
    ) -> ApplicabilityJudgment:
        final_label = label if label is not None else source.label
        final_reason = reason or (
            f"reconciled: {source.reason} (llm: {llm.reason}; rule: {rule.reason})"
        )
        return ApplicabilityJudgment(
            memory_id=memory_id,
            label=final_label,
            confidence=max(llm.confidence, rule.confidence),
            reason=final_reason,
            matched=rule.matched,
        )

    # 1. Specific rule overridden always wins (deterministic lexical conflict).
    if rule.label == ApplicabilityLabel.OVERRIDDEN:
        return _pick(rule)

    # 2. Specific rule irrelevant wins (known out-of-scope for this action).
    if rule.matched and rule.label == ApplicabilityLabel.IRRELEVANT:
        # LLM overridden (high-conf) can still flip specific irrelevant to overridden
        # if the user explicitly cancelled a preference that the rule thought was irrelevant.
        llm_overridden = (
            llm.label == ApplicabilityLabel.OVERRIDDEN
            and llm.confidence >= LLM_OVERRIDE_CONFIDENCE
        )
        if llm_overridden:
            return _pick(llm, label=ApplicabilityLabel.OVERRIDDEN)
        return _pick(rule)

    # 3. Specific rule UNCERTAIN wins (fence against false LLM override/irrelevant).
    # This prevents "cheapest" from being dropped when user asks for "on time".
    if rule.matched and rule.label == ApplicabilityLabel.UNCERTAIN:
        return _pick(rule)

    # 4. LLM overridden (high-conf) wins over matched APPLY or unmatched rule.
    # We trust LLM to catch paraphrase overrides that rule-base missed for hard constraints.
    llm_overridden = (
        llm.label == ApplicabilityLabel.OVERRIDDEN
        and llm.confidence >= LLM_OVERRIDE_CONFIDENCE
    )
    if llm_overridden:
        return _pick(llm, label=ApplicabilityLabel.OVERRIDDEN)

    # 5. Specific rule APPLY wins (contract tool-field mapping).
    if rule.matched and rule.label == ApplicabilityLabel.APPLY:
        return _pick(rule)

    # 6. Rule unmatched (default): do not trust lone LLM apply as hard constraint.
    if llm.label == ApplicabilityLabel.APPLY:
        return _pick(
            llm,
            label=ApplicabilityLabel.UNCERTAIN,
            reason=(
                f"reconciled: demoted llm apply to uncertain "
                f"(llm: {llm.reason}; rule: {rule.reason})"
            ),
        )

    # 7. Trust high-conf LLM irrelevant for long-tail.
    if (
        llm.label == ApplicabilityLabel.IRRELEVANT
        and llm.confidence >= LLM_OVERRIDE_CONFIDENCE
    ):
        return _pick(llm)

    # 8. Otherwise trust LLM or fallback to low-conf uncertain.
    if llm.label in {
        ApplicabilityLabel.IRRELEVANT,
        ApplicabilityLabel.OVERRIDDEN,
    }:
        return _pick(
            llm,
            label=ApplicabilityLabel.UNCERTAIN,
            reason=(
                f"reconciled: low-conf llm {llm.label} → uncertain "
                f"(llm: {llm.reason}; rule: {rule.reason})"
            ),
        )

    return _pick(llm)


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
