import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_eval.suites import evaluate_retrieval_file, make_eval_settings


def test_retrieval_suite_covers_applicability_scenarios():
    """Applicability gold now lives in retrieval_cases.jsonl."""
    fixture = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "long_term_memory_eval"
        / "retrieval_cases.jsonl"
    )
    report = asyncio.run(
        evaluate_retrieval_file(fixture, make_eval_settings(), split="development")
    )
    assert report.metrics["applicability_macro_f1"].value is not None
    assert report.metrics["applicability_macro_f1"].value >= 0.9
