from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

from memory.consolidation import (
    CompareCandidateExtractor,
    DeterministicCandidateExtractor,
    LangMemCandidateExtractor,
)
from memory_eval.candidate_extraction import (
    CandidateExtractionEvaluator,
    load_candidate_extraction_cases,
)
from memory_eval.retrieval_report import (
    default_retrieval_report_paths,
    write_retrieval_reports,
)
from memory_eval.suites import (
    DEFAULT_FIXTURE_DIR,
    evaluate_answer_file,
    evaluate_retrieval_file,
    evaluate_supersession_file,
    evaluate_transition_file,
    make_eval_settings,
)
from memory_eval.short_term import (
    evaluate_factual_recall_file,
    evaluate_reference_file,
    evaluate_state_file,
    evaluate_success_file,
)
from memory_eval.stm_report import (
    default_stm_report_paths,
    write_stm_reports,
)

STM_SUITES = frozenset(
    {"state", "reference", "factual-recall", "success", "stm-all"}
)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate long-term and short-term memory gold JSONL suites."
    )
    parser.add_argument(
        "--suite",
        choices=(
            "extraction",
            "transition",
            "retrieval",
            "answer",
            "all",
            "state",
            "reference",
            "factual-recall",
            "success",
            "stm-all",
        ),
        default="extraction",
        help="Evaluation suite to run",
    )
    parser.add_argument(
        "--gold",
        help="Path to gold JSONL, or a directory when --suite all/stm-all",
    )
    parser.add_argument(
        "--split",
        choices=("all", "development", "test"),
        default="all",
        help="Evaluate all cases or one pre-declared split",
    )
    parser.add_argument(
        "--extractor",
        choices=("deterministic", "langmem", "compare"),
        default="deterministic",
        help="Candidate extractor under evaluation",
    )
    parser.add_argument(
        "--langmem-model",
        default="gemini-2.5-flash",
        help="Model used when extractor is langmem or compare",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help=(
            "Model for semantic equivalence / evidence entailment judges. "
            "Defaults to --langmem-model. Pass empty string to disable LLM judge "
            "(exact match only)."
        ),
    )
    parser.add_argument(
        "--transition-path",
        choices=("lexical", "llm", "policy-mock"),
        default="lexical",
        help="Transition predictor: lexical rules, LLM judges, or policy-mock judges",
    )
    parser.add_argument(
        "--transition-model",
        default="gemini-2.5-flash",
        help="Model used when --transition-path llm",
    )
    parser.add_argument(
        "--applicability-judge",
        choices=("rule", "llm"),
        default="rule",
        help=(
            "Applicability judge for retrieval suite: rule (fast heuristics, CI default) "
            "or llm (Gemini judge, slower and production-like)"
        ),
    )
    parser.add_argument(
        "--applicability-judge-model",
        default="gemini-2.5-flash",
        help="Model used when --applicability-judge llm",
    )
    parser.add_argument("--output", help="Optional path for the JSON report")
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing default reports under reports/ (retrieval and STM suites)",
    )
    return parser


async def evaluate_file(
    path: str,
    split: str,
    *,
    extractor_name: str = "deterministic",
    langmem_model: str = "gemini-2.5-flash",
    judge_model: str | None = None,
) -> dict:
    cases = load_candidate_extraction_cases(path)
    if split != "all":
        cases = [case for case in cases if case.split == split]
    if not cases:
        raise ValueError(f"no cases found for split={split!r}")
    deterministic = DeterministicCandidateExtractor()
    if extractor_name == "deterministic":
        extractor = deterministic
    else:
        langmem = LangMemCandidateExtractor(model=langmem_model)
        extractor = (
            langmem
            if extractor_name == "langmem"
            else CompareCandidateExtractor(deterministic, langmem)
        )
    resolved_judge = langmem_model if judge_model is None else judge_model
    if resolved_judge == "":
        resolved_judge = None
    report = await CandidateExtractionEvaluator(
        extractor,
        judge_model=resolved_judge,
    ).evaluate(cases)
    result = {
        "suite": "candidate_extraction",
        "gold_path": str(Path(path)),
        "split": split,
        "extractor": extractor_name,
        "langmem_model": langmem_model if extractor_name != "deterministic" else None,
        "judge_model": resolved_judge,
        "case_count": len(cases),
        "report": report.to_dict(),
    }
    return result


async def evaluate_suite(args: argparse.Namespace) -> dict:
    if args.suite in STM_SUITES:
        return evaluate_stm_suite(args)
    if args.suite == "extraction":
        if not args.gold:
            raise ValueError("--gold is required for extraction")
        return await evaluate_file(
            args.gold,
            args.split,
            extractor_name=args.extractor,
            langmem_model=args.langmem_model,
            judge_model=args.judge_model,
        )
    gold = Path(args.gold) if args.gold else DEFAULT_FIXTURE_DIR
    settings = make_eval_settings(
        long_term_memory_transition_path=args.transition_path,
        long_term_memory_transition_model=args.transition_model,
    )
    if args.suite == "transition":
        path = gold if gold.is_file() else gold / "transition_cases.jsonl"
        report = await evaluate_transition_file(
            path,
            split=args.split,
            transition_path=args.transition_path,
            settings=settings,
        )
        super_report = await evaluate_supersession_file(
            path,
            settings,
            split=args.split,
            transition_path=args.transition_path,
        )
        payload = report.to_dict()
        payload["metrics"].update(
            {name: metric.to_dict() for name, metric in super_report.metrics.items()}
        )
        payload["supersession_cases"] = list(super_report.cases)
        return {
            "suite": "transition",
            "gold_path": str(path),
            "split": args.split,
            "transition_path": args.transition_path,
            "transition_model": (
                args.transition_model if args.transition_path == "llm" else None
            ),
            "case_count": len(report.cases),
            "report": payload,
        }
    if args.suite == "retrieval":
        path = gold if gold.is_file() else gold / "retrieval_cases.jsonl"
        report = await evaluate_retrieval_file(
            path,
            settings,
            split=args.split,
            applicability_judge=args.applicability_judge,
            judge_model=args.applicability_judge_model,
        )
        return {
            "suite": "retrieval",
            "gold_path": str(path),
            "split": args.split,
            "case_count": len(report.cases),
            "applicability_judge": args.applicability_judge,
            "applicability_judge_model": (
                args.applicability_judge_model
                if args.applicability_judge == "llm"
                else None
            ),
            "report": report.to_dict(),
        }
    if args.suite == "answer":
        path = gold if gold.is_file() else gold / "answer_cases.jsonl"
        report = evaluate_answer_file(path)
        return {"suite": "answer", "gold_path": str(path), "report": report.to_dict()}
    directory = gold if gold.is_dir() else gold.parent
    transition_cases = directory / "transition_cases.jsonl"
    transition = await evaluate_transition_file(
        transition_cases,
        split=args.split,
        transition_path=args.transition_path,
        settings=settings,
    )
    supersession = await evaluate_supersession_file(
        transition_cases,
        settings,
        split=args.split,
        transition_path=args.transition_path,
    )
    retrieval = await evaluate_retrieval_file(
        directory / "retrieval_cases.jsonl",
        settings,
        split=args.split,
        applicability_judge=args.applicability_judge,
        judge_model=args.applicability_judge_model,
    )
    answer = evaluate_answer_file(directory / "answer_cases.jsonl")
    combined = {
        **transition.metrics,
        **supersession.metrics,
        **retrieval.metrics,
        **answer.metrics,
    }
    return {
        "suite": "all",
        "gold_path": str(directory),
        "split": args.split,
        "transition_path": args.transition_path,
        "case_count": len(transition.cases),
        "report": {
            "metrics": {name: metric.to_dict() for name, metric in combined.items()},
            "transition": transition.to_dict(),
            "supersession": supersession.to_dict(),
            "retrieval": retrieval.to_dict(),
            "answer": answer.to_dict(),
        },
    }


def evaluate_stm_suite(args: argparse.Namespace) -> dict:
    gold = Path(args.gold) if args.gold else Path("tests/fixtures/short_term_memory_eval")
    split = getattr(args, "split", "all")
    single = {
        "state": ("state_cases.jsonl", evaluate_state_file),
        "reference": ("reference_cases.jsonl", evaluate_reference_file),
        "factual-recall": ("factual_recall_cases.jsonl", evaluate_factual_recall_file),
        "success": ("success_cases.jsonl", evaluate_success_file),
    }
    if args.suite in single:
        filename, evaluator = single[args.suite]
        path = gold if gold.is_file() else gold / filename
        report = evaluator(path, split=split)
        return {
            "suite": args.suite,
            "gold_path": str(path),
            "split": split,
            "case_count": len(report.cases),
            "report": report.to_dict(),
        }
    directory = gold if gold.is_dir() else gold.parent
    state = evaluate_state_file(directory / "state_cases.jsonl", split=split)
    reference = evaluate_reference_file(
        directory / "reference_cases.jsonl", split=split
    )
    factual = evaluate_factual_recall_file(
        directory / "factual_recall_cases.jsonl", split=split
    )
    success = evaluate_success_file(directory / "success_cases.jsonl", split=split)
    combined = {
        **state.metrics,
        **reference.metrics,
        **factual.metrics,
        **success.metrics,
    }
    case_count = (
        len(state.cases)
        + len(reference.cases)
        + len(factual.cases)
        + len(success.cases)
    )
    return {
        "suite": "stm-all",
        "gold_path": str(directory),
        "split": split,
        "case_count": case_count,
        "report": {
            "metrics": {name: metric.to_dict() for name, metric in combined.items()},
            "state": state.to_dict(),
            "reference": reference.to_dict(),
            "factual_recall": factual.to_dict(),
            "success": success.to_dict(),
        },
    }
def _run_async(coro):
    import asyncio
    import selectors
    import sys

    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    return asyncio.run(coro)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = _run_async(evaluate_suite(args))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.suite == "retrieval" and not args.no_report:
        if args.output:
            json_path = Path(args.output)
            md_path = json_path.with_suffix(".md")
        else:
            json_path, md_path = default_retrieval_report_paths(
                split=args.split,
                applicability_judge=args.applicability_judge,
            )
        write_retrieval_reports(result, json_path=json_path, md_path=md_path)
        print(f"Wrote {json_path}", flush=True)
        print(f"Wrote {md_path}", flush=True)
    elif args.suite in STM_SUITES and not args.no_report:
        if args.output:
            json_path = Path(args.output)
            md_path = json_path.with_suffix(".md")
        else:
            json_path, md_path = default_stm_report_paths(
                split=args.split,
                suite=args.suite,
            )
        write_stm_reports(result, json_path=json_path, md_path=md_path)
        print(f"Wrote {json_path}", flush=True)
        print(f"Wrote {md_path}", flush=True)
    elif args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    try:
        print(payload)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((payload + "\n").encode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
