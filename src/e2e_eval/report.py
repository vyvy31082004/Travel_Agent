from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_traces(runs_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(runs_dir)
    traces: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/*.json")):
        if path.name.endswith(".review.md"):
            continue
        traces.append(json.loads(path.read_text(encoding="utf-8")))
    return traces


def _rate(items: list[dict[str, Any]], key: str) -> float | None:
    values = []
    for trace in items:
        scores = (trace.get("human_review") or {}).get("scores") or {}
        status = scores.get(key)
        if status == "PASS":
            values.append(1.0)
        elif status == "FAIL":
            values.append(0.0)
    if not values:
        return None
    return sum(values) / len(values)


def _auto_rate(items: list[dict[str, Any]], key: str) -> float | None:
    values = []
    for trace in items:
        auto = (trace.get("auto_scores") or {}).get(key) or {}
        status = auto.get("status")
        if status == "PASS":
            values.append(1.0)
        elif status == "FAIL":
            values.append(0.0)
    if not values:
        return None
    return sum(values) / len(values)


def build_summary(traces: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [
        trace
        for trace in traces
        if ((trace.get("metadata") or {}).get("case_id"))
    ]
    return {
        "run_count": len(traces),
        "metrics": {
            "task_success_rate": _rate(answerable, "task_success"),
            "answer_faithfulness_rate": _rate(answerable, "answer_faithfulness"),
            "answer_relevance_rate": _rate(answerable, "answer_relevance"),
            "memory_grounded_accuracy_rate": _rate(answerable, "memory_grounded_accuracy"),
            "unanswerable_f1": _rate(answerable, "unanswerable"),
            "trace_integrity_rate": _auto_rate(answerable, "trace_integrity"),
        },
        "cases": [
            {
                "case_id": (trace.get("metadata") or {}).get("case_id"),
                "run_id": (trace.get("metadata") or {}).get("run_id"),
                "trace_integrity": ((trace.get("auto_scores") or {}).get("trace_integrity") or {}).get(
                    "status"
                ),
                "human_review_status": (trace.get("human_review") or {}).get("status"),
            }
            for trace in traces
        ],
    }


def write_summary_report(
    runs_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    traces = _load_traces(runs_dir)
    summary = build_summary(traces)
    out = Path(output_dir or Path(runs_dir).parent)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "e2e_summary.json"
    md_path = out / "e2e_summary.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# E2E Summary Report",
        "",
        f"- Runs: {summary['run_count']}",
        "",
        "## Metrics",
    ]
    for key, value in summary["metrics"].items():
        if value is None:
            lines.append(f"- {key}: (no human/auto labels yet)")
        else:
            lines.append(f"- {key}: {value:.1%}")
    lines.extend(["", "## Cases", ""])
    for case in summary["cases"]:
        lines.append(
            f"- {case['case_id']} / {case['run_id']}: "
            f"trace_integrity={case['trace_integrity']}, "
            f"human_review={case['human_review_status']}"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
