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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate TravelMemory candidate extraction against gold JSONL."
    )
    parser.add_argument("--gold", required=True, help="Path to extraction gold JSONL")
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
        default="gemini-3.6-flash",
        help="Model used when extractor is langmem or compare",
    )
    parser.add_argument("--output", help="Optional path for the JSON report")
    return parser


async def evaluate_file(
    path: str,
    split: str,
    *,
    extractor_name: str = "deterministic",
    langmem_model: str = "gemini-3.6-flash",
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
    report = await CandidateExtractionEvaluator(extractor).evaluate(cases)
    result = {
        "suite": "candidate_extraction",
        "gold_path": str(Path(path)),
        "split": split,
        "extractor": extractor_name,
        "langmem_model": langmem_model if extractor_name != "deterministic" else None,
        "case_count": len(cases),
        "report": report.to_dict(),
    }
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = asyncio.run(
        evaluate_file(
            args.gold,
            args.split,
            extractor_name=args.extractor,
            langmem_model=args.langmem_model,
        )
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
