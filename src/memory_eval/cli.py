from __future__ import annotations

import argparse
import asyncio
import json
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
from memory_eval.suites import (
    evaluate_answer_file,
    evaluate_retrieval_file,
    evaluate_supersession_file,
    evaluate_transition_file,
    make_eval_settings,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate long-term memory gold JSONL suites."
    )
    parser.add_argument(
        "--suite",
        choices=("extraction", "transition", "retrieval", "answer", "all"),
        default="extraction",
        help="Evaluation suite to run",
    )
    parser.add_argument(
        "--gold",
        help="Path to gold JSONL, or a directory when --suite all",
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
    parser.add_argument("--output", help="Optional path for the JSON report")
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
    gold = Path(args.gold) if args.gold else Path("tests/fixtures/long_term_memory_eval")
    settings = make_eval_settings()
    if args.suite == "transition":
        path = gold if gold.is_file() else gold / "transition_cases.jsonl"
        report = evaluate_transition_file(path)
        super_report = await evaluate_supersession_file(path, settings)
        payload = report.to_dict()
        payload["metrics"].update(
            {name: metric.to_dict() for name, metric in super_report.metrics.items()}
        )
        payload["supersession_cases"] = list(super_report.cases)
        return {"suite": "transition", "gold_path": str(path), "report": payload}
    if args.suite == "retrieval":
        path = gold if gold.is_file() else gold / "retrieval_cases.jsonl"
        report = await evaluate_retrieval_file(path, settings)
        return {"suite": "retrieval", "gold_path": str(path), "report": report.to_dict()}
    if args.suite == "answer":
        path = gold if gold.is_file() else gold / "answer_cases.jsonl"
        report = evaluate_answer_file(path)
        return {"suite": "answer", "gold_path": str(path), "report": report.to_dict()}
    directory = gold if gold.is_dir() else gold.parent
    settings = make_eval_settings()
    transition = evaluate_transition_file(directory / "transition_cases.jsonl")
    supersession = await evaluate_supersession_file(
        directory / "transition_cases.jsonl", settings
    )
    retrieval = await evaluate_retrieval_file(
        directory / "retrieval_cases.jsonl", settings
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
        "report": {
            "metrics": {name: metric.to_dict() for name, metric in combined.items()},
            "transition": transition.to_dict(),
            "supersession": supersession.to_dict(),
            "retrieval": retrieval.to_dict(),
            "answer": answer.to_dict(),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = asyncio.run(evaluate_suite(args))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
