from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"

METRIC_LABELS: dict[str, str] = {
    "candidate_pool_completeness": "SQL candidate pool completeness",
    "cross_user_candidate_leakage": "Cross-user candidate leakage",
    "cross_domain_candidate_leakage": "Cross-domain candidate leakage",
    "inactive_candidate_leakage": "Inactive candidate leakage",
    "context_recall": "Context recall (apply)",
    "context_precision": "Context precision",
    "uncertain_context_rate": "Uncertain in final context",
    "overridden_leakage_rate": "Overridden leakage",
    "applicability_macro_f1": "Applicability macro-F1",
    "cross_user_context_leakage": "Cross-user context leakage",
    "cross_domain_context_leakage": "Cross-domain context leakage",
    "inactive_context_leakage": "Inactive context leakage",
}


def default_retrieval_report_paths(
    *,
    split: str,
    applicability_judge: str,
) -> tuple[Path, Path]:
    suffix = "" if applicability_judge == "rule" else "_llm"
    stem = f"retrieval_{split}{suffix}"
    return REPORTS_DIR / f"{stem}.json", REPORTS_DIR / f"{stem}.md"


def render_retrieval_report_markdown(payload: dict[str, Any]) -> str:
    judge = payload.get("applicability_judge", "rule")
    judge_model = payload.get("applicability_judge_model")
    metrics = payload.get("report", {}).get("metrics", {})
    lines = [
        "# Retrieval evaluation",
        "",
        f"- Suite: `{payload.get('suite', 'retrieval')}`",
        f"- Split: `{payload.get('split', 'all')}`",
        f"- Cases: `{payload.get('case_count', 0)}`",
        f"- Gold: `{payload.get('gold_path', '')}`",
        f"- Applicability judge: `{judge}`",
    ]
    if judge == "llm" and judge_model:
        lines.append(f"- Judge model: `{judge_model}`")
    if judge == "rule":
        lines.extend(
            [
                "",
                "> Rule-based judge uses fixture-aligned heuristics and runs quickly in CI.",
                "> Use `--applicability-judge llm` for production-like Gemini judging.",
            ]
        )
    lines.extend(["", "## Metrics", "", "| Metric | Value |", "|--------|-------|"])
    for key, label in METRIC_LABELS.items():
        metric = metrics.get(key) or {}
        value = metric.get("value")
        if value is None:
            display = "n/a"
        else:
            display = f"{value:.4f}"
        lines.append(f"| {label} | {display} |")
    lines.append("")
    return "\n".join(lines)


def write_retrieval_reports(
    payload: dict[str, Any],
    *,
    json_path: Path,
    md_path: Path | None = None,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if md_path is not None:
        md_path.write_text(render_retrieval_report_markdown(payload), encoding="utf-8")
