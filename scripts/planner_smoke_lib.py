"""Shared helpers for planner smoke tests and scripts."""

from __future__ import annotations

import os
import socket
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from agents.primary.agent import build_primary_graph
from services.long_term_memory import MemoryService
from settings import Settings
from utils.tracing import with_trace_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

EMPTY_ANSWER = "(không có câu trả lời AI)"


def _build_default_planner_message(*, today: date | None = None) -> str:
    """Trip plan message with concrete dates so search tools can run."""
    depart = (today or date.today()) + timedelta(days=7)
    ret = depart + timedelta(days=2)
    depart_s = depart.strftime("%d/%m/%Y")
    ret_s = ret.strftime("%d/%m/%Y")
    return (
        f"Lên kế hoạch 3 ngày 2 đêm Đà Nẵng từ TP.HCM: "
        f"bay đi SGN→DAD ngày {depart_s}, "
        f"bay về DAD→SGN ngày {ret_s}, "
        f"check-in {depart_s}, check-out {ret_s}, "
        f"2 người lớn, ưu tiên yên tĩnh."
    )


DEFAULT_PLANNER_MESSAGE = _build_default_planner_message()


def message_content_to_text(content: Any) -> str:
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
            else:
                text = getattr(block, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()
    return str(content).strip()


def has_llm_api_key() -> bool:
    return bool(
        (os.getenv("GEMINI_API_KEY") or "").strip()
        or (os.getenv("GOOGLE_API_KEY") or "").strip()
    )


MCP_SERVER_PORTS = (8001, 8002, 8003, 8004)


def mcp_servers_available(timeout: float = 0.5) -> bool:
    """Return True if all domain MCP SSE ports accept TCP connections."""
    for port in MCP_SERVER_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                pass
        except OSError:
            return False
    return True


def planner_smoke_ready() -> bool:
    return has_llm_api_key() and mcp_servers_available()


def make_smoke_settings(**overrides) -> Settings:
    """Minimal settings for smoke runs (no real DB required for graph invoke)."""
    values = dict(
        database_url=os.getenv("DATABASE_URL", "postgresql://smoke:smoke@127.0.0.1/smoke"),
        cookie_secret=os.getenv("COOKIE_SECRET", "planner-smoke-secret"),
        long_term_memory_recall_enabled=False,
        long_term_memory_write_enabled=False,
    )
    values.update(overrides)
    return Settings(**values)


def extract_final_ai_response(messages: list[Any], *, since_index: int = 0) -> str:
    ai_responses: list[str] = []
    for msg in messages[since_index:]:
        if getattr(msg, "type", None) not in {"ai", "assistant"}:
            continue
        content = getattr(msg, "content", None)
        if not content:
            continue
        text = message_content_to_text(content)
        if not text.strip():
            continue
        if "Proceeding with the next requested task" in text:
            continue
        ai_responses.append(text)
    return "\n\n".join(ai_responses) if ai_responses else EMPTY_ANSWER


def format_branch_summary(domain_branch_results: list[dict] | None) -> str:
    branches = domain_branch_results or []
    if not branches:
        return "Domain branches: (none)"
    lines = [f"Domain branches: {len(branches)}"]
    for item in branches:
        domain = item.get("domain", "?")
        summary = message_content_to_text(item.get("summary") or "")
        warnings = item.get("warnings") or []
        preview = summary[:200] + ("..." if len(summary) > 200 else "")
        line = f"  - {domain}: {preview or '(empty summary)'}"
        if warnings:
            line += f" [warnings: {len(warnings)}]"
        lines.append(line)
    return "\n".join(lines)


async def run_planner_smoke(
    *,
    message: str = DEFAULT_PLANNER_MESSAGE,
    user_id: str = "planner-smoke-user",
    thread_id: str | None = None,
    settings: Settings | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Invoke the primary planner graph and return structured output."""
    active_settings = settings or make_smoke_settings()
    memory_service = MemoryService(settings=active_settings)
    if verbose:
        print("Building graph (loading MCP tools from 4 servers)...", flush=True)
    graph = await build_primary_graph(
        checkpointer=MemorySaver(),
        repo=None,
        memory_service=memory_service,
    )

    thread = thread_id or str(uuid.uuid4())
    config = with_trace_config(
        {"configurable": {"thread_id": thread, "user_id": user_id}},
        run_name="planner_smoke",
        tags=["planner-smoke"],
        metadata={"thread_id": thread, "user_id": user_id},
    )

    snapshot = await graph.aget_state(config)
    old_count = len(snapshot.values.get("messages", [])) if snapshot.values else 0

    invoke_input = {
        "messages": [HumanMessage(content=message)],
        "user_id": user_id,
        "thread_id": thread,
    }

    if verbose:
        print(
            "Running planner flow (primary → 4 domains → synthesize). "
            "This can take several minutes...",
            flush=True,
        )
        async for chunk in graph.astream(
            invoke_input,
            config,
            stream_mode="updates",
        ):
            for node_name, update in chunk.items():
                branch_count = len(update.get("domain_branch_results") or [])
                suffix = f" (+{branch_count} branch)" if branch_count else ""
                print(f"  → {node_name}{suffix}", flush=True)
        final = await graph.aget_state(config)
        result = dict(final.values or {})
    else:
        result = await graph.ainvoke(invoke_input, config)

    new_messages = result.get("messages") or []
    slice_messages = new_messages[old_count:] if old_count else new_messages
    answer = extract_final_ai_response(new_messages, since_index=old_count)
    branch_results = list(result.get("domain_branch_results") or [])

    return {
        "message": message,
        "thread_id": thread,
        "user_id": user_id,
        "answer": answer,
        "domain_branch_results": branch_results,
        "new_messages": slice_messages,
        "full_result": result,
    }


def print_planner_output(payload: dict[str, Any]) -> None:
    print(f"\nUser: {payload['message']}")
    print(format_branch_summary(payload.get("domain_branch_results")))
    print("\n========== FINAL ANSWER ==========")
    print(payload.get("answer") or EMPTY_ANSWER)
    print("==================================\n")
