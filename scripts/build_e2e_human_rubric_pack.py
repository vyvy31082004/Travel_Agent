from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(r"e:\Travel Agent\customer-support-agent")
RUNS_DIR = ROOT / "src" / "reports" / "e2e_runs"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "e2e_eval"
OUT_MD = ROOT / "reports" / "e2e_human_rubric.md"
OUT_CSV = ROOT / "reports" / "e2e_human_rubric_scoresheet.csv"

METRIC_KEYS = [
    ("task_success", "Task Success"),
    ("answer_faithfulness", "Answer Faithfulness"),
    ("answer_relevance", "Answer Relevance"),
    ("memory_grounded_accuracy", "Memory-Grounded Answer Accuracy"),
    ("unanswerable", "Unanswerable"),
    ("preference_compliance", "Preference Compliance"),
    ("hallucinated_memory", "Hallucinated Memory"),
]


def bullet(items):
    if not items:
        return "- (none)"
    return "\n".join(f"- {item}" for item in items)


def load_fixture(case_id: str) -> dict:
    path = FIXTURE_DIR / f"{case_id}.yaml"
    if not path.exists() or yaml is None:
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def format_seed_memories(fixture: dict) -> str:
    seeds = ((fixture.get("seed") or {}).get("long_term_memories")) or []
    if not seeds:
        return "(no seeded LTM)"
    lines = ["| fixture_id | domain | status | text |", "|---|---|---|---|"]
    for m in seeds:
        text = (m.get("text") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {m.get('id','')} | {m.get('domain','')} | {m.get('status','')} | {text} |"
        )
    return "\n".join(lines)


def format_conversation(trace: dict, fixture: dict) -> str:
    turns = trace.get("turns") or []
    final_answer = trace.get("final_answer") or "(empty)"
    if not turns:
        msgs = ((fixture.get("input") or {}).get("messages")) or []
        parts = ["## Conversation", "", "### User query", ""]
        parts.extend(f"- {m}" for m in msgs)
        parts.extend(["", "## Final answer", "", final_answer])
        return "\n".join(parts)

    parts = ["## Conversation", ""]
    for item in turns:
        tags = []
        if item.get("summarize_forced"):
            tags.append("force summarize")
        if item.get("scored"):
            tags.append("scored")
        suffix = f" ({', '.join(tags)})" if tags else ""
        answer = item.get("answer") or "(empty)"
        parts.append(f"### Turn {item.get('turn')}{suffix}")
        parts.append("")
        parts.append(f"**User:** {item.get('user_message') or ''}")
        parts.append("")
        parts.append(f"**Assistant:** {answer}")
        parts.append("")
    parts.extend(["## Final answer", "", final_answer])
    return "\n".join(parts)


def format_domain_recall_brief(domain_recall: dict) -> str:
    if not domain_recall:
        return "(none)"
    sections = []
    for domain, payload in domain_recall.items():
        applicability = payload.get("applicability") or {}
        final_ids = set(payload.get("final_context_ids") or [])
        constraints = payload.get("applied_constraints") or []
        rows = ["| fixture_id | label | in_context |", "|---|---|---|"]
        for fid, label in applicability.items():
            rows.append(f"| {fid} | {label} | {'yes' if fid in final_ids else 'no'} |")
        sections.append(
            f"### {domain}\n"
            + "\n".join(rows)
            + "\n\n**Applied constraints:**\n"
            + bullet([str(c) for c in constraints])
        )
    return "\n\n".join(sections)


def scoring_table(answerability: str) -> str:
    lines = [
        "| Metric | PASS / FAIL / SKIP | Notes |",
        "|---|---|---|",
    ]
    for key, label in METRIC_KEYS:
        extra = f" (expected: {answerability})" if key == "unanswerable" else ""
        lines.append(f"| {label}{extra} |  |  |")
    return "\n".join(lines)


def latest_traces() -> list[tuple[Path, dict]]:
    items = []
    for case_dir in sorted(RUNS_DIR.iterdir()):
        if not case_dir.is_dir():
            continue
        runs = sorted(case_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not runs:
            continue
        trace = json.loads(runs[0].read_text(encoding="utf-8"))
        items.append((runs[0], trace))
    return items


def main() -> None:
    traces = latest_traces()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    toc = []
    sections = []
    csv_rows = ["case_id,run_id,scenario,trace_integrity,task_success,answer_faithfulness,answer_relevance,memory_grounded_accuracy,unanswerable,preference_compliance,hallucinated_memory,notes"]

    for idx, (trace_path, trace) in enumerate(traces, start=1):
        meta = trace.get("metadata") or {}
        case_id = meta.get("case_id") or trace_path.parent.name
        run_id = meta.get("run_id") or trace_path.stem
        fixture = load_fixture(case_id)
        scenario = fixture.get("scenario") or "(no scenario)"
        rubric = fixture.get("expected_answer_rubric") or {}
        answerability = rubric.get("answerability", "ANSWERABLE")
        auto = trace.get("auto_scores") or {}
        integrity = (auto.get("trace_integrity") or {}).get("status", "?")
        stm = (trace.get("stm") or {}).get("summary") or "(none)"

        auto_lines = []
        for key, value in auto.items():
            if isinstance(value, dict):
                auto_lines.append(f"- **{key}**: {value.get('status')} — {value.get('detail', '')}")

        anchor = case_id.replace("_", "-")
        toc.append(f"{idx}. [{case_id}](#{anchor}) — integrity={integrity}")

        section = f"""# {idx}. {case_id}

- **Run ID:** `{run_id}`
- **Trace file:** `{trace_path.relative_to(ROOT).as_posix()}`
- **Scenario:** {scenario}
- **Answerability (expected):** `{answerability}`
- **Trace integrity (auto):** `{integrity}`

## Seeded long-term memories
{format_seed_memories(fixture)}

## Conversation summary (STM)
{stm}

{format_conversation(trace, fixture)}

## Domain recall (brief)
{format_domain_recall_brief(trace.get("domain_recall") or {})}

## Auto scores (informational only — not official)
{bullet(auto_lines) if auto_lines else "- (none)"}

## Rubric criteria (from fixture)
### Required constraints
{bullet(rubric.get("required_constraints") or [])}

### Trade-off rules
{bullet(rubric.get("tradeoff_rule") or [])}

### Forbidden claims
{bullet(rubric.get("forbidden_claims") or [])}

## Human scoring sheet
{scoring_table(answerability)}

**Overall notes:**
___

---
"""
        sections.append(section)
        csv_rows.append(
            ",".join(
                [
                    case_id,
                    run_id,
                    '"' + scenario.replace('"', "''") + '"',
                    integrity,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
        )

    header = f"""# E2E Human Rubric Pack

Báo cáo tổng hợp câu trả lời E2E để chấm **human rubric** (official PASS/FAIL).

- **Generated:** {now}
- **Source runs:** `src/reports/e2e_runs` (latest run per case)
- **Cases:** {len(traces)}
- **Scoresheet CSV:** `reports/e2e_human_rubric_scoresheet.csv`

## Hướng dẫn chấm

Với mỗi case, đọc **Conversation / Final answer**, đối chiếu **Seeded memories**, **Domain recall**, và **Rubric criteria**, rồi điền bảng scoring:

| Metric | Ý nghĩa ngắn |
|---|---|
| Task Success | Agent hoàn thành đúng nhiệm vụ user yêu cầu |
| Answer Faithfulness | Nội dung bám tool/evidence, không bịa giá/đặc điểm |
| Answer Relevance | Trả lời đúng trọng tâm câu hỏi |
| Memory-Grounded Answer Accuracy | Áp dụng đúng memory active phù hợp |
| Unanswerable | Xử lý đúng trường hợp không trả lời được (theo expected answerability) |
| Preference Compliance | Tuân thủ preference / constraint trong rubric |
| Hallucinated Memory | Không viện dẫn memory không tồn tại / inactive |

Điền `PASS` / `FAIL` / `SKIP`. Có thể ghi điểm vào CSV kèm theo để tổng hợp.

## Mục lục

""" + "\n".join(toc) + "\n\n---\n\n"

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(header + "\n".join(sections), encoding="utf-8")
    OUT_CSV.write_text("\n".join(csv_rows) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_CSV}")
    print(f"Cases: {len(traces)}")


if __name__ == "__main__":
    main()
