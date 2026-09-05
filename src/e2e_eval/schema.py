from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class Answerability(StrEnum):
    ANSWERABLE = "ANSWERABLE"
    UNANSWERABLE = "UNANSWERABLE"


class FinalizeAction(StrEnum):
    NO_STORE = "NO_STORE"
    STORE = "STORE"
    NOOP = "NOOP"
    INSERT = "INSERT"
    SUPERSEDE = "SUPERSEDE"


WRITE_FINALIZE_ACTIONS = {
    FinalizeAction.NOOP,
    FinalizeAction.INSERT,
    FinalizeAction.SUPERSEDE,
}


class SeedMemory(BaseModel):
    id: str
    text: str
    domain: str | None = None
    category: str | None = None
    family: str | None = None
    status: str = "active"
    user_id: str | None = None
    expect_in_context: bool | None = None
    evidence_text: str | None = None

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()


class ThreadStateSeed(BaseModel):
    messages: list[str] = Field(default_factory=list)
    summary: str | None = None


class CaseSeed(BaseModel):
    user_id: str
    long_term_memories: list[SeedMemory]
    thread_state: ThreadStateSeed = Field(default_factory=ThreadStateSeed)


class CaseInput(BaseModel):
    messages: list[str]
    force_summarize_penultimate: bool = True

    @field_validator("messages")
    @classmethod
    def _non_empty_messages(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("input.messages must contain at least one message")
        return cleaned


class ExpectedContextRule(BaseModel):
    must_include: list[str] = Field(default_factory=list)
    must_exclude: list[str] = Field(default_factory=list)
    expected_applicability: dict[str, str] = Field(default_factory=dict)


class ExpectedToolRule(BaseModel):
    name: str
    required_arguments: list[str] = Field(default_factory=list)
    forbidden_arguments: list[str] = Field(default_factory=list)
    forbidden_value_substrings: list[str] = Field(default_factory=list)


class ExpectedTrace(BaseModel):
    expected_route: list[str]
    expected_context: dict[str, ExpectedContextRule] = Field(default_factory=dict)
    expected_tools: list[ExpectedToolRule] = Field(default_factory=list)
    expected_node_sequence_contains: list[str] = Field(default_factory=list)


class ExpectedAnswerRubric(BaseModel):
    answerability: Answerability = Answerability.ANSWERABLE
    required_constraints: list[str] = Field(default_factory=list)
    tradeoff_rule: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)


class ExpectedFinalizeMemory(BaseModel):
    domain: str | None = None
    category: str | None = None
    family: str | None = None
    text_contains: list[str] = Field(default_factory=list)
    supersedes_fixture_id: str | None = None
    existing_fixture_id: str | None = None
    reasons_any: list[str] = Field(default_factory=list)


class ExpectedFinalize(BaseModel):
    action: FinalizeAction = FinalizeAction.NO_STORE
    memories: list[ExpectedFinalizeMemory] = Field(default_factory=list)


class E2ECase(BaseModel):
    id: str
    scenario: str
    seed: CaseSeed
    input: CaseInput
    expected_trace: ExpectedTrace
    expected_answer_rubric: ExpectedAnswerRubric
    expected_finalize: ExpectedFinalize = Field(default_factory=ExpectedFinalize)


class ScoreStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    PENDING = "PENDING"


class MetricScore(BaseModel):
    status: ScoreStatus
    detail: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class AutoScores(BaseModel):
    routing_accuracy: MetricScore | None = None
    tool_call_correctness: MetricScore | None = None
    context_recall_precision: MetricScore | None = None
    applicability_correctness: MetricScore | None = None
    cross_user_inactive_leakage: MetricScore | None = None
    finalize_correctness: MetricScore | None = None
    execution_path: MetricScore | None = None
    join_integrity: MetricScore | None = None
    trace_integrity: MetricScore | None = None


class HumanReviewScores(BaseModel):
    task_success: ScoreStatus | None = None
    answer_faithfulness: ScoreStatus | None = None
    answer_relevance: ScoreStatus | None = None
    memory_grounded_accuracy: ScoreStatus | None = None
    preference_compliance: ScoreStatus | None = None
    hallucinated_memory: ScoreStatus | None = None
    unanswerable: ScoreStatus | None = None
    notes: str = ""


class HumanReview(BaseModel):
    status: str = "pending"
    scores: HumanReviewScores | None = None
    draft_scores: dict[str, Any] | None = None


DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "e2e_eval"


def load_case(path: str | Path) -> E2ECase:
    raw_path = Path(path)
    text = raw_path.read_text(encoding="utf-8")
    if raw_path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    return E2ECase.model_validate(payload)


def load_cases_from_dir(directory: str | Path | None = None) -> list[E2ECase]:
    root = Path(directory or DEFAULT_FIXTURE_DIR)
    manifest = root / "manifest.json"
    if manifest.exists():
        entries = json.loads(manifest.read_text(encoding="utf-8"))
        case_files = [root / item["file"] for item in entries.get("cases", [])]
    else:
        case_files = sorted(root.glob("e2e_*.yaml"))
    return [load_case(path) for path in case_files]
