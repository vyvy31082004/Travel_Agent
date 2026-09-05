from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from e2e_eval.json_util import dumps_json, to_json_safe

from e2e_eval.schema import E2ECase, HumanReviewScores, ScoreStatus, load_case


def _bullet(items: list[str]) -> str:
    if not items:
        return "- (none)"
    return "\n".join(f"- {item}" for item in items)


def _format_sub_agents(sub_agents: list[dict[str, Any]]) -> str:
    if not sub_agents:
        return "(no sub-agent branches captured)"
    sections: list[str] = []
    for branch in sub_agents:
        domain = branch.get("domain") or "unknown"
        constraints = branch.get("applied_constraints") or []
        warnings = branch.get("warnings") or []
        sections.append(
            f"### {domain}\n"
            f"- **summary:** {branch.get('summary') or '(empty)'}\n"
            f"- **domain_action:** {branch.get('domain_action') or '(none)'}\n"
            f"- **applied_constraints:**\n{_bullet([str(item) for item in constraints])}\n"
            f"- **warnings:**\n{_bullet([str(item) for item in warnings])}"
        )
    return "\n\n".join(sections)


def _format_domain_recall(domain_recall: dict[str, Any]) -> str:
    if not domain_recall:
        return "(none)"
    sections: list[str] = []
    for domain, payload in domain_recall.items():
        applicability = payload.get("applicability") or {}
        reasons = payload.get("applicability_reasons") or {}
        final_ids = set(payload.get("final_context_ids") or [])
        table_rows = ["| fixture_id | label | reason | in_context |", "|---|---|---|---|"]
        for fixture_id, label in applicability.items():
            reason = reasons.get(fixture_id, "")
            in_context = "yes" if fixture_id in final_ids else "no"
            table_rows.append(
                f"| {fixture_id} | {label} | {reason or '(none)'} | {in_context} |"
            )
        constraints = payload.get("applied_constraints") or []
        sections.append(
            f"### {domain}\n"
            + "\n".join(table_rows)
            + f"\n\n**Derived constraints:**\n{_bullet([str(item) for item in constraints])}"
        )
    return "\n\n".join(sections)


def _format_conversation(case: E2ECase, trace: dict[str, Any]) -> str:
    turns = trace.get("turns") or []
    final_answer = trace.get("final_answer") or "(empty)"
    if not turns:
        return (
            "## Query\n"
            f"{_bullet(case.input.messages)}\n\n"
            "## Final answer\n"
            f"{final_answer}"
        )

    sections = ["## Conversation (one chat turn at a time)"]
    for item in turns:
        tags: list[str] = []
        if item.get("summarize_forced"):
            tags.append("force summarize")
        if item.get("scored"):
            tags.append("scored")
        suffix = f" ({', '.join(tags)})" if tags else ""
        answer = item.get("answer") or "(empty)"
        sections.append(
            f"### Turn {item.get('turn')}{suffix}\n"
            f"**User:** {item.get('user_message') or ''}\n\n"
            f"**Assistant:** {answer}"
        )
    sections.append(f"## Final answer\n{final_answer}")
    return "\n\n".join(sections)


def _format_execution_path(execution_path: list[dict[str, Any]]) -> str:
    if not execution_path:
        return "(no execution path captured)"
    lines = ["| seq | node | graph | domain | tools |", "|---|---|---|---|---|"]
    for step in execution_path:
        tool_names = []
        for tool in step.get("tools") or []:
            name = tool.get("name") or ""
            sub_steps = tool.get("sub_steps") or []
            if sub_steps:
                tool_names.append(f"{name} ({', '.join(sub_steps)})")
            elif name:
                tool_names.append(name)
        lines.append(
            "| {seq} | {node} | {graph} | {domain} | {tools} |".format(
                seq=step.get("seq", ""),
                node=step.get("node", ""),
                graph=step.get("graph", ""),
                domain=step.get("domain") or "",
                tools=", ".join(tool_names) if tool_names else "",
            )
        )
    return "\n".join(lines)


def build_review_markdown(case: E2ECase, trace: dict[str, Any]) -> str:
    rubric = case.expected_answer_rubric
    tools = trace.get("tools") or []
    tool_sections: list[str] = []
    for tool in tools:
        name = tool.get("name") or "unknown_tool"
        normalized = tool.get("normalized_result") or tool.get("raw_result") or {}
        tool_sections.append(
            f"### {name}\n```json\n{json.dumps(normalized, ensure_ascii=False, indent=2)}\n```"
        )

    auto_scores = trace.get("auto_scores") or {}
    auto_lines = []
    for key, value in auto_scores.items():
        if isinstance(value, dict):
            auto_lines.append(f"- **{key}**: {value.get('status')} — {value.get('detail', '')}")

    join = trace.get("join") or {}
    metadata = trace.get("metadata") or {}
    stm = trace.get("stm") or {}
    stm_summary = stm.get("summary") or "(none)"

    return f"""# E2E Review — {case.id}

## Scenario
{case.scenario}

{_format_conversation(case, trace)}

## Conversation summary (STM)
{stm_summary}

- **message_count:** {stm.get("message_count", 0)}
- **summarized_after_turn:** {stm.get("summarized_after_turn") or "(none)"}

## Auto scores (informational)
{_bullet(auto_lines) if auto_lines else "- (none)"}

## Evidence bundle

### Postgres run metadata
```json
{json.dumps({
    "postgres_persist": metadata.get("postgres_persist"),
    "teardown": metadata.get("teardown"),
    "fresh_seed": metadata.get("fresh_seed"),
    "user_id": metadata.get("user_id"),
    "thread_id": metadata.get("thread_id"),
}, ensure_ascii=False, indent=2)}
```

### Active memories (fixture ids)
```json
{json.dumps(metadata.get("fixture_to_uuid", {}), ensure_ascii=False, indent=2)}
```

### Global recall
```json
{json.dumps(trace.get("global_recall", {}), ensure_ascii=False, indent=2)}
```

### Domain recall
{_format_domain_recall(trace.get("domain_recall") or {})}

### Execution path
{_format_execution_path(trace.get("execution_path") or [])}

### Join
```json
{json.dumps(join, ensure_ascii=False, indent=2)}
```

### Sub-agents
{_format_sub_agents(trace.get("sub_agents") or [])}

### Tool snapshots
{chr(10).join(tool_sections) if tool_sections else "(no tools captured)"}

### Finalize
```json
{json.dumps({
    "expected_action": (trace.get("finalize") or {}).get("expected_action"),
    "memory_job": (trace.get("finalize") or {}).get("memory_job"),
    "db_mutations": (trace.get("finalize") or {}).get("db_mutations") or [],
    "audits": (trace.get("finalize") or {}).get("audits") or [],
    "seeded_status": (trace.get("finalize") or {}).get("seeded_status") or {},
}, ensure_ascii=False, indent=2)}
```

## Rubric checklist (human — official)
- [ ] Task Success
- [ ] Answer Faithfulness
- [ ] Answer Relevance
- [ ] Memory-Grounded Answer Accuracy
- [ ] Unanswerable ({rubric.answerability.value})
- [ ] Preference Compliance
- [ ] Hallucinated Memory (none expected)

### Required constraints
{_bullet(rubric.required_constraints)}

### Trade-off rules
{_bullet(rubric.tradeoff_rule)}

### Forbidden claims
{_bullet(rubric.forbidden_claims)}

## Notes
___
"""


def export_review(trace_path: str | Path, *, case_path: str | Path | None = None) -> Path:
    trace_file = Path(trace_path)
    trace = json.loads(trace_file.read_text(encoding="utf-8"))
    case_id = trace.get("metadata", {}).get("case_id")
    if case_path is None:
        from e2e_eval.schema import DEFAULT_FIXTURE_DIR

        case_path = DEFAULT_FIXTURE_DIR / f"{case_id}.yaml"
    case = load_case(case_path)
    review_path = trace_file.with_suffix(".review.md")
    review_path.write_text(build_review_markdown(case, trace), encoding="utf-8")
    return review_path


def import_human_scores(trace_path: str | Path, scores: dict[str, Any]) -> dict[str, Any]:
    trace_file = Path(trace_path)
    trace = json.loads(trace_file.read_text(encoding="utf-8"))
    parsed = HumanReviewScores.model_validate(scores)
    trace["human_review"] = {
        "status": "completed",
        "scores": parsed.model_dump(mode="json"),
    }
    trace_file.write_text(dumps_json(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    return trace


def draft_llm_judge_placeholder(trace: dict[str, Any]) -> dict[str, Any]:
    """Optional draft scores — not official PASS/FAIL."""
    return {
        "task_success": ScoreStatus.PENDING.value,
        "answer_faithfulness": ScoreStatus.PENDING.value,
        "note": "LLM-as-judge draft not run; fill human review instead.",
        "final_answer_preview": (trace.get("final_answer") or "")[:500],
    }
