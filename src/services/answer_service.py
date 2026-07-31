from __future__ import annotations

import json
from typing import Any, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from repositories.result_store import (
    ResultStoreExpiredError,
    ResultStoreNotFoundError,
    ResultStoreRepository,
)
from services.reference_resolver import ClarificationNeeded, resolve_item_reference

DOMAIN_ANSWER_INSTRUCTIONS = {
    "flight": "Trình bày đầy đủ kết quả chuyến bay bằng tiếng Việt.",
    "hotel": "Trình bày đầy đủ kết quả khách sạn bằng tiếng Việt.",
    "tour": "Trình bày đầy đủ kết quả tour/điểm tham quan bằng tiếng Việt.",
    "car": "Trình bày đầy đủ kết quả thuê xe bằng tiếng Việt.",
}


def _thread_id_from_state(state: dict[str, Any]) -> str:
    return str(state.get("thread_id") or "")


async def build_answer_from_store(
    llm: BaseChatModel,
    repo: ResultStoreRepository,
    state: dict[str, Any],
    domain: str,
    request_id: Optional[str] = None,
    item_ids: Optional[Sequence[str]] = None,
    user_question: Optional[str] = None,
) -> AIMessage:
    user_id = str(state.get("user_id") or "")
    thread_id = _thread_id_from_state(state)
    latest = state.get("latest_request_by_domain") or {}
    request_id = request_id or latest.get(domain) or state.get("active_request_id")
    if not request_id:
        return AIMessage(
            content="Chưa có kết quả tìm kiếm để trình bày. Vui lòng tìm kiếm trước."
        )

    visible = (state.get("visible_results") or {}).get(request_id) or {}
    search_id = visible.get("search_id") or (
        (state.get("request_results") or {}).get(request_id) or {}
    ).get("search_id")
    displayed = list(item_ids or visible.get("displayed_item_ids") or [])
    if not search_id or not displayed:
        return AIMessage(
            content="Không tìm thấy tham chiếu kết quả để tải dữ liệu chi tiết."
        )
    if not user_id or not thread_id:
        return AIMessage(
            content="Thiếu user_id/thread_id nên không thể tải Result Store an toàn."
        )

    try:
        items = await repo.load_items(
            search_id=search_id,
            item_ids=displayed,
            user_id=user_id,
            thread_id=thread_id,
        )
    except ResultStoreExpiredError:
        return AIMessage(
            content=(
                "Kết quả tìm kiếm đã hết hạn. Vui lòng tìm lại trước khi xem "
                "chi tiết hoặc đặt dịch vụ."
            )
        )
    except ResultStoreNotFoundError:
        return AIMessage(
            content="Không tìm thấy dữ liệu kết quả tương ứng với phiên hiện tại."
        )

    request_meta = (state.get("requests") or {}).get(request_id) or {
        "domain": domain,
        "status": "completed",
    }
    instruction = DOMAIN_ANSWER_INSTRUCTIONS.get(
        domain, "Trình bày đầy đủ kết quả bằng tiếng Việt."
    )
    instruction += (
        " Chỉ dùng dữ liệu được cung cấp, không tự suy đoán. "
        "Không invent ID/giá/ngày. Đánh số thứ tự theo danh sách được cung cấp."
    )
    model_input = [
        SystemMessage(content=instruction),
        HumanMessage(
            content=(
                "Yêu cầu hiện tại và dữ liệu công cụ:\n"
                + json.dumps(
                    {
                        "user_question": user_question,
                        "request": request_meta,
                        "items": items,
                    },
                    ensure_ascii=False,
                )
            )
        ),
    ]
    answer = await llm.ainvoke(model_input)
    if isinstance(answer, AIMessage):
        return answer
    return AIMessage(content=getattr(answer, "content", str(answer)))


async def answer_item_detail(
    llm: BaseChatModel,
    repo: ResultStoreRepository,
    state: dict[str, Any],
    domain: Optional[str] = None,
    position: Optional[int] = None,
    item_id: Optional[str] = None,
    user_question: Optional[str] = None,
) -> AIMessage:
    resolved = resolve_item_reference(
        state, domain=domain, position=position, item_id=item_id
    )
    if isinstance(resolved, ClarificationNeeded):
        return AIMessage(
            content=json.dumps(
                {
                    "needs_clarification": True,
                    "reason": resolved.reason,
                    "candidates": resolved.candidates,
                },
                ensure_ascii=False,
            )
        )
    return await build_answer_from_store(
        llm,
        repo,
        state,
        domain=resolved.domain,
        request_id=resolved.request_id,
        item_ids=[resolved.item_id],
        user_question=user_question,
    )


async def enrich_invoke_messages_with_payloads(
    messages: Sequence[Any],
    repo: ResultStoreRepository,
    user_id: str,
    thread_id: str,
) -> list[Any]:
    """Build a temporary message list for llm.ainvoke without mutating State."""
    from langchain_core.messages import ToolMessage

    from memory.normalize import parse_tool_content

    enriched: list[Any] = []
    for message in messages:
        enriched.append(message)
        if not isinstance(message, ToolMessage):
            continue

        parsed = parse_tool_content(message.content)
        if not isinstance(parsed, dict):
            continue
        search_id = parsed.get("search_id")
        item_ids = parsed.get("displayed_item_ids")
        if not search_id or not item_ids:
            continue
        try:
            items = await repo.load_items(
                search_id=str(search_id),
                item_ids=list(item_ids),
                user_id=user_id,
                thread_id=thread_id,
            )
        except (ResultStoreExpiredError, ResultStoreNotFoundError):
            enriched.append(
                HumanMessage(
                    content=(
                        "Temporary tool payload unavailable (expired or not found). "
                        "Ask user to search again."
                    )
                )
            )
            continue

        enriched.append(
            HumanMessage(
                content=(
                    "Temporary Result Store payload for answering "
                    "(do not treat as durable state):\n"
                    + json.dumps(
                        {
                            "search_id": search_id,
                            "request_id": parsed.get("request_id"),
                            "domain": parsed.get("domain"),
                            "items": items,
                        },
                        ensure_ascii=False,
                    )
                )
            )
        )
    return enriched
