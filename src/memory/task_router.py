from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from memory.domain_actions import (
    CarAction,
    ExcursionAction,
    FlightAction,
    HotelAction,
    allowed_actions_for_domain,
)


class ActionInference(BaseModel):
    action: str
    rationale: str = ""


class ActionInferrer(Protocol):
    async def infer_domain_action(
        self,
        *,
        user_query: str,
        domain: str,
        domain_state: dict[str, Any],
    ) -> str:
        """Return a domain action value."""


_KEYWORD_RULES: dict[str, list[tuple[re.Pattern[str], str]]] = {
    "hotel": [
        (re.compile(r"đánh giá|review", re.I), HotelAction.GET_REVIEWS.value),
        (
            re.compile(r"chọn(?: giúp)?(?: tôi)?[^.]*phòng|select room|đặt phòng", re.I),
            HotelAction.SELECT_ROOM.value,
        ),
        (
            re.compile(r"chi tiết|detail|thông tin khách sạn|loại phòng", re.I),
            HotelAction.GET_HOTEL_DETAILS.value,
        ),
        (
            re.compile(r"khách sạn|hotel|search hotel|đặt khách sạn", re.I),
            HotelAction.SEARCH_HOTELS.value,
        ),
    ],
    "flight": [
        (
            re.compile(
                r"so sánh|compare|chọn chuyến[^.]*danh sách|phù hợp nhất[^.]*danh sách",
                re.I,
            ),
            FlightAction.COMPARE_OFFERS.value,
        ),
        (re.compile(r"khứ hồi|round.?trip|bay về", re.I), FlightAction.SEARCH_ROUND_TRIP.value),
        (
            re.compile(
                r"tìm chuyến|tìm vé|search flight|chuyến bay|bay đi|bay từ|một chiều|one.?way",
                re.I,
            ),
            FlightAction.SEARCH_ONE_WAY.value,
        ),
    ],
    "excursion": [
        (re.compile(r"lịch trình|day plan|kế hoạch ngày", re.I), ExcursionAction.BUILD_DAY_PLAN.value),
        (re.compile(r"chi tiết|detail|thông tin tour", re.I), ExcursionAction.GET_DETAILS.value),
        (re.compile(r"tìm tour|attraction|tham quan|hoạt động", re.I), ExcursionAction.SEARCH_ATTRACTIONS.value),
    ],
    "car": [
        (re.compile(r"chọn xe|select car|đặt xe", re.I), CarAction.SELECT_CAR.value),
        (re.compile(r"so sánh|compare", re.I), CarAction.COMPARE_CARS.value),
        (re.compile(r"thuê xe|rent car|tìm xe", re.I), CarAction.SEARCH_CARS.value),
    ],
}


def infer_domain_action_heuristic(
    *,
    user_query: str,
    domain: str,
    domain_state: dict[str, Any] | None = None,
) -> str:
    text = (user_query or "").strip()
    allowed = set(allowed_actions_for_domain(domain))
    if domain_state and domain_state.get("selected_items"):
        if domain == "hotel" and HotelAction.SELECT_ROOM.value in allowed:
            return HotelAction.SELECT_ROOM.value
        if domain == "car" and CarAction.SELECT_CAR.value in allowed:
            return CarAction.SELECT_CAR.value
    for pattern, action in _KEYWORD_RULES.get(domain, []):
        if action in allowed and pattern.search(text):
            return action
    general = next((a for a in allowed if a.endswith("general")), None)
    return general or next(iter(allowed))


class HeuristicActionInferrer:
    async def infer_domain_action(
        self,
        *,
        user_query: str,
        domain: str,
        domain_state: dict[str, Any],
    ) -> str:
        return infer_domain_action_heuristic(
            user_query=user_query,
            domain=domain,
            domain_state=domain_state,
        )


class LlmActionInferrer:
    def __init__(self, llm) -> None:
        self._llm = llm

    async def infer_domain_action(
        self,
        *,
        user_query: str,
        domain: str,
        domain_state: dict[str, Any],
    ) -> str:
        allowed = allowed_actions_for_domain(domain)
        schema = ActionInference.model_json_schema()
        schema["properties"]["action"]["enum"] = list(allowed)
        prompt = (
            "Classify the current domain task action for memory recall.\n"
            f"Domain: {domain}\n"
            f"Allowed actions: {', '.join(allowed)}\n"
            f"User query: {user_query}\n"
            f"Domain state: {domain_state}\n"
            "Return JSON with action and brief rationale."
        )
        try:
            structured = self._llm.with_structured_output(ActionInference)
            result = await structured.ainvoke(prompt)
            if isinstance(result, ActionInference) and result.action in allowed:
                return result.action
        except Exception:
            pass
        return infer_domain_action_heuristic(
            user_query=user_query,
            domain=domain,
            domain_state=domain_state,
        )


def build_action_inferrer(*, llm=None, use_llm: bool = True) -> ActionInferrer:
    if llm is not None and use_llm:
        return LlmActionInferrer(llm)
    return HeuristicActionInferrer()
