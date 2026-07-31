from __future__ import annotations

import json
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from services.answer_service import enrich_invoke_messages_with_payloads
from services.reference_resolver import ClarificationNeeded, resolve_item_reference


def _config_get(config: Optional[dict], key: str, default: Any = None) -> Any:
    if not config:
        try:
            from langgraph.config import get_config

            config = get_config()
        except Exception:
            config = None
    if not config:
        return default
    configurable = config.get("configurable") or {}
    return configurable.get(key, default)


def last_user_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def dumps_compact(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def extract_ordinal_position(text: str) -> Optional[int]:
    """Extract 1-based ordinal like 'thứ 2', '#3', 'so 1' from user text."""
    if not text:
        return None
    patterns = [
        r"thứ\s*(\d+)",
        r"thu\s*(\d+)",
        r"số\s*(\d+)",
        r"so\s*(\d+)",
        r"#\s*(\d+)",
        r"number\s*(\d+)",
        r"\b(\d+)\s*(?:st|nd|rd|th)\b",
        r"(?:item|hotel|khách sạn|chuyến bay|tour|xe)\s*(?:số\s*)?(\d+)\b",
    ]
    lowered = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if match:
            value = int(match.group(1))
            if value >= 1:
                return value
    return None


async def inject_visible_result_context(
    messages: list[Any],
    *,
    state: dict[str, Any],
    repo,
    user_id: str,
    thread_id: str,
    domain_hint: Optional[str] = None,
) -> list[Any]:
    """Inject Result Store payloads for the active domain list / ordinal item.

    Domain subgraphs start with a fresh HumanMessage, so ToolMessage enrichment
    alone is not enough for follow-ups like 'khách sạn thứ 2'.
    """
    if repo is None or not user_id or not thread_id:
        return messages

    user_text = last_user_text(messages)
    position = extract_ordinal_position(user_text)
    domain = domain_hint
    if not domain:
        latest = state.get("latest_request_by_domain") or {}
        active = state.get("active_request_id")
        visible = state.get("visible_results") or {}
        if active and active in visible:
            domain = (visible.get(active) or {}).get("domain")
        elif len(latest) == 1:
            domain = next(iter(latest.keys()))

    extra_messages: list[Any] = []

    if position is not None:
        resolved = resolve_item_reference(
            state, domain=domain, position=position
        )
        if isinstance(resolved, ClarificationNeeded):
            extra_messages.append(
                HumanMessage(
                    content=(
                        "REFERENCE RESOLVER needs clarification "
                        "(do NOT invent IDs; ask briefly):\n"
                        + dumps_compact(
                            {
                                "reason": resolved.reason,
                                "candidates": resolved.candidates,
                            }
                        )
                    )
                )
            )
        else:
            try:
                item = await repo.load_item(
                    search_id=resolved.search_id,
                    item_id=resolved.item_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    include_detail_token=False,
                )
            except Exception as exc:
                extra_messages.append(
                    HumanMessage(
                        content=(
                            "Temporary Result Store payload unavailable for the "
                            f"requested item ({exc}). Ask user to search again."
                        )
                    )
                )
            else:
                extra_messages.append(
                    HumanMessage(
                        content=(
                            "RESOLVED ITEM REFERENCE (deterministic code mapping; "
                            "use this item_id / hotel_id / Offer_ID; do NOT escalate):\n"
                            + dumps_compact(
                                {
                                    "domain": resolved.domain,
                                    "position": resolved.position,
                                    "request_id": resolved.request_id,
                                    "search_id": resolved.search_id,
                                    "item_id": resolved.item_id,
                                    "item": item,
                                }
                            )
                        )
                    )
                )
            # Still include full visible list for context.
            domain = resolved.domain

    # Inject current visible list for the domain (search follow-ups / detail tools).
    request_id = None
    if domain:
        request_id = (state.get("latest_request_by_domain") or {}).get(domain)
    if not request_id:
        request_id = state.get("active_request_id")
    visible = (state.get("visible_results") or {}).get(request_id or "") or {}
    search_id = visible.get("search_id")
    item_ids = list(visible.get("displayed_item_ids") or [])
    if search_id and item_ids:
        try:
            items = await repo.load_items(
                search_id=str(search_id),
                item_ids=item_ids,
                user_id=user_id,
                thread_id=thread_id,
            )
            # Strip detail tokens from temporary prompt context.
            safe_items = []
            for item in items:
                cleaned = dict(item)
                cleaned.pop("detail_token", None)
                safe_items.append(cleaned)
            extra_messages.append(
                HumanMessage(
                    content=(
                        "Temporary Result Store visible list for this domain "
                        "(do not treat as durable state). "
                        "Ordinal 'thứ N' maps by list order below:\n"
                        + dumps_compact(
                            {
                                "domain": visible.get("domain") or domain,
                                "request_id": request_id,
                                "search_id": search_id,
                                "displayed_item_ids": item_ids,
                                "items": safe_items,
                            }
                        )
                    )
                )
            )
        except Exception as exc:
            extra_messages.append(
                HumanMessage(
                    content=(
                        "Temporary visible list unavailable "
                        f"(expired or not found: {exc}). Ask user to search again."
                    )
                )
            )

    if not extra_messages:
        return messages
    # Keep user request last so the model answers the latest ask with context above.
    if messages:
        return [*messages[:-1], *extra_messages, messages[-1]]
    return extra_messages


async def invoke_domain_llm_with_temp_payloads(
    runnable,
    state: dict[str, Any],
    config: dict[str, Any],
    repo,
    summary_prefix: Optional[str] = None,
    domain_hint: Optional[str] = None,
):
    """Invoke domain LLM with Result Store payloads injected temporarily."""
    user_id = str(state.get("user_id") or _config_get(config, "user_id", "") or "")
    thread_id = str(
        state.get("thread_id") or _config_get(config, "thread_id", "") or ""
    )
    messages = list(state.get("messages") or [])
    if repo is not None and user_id and thread_id:
        messages = await enrich_invoke_messages_with_payloads(
            messages, repo=repo, user_id=user_id, thread_id=thread_id
        )
        messages = await inject_visible_result_context(
            messages,
            state=state,
            repo=repo,
            user_id=user_id,
            thread_id=thread_id,
            domain_hint=domain_hint,
        )

    summary_text = summary_prefix if summary_prefix is not None else state.get("summary")
    if summary_text:
        messages = [
            SystemMessage(content=f"Conversation summary so far:\n{summary_text}"),
            *messages,
        ]

    invoke_state = {**state, "messages": messages}
    return await runnable.ainvoke(invoke_state, config=config)
