from __future__ import annotations

from typing import Any


def _filter_domain_dict(data: dict[str, Any] | None, domain: str) -> dict[str, Any]:
    if not data:
        return {}
    filtered: dict[str, Any] = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        entry_domain = value.get("domain")
        if entry_domain is None or entry_domain == domain:
            filtered[key] = value
    return filtered


def compact_domain_state(state: dict[str, Any], domain: str) -> dict[str, Any]:
    latest_request_id = (state.get("latest_request_by_domain") or {}).get(domain)
    visible = _filter_domain_dict(state.get("visible_results"), domain)
    requests = _filter_domain_dict(state.get("requests"), domain)
    request_results = _filter_domain_dict(state.get("request_results"), domain)
    selected_items = _filter_domain_dict(state.get("selected_items"), domain)
    return {
        "domain": domain,
        "active_request_id": state.get("active_request_id")
        if latest_request_id == state.get("active_request_id")
        else latest_request_id,
        "latest_request_id": latest_request_id,
        "visible_results": visible,
        "requests": requests,
        "request_results": request_results,
        "selected_items": selected_items,
        "pending_action": state.get("pending_action"),
    }


def build_domain_scoped_state(state: dict[str, Any], domain: str) -> dict[str, Any]:
    """Return branch input for a sub-agent without global or cross-domain context."""
    domain_state = compact_domain_state(state, domain)
    scoped: dict[str, Any] = {
        "user_id": state.get("user_id"),
        "thread_id": state.get("thread_id"),
        "delegated_request": state.get("delegated_request") or "",
        "turn_constraints": list(state.get("turn_constraints") or []),
        "trip_plan_user_message": state.get("trip_plan_user_message") or "",
        "user_query": state.get("user_query")
        or state.get("trip_plan_user_message")
        or "",
        "domain_action": state.get("domain_action"),
        "domain_memory_context": state.get("domain_memory_context") or "",
        "domain_soft_memory_context": state.get("domain_soft_memory_context") or "",
        "memory_applicability": list(state.get("memory_applicability") or []),
        "recalled_memory_ids": list(state.get("recalled_memory_ids") or []),
        "visible_results": domain_state["visible_results"],
        "requests": domain_state["requests"],
        "request_results": domain_state["request_results"],
        "selected_items": domain_state["selected_items"],
        "latest_request_by_domain": {
            domain: domain_state["latest_request_id"]
        }
        if domain_state["latest_request_id"]
        else {},
        "active_request_id": domain_state["active_request_id"],
        "pending_action": domain_state["pending_action"],
    }
    if domain == "flight":
        scoped["flight_token_map"] = dict(state.get("flight_token_map") or {})
    return scoped


def resolve_user_query(state: dict[str, Any]) -> str:
    delegated = (state.get("delegated_request") or "").strip()
    if delegated:
        return delegated
    for key in ("user_query", "trip_plan_user_message"):
        value = (state.get(key) or "").strip()
        if value:
            return value
    return ""
