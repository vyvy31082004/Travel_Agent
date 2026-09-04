from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

from memory_eval.retrieval_postgres import (
    EVAL_BRANCH,
    load_distance_scores_jsonl,
    seeded_memory_uuid,
)
from memory_eval.common import memory_from_dict
from memory_eval.suites import tokenize
from memory.long_term import format_memory_for_prompt
from settings import Settings

SWEEP_K_VALUES = tuple(range(1, 11))
RECALL_TOLERANCE = 0.01
SELECTION_RULE = (
    "relative: zero leakage, recall within 1pp of max, min spurious, "
    "tie-break context_precision desc, memory_per_query asc, k asc"
)


@dataclass(frozen=True)
class DistributionStats:
    count: int
    minimum: float | None
    p25: float | None
    median: float | None
    p75: float | None
    p90: float | None
    maximum: float | None
    mean: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "min": self.minimum,
            "p25": self.p25,
            "median": self.median,
            "p75": self.p75,
            "p90": self.p90,
            "max": self.maximum,
            "mean": self.mean,
        }


@dataclass(frozen=True)
class SweepMetrics:
    tau: float
    k: int
    recall_at_k: float | None
    spurious_recall_rate: float | None
    context_precision: float | None
    memory_per_query: float | None
    tokens_per_query: float | None
    total_context_tokens: int
    cross_user_leakage_rate: float | None
    inactive_leakage_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tau": self.tau,
            "k": self.k,
            "recall_at_k": self.recall_at_k,
            "spurious_recall_rate": self.spurious_recall_rate,
            "context_precision": self.context_precision,
            "memory_per_query": self.memory_per_query,
            "tokens_per_query": self.tokens_per_query,
            "total_context_tokens": self.total_context_tokens,
            "cross_user_leakage_rate": self.cross_user_leakage_rate,
            "inactive_leakage_rate": self.inactive_leakage_rate,
        }


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def distribution_stats(values: Sequence[float]) -> DistributionStats:
    if not values:
        return DistributionStats(0, None, None, None, None, None, None, None)
    return DistributionStats(
        count=len(values),
        minimum=min(values),
        p25=_percentile(values, 0.25),
        median=statistics.median(values),
        p75=_percentile(values, 0.75),
        p90=_percentile(values, 0.90),
        maximum=max(values),
        mean=statistics.mean(values),
    )


def estimate_context_tokens(text: str) -> int:
    """Word-token proxy aligned with memory_eval.suite tokenization."""
    return len(tokenize(text))


def _fixture_prompt_text(
    case: dict[str, Any], *, fixture_memory_id: str
) -> str:
    case_id = str(case["case_id"])
    for raw in case.get("memories") or []:
        if str(raw.get("memory_id")) != fixture_memory_id:
            continue
        memory = memory_from_dict(raw)
        seeded_id = str(seeded_memory_uuid(case_id, fixture_memory_id))
        return format_memory_for_prompt(replace(memory, memory_id=seeded_id))
    return ""


def build_context_prompt_lookup(
    records: Sequence[dict[str, Any]],
    *,
    fixture_cases: Sequence[dict[str, Any]] | None = None,
) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for record in records:
        if str(record.get("record_type") or "") != "score":
            continue
        case_id = str(record["case_id"])
        fixture_id = str(record["fixture_memory_id"])
        text = str(record.get("context_prompt_text") or "").strip()
        if text:
            lookup[(case_id, fixture_id)] = text

    if not fixture_cases:
        return lookup

    cases_by_id = {str(case["case_id"]): case for case in fixture_cases}
    for record in records:
        if str(record.get("record_type") or "") != "score":
            continue
        case_id = str(record["case_id"])
        fixture_id = str(record["fixture_memory_id"])
        key = (case_id, fixture_id)
        if key in lookup:
            continue
        case = cases_by_id.get(case_id)
        if case is None:
            continue
        text = _fixture_prompt_text(case, fixture_memory_id=fixture_id)
        if text:
            lookup[key] = text
    return lookup


def parse_locked_pair(value: str) -> tuple[float, int]:
    parts = value.split(",")
    if len(parts) != 2:
        raise ValueError("locked pair must be formatted as tau,k")
    return float(parts[0].strip()), int(parts[1].strip())


def _index_records(
    records: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    metadata: dict[str, Any] | None = None
    summaries: dict[str, dict[str, Any]] = {}
    scores_by_case: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        record_type = str(record.get("record_type") or "")
        if record_type == "run_metadata":
            metadata = record
        elif record_type == "case_summary":
            summaries[str(record["case_id"])] = record
        elif record_type == "score":
            case_id = str(record["case_id"])
            scores_by_case.setdefault(case_id, []).append(record)
    return metadata, summaries, scores_by_case


def distance_distribution(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    relevant: list[float] = []
    irrelevant: list[float] = []
    for record in records:
        if str(record.get("record_type") or "") != "score":
            continue
        distance = float(record["cosine_distance"])
        if record.get("gold_relevant"):
            relevant.append(distance)
        else:
            irrelevant.append(distance)
    rel = distribution_stats(relevant)
    irrel = distribution_stats(irrelevant)
    warnings: list[str] = []
    if rel.median is not None and irrel.median is not None and rel.median >= irrel.median:
        warnings.append("median relevant distance is not lower than irrelevant median")
    return {
        "relevant": rel.to_dict(),
        "irrelevant": irrel.to_dict(),
        "warnings": warnings,
    }


def candidate_thresholds(
    distribution: dict[str, Any], *, default_tau: float
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    rel = distribution["relevant"]
    irrel = distribution["irrelevant"]
    for source, key in (("p75_relevant", "p75"), ("p90_relevant", "p90")):
        value = rel.get(key)
        if value is not None:
            candidates.append({"tau": round(float(value), 6), "source": source})
    p75_rel = rel.get("p75")
    p25_irrel = irrel.get("p25")
    if p75_rel is not None and p25_irrel is not None:
        candidates.append(
            {
                "tau": round((float(p75_rel) + float(p25_irrel)) / 2, 6),
                "source": "midpoint_boundary",
            }
        )
    candidates.append({"tau": round(default_tau, 6), "source": "current_default"})
    deduped: dict[float, dict[str, Any]] = {}
    for item in candidates:
        deduped[float(item["tau"])] = item
    return [deduped[key] for key in sorted(deduped)]


def _returned_for_case(
    summary: dict[str, Any],
    scores: list[dict[str, Any]],
    *,
    tau: float,
    k: int,
) -> list[str]:
    filtered = [
        row
        for row in scores
        if float(row["cosine_distance"]) <= tau
    ]
    filtered.sort(key=lambda row: int(row["rank"]))
    return [str(row["fixture_memory_id"]) for row in filtered[:k]]


def _context_tokens_for_returned(
    case_id: str,
    returned: Sequence[str],
    prompt_lookup: dict[tuple[str, str], str],
) -> int:
    lines = [
        prompt_lookup[(case_id, memory_id)]
        for memory_id in returned
        if (case_id, memory_id) in prompt_lookup
    ]
    if not lines:
        return 0
    return estimate_context_tokens("\n".join(lines))


def _compute_sweep_metrics(
    summaries: dict[str, dict[str, Any]],
    scores_by_case: dict[str, list[dict[str, Any]]],
    *,
    tau: float,
    k: int,
    prompt_lookup: dict[tuple[str, str], str],
) -> SweepMetrics:
    recall_num = 0
    recall_den = 0
    zero_gold_cases = 0
    spurious_cases = 0
    relevant_returned = 0
    total_returned = 0
    cross_user_returned = 0
    inactive_returned = 0
    total_context_tokens = 0

    for case_id, summary in summaries.items():
        gold_ids = set(summary.get("gold_relevant_memory_ids") or [])
        gold_count = int(summary.get("gold_relevant_count") or 0)
        forbidden_ids = set(summary.get("forbidden_memory_ids") or [])
        forbidden_reasons = dict(summary.get("forbidden_reasons") or {})
        returned = _returned_for_case(
            summary, scores_by_case.get(case_id, []), tau=tau, k=k
        )

        recall_den += gold_count
        recall_num += sum(1 for memory_id in returned if memory_id in gold_ids)

        if gold_count == 0 or summary.get("expect_empty_recall"):
            zero_gold_cases += 1
            if returned:
                spurious_cases += 1

        total_returned += len(returned)
        relevant_returned += sum(1 for memory_id in returned if memory_id in gold_ids)
        total_context_tokens += _context_tokens_for_returned(
            case_id, returned, prompt_lookup
        )

        for memory_id in returned:
            if memory_id not in forbidden_ids:
                continue
            reason = forbidden_reasons.get(memory_id)
            if reason == "cross_user":
                cross_user_returned += 1
            else:
                inactive_returned += 1

    recall_at_k = None if recall_den == 0 else recall_num / recall_den
    spurious = None if zero_gold_cases == 0 else spurious_cases / zero_gold_cases
    context_precision = None if total_returned == 0 else relevant_returned / total_returned
    memory_per_query = total_returned / len(summaries) if summaries else None
    tokens_per_query = (
        total_context_tokens / len(summaries) if summaries else None
    )
    cross_user = None if total_returned == 0 else cross_user_returned / total_returned
    inactive = None if total_returned == 0 else inactive_returned / total_returned

    return SweepMetrics(
        tau=tau,
        k=k,
        recall_at_k=recall_at_k,
        spurious_recall_rate=spurious,
        context_precision=context_precision,
        memory_per_query=memory_per_query,
        tokens_per_query=tokens_per_query,
        total_context_tokens=total_context_tokens,
        cross_user_leakage_rate=cross_user,
        inactive_leakage_rate=inactive,
    )


def sweep_threshold_grid(
    records: Sequence[dict[str, Any]],
    *,
    tau_values: Sequence[float],
    k_values: Sequence[int] = SWEEP_K_VALUES,
    fixture_cases: Sequence[dict[str, Any]] | None = None,
) -> list[SweepMetrics]:
    _, summaries, scores_by_case = _index_records(records)
    prompt_lookup = build_context_prompt_lookup(records, fixture_cases=fixture_cases)
    metrics: list[SweepMetrics] = []
    for tau in tau_values:
        for k in k_values:
            metrics.append(
                _compute_sweep_metrics(
                    summaries,
                    scores_by_case,
                    tau=float(tau),
                    k=int(k),
                    prompt_lookup=prompt_lookup,
                )
            )
    return metrics


def select_pair_relative(metrics: Sequence[SweepMetrics]) -> dict[str, Any]:
    eligible = [
        metric
        for metric in metrics
        if (metric.cross_user_leakage_rate or 0.0) == 0.0
        and (metric.inactive_leakage_rate or 0.0) == 0.0
    ]
    if not eligible:
        raise ValueError("no (tau, k) pair with zero leakage")

    recall_max = max(
        metric.recall_at_k for metric in eligible if metric.recall_at_k is not None
    )
    near_best = [
        metric
        for metric in eligible
        if metric.recall_at_k is not None
        and metric.recall_at_k >= recall_max - RECALL_TOLERANCE
    ]

    def sort_key(metric: SweepMetrics) -> tuple[float, float, float, int]:
        spurious = metric.spurious_recall_rate if metric.spurious_recall_rate is not None else 1.0
        precision = (
            metric.context_precision if metric.context_precision is not None else -1.0
        )
        memory = metric.memory_per_query if metric.memory_per_query is not None else 999.0
        return (spurious, -precision, memory, metric.k)

    selected = min(near_best, key=sort_key)
    return {
        "selected_pair": {"tau": selected.tau, "k": selected.k},
        "selection_rule": SELECTION_RULE,
        "recall_max": recall_max,
        "eval_branch": EVAL_BRANCH,
    }


def analyze_distance_scores(
    records: Sequence[dict[str, Any]],
    *,
    settings: Settings,
    locked_pair: tuple[float, int] | None = None,
    fixture_cases: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata, summaries, scores_by_case = _index_records(records)
    prompt_lookup = build_context_prompt_lookup(records, fixture_cases=fixture_cases)
    distribution = distance_distribution(records)
    candidates = candidate_thresholds(
        distribution, default_tau=settings.long_term_memory_vector_distance_threshold
    )
    tau_values = [float(item["tau"]) for item in candidates]
    sweep = sweep_threshold_grid(
        records, tau_values=tau_values, fixture_cases=fixture_cases
    )

    result: dict[str, Any] = {
        "eval_branch": EVAL_BRANCH,
        "metadata": metadata,
        "case_count": len(summaries),
        "distance_distribution": distribution,
        "candidate_thresholds": candidates,
        "threshold_sweep": [metric.to_dict() for metric in sweep],
        "token_metric_note": (
            "tokens_per_query and total_context_tokens use word-token proxy "
            "over production format_memory_for_prompt lines joined by newline."
        ),
        "limitations": [
            "Sweep operates on Top-N candidate pool only; rank > N memories are never returnable.",
            "Eval branch is pgvector semantic search only; production fallback paths are out of scope.",
        ],
    }

    if locked_pair is not None:
        tau, k = locked_pair
        locked_metrics = _compute_sweep_metrics(
            summaries,
            scores_by_case,
            tau=tau,
            k=k,
            prompt_lookup=prompt_lookup,
        )
        result["locked_pair_validation"] = locked_metrics.to_dict()
    else:
        result.update(select_pair_relative(sweep))

    return result


def render_analysis_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Retrieval threshold analysis",
        "",
        f"Eval branch: `{report.get('eval_branch')}`",
        "",
        "## Distance distribution",
        "",
        "| Group | n | P25 | Median | P75 | P90 |",
        "|-------|---|-----|--------|-----|-----|",
    ]
    for label in ("relevant", "irrelevant"):
        stats = report["distance_distribution"][label]
        lines.append(
            f"| {label.title()} | {stats['count']} | {stats.get('p25')} | "
            f"{stats.get('median')} | {stats.get('p75')} | {stats.get('p90')} |"
        )
    lines.extend(["", "## Threshold sweep", ""])
    lines.append(
        "| tau | K | Recall@K | Spurious | Context Precision | Memory/query | "
        "Tokens/query | Total tokens | Cross-user | Inactive |"
    )
    lines.append(
        "|-----|---|----------|----------|-------------------|--------------|"
        "--------------|--------------|------------|----------|"
    )
    for row in report.get("threshold_sweep") or []:
        lines.append(
            f"| {row['tau']} | {row['k']} | {row['recall_at_k']} | "
            f"{row['spurious_recall_rate']} | {row['context_precision']} | "
            f"{row['memory_per_query']} | {row['tokens_per_query']} | "
            f"{row['total_context_tokens']} | {row['cross_user_leakage_rate']} | "
            f"{row['inactive_leakage_rate']} |"
        )
    if "selected_pair" in report:
        pair = report["selected_pair"]
        lines.extend(
            [
                "",
                "## Selected pair",
                "",
                f"- tau: `{pair['tau']}`",
                f"- K: `{pair['k']}`",
                f"- Rule: {report.get('selection_rule')}",
            ]
        )
    if "locked_pair_validation" in report:
        locked = report["locked_pair_validation"]
        lines.extend(
            [
                "",
                "## Locked pair validation",
                "",
                f"- tau: `{locked['tau']}`, K: `{locked['k']}`",
                f"- Recall@K: {locked['recall_at_k']}",
                f"- Context Precision: {locked['context_precision']}",
                f"- Tokens/query: {locked['tokens_per_query']}",
                f"- Total tokens: {locked['total_context_tokens']}",
            ]
        )
    warnings = report.get("distance_distribution", {}).get("warnings") or []
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines) + "\n"


def write_analysis_outputs(
    report: dict[str, Any], *, json_path: str | Path, markdown_path: str | Path | None = None
) -> None:
    json_output = Path(json_path)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if markdown_path is not None:
        md_output = Path(markdown_path)
        md_output.write_text(render_analysis_markdown(report), encoding="utf-8")


def analyze_distance_scores_file(
    path: str | Path,
    *,
    settings: Settings,
    locked_pair: tuple[float, int] | None = None,
    fixture_cases: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return analyze_distance_scores(
        load_distance_scores_jsonl(path),
        settings=settings,
        locked_pair=locked_pair,
        fixture_cases=fixture_cases,
    )
