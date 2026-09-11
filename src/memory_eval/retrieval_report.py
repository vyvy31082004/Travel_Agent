from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"

QUALITY_METRIC_LABELS: dict[str, str] = {
    "candidate_pool_completeness": "SQL candidate pool completeness",
    "context_recall": "Apply recall",
    "allowed_context_precision": "Allowed context precision",
    "uncertain_recall": "Uncertain recall",
    "irrelevant_leakage_rate": "Irrelevant leakage",
    "overridden_leakage_rate": "Overridden leakage",
    "context_case_pass_rate": "Context case pass rate",
    "applicability_macro_f1": "Applicability macro-F1",
}

ISOLATION_METRIC_LABELS: dict[str, str] = {
    "cross_user_candidate_leakage": "Cross-user candidate leakage",
    "cross_domain_candidate_leakage": "Cross-domain candidate leakage",
    "inactive_candidate_leakage": "Inactive candidate leakage",
    "cross_user_context_leakage": "Cross-user context leakage",
    "cross_domain_context_leakage": "Cross-domain context leakage",
    "inactive_context_leakage": "Inactive context leakage",
}

DIAGNOSTIC_METRIC_LABELS: dict[str, str] = {
    "context_precision": "Apply-only share in final context (diagnostic)",
    "uncertain_context_rate": "Uncertain share in final context (diagnostic)",
}

METRIC_LABELS: dict[str, str] = {
    **QUALITY_METRIC_LABELS,
    **ISOLATION_METRIC_LABELS,
    **DIAGNOSTIC_METRIC_LABELS,
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
    def append_metric_section(title: str, labels: dict[str, str]) -> None:
        lines.extend(["", f"## {title}", "", "| Metric | Value |", "|--------|-------|"])
        for key, label in labels.items():
            metric = metrics.get(key) or {}
            value = metric.get("value")
            display = "n/a" if value is None else f"{value:.4f}"
            lines.append(f"| {label} | {display} |")

    append_metric_section("Quality metrics", QUALITY_METRIC_LABELS)
    append_metric_section("Isolation metrics", ISOLATION_METRIC_LABELS)
    append_metric_section("Context composition diagnostics", DIAGNOSTIC_METRIC_LABELS)
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
