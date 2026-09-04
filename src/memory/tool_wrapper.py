from __future__ import annotations

import json
import uuid
from typing import Any, Optional, Sequence

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from pydantic import ConfigDict, Field

from memory.normalize import (
    SEARCH_TOOL_NAMES,
    TOOL_DOMAIN,
    compact_tool_ref,
    label_from_normalized,
    normalize_search_results,
    parse_tool_content,
)
from repositories.result_store import ResultStoreRepository


def _config_value(
    config: Optional[RunnableConfig], key: str, default: Any = None
) -> Any:
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


async def persist_search_tool_result(
    tool_name: str,
    raw_result: Any,
    config: Optional[RunnableConfig],
    repo: ResultStoreRepository,
    query: Optional[dict[str, Any]] = None,
    display_limit: int = 10,
) -> dict[str, Any]:
    domain = TOOL_DOMAIN.get(tool_name)
    if not domain:
        return raw_result if isinstance(raw_result, dict) else {"result": raw_result}

    user_id = str(_config_value(config, "user_id", "") or "dev-user")
    thread_id = str(_config_value(config, "thread_id", "") or "dev-thread")
    request_id = str(
        _config_value(config, "request_id", "")
        or f"req_{domain}_{uuid.uuid4().hex[:8]}"
    )

    parsed = parse_tool_content(raw_result)
    items = normalize_search_results(domain, parsed)
    saved = await repo.save_search(
        user_id=user_id,
        thread_id=thread_id,
        request_id=request_id,
        domain=domain,
        query=query or {},
        items=items,
        display_limit=display_limit,
    )
    labels = [label_from_normalized(item) for item in items[:display_limit]]
    return compact_tool_ref(
        request_id=saved.request_id,
        search_id=saved.search_id,
        domain=domain,
        total_results=saved.total_results,
        displayed_item_ids=saved.displayed_item_ids,
        labels=labels,
    )


class ResultStoreTool(BaseTool):
    """Delegate to an underlying tool, persist search payloads, return compact refs."""

    name: str
    description: str
    underlying: Any
    repo: Any
    display_limit: int = 10
    model_config = ConfigDict(arbitrary_types_allowed=True)
    args_schema: Any = Field(default=None)

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("ResultStoreTool only supports async invocation")

    async def _arun(
        self,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> Any:
        call_input: Any = kwargs
        # Some adapters wrap args under "args" / pass a single positional-like value.
        if set(kwargs.keys()) == {"args"} and isinstance(kwargs.get("args"), dict):
            call_input = kwargs["args"]
        elif "args" in kwargs and len(kwargs) > 1:
            call_input = {k: v for k, v in kwargs.items() if k != "args"}

        query = call_input if isinstance(call_input, dict) else {"value": call_input}
        raw = await self.underlying.ainvoke(call_input, config=config)
        if self.name in SEARCH_TOOL_NAMES:
            return await persist_search_tool_result(
                self.name,
                raw,
                config,
                self.repo,
                query=query if isinstance(query, dict) else None,
                display_limit=self.display_limit,
            )
        return raw


def wrap_tools_with_result_store(
    tools: Sequence[BaseTool],
    repo: ResultStoreRepository,
    display_limit: int = 10,
) -> list[BaseTool]:
    wrapped: list[BaseTool] = []
    for tool in tools:
        if tool.name in SEARCH_TOOL_NAMES:
            wrapped.append(
                ResultStoreTool(
                    name=tool.name,
                    description=tool.description,
                    underlying=tool,
                    repo=repo,
                    display_limit=display_limit,
                    args_schema=getattr(tool, "args_schema", None),
                )
            )
        else:
            wrapped.append(tool)
    return wrapped


def extract_refs_from_messages(messages: Sequence[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        parsed = parse_tool_content(message.content)
        candidates: list[Any]
        if isinstance(parsed, dict):
            candidates = [parsed]
        elif isinstance(parsed, list):
            candidates = parsed
        else:
            continue
        for data in candidates:
            if not isinstance(data, dict):
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                else:
                    continue
            if "search_id" in data and "displayed_item_ids" in data:
                refs.append(data)
    return refs


def state_updates_from_refs(
    refs: Sequence[dict[str, Any]],
    domain_hint: Optional[str] = None,
) -> dict[str, Any]:
    requests: dict[str, dict] = {}
    request_results: dict[str, dict] = {}
    visible_results: dict[str, dict] = {}
    latest_request_by_domain: dict[str, str] = {}
    active_request_id: Optional[str] = None

    for ref in refs:
        request_id = str(ref.get("request_id") or "")
        if not request_id:
            continue
        domain = str(ref.get("domain") or domain_hint or "unknown")
        search_id = str(ref.get("search_id") or "")
        displayed = list(ref.get("displayed_item_ids") or [])

        requests[request_id] = {
            "domain": domain,
            "status": "completed",
        }
        request_results[request_id] = {
            "search_id": search_id,
            "total_results": ref.get("total_results", len(displayed)),
            "domain": domain,
        }
        visible_results[request_id] = {
            "search_id": search_id,
            "displayed_item_ids": displayed,
            "domain": domain,
        }
        latest_request_by_domain[domain] = request_id
        active_request_id = request_id

    update: dict[str, Any] = {
        "requests": requests,
        "request_results": request_results,
        "visible_results": visible_results,
        "latest_request_by_domain": latest_request_by_domain,
    }
    if active_request_id is not None:
        update["active_request_id"] = active_request_id
    return update
