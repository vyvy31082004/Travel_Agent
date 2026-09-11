from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from memory.domain_runtime import invoke_domain_llm_with_temp_payloads
from memory.presented_items import extract_presented_item_ids
from memory.tool_wrapper import (
    extract_refs_from_messages,
    latest_search_ref,
    state_updates_from_refs,
)
from repositories.result_store import ResultStoreRepository

logger = logging.getLogger(__name__)


def repo_from_config(config: Optional[RunnableConfig]) -> ResultStoreRepository | None:
    if not config:
        return None
    configurable = config.get("configurable") or {}
    repo = configurable.get("result_store")
    return repo if isinstance(repo, ResultStoreRepository) else None


def _ai_message_content(message: Any) -> str:
    if not isinstance(message, AIMessage):
        content = getattr(message, "content", "")
    else:
        content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(part for part in parts if part)
    return str(content) if content is not None else ""


async def _persist_display_decisions(
    *,
    repo: ResultStoreRepository,
    response: Any,
    messages: list[Any],
    domain_hint: str,
    user_id: str,
    thread_id: str,
) -> dict[str, Any] | None:
    if isinstance(response, list):
        ai_messages = [msg for msg in response if isinstance(msg, AIMessage)]
        if not ai_messages:
            return None
        ai_msg = ai_messages[-1]
    elif isinstance(response, AIMessage):
        ai_msg = response
    else:
        return None

    if getattr(ai_msg, "tool_calls", None):
        return None

    ref = latest_search_ref(messages, domain_hint=domain_hint)
    if not ref:
        return None

    search_id = str(ref.get("search_id") or "")
    request_id = str(ref.get("request_id") or "")
    if not search_id or not request_id:
        return None

    try:
        known_items = await repo.list_all_items(
            search_id=search_id,
            user_id=user_id,
            thread_id=thread_id,
        )
    except Exception as exc:
        logger.warning("display persist: failed to load items for %s: %s", search_id, exc)
        return None

    known_ids = [str(item["item_id"]) for item in known_items if item.get("item_id")]
    presented_ids = extract_presented_item_ids(
        ai_text=_ai_message_content(ai_msg),
        domain=str(ref.get("domain") or domain_hint),
        known_item_ids=known_ids,
        known_items=known_items,
    )
    if not presented_ids:
        logger.warning(
            "display persist: no item_ids extracted for search %s domain %s",
            search_id,
            domain_hint,
        )
        return None

    try:
        displayed_ids = await repo.update_display_decisions(
            search_id=search_id,
            presented_item_ids=presented_ids,
            user_id=user_id,
            thread_id=thread_id,
        )
    except Exception as exc:
        logger.warning("display persist: update failed for %s: %s", search_id, exc)
        return None

    domain = str(ref.get("domain") or domain_hint)
    return {
        "visible_results": {
            request_id: {
                "search_id": search_id,
                "displayed_item_ids": displayed_ids,
                "domain": domain,
            }
        },
        "latest_request_by_domain": {domain: request_id},
        "active_request_id": request_id,
    }


async def domain_chat_with_memory(
    *,
    runnable,
    state: dict[str, Any],
    config: RunnableConfig,
    domain_hint: str,
    repo: ResultStoreRepository | None = None,
) -> dict[str, Any]:
    active_repo = repo or repo_from_config(config)
    response = await invoke_domain_llm_with_temp_payloads(
        runnable,
        state,
        config,
        active_repo,
        domain_hint=domain_hint,
    )
    messages = [response] if not isinstance(response, list) else response
    updates: dict[str, Any] = {"messages": messages}

    refs = extract_refs_from_messages(state.get("messages") or [])
    if refs:
        updates.update(state_updates_from_refs(refs, domain_hint=domain_hint))

        token_map: dict[str, str] = {}
        for ref in refs:
            if ref.get("domain") != "flight":
                continue
            for label in ref.get("labels") or []:
                item_id = label.get("item_id")
                if item_id and label.get("detail_token"):
                    token_map[str(item_id)] = str(label["detail_token"])
        if token_map:
            updates["flight_token_map"] = token_map

    user_id = str(state.get("user_id") or (config.get("configurable") or {}).get("user_id") or "")
    thread_id = str(state.get("thread_id") or (config.get("configurable") or {}).get("thread_id") or "")
    if active_repo is not None and user_id and thread_id:
        display_updates = await _persist_display_decisions(
            repo=active_repo,
            response=response,
            messages=list(state.get("messages") or []),
            domain_hint=domain_hint,
            user_id=user_id,
            thread_id=thread_id,
        )
        if display_updates:
            visible = dict(updates.get("visible_results") or {})
            visible.update(display_updates.get("visible_results") or {})
            updates["visible_results"] = visible
            updates["latest_request_by_domain"] = {
                **(updates.get("latest_request_by_domain") or {}),
                **(display_updates.get("latest_request_by_domain") or {}),
            }
            if display_updates.get("active_request_id"):
                updates["active_request_id"] = display_updates["active_request_id"]

    return updates


def merge_structured_state(result: dict[str, Any]) -> dict[str, Any]:
    """Pick structured memory fields from a domain graph result."""
    keys = (
        "requests",
        "request_results",
        "visible_results",
        "latest_request_by_domain",
        "active_request_id",
        "selected_items",
        "summary",
        "flight_token_map",
    )
    return {key: result[key] for key in keys if key in result}
