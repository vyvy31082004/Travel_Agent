"""Run extraction_cases.jsonl against memory candidate extractors.

Usage:
  python -m memory_eval.run_extraction --split dev --extractor langmem
  python -m memory_eval.run_extraction --split held_out --held-out-run --extractor langmem
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory.consolidation import (
    DeterministicCandidateExtractor,
    LangMemCandidateExtractor,
    build_candidate_extractor,
    validate_memory_candidate,
)
from memory.long_term import TravelMemory
from memory_eval.schema import validate_extraction_cases
from settings import get_settings


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "long_term_memory_eval"
    / "extraction_cases.jsonl"
)
DEFAULT_MANIFEST = DEFAULT_FIXTURE.parent / "split_manifest.json"


@dataclass
class MatchResult:
    matched_gold_indexes: set[int] = field(default_factory=set)
    matched_pred_indexes: set[int] = field(default_factory=set)
    faithful_preds: int = 0
    total_preds: int = 0


@dataclass
class EvalMetrics:
    split: str | None
    extractor: str
    cases_run: int
    true_positive_preds: int = 0
    total_preds: int = 0
    matched_golds: int = 0
    total_golds: int = 0
    faithful: int = 0
    unsafe_total: int = 0
    unsafe_rejected: int = 0
    sensitive_stored: int = 0
    failures: list[str] = field(default_factory=list)
    case_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.true_positive_preds / self.total_preds if self.total_preds else 1.0

    @property
    def recall(self) -> float:
        return self.matched_golds / self.total_golds if self.total_golds else 1.0

    @property
    def faithfulness(self) -> float:
        return self.faithful / self.total_preds if self.total_preds else 1.0

    @property
    def unsafe_rejection_rate(self) -> float:
        return self.unsafe_rejected / self.unsafe_total if self.unsafe_total else 1.0

    def gates(self) -> dict[str, bool]:
        return {
            "Precision>=0.85": self.precision >= 0.85,
            "Recall>=0.70": self.recall >= 0.70,
            "Faithfulness>=0.95": self.faithfulness >= 0.95,
            "UnsafeReject>=0.98": self.unsafe_rejection_rate >= 0.98,
            "SensitiveStored=0": self.sensitive_stored == 0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "extractor": self.extractor,
            "cases_run": self.cases_run,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "faithfulness": round(self.faithfulness, 4),
            "unsafe_rejection_rate": round(self.unsafe_rejection_rate, 4),
            "sensitive_stored": self.sensitive_stored,
            "counts": {
                "true_positive_preds": self.true_positive_preds,
                "total_preds": self.total_preds,
                "matched_golds": self.matched_golds,
                "total_golds": self.total_golds,
                "faithful": self.faithful,
                "unsafe_total": self.unsafe_total,
                "unsafe_rejected": self.unsafe_rejected,
            },
            "gates": self.gates(),
            "failures": self.failures,
            "case_results": self.case_results,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("#"):
            continue
        try:
            cases.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return cases


def filter_by_split(
    cases: list[dict[str, Any]],
    split: str | None,
    manifest_path: Path,
) -> list[dict[str, Any]]:
    if not split:
        return cases
    if split not in {"dev", "held_out"}:
        raise SystemExit(f"Invalid split {split!r}")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mapping = manifest.get("cases") or {}
        return [c for c in cases if mapping.get(c.get("case_id")) == split or c.get("split") == split]
    return [c for c in cases if c.get("split") == split]


def _normalize_match_text(text: str) -> str:
    return " ".join(text.lower().replace(".", " ").replace(",", " ").split())


def _contains_all(text: str, tokens: list[str]) -> bool:
    lowered = _normalize_match_text(text)
    return all(_normalize_match_text(token) in lowered for token in tokens)


def _contains_any(text: str, tokens: list[str]) -> bool:
    lowered = _normalize_match_text(text)
    return any(_normalize_match_text(token) in lowered for token in tokens)


def _pred_matches_gold(pred: TravelMemory, gold: dict[str, Any]) -> bool:
    must = list(gold.get("memory_text_contains") or [])
    if must and not _contains_all(pred.memory_text, must):
        return False
    any_tokens = list(gold.get("memory_text_contains_any") or [])
    if any_tokens and not _contains_any(pred.memory_text, any_tokens):
        return False
    if gold.get("category") and str(pred.category) != gold["category"]:
        return False
    if gold.get("domain") and str(pred.domain) != gold["domain"]:
        return False
    condition_tokens = list(gold.get("condition_contains") or [])
    if condition_tokens:
        condition = (pred.condition or "") + " " + pred.memory_text
        if not _contains_all(condition, condition_tokens):
            return False
    return True


def _is_faithful(pred: TravelMemory, case: dict[str, Any]) -> bool:
    if not validate_memory_candidate(pred).ok:
        return False
    forbidden = [t.lower() for t in case.get("forbidden_tokens") or []]
    memory_l = pred.memory_text.lower()
    if any(tok in memory_l for tok in forbidden):
        return False
    human_blobs = [
        str(m.get("content") or "").lower()
        for m in case.get("messages") or []
        if str(m.get("type") or "").lower() in {"human", "user"}
    ]
    if not human_blobs:
        return False
    evidence_l = pred.evidence_text.lower()
    if evidence_l and not any(
        evidence_l in blob or blob in evidence_l or evidence_l[:40] in blob
        for blob in human_blobs
    ):
        return False
    return True


def score_case(case: dict[str, Any], preds: list[TravelMemory]) -> MatchResult:
    golds: list[dict[str, Any]] = list(case.get("gold_memories") or [])
    result = MatchResult(total_preds=len(preds))
    used_preds: set[int] = set()

    for gi, gold in enumerate(golds):
        for pi, pred in enumerate(preds):
            if pi in used_preds:
                continue
            if _pred_matches_gold(pred, gold):
                result.matched_gold_indexes.add(gi)
                result.matched_pred_indexes.add(pi)
                used_preds.add(pi)
                break

    for pred in preds:
        if _is_faithful(pred, case):
            result.faithful_preds += 1
    return result


def _resolve_extractor(name: str):
    settings = get_settings()
    chosen = (name or settings.long_term_memory_extractor or "langmem").strip().lower()
    if chosen == "deterministic":
        return chosen, DeterministicCandidateExtractor()
    if chosen == "langmem":
        return chosen, LangMemCandidateExtractor(model=settings.long_term_memory_langmem_model)
    if chosen == "compare":
        from dataclasses import replace

        return chosen, build_candidate_extractor(
            replace(settings, long_term_memory_extractor="compare")
        )
    raise SystemExit(
        f"Unknown extractor {chosen!r}; use deterministic, langmem, or compare"
    )


async def extract_for_case(extractor, case: dict[str, Any]) -> list[TravelMemory]:
    raw = await extractor.extract(
        case.get("messages") or [],
        user_id="eval-user",
        thread_id=f"eval-{case.get('case_id', 'case')}",
        limit=5,
    )
    return [c for c in raw if validate_memory_candidate(c).ok]


def run_eval(
    fixture: Path,
    *,
    case_id: str | None = None,
    split: str | None = None,
    manifest_path: Path = DEFAULT_MANIFEST,
    extractor_name: str | None = None,
    held_out_run: bool = False,
    verbose: bool = True,
) -> tuple[EvalMetrics, int]:
    if split == "held_out" and not held_out_run and not case_id:
        raise SystemExit(
            "Held-out evaluation requires --held-out-run (one-shot report; do not tune on these cases)."
        )

    cases = load_cases(fixture)
    cases = filter_by_split(cases, split, manifest_path)
    if case_id:
        cases = [c for c in cases if c.get("case_id") == case_id]
        if not cases:
            raise SystemExit(f"No case with case_id={case_id!r}")

    schema_errors = validate_extraction_cases(load_cases(fixture)) if not case_id and split is None else []
    if schema_errors and verbose:
        print("Schema warnings (full file):", file=sys.stderr)
        for err in schema_errors[:5]:
            print(f"  - {err}", file=sys.stderr)

    resolved_name, extractor = _resolve_extractor(extractor_name or "")
    metrics = EvalMetrics(split=split, extractor=resolved_name, cases_run=len(cases))

    if verbose:
        print(f"Fixture: {fixture}")
        print(f"Extractor: {resolved_name}")
        label = f"split={split}" if split else "split=all"
        print(f"Cases: {len(cases)} ({label})" + (f" filter={case_id}" if case_id else ""))
        print("-" * 60)

    import asyncio

    for case in cases:
        cid = case.get("case_id", "?")
        case_failures: list[str] = []
        preds: list[TravelMemory] = []
        try:
            preds = asyncio.run(extract_for_case(extractor, case))
        except Exception as exc:  # noqa: BLE001
            msg = f"{cid}: extract error — {type(exc).__name__}: {exc}"
            metrics.failures.append(msg)
            case_failures.append(msg)
            if verbose:
                print(f"[FAIL] {cid}: extract error — {exc}")
            metrics.case_results.append(
                {"case_id": cid, "status": "FAIL", "pred_count": 0, "pred_texts": [], "failures": case_failures}
            )
            continue

        match = score_case(case, preds)
        golds = list(case.get("gold_memories") or [])
        metrics.total_golds += len(golds)
        metrics.matched_golds += len(match.matched_gold_indexes)
        metrics.total_preds += match.total_preds
        metrics.true_positive_preds += len(match.matched_pred_indexes)
        metrics.faithful += match.faithful_preds

        if case.get("unsafe"):
            metrics.unsafe_total += 1
            if len(preds) == 0:
                metrics.unsafe_rejected += 1
            else:
                metrics.sensitive_stored += len(preds)
                msg = f"{cid}: unsafe leak — kept {[p.memory_text for p in preds]!r}"
                metrics.failures.append(msg)
                case_failures.append(msg)

        expect = bool(case.get("expect_extract", bool(golds)))
        if expect and golds and len(match.matched_gold_indexes) < len(golds):
            missing = [
                g.get("memory_text_contains")
                for i, g in enumerate(golds)
                if i not in match.matched_gold_indexes
            ]
            msg = (
                f"{cid}: recall miss — missing gold {missing!r}; "
                f"got {[p.memory_text for p in preds]!r}"
            )
            metrics.failures.append(msg)
            case_failures.append(msg)
        if not expect and preds:
            msg = f"{cid}: unexpected extract — {[p.memory_text for p in preds]!r}"
            metrics.failures.append(msg)
            case_failures.append(msg)
        if case.get("forbidden_tokens"):
            for pred in preds:
                bad = [
                    t
                    for t in case["forbidden_tokens"]
                    if t.lower() in pred.memory_text.lower()
                ]
                if bad:
                    msg = f"{cid}: faithfulness fail — forbidden {bad!r} in {pred.memory_text!r}"
                    metrics.failures.append(msg)
                    case_failures.append(msg)

        status = "OK" if not case_failures else "FAIL"
        pred_texts = [p.memory_text for p in preds]
        metrics.case_results.append(
            {
                "case_id": cid,
                "status": status,
                "pred_count": len(preds),
                "pred_texts": pred_texts,
                "requirement_id": case.get("requirement_id"),
                "risk_type": case.get("risk_type"),
                "failures": case_failures,
            }
        )
        if verbose:
            pred_preview = "; ".join(pred_texts) or "(none)"
            print(f"[{status}] {cid}: n={len(preds)} -> {pred_preview}")
            if case_id:
                for p in preds:
                    print(
                        f"    category={p.category} domain={p.domain} "
                        f"evidence={p.evidence_text!r}"
                    )

    if verbose:
        print("-" * 60)
        print(
            f"Extraction Precision:     {metrics.precision:.3f}  "
            f"({metrics.true_positive_preds}/{metrics.total_preds})"
        )
        print(
            f"Extraction Recall:        {metrics.recall:.3f}  "
            f"({metrics.matched_golds}/{metrics.total_golds})"
        )
        print(
            f"Evidence Faithfulness:    {metrics.faithfulness:.3f}  "
            f"({metrics.faithful}/{metrics.total_preds})"
        )
        print(
            f"Unsafe Rejection Rate:    {metrics.unsafe_rejection_rate:.3f}  "
            f"({metrics.unsafe_rejected}/{metrics.unsafe_total})"
        )
        print(f"Sensitive stored (hard):  {metrics.sensitive_stored}")
        print(f"Case failures:            {len(metrics.failures)}")
        if metrics.failures:
            print("\nFailures:")
            for line in metrics.failures[:50]:
                print(f"  - {line}")
            if len(metrics.failures) > 50:
                print(f"  ... and {len(metrics.failures) - 50} more")

        if not case_id:
            print("\nGates:")
            for name, ok in metrics.gates().items():
                print(f"  {'PASS' if ok else 'FAIL'}: {name}")

    exit_code = 0
    if case_id:
        exit_code = 0 if not metrics.failures else 1
    else:
        exit_code = 0 if all(metrics.gates().values()) else 1
    return metrics, exit_code


def _write_markdown_report(path: Path, metrics: EvalMetrics) -> None:
    lines = [
        f"# Extraction eval — split={metrics.split or 'all'}",
        "",
        f"- Extractor: `{metrics.extractor}`",
        f"- Cases: {metrics.cases_run}",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Metrics",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Precision | {metrics.precision:.3f} |",
        f"| Recall | {metrics.recall:.3f} |",
        f"| Faithfulness | {metrics.faithfulness:.3f} |",
        f"| Unsafe Rejection | {metrics.unsafe_rejection_rate:.3f} |",
        f"| Sensitive stored | {metrics.sensitive_stored} |",
        "",
        "## Gates",
        "",
    ]
    for name, ok in metrics.gates().items():
        lines.append(f"- {'PASS' if ok else 'FAIL'}: {name}")
    if metrics.failures:
        lines.extend(["", "## Failures (sample)", ""])
        for f in metrics.failures[:30]:
            lines.append(f"- {f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Eval memory extraction fixtures")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--split", choices=["dev", "held_out"], default=None)
    parser.add_argument(
        "--extractor",
        default=None,
        choices=["deterministic", "langmem", "compare"],
    )
    parser.add_argument(
        "--held-out-run",
        action="store_true",
        help="Required for held-out split (one-shot evaluation)",
    )
    parser.add_argument("--out", type=Path, default=None, help="UTF-8 text report")
    parser.add_argument("--json-out", type=Path, default=None, help="JSON metrics report")
    parser.add_argument("--md-out", type=Path, default=None, help="Markdown summary report")
    args = parser.parse_args(argv)

    if not args.fixture.exists():
        print(f"Fixture not found: {args.fixture}", file=sys.stderr)
        return 2

    run_kwargs = {
        "case_id": args.case_id,
        "split": args.split,
        "manifest_path": args.manifest,
        "extractor_name": args.extractor,
        "held_out_run": args.held_out_run,
        "verbose": args.out is None,
    }

    if args.out is not None:
        from contextlib import redirect_stdout
        from io import StringIO

        buffer = StringIO()
        with redirect_stdout(buffer):
            metrics, code = run_eval(args.fixture, **run_kwargs)
        text = buffer.getvalue()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        try:
            sys.stdout.write(text)
        except UnicodeEncodeError:
            sys.stdout.write(text.encode("ascii", errors="replace").decode("ascii"))
        print(f"Wrote: {args.out.resolve()}", file=sys.stderr)
    else:
        metrics, code = run_eval(args.fixture, **run_kwargs)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote JSON: {args.json_out.resolve()}", file=sys.stderr)

    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        _write_markdown_report(args.md_out, metrics)
        print(f"Wrote Markdown: {args.md_out.resolve()}", file=sys.stderr)

    return code


if __name__ == "__main__":
    raise SystemExit(main())
