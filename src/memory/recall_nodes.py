from __future__ import annotations

from typing import Any, Callable

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from agents.primary.domain_scope import compact_domain_state, resolve_user_query
from memory.long_term import MemoryDomain
from services.long_term_memory import MemoryService, config_user_thread


def _last_user_text(state: dict[str, Any]) -> str:
    for message in reversed(state.get("messages") or []):
        message_type = getattr(message, "type", None)
        if message_type in {"human", "user"}:
            content = getattr(message, "content", "")
            return content if isinstance(content, str) else str(content)
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
        if isinstance(message, tuple) and len(message) >= 2 and message[0] in {"user", "human"}:
            return str(message[1])
    return ""


def make_global_recall_node(
    memory_service: MemoryService | None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    async def memory_recall_global_node(
        state: dict[str, Any], config: RunnableConfig
    ) -> dict:
        if memory_service is None:
            return {"memory_context": "", "recalled_memory_ids": []}
        user_id, _ = config_user_thread(config)
        recall = await memory_service.recall_global(
            user_id=state.get("user_id") or user_id,
            query=_last_user_text(state),
        )
        return {
            "memory_context": recall.memory_context,
            "recalled_memory_ids": recall.recalled_memory_ids,
        }

    return memory_recall_global_node


def make_domain_memory_recall_node(
    memory_service: MemoryService | None,
    *,
    domain: MemoryDomain | str,
    llm=None,
    node_name: str | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    domain_value = domain.value if isinstance(domain, MemoryDomain) else str(domain)

    async def memory_recall_node(state: dict[str, Any], config: RunnableConfig) -> dict:
        if memory_service is None:
            return {
                "domain_memory_context": "",
                "domain_soft_memory_context": "",
                "recalled_memory_ids": [],
                "memory_applicability": [],
            }
        user_id, _ = config_user_thread(config)
        user_query = resolve_user_query(state)
        if not user_query:
            return {
                "domain_memory_context": "",
                "domain_soft_memory_context": "",
                "recalled_memory_ids": [],
                "memory_applicability": [],
            }
        domain_state = compact_domain_state(state, domain_value)
        recall = await memory_service.recall_domain_with_applicability(
            user_id=state.get("user_id") or user_id,
            query=user_query,
            domain=domain_value,
            domain_state=domain_state,
            llm=llm,
        )
        return {
            "domain_action": recall.domain_action,
            "domain_memory_context": recall.memory_context,
            "domain_soft_memory_context": recall.domain_soft_memory_context,
            "recalled_memory_ids": recall.recalled_memory_ids,
            "memory_applicability": recall.applicability,
        }

    memory_recall_node.__name__ = node_name or f"memory_recall_{domain_value}"
    return memory_recall_node


# Backward-compatible alias for older tests/imports.
make_domain_recall_node = make_domain_memory_recall_node
