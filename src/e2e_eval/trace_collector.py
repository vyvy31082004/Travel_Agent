from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from memory.normalize import SEARCH_TOOL_NAMES, TOOL_DOMAIN, parse_tool_content
from repositories.result_store import ResultStoreRepository

ASSISTANT_TO_DOMAIN = {
    "hotel_assistant": "hotel",
    "flight_assistant": "flight",
    "car_assistant": "car",
    "excursion_assistant": "excursion",
}

DELEGATION_TOOL_TO_DOMAIN = {
    "ToHotelAssistant": "hotel",
    "ToFlightAssistant": "flight",
    "ToCarAssistant": "car",
    "ToExcursionAssistant": "excursion",
}

DELEGATION_TOOL_NAMES = set(DELEGATION_TOOL_TO_DOMAIN.keys())

DOMAIN_DEFAULT_SEARCH_TOOL = {
    "hotel": "search_hotels_tool",
    "flight": "search_one_way_flights_tool",
    "car": "search_cars_tool",
    "excursion": "search_attractions_tool",
    "tour": "search_attractions_tool",
}

# Map MCP tool query keys to canonical E2E argument names used in fixtures.
_QUERY_ARGUMENT_ALIASES = {
    "location": "destination",
    "checkin_date": "check_in",
    "checkout_date": "check_out",
}

DOMAIN_ACTION_SEARCH_TOOLS = {
    "search_hotels": "search_hotels_tool",
    "search_one_way": "search_one_way_flights_tool",
    "search_round_trip": "search_round_trip_flights_tool",
    "search_attractions": "search_attractions_tool",
    "search_cars": "search_cars_tool",
}

DOMAIN_CHAT_NODE = {
    "hotel": "hotel_chat",
    "flight": "flight_chat",
    "car": "car_chat",
    "excursion": "excursion_chat",
}

TOOL_SUB_STEPS = {
    "search_attractions_tool": ["searchLocation", "searchAttractions"],
}

APPLY_CONTEXT_LABELS = {"apply", "uncertain"}


def _normalize_query_arguments(query: dict[str, Any]) -> dict[str, Any]:
    arguments = dict(query)
    for src, dest in _QUERY_ARGUMENT_ALIASES.items():
        if src in arguments and dest not in arguments:
            arguments[dest] = arguments[src]
    return arguments


def _branch_options(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    options = raw.get("options") or []
    return [item for item in options if isinstance(item, dict)]


def _resolve_search_tool_name(domain: str) -> str:
    return DOMAIN_DEFAULT_SEARCH_TOOL.get(domain) or DOMAIN_DEFAULT_SEARCH_TOOL.get(
        "tour" if domain == "excursion" else "",
        "",
    )


def _location_from_input_messages(messages: list[str]) -> str | None:
    import re

    for message in messages:
        match = re.search(r"ở\s+(.+?)\s+(?:nên|cho|từ|vào)", message, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _tool_entry_from_option(
    *,
    domain: str,
    option: dict[str, Any],
    tool_name: str | None = None,
) -> dict[str, Any] | None:
    search_id = option.get("search_id")
    if not search_id:
        return None
    resolved_tool = tool_name or _resolve_search_tool_name(domain)
    if not resolved_tool:
        return None
    displayed_item_ids = list(option.get("displayed_item_ids") or [])
    return {
        "domain": TOOL_DOMAIN.get(resolved_tool, domain),
        "name": resolved_tool,
        "arguments": {},
        "timestamp": _utc_now(),
        "raw_result": {
            "search_id": str(search_id),
            "domain": domain,
            "displayed_item_ids": displayed_item_ids,
            "labels": option.get("labels") or [],
            "total_results": len(displayed_item_ids),
        },
        "normalized_result": None,
        "error": None,
        "inferred": True,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _message_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()
    return str(content).strip()


class TraceCollector:
    def __init__(
        self,
        *,
        case_id: str,
        run_id: str,
        user_id: str,
        thread_id: str,
        fixture_to_uuid: dict[str, str],
        input_messages: list[str],
        resolved_dates: dict[str, Any] | None = None,
        model: str = "",
        prompt_version: str = "",
        git_commit: str = "",
        postgres_persist: bool = True,
        teardown: bool = False,
        fresh_seed: bool = False,
    ) -> None:
        self._fixture_to_uuid = fixture_to_uuid
        self._uuid_to_fixture = {value: key for key, value in fixture_to_uuid.items()}
        self._user_id = user_id
        self._thread_id = thread_id
        self.trace: dict[str, Any] = {
            "metadata": {
                "case_id": case_id,
                "run_id": run_id,
                "started_at": _utc_now(),
                "finished_at": None,
                "user_id": user_id,
                "thread_id": thread_id,
                "model": model,
                "prompt_version": prompt_version,
                "git_commit": git_commit,
                "fixture_to_uuid": fixture_to_uuid,
                "postgres_persist": postgres_persist,
                "teardown": teardown,
                "fresh_seed": fresh_seed,
            },
            "input": {
                "messages": input_messages,
                "resolved_dates": resolved_dates or {},
            },
            "turns": [],
            "global_recall": {
                "memory_context": "",
                "recalled_memory_ids": [],
                "recalled_fixture_ids": [],
            },
            "primary_route": {
                "delegated_domains": [],
                "delegation_tool_calls": [],
                "node_updates": [],
            },
            "domain_recall": {},
            "tools": [],
            "sub_agents": [],
            "join": {"branch_count": 0, "merged_domains": []},
            "final_answer": "",
            "stm": {"summary": None, "message_count": 0, "summarized_after_turn": None},
            "finalize": {
                "memory_job_id": None,
                "expected_action": None,
                "db_mutations": [],
                "audits": [],
                "seeded_status": {},
            },
            "auto_scores": None,
            "human_review": {"status": "pending", "scores": None},
        }
        self._node_updates: list[str] = []
        self._execution_path: list[dict[str, Any]] = []
        self._execution_seq = 0
        self._delegated_domains: set[str] = set()
        self._assistant_graphs_started: set[str] = set()

    def record_turn(
        self,
        *,
        turn: int,
        user_message: str,
        answer: str,
        summarize_forced: bool,
        scored: bool,
        nodes: list[str],
        message_count: int,
    ) -> None:
        self.trace.setdefault("turns", []).append(
            {
                "turn": turn,
                "user_message": user_message,
                "answer": answer,
                "summarize_forced": summarize_forced,
                "scored": scored,
                "nodes": list(nodes),
                "message_count": message_count,
            }
        )

    def begin_scored_turn(self) -> None:
        """Keep execution_path and accumulated tools; reset route/recall for this turn."""
        self._delegated_domains = set()
        self._assistant_graphs_started = set()
        # Keep trace["tools"] so multi-turn cases can assert tools from earlier turns.
        self.trace["sub_agents"] = []
        self.trace["domain_recall"] = {}
        self.trace["join"] = {"branch_count": 0, "merged_domains": []}
        self.trace["global_recall"] = {
            "memory_context": "",
            "recalled_memory_ids": [],
            "recalled_fixture_ids": [],
        }
        self.trace["primary_route"]["delegation_tool_calls"] = []

    def record_execution_step(
        self,
        node: str,
        *,
        graph: str = "primary",
        domain: str | None = None,
        memory: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        parent_chat_node: str | None = None,
    ) -> None:
        self._execution_seq += 1
        step: dict[str, Any] = {
            "seq": self._execution_seq,
            "node": node,
            "graph": graph,
            "domain": domain,
            "tools": tools or [],
        }
        if memory is not None:
            step["memory"] = memory
        if parent_chat_node:
            step["parent_chat_node"] = parent_chat_node
        self._execution_path.append(step)
        if node:
            self._node_updates.append(node)

    def record_subgraph_node(
        self,
        node_name: str,
        *,
        graph: str,
        domain: str,
        update: dict[str, Any],
    ) -> None:
        if node_name == "tools":
            tool_entries = self._tool_entries_from_update(update, domain=domain)
            if tool_entries:
                parent_chat = DOMAIN_CHAT_NODE.get(domain)
                if len(tool_entries) == 1:
                    entry = tool_entries[0]
                    self.record_execution_step(
                        entry["name"],
                        graph=graph,
                        domain=domain,
                        tools=tool_entries,
                        parent_chat_node=parent_chat,
                    )
                else:
                    self.record_execution_step(
                        "tools",
                        graph=graph,
                        domain=domain,
                        tools=tool_entries,
                        parent_chat_node=parent_chat,
                    )
            return

        if node_name.endswith("_chat"):
            self.record_execution_step(
                node_name,
                graph=graph,
                domain=domain,
            )
            tool_entries = self._tool_entries_from_update(update, domain=domain)
            if tool_entries:
                parent_chat = node_name
                if len(tool_entries) == 1:
                    entry = tool_entries[0]
                    self.record_execution_step(
                        entry["name"],
                        graph=graph,
                        domain=domain,
                        tools=tool_entries,
                        parent_chat_node=parent_chat,
                    )
                else:
                    self.record_execution_step(
                        "tools",
                        graph=graph,
                        domain=domain,
                        tools=tool_entries,
                        parent_chat_node=parent_chat,
                    )
            return

        memory = self._memory_snapshot_from_update(node_name, update)
        self.record_execution_step(
            node_name,
            graph=graph,
            domain=domain,
            memory=memory,
        )

    def record_assistant_boundary(self, dialog_state: str, domain: str) -> None:
        if dialog_state in self._assistant_graphs_started:
            return
        self._assistant_graphs_started.add(dialog_state)
        self.record_execution_step(
            dialog_state,
            graph="primary",
            domain=domain,
        )

    def _memory_snapshot_from_update(
        self,
        node_name: str,
        update: dict[str, Any],
    ) -> dict[str, Any] | None:
        if node_name == "memory_recall_global":
            recalled = list(update.get("recalled_memory_ids") or [])
            return {
                "recalled_fixture_ids": self._map_fixture_ids(recalled),
                "applicability": {},
            }
        if not node_name.startswith("memory_recall_"):
            return None

        applicability_raw = update.get("memory_applicability") or []
        applicability: dict[str, str] = {}
        applicability_reasons: dict[str, str] = {}
        applied_to_context: list[str] = []
        for item in applicability_raw:
            memory_id = str(item.get("memory_id") or "")
            fixture_id = self._uuid_to_fixture.get(memory_id, memory_id)
            label = str(item.get("label") or "").lower()
            applicability[fixture_id] = label
            reason = str(item.get("reason") or "")
            if reason:
                applicability_reasons[fixture_id] = reason
            if label in APPLY_CONTEXT_LABELS:
                applied_to_context.append(fixture_id)

        return {
            "candidate_pool_ids": list(applicability.keys()),
            "applicability": applicability,
            "applicability_reasons": applicability_reasons,
            "applied_to_context": applied_to_context,
        }

    def _tool_entries_from_update(
        self,
        update: dict[str, Any],
        *,
        domain: str,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for message in update.get("messages") or []:
            if not isinstance(message, AIMessage):
                continue
            for tool_call in getattr(message, "tool_calls", None) or []:
                name = str(tool_call.get("name") or "")
                if not name or name in DELEGATION_TOOL_NAMES:
                    continue
                entry: dict[str, Any] = {
                    "name": name,
                    "arguments": dict(tool_call.get("args") or {}),
                }
                sub_steps = TOOL_SUB_STEPS.get(name)
                if sub_steps:
                    entry["sub_steps"] = list(sub_steps)
                entries.append(entry)
        return entries

    def record_node_update(self, node_name: str, update: dict[str, Any]) -> None:
        if node_name in ASSISTANT_TO_DOMAIN:
            self._delegated_domains.add(ASSISTANT_TO_DOMAIN[node_name])
            return

        if node_name == "memory_recall_global":
            self.trace["global_recall"]["memory_context"] = update.get("memory_context") or ""
            recalled = list(update.get("recalled_memory_ids") or [])
            self.trace["global_recall"]["recalled_memory_ids"] = recalled
            self.trace["global_recall"]["recalled_fixture_ids"] = self._map_fixture_ids(recalled)

        if node_name == "join_results":
            branches = update.get("domain_branch_results") or []
            if branches:
                self.trace["join"]["branch_count"] = len(branches)
                self.trace["join"]["merged_domains"] = [
                    item.get("domain") for item in branches if item.get("domain")
                ]

        if node_name == "memory_finalize":
            self.trace["finalize"]["memory_job_id"] = update.get("memory_job_id")

        memory = self._memory_snapshot_from_update(node_name, update)
        self.record_execution_step(
            node_name,
            graph="primary",
            domain=ASSISTANT_TO_DOMAIN.get(node_name),
            memory=memory,
        )

        for branch in update.get("domain_branch_results") or []:
            domain = branch.get("domain")
            if domain:
                self._record_sub_agent(branch)
                self._record_domain_recall(domain, branch)

    def _record_sub_agent(self, branch: dict[str, Any]) -> None:
        entry = {
            "domain": branch.get("domain"),
            "summary": branch.get("summary") or "",
            "warnings": branch.get("warnings") or [],
            "applied_constraints": branch.get("applied_constraints") or [],
            "domain_action": branch.get("domain_action"),
        }
        existing = [item.get("domain") for item in self.trace["sub_agents"]]
        if entry["domain"] not in existing:
            self.trace["sub_agents"].append(entry)

    def _record_domain_recall(self, domain: str, branch: dict[str, Any]) -> None:
        applicability_raw = branch.get("memory_applicability") or []
        applicability: dict[str, str] = {}
        applicability_reasons: dict[str, str] = {}
        final_context_ids: list[str] = []
        for item in applicability_raw:
            memory_id = str(item.get("memory_id") or "")
            label = str(item.get("label") or "")
            reason = str(item.get("reason") or "")
            fixture_id = self._uuid_to_fixture.get(memory_id, memory_id)
            applicability[fixture_id] = label
            if reason:
                applicability_reasons[fixture_id] = reason
            if label.lower() in {"apply", "overridden", "uncertain"}:
                final_context_ids.append(fixture_id)

        applied = branch.get("applied_constraints") or []
        self.trace["domain_recall"][domain] = {
            "candidate_pool_ids": list(applicability.keys()),
            "applicability": applicability,
            "applicability_reasons": applicability_reasons,
            "final_context_ids": final_context_ids,
            "applied_constraints": applied,
        }

    def record_delegation_from_messages(self, messages: list[Any]) -> None:
        tool_calls: list[dict[str, Any]] = []
        domains: set[str] = set()
        for message in messages:
            if not isinstance(message, AIMessage):
                continue
            for tool_call in getattr(message, "tool_calls", None) or []:
                name = tool_call.get("name") or ""
                domain = DELEGATION_TOOL_TO_DOMAIN.get(name)
                if domain:
                    domains.add(domain)
                tool_calls.append(
                    {
                        "name": name,
                        "args": tool_call.get("args") or {},
                        "timestamp": _utc_now(),
                    }
                )
        self._delegated_domains.update(domains)
        self.trace["primary_route"]["delegation_tool_calls"] = tool_calls

    def record_tool_messages(self, messages: list[Any]) -> None:
        pending_calls: dict[str, dict[str, Any]] = {}
        for message in messages:
            if isinstance(message, AIMessage):
                for tool_call in getattr(message, "tool_calls", None) or []:
                    name = tool_call.get("name") or ""
                    if name in DELEGATION_TOOL_NAMES or name not in SEARCH_TOOL_NAMES:
                        continue
                    call_id = tool_call.get("id") or tool_call.get("name") or ""
                    pending_calls[call_id] = {
                        "name": name,
                        "arguments": dict(tool_call.get("args") or {}),
                        "timestamp": _utc_now(),
                    }
            if isinstance(message, ToolMessage):
                call_id = getattr(message, "tool_call_id", None) or ""
                meta = pending_calls.pop(call_id, {})
                name = meta.get("name") or getattr(message, "name", "") or ""
                if name in DELEGATION_TOOL_NAMES or (
                    name and name not in SEARCH_TOOL_NAMES
                ):
                    continue
                if not name:
                    continue
                domain = TOOL_DOMAIN.get(name, "")
                raw_content = parse_tool_content(message.content)
                self.trace["tools"].append(
                    {
                        "domain": domain,
                        "name": name,
                        "arguments": meta.get("arguments") or {},
                        "timestamp": meta.get("timestamp") or _utc_now(),
                        "raw_result": raw_content,
                        "normalized_result": None,
                        "error": None,
                    }
                )

    def _infer_mcp_tools_from_visible_results(
        self,
        final_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        inferred: list[dict[str, Any]] = []
        for entry in (final_state.get("visible_results") or {}).values():
            if not isinstance(entry, dict) or not entry.get("search_id"):
                continue
            store_domain = str(entry.get("domain") or "")
            branch_domain = "excursion" if store_domain == "tour" else store_domain
            option = {
                "search_id": entry.get("search_id"),
                "displayed_item_ids": entry.get("displayed_item_ids") or [],
                "labels": entry.get("labels") or [],
            }
            tool_entry = _tool_entry_from_option(domain=branch_domain, option=option)
            if tool_entry:
                inferred.append(tool_entry)
        return inferred

    def _infer_mcp_tools_from_domain_action(
        self,
        branches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        inferred: list[dict[str, Any]] = []
        existing_names = {entry.get("name") for entry in self.trace["tools"]}
        resolved_dates = self.trace.get("input", {}).get("resolved_dates") or {}
        input_messages = self.trace.get("input", {}).get("messages") or []

        for branch in branches:
            domain = str(branch.get("domain") or "")
            action = str(branch.get("domain_action") or "")
            tool_name = DOMAIN_ACTION_SEARCH_TOOLS.get(action)
            if not tool_name or tool_name in existing_names:
                continue
            if branch.get("options"):
                continue

            arguments: dict[str, Any] = {}
            if resolved_dates.get("tomorrow"):
                arguments["date"] = resolved_dates["tomorrow"]
                arguments["start_date"] = resolved_dates["tomorrow"]
            location = _location_from_input_messages(input_messages)
            if location:
                arguments["location"] = location

            inferred.append(
                {
                    "domain": TOOL_DOMAIN.get(tool_name, domain),
                    "name": tool_name,
                    "arguments": arguments,
                    "timestamp": _utc_now(),
                    "raw_result": None,
                    "normalized_result": None,
                    "error": None,
                    "inferred": True,
                    "inferred_from": "domain_action",
                }
            )
            existing_names.add(tool_name)
        return inferred

    def _infer_mcp_tools_from_branches(
        self,
        branches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        inferred: list[dict[str, Any]] = []
        for branch in branches:
            domain = str(branch.get("domain") or "")
            if not domain:
                continue
            for option in branch.get("options") or []:
                if not isinstance(option, dict):
                    continue
                entry = _tool_entry_from_option(domain=domain, option=option)
                if entry:
                    inferred.append(entry)
        return inferred

    def _infer_mcp_tools_from_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        inferred: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            tool_name = getattr(message, "name", "") or ""
            parsed = parse_tool_content(message.content)
            if not isinstance(parsed, dict):
                continue
            domain = parsed.get("domain") or DELEGATION_TOOL_TO_DOMAIN.get(tool_name, "")
            if not domain:
                continue
            for option in _branch_options(parsed):
                entry = _tool_entry_from_option(domain=str(domain), option=option)
                if entry:
                    inferred.append(entry)
        return inferred

    def _merge_inferred_tools(self, inferred: list[dict[str, Any]]) -> None:
        existing_search_ids = {
            str((entry.get("raw_result") or {}).get("search_id"))
            for entry in self.trace["tools"]
            if isinstance(entry.get("raw_result"), dict)
            and (entry.get("raw_result") or {}).get("search_id")
        }
        for entry in inferred:
            raw = entry.get("raw_result") or {}
            search_id = raw.get("search_id") if isinstance(raw, dict) else None
            if search_id and str(search_id) in existing_search_ids:
                continue
            if search_id:
                existing_search_ids.add(str(search_id))
            self.trace["tools"].append(entry)

    async def enrich_tool_snapshots(
        self,
        repo: ResultStoreRepository | None,
    ) -> None:
        if repo is None:
            return
        for entry in self.trace["tools"]:
            raw = entry.get("raw_result")
            if not isinstance(raw, dict):
                continue
            search_id = raw.get("search_id")
            if not search_id:
                continue
            item_ids = raw.get("displayed_item_ids") or []
            try:
                search = await repo.load_search(
                    search_id=str(search_id),
                    user_id=self._user_id,
                    thread_id=self._thread_id,
                    allow_expired=True,
                )
                query = search.get("query") or {}
                if isinstance(query, dict) and query:
                    merged = dict(entry.get("arguments") or {})
                    merged.update(_normalize_query_arguments(query))
                    entry["arguments"] = merged
                all_items = await repo.list_all_items(
                    search_id=str(search_id),
                    user_id=self._user_id,
                    thread_id=self._thread_id,
                    allow_expired=True,
                )
                items = all_items
                if await repo.has_display_decisions(
                    search_id=str(search_id),
                    user_id=self._user_id,
                    thread_id=self._thread_id,
                    allow_expired=True,
                ):
                    displayed_ids = await repo.load_displayed_item_ids(
                        search_id=str(search_id),
                        user_id=self._user_id,
                        thread_id=self._thread_id,
                        allow_expired=True,
                    )
                    displayed_items = await repo.load_displayed_items(
                        search_id=str(search_id),
                        user_id=self._user_id,
                        thread_id=self._thread_id,
                        allow_expired=True,
                    )
                    entry["display_decisions"] = {
                        "displayed_item_ids": displayed_ids,
                        "items": displayed_items,
                    }
                    items = all_items
                else:
                    items = await repo.load_items(
                        search_id=str(search_id),
                        item_ids=[str(item_id) for item_id in item_ids],
                        user_id=self._user_id,
                        thread_id=self._thread_id,
                        allow_expired=True,
                    )
                entry["normalized_result"] = {
                    "search_id": search_id,
                    "request_id": raw.get("request_id") or search.get("request_id"),
                    "domain": raw.get("domain") or entry.get("domain") or search.get("domain"),
                    "total_results": raw.get("total_results") or search.get("total_results"),
                    "items": items,
                    "labels": raw.get("labels") or [],
                }
            except Exception as exc:
                entry["error"] = str(exc)

    def finalize_trace(
        self,
        *,
        final_state: dict[str, Any],
        final_answer: str,
        expected_finalize_action: str | None = None,
    ) -> dict[str, Any]:
        messages = final_state.get("messages") or []
        self.record_delegation_from_messages(messages)
        self.record_tool_messages(messages)

        branches = final_state.get("domain_branch_results") or []
        inferred = self._infer_mcp_tools_from_visible_results(final_state)
        inferred.extend(self._infer_mcp_tools_from_branches(branches))
        inferred.extend(self._infer_mcp_tools_from_messages(messages))
        inferred.extend(self._infer_mcp_tools_from_domain_action(branches))
        self._merge_inferred_tools(inferred)

        for branch in branches:
            self._record_sub_agent(branch)
            domain = branch.get("domain")
            if domain:
                self._record_domain_recall(domain, branch)

        self.trace["primary_route"]["delegated_domains"] = sorted(self._delegated_domains)
        self.trace["primary_route"]["node_updates"] = list(self._node_updates)
        self.trace["execution_path"] = list(self._execution_path)
        for entry in self.trace["tools"]:
            seq = self._tool_execution_seq(entry.get("name"))
            if seq is not None:
                entry["execution_seq"] = seq

        if branches:
            self.trace["join"]["branch_count"] = len(branches)
            self.trace["join"]["merged_domains"] = [
                item.get("domain") for item in branches if item.get("domain")
            ]

        self.trace["final_answer"] = final_answer
        self.trace["stm"]["summary"] = final_state.get("summary")
        self.trace["stm"]["message_count"] = len(messages)
        if final_state.get("memory_job_id") is not None:
            self.trace["finalize"]["memory_job_id"] = final_state.get("memory_job_id")
        if expected_finalize_action:
            self.trace["finalize"]["expected_action"] = expected_finalize_action
        self.trace["metadata"]["finished_at"] = _utc_now()
        return self.trace

    def _map_fixture_ids(self, memory_ids: list[str]) -> list[str]:
        mapped: list[str] = []
        for memory_id in memory_ids:
            mapped.append(self._uuid_to_fixture.get(str(memory_id), str(memory_id)))
        return mapped

    def _tool_execution_seq(self, tool_name: str | None) -> int | None:
        if not tool_name:
            return None
        for step in self._execution_path:
            for tool in step.get("tools") or []:
                if tool.get("name") == tool_name:
                    return step.get("seq")
            if step.get("node") == tool_name:
                return step.get("seq")
        return None

    @staticmethod
    def extract_final_ai_response(messages: list[Any], *, since_index: int = 0) -> str:
        responses: list[str] = []
        for message in messages[since_index:]:
            if getattr(message, "type", None) not in {"ai", "assistant"}:
                continue
            if not isinstance(message, AIMessage) and getattr(message, "type", None) not in {
                "ai",
                "assistant",
            }:
                continue
            content = getattr(message, "content", None)
            if not content:
                continue
            text = _message_content_to_text(content)
            if not text.strip():
                continue
            if "Proceeding with the next requested task" in text:
                continue
            if getattr(message, "tool_calls", None):
                continue
            responses.append(text)
        return "\n\n".join(responses)


def trace_collector_from_config(config: Any) -> TraceCollector | None:
    if not config:
        return None
    configurable = config.get("configurable") if isinstance(config, dict) else {}
    if not isinstance(configurable, dict):
        return None
    collector = configurable.get("e2e_trace_collector")
    return collector if isinstance(collector, TraceCollector) else None
