from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

_VISIBLE_DOMAIN_ALIASES: dict[str, set[str]] = {
    "hotel": {"hotel"},
    "car": {"car"},
    "flight": {"flight"},
    "tour": {"tour", "excursion"},
    "excursion": {"tour", "excursion"},
}


def _domain_matches(visible_domain: str | None, domain: str | None) -> bool:
    if not domain:
        return True
    value = str(visible_domain or "").strip().lower()
    if not value:
        return True
    hint = str(domain).strip().lower()
    if value == hint:
        return True
    return value in _VISIBLE_DOMAIN_ALIASES.get(hint, {hint})


@dataclass(frozen=True)
class ResolvedReference:
    domain: str
    request_id: str
    search_id: str
    item_id: str
    position: int


@dataclass(frozen=True)
class ClarificationNeeded:
    reason: str
    candidates: list[dict[str, Any]]


def resolve_item_reference(
    state: dict[str, Any],
    domain: Optional[str] = None,
    position: Optional[int] = None,
    item_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> ResolvedReference | ClarificationNeeded:
    """Map ordinal/domain references to concrete item IDs using structured State.

    LLM may extract domain/position only. Position -> item_id mapping is deterministic
    code over visible_results, never guessed from summary text.
    """
    visible_results = state.get("visible_results") or {}

    def _candidate(req_id: str, visible: dict[str, Any]) -> dict[str, Any]:
        return {
            "request_id": req_id,
            "domain": visible.get("domain"),
            "search_id": visible.get("search_id"),
            "displayed_item_ids": list(visible.get("displayed_item_ids") or []),
        }

    candidates: list[dict[str, Any]] = []
    if request_id and request_id in visible_results:
        candidates.append(_candidate(request_id, visible_results[request_id]))
    else:
        for req_id, visible in visible_results.items():
            visible_domain = visible.get("domain")
            if domain and not _domain_matches(visible_domain, domain):
                continue
            candidates.append(_candidate(req_id, visible))

        if not candidates and domain:
            latest = (state.get("latest_request_by_domain") or {}).get(domain)
            if latest and latest in visible_results:
                candidates.append(_candidate(latest, visible_results[latest]))

        if not domain and not request_id:
            active = state.get("active_request_id")
            if active and active in visible_results:
                candidates = [_candidate(active, visible_results[active])]

    if not candidates:
        return ClarificationNeeded(
            reason="Không tìm thấy danh sách kết quả phù hợp để tham chiếu.",
            candidates=[],
        )
    if len(candidates) > 1 and not request_id:
        # If domain uniquely selects one, keep it; otherwise clarify.
        if domain:
            domain_matches = [c for c in candidates if _domain_matches(c.get("domain"), domain)]
            if len(domain_matches) == 1:
                candidates = domain_matches
            elif len(domain_matches) > 1:
                return ClarificationNeeded(
                    reason=(
                        "Có nhiều danh sách phù hợp. Vui lòng nêu rõ tuyến/ngày hoặc domain."
                    ),
                    candidates=domain_matches,
                )
        else:
            return ClarificationNeeded(
                reason=(
                    "Có nhiều danh sách phù hợp. Vui lòng nêu rõ tuyến/ngày hoặc domain."
                ),
                candidates=candidates,
            )

    chosen = candidates[0]
    displayed = list(chosen.get("displayed_item_ids") or [])
    if not displayed:
        return ClarificationNeeded(
            reason="Danh sách hiển thị đang trống.",
            candidates=candidates,
        )

    if item_id:
        if item_id not in displayed:
            return ClarificationNeeded(
                reason=f"item_id '{item_id}' không nằm trong danh sách đang hiển thị.",
                candidates=candidates,
            )
        resolved_item_id = item_id
        resolved_position = displayed.index(item_id) + 1
    elif position is not None:
        if position < 1 or position > len(displayed):
            return ClarificationNeeded(
                reason=(
                    f"Vị trí {position} nằm ngoài danh sách ({len(displayed)} mục)."
                ),
                candidates=candidates,
            )
        resolved_position = int(position)
        resolved_item_id = displayed[resolved_position - 1]
    else:
        return ClarificationNeeded(
            reason="Thiếu position hoặc item_id để resolve.",
            candidates=candidates,
        )

    return ResolvedReference(
        domain=str(chosen.get("domain") or domain or "unknown"),
        request_id=str(chosen.get("request_id")),
        search_id=str(chosen.get("search_id") or ""),
        item_id=str(resolved_item_id),
        position=int(resolved_position),
    )
