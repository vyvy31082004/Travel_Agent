from __future__ import annotations

import re
from typing import Any, Iterable, Sequence


_DOMAIN_ID_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "hotel": [
        re.compile(r"\(ID:\s*([A-Za-z0-9_-]+)\)", re.IGNORECASE),
        re.compile(r"external_hotel_id[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE),
        re.compile(r"hotel_id[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE),
    ],
    "car": [
        re.compile(r"item_id[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE),
        re.compile(r"\(ID:\s*([A-Za-z0-9_-]+)\)", re.IGNORECASE),
    ],
    "flight": [
        re.compile(r"Offer_ID[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE),
        re.compile(r"\b(FL-[A-Z0-9]+)\b"),
        re.compile(r"flight_id[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE),
        re.compile(r"\(ID:\s*([A-Za-z0-9_-]+)\)", re.IGNORECASE),
    ],
    "tour": [
        re.compile(r"external_attraction_id[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE),
        re.compile(r"\(ID:\s*([A-Za-z0-9_-]+)\)", re.IGNORECASE),
        re.compile(r"slug[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE),
    ],
}

# excursion branch uses Result Store domain "tour"
_DOMAIN_ALIASES = {
    "excursion": "tour",
}


def _normalize_domain(domain: str | None) -> str:
    value = (domain or "").strip().lower()
    return _DOMAIN_ALIASES.get(value, value)


def _ai_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(_ai_text(block.get("text")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(part for part in parts if part)
    return str(content) if content is not None else ""


def _candidate_ids_from_text(text: str, domain: str) -> list[str]:
    patterns = _DOMAIN_ID_PATTERNS.get(domain, _DOMAIN_ID_PATTERNS["hotel"])
    found: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            candidate = str(match.group(1)).strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            found.append(candidate)
    return found


def _fallback_by_name_price(
    text: str,
    known_items: Sequence[dict[str, Any]],
) -> list[str]:
    lowered = text.lower()
    matched: list[str] = []
    seen: set[str] = set()
    for item in known_items:
        item_id = str(item.get("item_id") or "")
        if not item_id or item_id in seen:
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
        if not isinstance(payload, dict):
            payload = item
        name = str(payload.get("name") or payload.get("airline") or payload.get("Tên xe") or "").strip()
        if not name:
            continue
        if name.lower() not in lowered:
            continue
        seen.add(item_id)
        matched.append(item_id)
    return matched


def extract_presented_item_ids(
    *,
    ai_text: str,
    domain: str | None,
    known_item_ids: Iterable[str],
    known_items: Sequence[dict[str, Any]] | None = None,
) -> list[str]:
    """Return item_ids the domain LLM presented, in first-seen order."""
    domain_key = _normalize_domain(domain)
    known = {str(item_id) for item_id in known_item_ids if item_id}
    if not known:
        return []

    text = _ai_text(ai_text)
    if not text.strip():
        return []

    ordered: list[str] = []
    seen: set[str] = set()
    for candidate in _candidate_ids_from_text(text, domain_key):
        if candidate not in known or candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)

    if ordered:
        return ordered

    if known_items:
        for item_id in _fallback_by_name_price(text, known_items):
            if item_id in known and item_id not in seen:
                seen.add(item_id)
                ordered.append(item_id)

    return ordered
