from __future__ import annotations

from typing import Any, Callable

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from agents.primary.domain_scope import compact_domain_state, resolve_user_query
from memory.constraint_hints import derive_turn_constraints, merge_turn_constraints
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


def applicability_user_query(state: dict[str, Any]) -> str:
    """Build the utterance used for applicability / action inference.

    Primary often rewrites ``delegated_request`` to a search-only slice and moves
    preference updates into ``turn_constraints``. Applicability must still see
    those preference flips (e.g. nhóm lớn → nhóm nhỏ), so prefer the full
    user utterance and append any constraints missing from it.
    """
    full = (
        (state.get("trip_plan_user_message") or "").strip()
        or (state.get("user_query") or "").strip()
    )
    delegated = (state.get("delegated_request") or "").strip()
    base = full or delegated or resolve_user_query(state)
    constraints = [
        str(item).strip()
        for item in (state.get("turn_constraints") or [])
        if str(item).strip()
    ]
    if not constraints:
        return base
    missing = [item for item in constraints if item.lower() not in base.lower()]
    if not missing:
        return base
    if not base:
        return "\n".join(missing)
    return f"{base}\n" + "\n".join(missing)


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
        user_query = applicability_user_query(state)
        if not user_query:
            return {
                "domain_memory_context": "",
                "domain_soft_memory_context": "",
                "recalled_memory_ids": [],
                "memory_applicability": [],
            }
        domain_state = compact_domain_state(state, domain_value)
        domain_state["turn_constraints"] = list(state.get("turn_constraints") or [])
        recall = await memory_service.recall_domain_with_applicability(
            user_id=state.get("user_id") or user_id,
            query=user_query,
            domain=domain_value,
            domain_state=domain_state,
            llm=llm,
        )
        from memory.applicability import ApplicabilityJudgment, ApplicabilityLabel

        judgments = [
            ApplicabilityJudgment(
                memory_id=str(item.get("memory_id") or ""),
                label=ApplicabilityLabel(str(item.get("label") or "uncertain")),
                confidence=float(item.get("confidence") or 0.0),
                reason=str(item.get("reason") or ""),
            )
            for item in recall.applicability
        ]
        derived_constraints = derive_turn_constraints(
            recall.memories,
            judgments,
            domain=domain_value,
        )
        turn_constraints = merge_turn_constraints(
            state.get("turn_constraints"),
            derived_constraints,
        )
        return {
            "domain_action": recall.domain_action,
            "domain_memory_context": recall.memory_context,
            "domain_soft_memory_context": recall.domain_soft_memory_context,
            "recalled_memory_ids": recall.recalled_memory_ids,
            "memory_applicability": recall.applicability,
            "turn_constraints": turn_constraints,
            "applied_constraints": derived_constraints,
        }

    memory_recall_node.__name__ = node_name or f"memory_recall_{domain_value}"
    return memory_recall_node


# Backward-compatible alias for older tests/imports.
make_domain_recall_node = make_domain_memory_recall_node
