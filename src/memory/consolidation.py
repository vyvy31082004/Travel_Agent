from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, Sequence

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from memory.long_term import MemoryCategory, MemoryDomain, TravelMemory
from services.long_term_memory import serialize_message
from settings import Settings


class TransitionAction(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    SUPERSEDE = "supersede"
    REJECT = "reject"
    NOOP = "noop"


@dataclass(frozen=True)
class RuleResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryTransition:
    action: TransitionAction
    candidate: TravelMemory | None = None
    existing_memory_id: str | None = None
    reasons: list[str] = field(default_factory=list)


class MemoryCandidateExtractor(Protocol):
    async def extract(
        self,
        messages: Sequence[dict[str, Any] | Any],
        *,
        user_id: str,
        thread_id: str,
        existing_active: Sequence[TravelMemory] = (),
        limit: int = 5,
    ) -> list[TravelMemory]:
        """Extract atomic durable memory candidates."""


class LangMemTravelMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_text: str = Field(
        min_length=3,
        max_length=500,
        description=(
            "Tiếng Việt. Một ý durable duy nhất, trung thực với lời user; "
            "không dịch sang tiếng Anh, không thêm chi tiết suy diễn."
        ),
    )
    category: MemoryCategory | str
    domain: MemoryDomain | str
    evidence_text: str = Field(
        description="Nguyên văn hoặc gần nguyên văn câu user làm bằng chứng."
    )
    condition: str | None = Field(
        default=None,
        description=(
            "Điều kiện tiếng Việt nếu user nêu (ví dụ: khi đi công tác, khi đi gia đình). "
            "null nếu không có điều kiện."
        ),
    )


_LANGMEM_EXTRACT_INSTRUCTIONS = """\
Extract only durable, reusable travel preferences, profile facts, or interaction rules
from the user's own evidence.

Language (required):
- Write memory_text, condition, and evidence_text in Vietnamese only.
- Never start with English words like "User".
- Keep the user's key phrases (e.g. "bay thẳng", "bữa sáng", "gần biển", "yên tĩnh",
  "boutique", "đừng hỏi lại").

Multi-fact coverage (required — hard rule):
- Count every durable preference in the user message; emit that many memories (1 fact = 1 memory).
- "boutique gần biển, yên tĩnh" => exactly 3 memories covering boutique, gần biển, yên tĩnh.
- "số tự động, rộng rãi, có tài xế" => exactly 3 memories; never only the first fact.
- Omitting any durable fact is a failure.

Conditions (required — hard rule):
- If the user says "khi đi công tác" / "khi đi gia đình", you MUST set condition to that phrase
  AND keep it visible in memory_text (e.g. "Thích business khi đi công tác").
- Forbidden: "Thích business class" / "Thích economy class" / "Thích resort yên tĩnh"
  without the matching condition when the user stated one.

Category / domain (required):
- "Gọi tôi là …" / tên xưng hô => category=profile_fact, domain=general.
- Sân bay nhà / điểm xuất phát (SGN, …) => category=flight_preference, domain=flight.
- Lịch trình thong thả => category=general_preference, domain=general.
- "đừng hỏi lại" / quy tắc trả lời => category=interaction_rule, domain=general.
- Hotel / flight / car / excursion prefs => matching *_preference and domain.

Do not extract:
- temporary tool/API search results, prices, or one-off trip logistics
- assistant suggestions the user has not confirmed
- ambiguous claims ("có thể", "chưa chắc", "maybe")
- sensitive data (passport, card, CVV, password)

Return no memory if evidence is ambiguous or sensitive.\
"""


class DeterministicCandidateExtractor:
    async def extract(
        self,
        messages: Sequence[dict[str, Any] | Any],
        *,
        user_id: str,
        thread_id: str,
        existing_active: Sequence[TravelMemory] = (),
        limit: int = 5,
    ) -> list[TravelMemory]:
        return extract_candidate_memories(
            messages,
            user_id=user_id,
            thread_id=thread_id,
            limit=limit,
        )


class LangMemCandidateExtractor:
    def __init__(
        self,
        *,
        model: str = "gemini-3.6-flash",
        manager: Any | None = None,
    ) -> None:
        self._model = model
        self._manager = manager

    def _manager_instance(self):
        if self._manager is None:
            from langmem import create_memory_manager

            llm = ChatGoogleGenerativeAI(model=self._model)
            self._manager = create_memory_manager(
                llm,
                schemas=[LangMemTravelMemory],
                instructions=_LANGMEM_EXTRACT_INSTRUCTIONS,
                enable_inserts=True,
                enable_updates=True,
                enable_deletes=False,
            )
        return self._manager

    async def extract(
        self,
        messages: Sequence[dict[str, Any] | Any],
        *,
        user_id: str,
        thread_id: str,
        existing_active: Sequence[TravelMemory] = (),
        limit: int = 5,
    ) -> list[TravelMemory]:
        serialized = [serialize_message(message) for message in messages]
        langmem_messages = [
            {"role": _message_role(message), "content": str(message.get("content") or "")}
            for message in serialized
            if _message_role(message) in {"user", "assistant"}
        ]
        if not langmem_messages:
            return []
        
        existing_dicts = [
            {
                "memory_id": m.memory_id,
                "memory_text": m.memory_text,
                "category": str(m.category),
                "domain": str(m.domain),
            }
            for m in existing_active
        ]
        
        manager = self._manager_instance()
        raw = await manager.ainvoke({"messages": langmem_messages, "existing": existing_dicts})
        return normalize_langmem_outputs(
            raw,
            user_id=user_id,
            thread_id=thread_id,
            fallback_evidence=_latest_user_evidence(serialized),
            limit=limit,
        )


class CompareCandidateExtractor:
    def __init__(self, deterministic: MemoryCandidateExtractor, langmem: MemoryCandidateExtractor) -> None:
        self._deterministic = deterministic
        self._langmem = langmem

    async def extract(
        self,
        messages: Sequence[dict[str, Any] | Any],
        *,
        user_id: str,
        thread_id: str,
        existing_active: Sequence[TravelMemory] = (),
        limit: int = 5,
    ) -> list[TravelMemory]:
        # Dry-run comparison mode: run LangMem to surface adapter errors, but keep
        # deterministic output as the persisted candidate source until explicitly switched.
        await self._langmem.extract(
            messages,
            user_id=user_id,
            thread_id=thread_id,
            existing_active=existing_active,
            limit=limit,
        )
        return await self._deterministic.extract(
            messages,
            user_id=user_id,
            thread_id=thread_id,
            existing_active=existing_active,
            limit=limit,
        )


def build_candidate_extractor(settings: Settings) -> MemoryCandidateExtractor:
    deterministic = DeterministicCandidateExtractor()
    if settings.long_term_memory_extractor == "deterministic":
        return deterministic
    langmem = LangMemCandidateExtractor(model=settings.long_term_memory_langmem_model)
    if settings.long_term_memory_extractor == "langmem":
        return langmem
    return CompareCandidateExtractor(deterministic, langmem)


def extract_candidate_memories(
    messages: Sequence[dict[str, Any] | Any],
    *,
    user_id: str,
    thread_id: str,
    limit: int = 5,
) -> list[TravelMemory]:
    """Extract durable memory candidates from bounded turn messages.

    This deterministic adapter is intentionally conservative. It provides a
    testable fallback while LangMem quality is evaluated in the worker.
    """

    candidates: list[TravelMemory] = []
    for message in messages:
        serialized = serialize_message(message)
        if serialized.get("type") not in {"human", "user"}:
            continue
        text = str(serialized.get("content") or "").strip()
        if not _looks_like_durable_user_evidence(text):
            continue
        memory_text = _clean_memory_text(text)
        if len(memory_text) < 3:
            continue
        category, domain = classify_memory(memory_text)
        try:
            candidates.append(
                TravelMemory(
                    user_id=user_id,
                    memory_text=memory_text,
                    category=category,
                    domain=domain,
                    condition=_extract_condition(memory_text),
                    evidence_text=text,
                    source_thread_id=thread_id,
                )
            )
        except ValueError:
            continue
        if len(candidates) >= limit:
            break
    return candidates


def normalize_langmem_outputs(
    raw_outputs: Any,
    *,
    user_id: str,
    thread_id: str,
    fallback_evidence: str,
    limit: int = 5,
) -> list[TravelMemory]:
    candidates: list[TravelMemory] = []
    for item in raw_outputs or []:
        content = _extract_langmem_content(item)
        try:
            model = _coerce_langmem_memory(content, fallback_evidence=fallback_evidence)
            candidate = TravelMemory(
                user_id=user_id,
                memory_text=model.memory_text,
                category=model.category,
                domain=model.domain,
                condition=model.condition,
                evidence_text=model.evidence_text,
                source_thread_id=thread_id,
            )
        except (TypeError, ValueError, ValidationError):
            continue
        if validate_memory_candidate(candidate).ok:
            candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def validate_memory_candidate(candidate: TravelMemory) -> RuleResult:
    reasons: list[str] = []
    if not candidate.evidence_text.strip():
        reasons.append("missing user evidence")
    if len(candidate.memory_text) > 500:
        reasons.append("memory text is too long")
    lowered = candidate.evidence_text.lower()
    if any(token in lowered for token in _SENSITIVE_TOKENS):
        reasons.append("contains sensitive credential or payment data")
    if any(token in lowered for token in _TOOL_ONLY_MARKERS):
        reasons.append("appears to be tool/API output rather than user evidence")
    if _is_ambiguous(lowered):
        reasons.append("evidence is ambiguous")
    return RuleResult(ok=not reasons, reasons=reasons)


def calculate_transition(
    candidate: TravelMemory,
    existing_active: Sequence[TravelMemory],
) -> MemoryTransition:
    rule_result = validate_memory_candidate(candidate)
    if not rule_result.ok:
        return MemoryTransition(
            action=TransitionAction.REJECT,
            candidate=candidate,
            reasons=rule_result.reasons,
        )

    normalized_candidate = _normalize_statement(candidate.memory_text)
    for existing in existing_active:
        normalized_existing = _normalize_statement(existing.memory_text)
        if normalized_candidate == normalized_existing:
            return MemoryTransition(
                action=TransitionAction.NOOP,
                candidate=candidate,
                existing_memory_id=existing.memory_id,
                reasons=["duplicate active memory"],
            )
        if (
            candidate.category == existing.category
            and candidate.domain == existing.domain
            and _memories_conflict(candidate, existing)
        ):
            return MemoryTransition(
                action=TransitionAction.SUPERSEDE,
                candidate=candidate,
                existing_memory_id=existing.memory_id,
                reasons=["same category/domain with conflicting preference"],
            )

    return MemoryTransition(action=TransitionAction.INSERT, candidate=candidate)


def _extract_langmem_content(item: Any) -> Any:
    if isinstance(item, tuple) and len(item) >= 2:
        return item[1]
    return getattr(item, "content", item)


def _coerce_langmem_memory(content: Any, *, fallback_evidence: str) -> LangMemTravelMemory:
    if isinstance(content, LangMemTravelMemory):
        return content
    if isinstance(content, BaseModel):
        content = content.model_dump()
    if isinstance(content, str):
        content = {
            "memory_text": content,
            "category": MemoryCategory.GENERAL_PREFERENCE,
            "domain": MemoryDomain.GENERAL,
            "evidence_text": fallback_evidence,
        }
    if not isinstance(content, dict):
        raise TypeError("unsupported LangMem output content")
    data = dict(content)
    data.setdefault("evidence_text", fallback_evidence)
    return LangMemTravelMemory(**data)


def _message_role(message: dict[str, Any]) -> str:
    message_type = str(message.get("type") or "").lower()
    if message_type in {"human", "user"}:
        return "user"
    if message_type in {"ai", "assistant"}:
        return "assistant"
    return message_type


def _latest_user_evidence(messages: Sequence[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if _message_role(message) == "user":
            return str(message.get("content") or "")
    return ""


def _looks_like_durable_user_evidence(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _DURABLE_MARKERS)


def _clean_memory_text(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    # Keep polarity markers so conflict detection still works after cleaning.
    polarity_prefixes = [
        ("tôi không thích", "không thích"),
        ("i don't like", "don't like"),
        ("i do not like", "do not like"),
        ("tôi thích", "thích"),
        ("tôi thường", "thường"),
        ("tôi ưu tiên", "ưu tiên"),
        ("ưu tiên của tôi là", "ưu tiên"),
        ("i prefer", "prefer"),
    ]
    lowered = cleaned.lower()
    for prefix, keep in polarity_prefixes:
        if lowered.startswith(prefix):
            rest = cleaned[len(prefix) :].strip(" :,-.")
            return f"{keep} {rest}".strip() if rest else keep

    neutral_prefixes = [
        "hãy nhớ rằng",
        "hãy nhớ",
        "nhớ là",
        "remember that",
        "please remember",
    ]
    for prefix in neutral_prefixes:
        if lowered.startswith(prefix):
            return cleaned[len(prefix) :].strip(" :,-.") or cleaned
    return cleaned


def classify_memory(text: str) -> tuple[MemoryCategory, MemoryDomain]:
    lowered = text.lower()
    if any(token in lowered for token in ["gọi tôi", "tên tôi", "my name"]):
        return MemoryCategory.PROFILE_FACT, MemoryDomain.GENERAL
    if any(
        token in lowered
        for token in ["sân bay nhà", "điểm xuất phát", "home airport", "homeairport"]
    ):
        return MemoryCategory.FLIGHT_PREFERENCE, MemoryDomain.FLIGHT
    if any(token in lowered for token in ["flight", "bay", "chuyến bay", "sân bay"]):
        return MemoryCategory.FLIGHT_PREFERENCE, MemoryDomain.FLIGHT
    if any(token in lowered for token in ["hotel", "khách sạn", "resort", "homestay"]):
        return MemoryCategory.HOTEL_PREFERENCE, MemoryDomain.HOTEL
    if any(token in lowered for token in ["xe", "car", "thuê xe", "tài xế"]):
        return MemoryCategory.CAR_PREFERENCE, MemoryDomain.CAR
    if any(token in lowered for token in ["tour", "excursion", "tham quan", "hoạt động"]):
        return MemoryCategory.EXCURSION_PREFERENCE, MemoryDomain.EXCURSION
    if any(token in lowered for token in ["trả lời", "answer", "luôn", "đừng"]):
        return MemoryCategory.INTERACTION_RULE, MemoryDomain.GENERAL
    return MemoryCategory.GENERAL_PREFERENCE, MemoryDomain.GENERAL


def _extract_condition(text: str) -> str | None:
    lowered = text.lower()
    for marker in ["khi đi công tác", "khi đi gia đình", "business", "family trip"]:
        if marker in lowered:
            return marker
    return None


def _normalize_statement(text: str) -> str:
    import re
    text = text.lower()
    text = re.sub(r'[,.;!?]', ' ', text)
    text = re.sub(r'\b(và|and)\b', ' ', text)
    return " ".join(text.split())


def _is_ambiguous(lowered: str) -> bool:
    return any(token in lowered for token in ["có thể", "maybe", "perhaps", "không chắc"])


def _looks_conflicting(left: str, right: str) -> bool:
    positive = ["thích", "prefer", "ưu tiên", "muốn"]
    negative = ["không thích", "don't like", "do not like", "tránh", "avoid"]

    def _has_negative(text: str) -> bool:
        return any(token in text for token in negative)

    def _has_positive(text: str) -> bool:
        # Avoid counting "thích" inside "không thích".
        stripped = text
        for token in negative:
            stripped = stripped.replace(token, " ")
        return any(token in stripped for token in positive)

    def _is_conflict_simple(l: str, r: str) -> bool:
        l_pos = _has_positive(l)
        l_neg = _has_negative(l)
        r_pos = _has_positive(r)
        r_neg = _has_negative(r)
        
        # Nếu cả hai đều có cả pos và neg (câu phức), không thể kết luận đơn giản
        if (l_pos and l_neg) or (r_pos and r_neg):
            return False
            
        return (l_pos and r_neg) or (l_neg and r_pos)

    import re
    delimiters = r'[,.;]|\bnhưng\b|\btuy nhiên\b'
    left_clauses = [c.strip() for c in re.split(delimiters, left) if c.strip()]
    right_clauses = [c.strip() for c in re.split(delimiters, right) if c.strip()]
    if not left_clauses: left_clauses = [left]
    if not right_clauses: right_clauses = [right]

    for lc in left_clauses:
        for rc in right_clauses:
            if _is_conflict_simple(lc, rc):
                overlap = _topic_tokens(lc) & _topic_tokens(rc)
                meaningful_overlap = {tok for tok in overlap if tok not in {"khách", "sạn", "chuyến", "bay", "xe"}}
                if bool(meaningful_overlap) or len(overlap) >= 3:
                    return True

    return False


def _polarity_corpus(memory: TravelMemory) -> str:
    """Combine memory_text + evidence so cleaning cannot erase conflict signals."""
    return _normalize_statement(f"{memory.memory_text} {memory.evidence_text}")


def _topic_tokens(text: str) -> set[str]:
    stop = {
        "tôi",
        "thích",
        "không",
        "ưu",
        "tiên",
        "prefer",
        "like",
        "don't",
        "do",
        "not",
        "ở",
        "và",
        "có",
        "của",
        "là",
        "the",
        "a",
        "an",
    }
    return {tok for tok in text.split() if len(tok) >= 3 and tok not in stop}


def _memories_conflict(left: TravelMemory, right: TravelMemory) -> bool:
    left_text = _polarity_corpus(left)
    right_text = _polarity_corpus(right)
    return _looks_conflicting(left_text, right_text)


_DURABLE_MARKERS = [
    "hãy nhớ",
    "nhớ là",
    "tôi thích",
    "tôi không thích",
    "tôi thường",
    "tôi ưu tiên",
    "ưu tiên của tôi",
    "gọi tôi",
    "tên tôi",
    "i prefer",
    "i usually",
    "remember that",
    "please remember",
]

_SENSITIVE_TOKENS = [
    "số hộ chiếu",
    "passport number",
    "credit card",
    "thẻ tín dụng",
    "cvv",
    "mật khẩu",
    "password",
]

_TOOL_ONLY_MARKERS = [
    "search_id",
    "displayed_item_ids",
    "total_results",
    "item_id",
]
