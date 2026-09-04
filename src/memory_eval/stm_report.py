from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"

METRIC_LABELS: dict[str, str] = {
    "joint_goal_accuracy": "Joint Goal Accuracy (JGA)",
    "slot_f1": "Slot F1",
    "resolution_accuracy": "Resolution Accuracy",
    "factual_recall_accuracy": "Factual Recall Accuracy",
    "success_rate": "Task Success Rate",
}


def default_stm_report_paths(*, split: str, suite: str) -> tuple[Path, Path]:
    stem = f"short_term_memory_{suite}_{split}".replace("-", "_")
    return REPORTS_DIR / f"{stem}.json", REPORTS_DIR / f"{stem}.md"


def render_stm_report_markdown(payload: dict[str, Any]) -> str:
    report = payload.get("report") or {}
    metrics = report.get("metrics") or {}
    lines = [
        "# Short-term memory evaluation",
        "",
        f"- Suite: `{payload.get('suite', 'stm-all')}`",
        f"- Split: `{payload.get('split', 'all')}`",
        f"- Cases: `{payload.get('case_count', 0)}`",
        f"- Gold: `{payload.get('gold_path', '')}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value | Numerator | Denominator |",
        "|--------|-------|-----------|-------------|",
    ]
    for key, label in METRIC_LABELS.items():
        metric = metrics.get(key) or {}
        value = metric.get("value")
        display = "n/a" if value is None else f"{value:.4f}"
        lines.append(
            f"| {label} | {display} | {metric.get('numerator', '')} | "
            f"{metric.get('denominator', '')} |"
        )
    lines.append("")

    for sub_key in ("state", "reference", "factual_recall", "success"):
        sub = report.get(sub_key)
        if not isinstance(sub, dict):
            continue
        lines.extend([f"## {sub_key}", ""])
        sub_metrics = sub.get("metrics") or {}
        for name, metric in sub_metrics.items():
            value = metric.get("value")
            display = "n/a" if value is None else f"{value:.4f}"
            lines.append(
                f"- `{name}`: {display} "
                f"({metric.get('numerator')}/{metric.get('denominator')})"
            )
        extra = sub.get("extra") or {}
        if extra.get("by_position"):
            lines.append("- By position:")
            for pos, metric in extra["by_position"].items():
                value = metric.get("value")
                display = "n/a" if value is None else f"{value:.4f}"
                lines.append(f"  - `{pos}`: {display}")
        if extra.get("by_phase"):
            lines.append("- By phase:")
            for phase, metric in extra["by_phase"].items():
                value = metric.get("value")
                display = "n/a" if value is None else f"{value:.4f}"
                lines.append(f"  - `{phase}`: {display}")
        lines.append("")
    return "\n".join(lines)


def write_stm_reports(
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
        md_path.write_text(render_stm_report_markdown(payload), encoding="utf-8")
