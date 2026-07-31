from __future__ import annotations

from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from memory.domain_runtime import invoke_domain_llm_with_temp_payloads
from memory.tool_wrapper import extract_refs_from_messages, state_updates_from_refs
from repositories.result_store import ResultStoreRepository


def repo_from_config(config: Optional[RunnableConfig]) -> ResultStoreRepository | None:
    if not config:
        return None
    configurable = config.get("configurable") or {}
    repo = configurable.get("result_store")
    return repo if isinstance(repo, ResultStoreRepository) else None


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

        # Keep flight detail tokens in structured session map for booking tools.
        token_map: dict[str, str] = {}
        for ref in refs:
            if ref.get("domain") != "flight":
                continue
            for label in ref.get("labels") or []:
                item_id = label.get("item_id")
                # detail tokens are not in labels; filled after payload enrich path.
                if item_id and label.get("detail_token"):
                    token_map[str(item_id)] = str(label["detail_token"])
        if token_map:
            updates["flight_token_map"] = token_map

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
