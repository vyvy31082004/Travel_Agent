"""LLM judges for semantic memory equivalence and evidence entailment."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol, Sequence

from pydantic import BaseModel, Field


_EQUIVALENCE_PROMPT = """\
Bạn là bộ so khớp semantic cho long-term memory du lịch.

Hãy xác định hai memory có tương đương về nghĩa hay không.

Trả true chỉ khi cả hai cùng:
- đối tượng/thuộc tính;
- chiều preference: thích, tránh, bắt buộc, từ chối...;
- giá trị;
- điều kiện áp dụng (nếu có).

Được bỏ qua: khác động từ tương đương (ví dụ "thích" và
"thường chọn"), đảo trật tự từ, thêm/bớt chủ ngữ như "tôi".

Trả false nếu một bên thêm, mất hoặc đổi một preference/điều kiện
quan trọng.

Chỉ trả JSON:
{{"equivalent": true | false}}

Memory A: {memory_a}
Memory B: {memory_b}
"""

_SUPPORTS_PROMPT = """\
Bạn là bộ kiểm tra evidence cho long-term memory du lịch.

Hãy xác định evidence_text có hỗ trợ / entail memory_text hay không.

Trả true chỉ khi evidence đủ để suy ra đúng nội dung memory
(đối tượng, chiều preference, giá trị, điều kiện nếu memory có).

Trả false nếu evidence thiếu, mâu thuẫn, hoặc không liên quan tới memory.

Chỉ trả JSON:
{{"supports": true | false}}

evidence_text: {evidence}
memory_text: {memory}
"""


class EquivalenceJudgment(BaseModel):
    equivalent: bool = Field(description="True when memories are semantically equivalent.")


class SupportJudgment(BaseModel):
    supports: bool = Field(description="True when evidence entails/supports the memory.")


class SemanticJudge(Protocol):
    async def are_equivalent(self, memory_a: str, memory_b: str) -> bool: ...

    async def evidence_supports(self, evidence_text: str, memory_text: str) -> bool: ...


def normalize_match_text(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[\s:,.!?;\-]+$", "", value)
    return value


def texts_exactly_equivalent(left: str, right: str) -> bool:
    return normalize_match_text(left) == normalize_match_text(right)


class ExactThenLlmSemanticJudge:
    """Fast-path exact normalize match; otherwise call Gemini structured JSON."""

    def __init__(self, *, model: str = "gemini-2.5-flash", llm: Any | None = None) -> None:
        self._model = model
        self._llm = llm
        self._equivalence_llm: Any | None = None
        self._support_llm: Any | None = None

    def _base_llm(self) -> Any:
        if self._llm is not None:
            return self._llm
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=self._model, temperature=0)

    def _equivalence_chain(self) -> Any:
        if self._equivalence_llm is None:
            self._equivalence_llm = self._base_llm().with_structured_output(
                EquivalenceJudgment
            )
        return self._equivalence_llm

    def _support_chain(self) -> Any:
        if self._support_llm is None:
            self._support_llm = self._base_llm().with_structured_output(SupportJudgment)
        return self._support_llm

    async def are_equivalent(self, memory_a: str, memory_b: str) -> bool:
        if texts_exactly_equivalent(memory_a, memory_b):
            return True
        try:
            from langchain_core.messages import HumanMessage

            prompt = _EQUIVALENCE_PROMPT.format(memory_a=memory_a, memory_b=memory_b)
            scored = await self._equivalence_chain().ainvoke(
                [HumanMessage(content=prompt)]
            )
            if isinstance(scored, dict):
                scored = EquivalenceJudgment.model_validate(scored)
            if isinstance(scored, EquivalenceJudgment):
                return bool(scored.equivalent)
        except Exception as exc:
            # Fail closed for matching, but keep a breadcrumb for debugging.
            import logging

            logging.getLogger(__name__).warning(
                "semantic equivalence judge failed: %s", exc
            )
            return False
        return False

    async def evidence_supports(self, evidence_text: str, memory_text: str) -> bool:
        if not evidence_text.strip() or not memory_text.strip():
            return False
        try:
            from langchain_core.messages import HumanMessage

            prompt = _SUPPORTS_PROMPT.format(
                evidence=evidence_text, memory=memory_text
            )
            scored = await self._support_chain().ainvoke([HumanMessage(content=prompt)])
            if isinstance(scored, dict):
                scored = SupportJudgment.model_validate(scored)
            if isinstance(scored, SupportJudgment):
                return bool(scored.supports)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "evidence support judge failed: %s", exc
            )
            return False
        return False


class CallableSemanticJudge:
    """Test double: inject sync/async callables for equivalence and support."""

    def __init__(
        self,
        *,
        equivalent_fn: Any | None = None,
        supports_fn: Any | None = None,
    ) -> None:
        self._equivalent_fn = equivalent_fn or (
            lambda a, b: texts_exactly_equivalent(a, b)
        )
        self._supports_fn = supports_fn or (lambda evidence, memory: True)

    async def are_equivalent(self, memory_a: str, memory_b: str) -> bool:
        result = self._equivalent_fn(memory_a, memory_b)
        if hasattr(result, "__await__"):
            result = await result
        return bool(result)

    async def evidence_supports(self, evidence_text: str, memory_text: str) -> bool:
        result = self._supports_fn(evidence_text, memory_text)
        if hasattr(result, "__await__"):
            result = await result
        return bool(result)


def maximum_bipartite_matching(
    equivalence: Sequence[Sequence[bool]],
) -> list[tuple[int, int]]:
    """Maximum 1-1 matching with deterministic tie-break.

    Rows = extracted indices, cols = gold indices.
    When multiple maximum matchings exist, prefer the lexicographically smallest
    matching encoded as the tuple of gold partners for each extracted index
    (unmatched = -1), by DFS in increasing extracted then gold index order.
    """
    n_pred = len(equivalence)
    n_gold = len(equivalence[0]) if n_pred else 0
    if n_pred == 0 or n_gold == 0:
        return []

    best_pairs: list[tuple[int, int]] = []
    best_signature: tuple[int, ...] | None = None

    def signature(assignment: dict[int, int]) -> tuple[int, ...]:
        return tuple(assignment.get(i, -1) for i in range(n_pred))

    def consider(assignment: dict[int, int]) -> None:
        nonlocal best_pairs, best_signature
        pairs = sorted((pi, gi) for pi, gi in assignment.items())
        sig = signature(assignment)
        if len(pairs) > len(best_pairs) or (
            len(pairs) == len(best_pairs)
            and (best_signature is None or sig < best_signature)
        ):
            best_pairs = pairs
            best_signature = sig

    def dfs(pred_index: int, used_gold: set[int], assignment: dict[int, int]) -> None:
        if pred_index == n_pred:
            consider(assignment)
            return
        # Option: leave this extracted unmatched (still explore for max size later).
        dfs(pred_index + 1, used_gold, assignment)
        for gold_index in range(n_gold):
            if gold_index in used_gold:
                continue
            if not equivalence[pred_index][gold_index]:
                continue
            used_gold.add(gold_index)
            assignment[pred_index] = gold_index
            dfs(pred_index + 1, used_gold, assignment)
            del assignment[pred_index]
            used_gold.remove(gold_index)

    dfs(0, set(), {})
    return best_pairs


async def build_equivalence_matrix(
    pred_texts: Sequence[str],
    gold_texts: Sequence[str],
    judge: SemanticJudge,
    *,
    gold_aliases: Sequence[Sequence[str]] | None = None,
) -> list[list[bool]]:
    matrix: list[list[bool]] = []
    aliases = gold_aliases or [() for _ in gold_texts]
    for pred in pred_texts:
        row: list[bool] = []
        for gold_index, gold in enumerate(gold_texts):
            accepted = (gold, *aliases[gold_index])
            if any(texts_exactly_equivalent(pred, text) for text in accepted):
                row.append(True)
                continue
            equivalent = False
            for text in accepted:
                if await judge.are_equivalent(pred, text):
                    equivalent = True
                    break
            row.append(equivalent)
        matrix.append(row)
    return matrix


def parse_json_bool_field(raw: Any, field: str) -> bool | None:
    if isinstance(raw, dict) and field in raw:
        return bool(raw[field])
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict) and field in payload:
            return bool(payload[field])
    return None
