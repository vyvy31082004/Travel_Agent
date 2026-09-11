"""Schema for short-term memory live evaluation fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

MetricName = Literal["reference", "factual_recall", "success"]
SplitName = Literal["development", "test"]


class ReferenceSpec(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    gold: dict[str, Any] = Field(default_factory=dict)
    # When set, inject into graph state after dialogue turns (deterministic ref gold).
    seed_visible_state: dict[str, Any] | None = None


class StmLiveCase(BaseModel):
    id: str
    split: SplitName
    scenario: str
    metrics: list[MetricName]
    user_id: str = "user_a"
    messages: list[str]
    force_summarize_penultimate: bool = False
    probe: str | None = None
    gold_answer: str | None = None
    position: str | None = None
    phase: str | None = None
    reference: ReferenceSpec | None = None
    constraints: dict[str, Any] | None = None
    # Domain used to pick the latest search tool / Result Store query for success.
    success_domain: str | None = None
    long_term_memories: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("messages")
    @classmethod
    def _non_empty_messages(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if str(item).strip()]
        if not cleaned:
            raise ValueError("messages must contain at least one message")
        return cleaned

    @field_validator("metrics")
    @classmethod
    def _non_empty_metrics(cls, value: list[MetricName]) -> list[MetricName]:
        if not value:
            raise ValueError("metrics must be non-empty")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _validate_metric_fields(self) -> StmLiveCase:
        names = set(self.metrics)
        if "reference" in names and self.reference is None:
            raise ValueError(f"{self.id}: reference metric requires reference")
        if "factual_recall" in names:
            if not self.probe or not self.gold_answer:
                raise ValueError(
                    f"{self.id}: factual_recall requires probe and gold_answer"
                )
        if "success" in names and not self.constraints:
            raise ValueError(f"{self.id}: success metric requires constraints")
        return self


DEFAULT_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "short_term_memory_live"
)

DEV_COUNT = 20
TEST_COUNT = 30
TOTAL_COUNT = DEV_COUNT + TEST_COUNT


def load_case(path: str | Path) -> StmLiveCase:
    raw_path = Path(path)
    text = raw_path.read_text(encoding="utf-8")
    if raw_path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    return StmLiveCase.model_validate(payload)


def load_cases_from_dir(
    directory: str | Path | None = None,
    *,
    split: str = "all",
) -> list[StmLiveCase]:
    root = Path(directory or DEFAULT_FIXTURE_DIR)
    manifest = root / "manifest.json"
    if not manifest.exists():
        raise FileNotFoundError(f"missing STM live manifest: {manifest}")
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    cases = [load_case(root / item["file"]) for item in entries.get("cases", [])]
    if split != "all":
        cases = [case for case in cases if case.split == split]
        if not cases:
            raise ValueError(f"no STM live cases found for split={split!r}")
    return cases


def validate_manifest_counts(directory: str | Path | None = None) -> dict[str, int]:
    root = Path(directory or DEFAULT_FIXTURE_DIR)
    cases = load_cases_from_dir(root, split="all")
    counts = {
        "total": len(cases),
        "development": sum(1 for c in cases if c.split == "development"),
        "test": sum(1 for c in cases if c.split == "test"),
    }
    if counts["development"] != DEV_COUNT:
        raise ValueError(
            f"expected {DEV_COUNT} development cases, got {counts['development']}"
        )
    if counts["test"] != TEST_COUNT:
        raise ValueError(f"expected {TEST_COUNT} test cases, got {counts['test']}")
    return counts
