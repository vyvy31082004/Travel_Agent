"""Unified offline entry point for long-term memory evaluation.

Usage:
  python -m memory_eval.run --suite extraction --split dev
  python -m memory_eval.run --suite all --split dev --extractor deterministic
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from memory_eval.run_extraction import DEFAULT_FIXTURE, run_eval

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Long-term memory offline eval")
    parser.add_argument(
        "--suite",
        choices=["extraction", "all"],
        default="extraction",
        help="Eval suite (Phase 1: extraction only)",
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--split", choices=["dev", "held_out"], default="dev")
    parser.add_argument(
        "--extractor",
        default="deterministic",
        choices=["deterministic", "langmem", "compare"],
    )
    parser.add_argument("--held-out-run", action="store_true")
    parser.add_argument("--case-id", default=None)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=REPORTS_DIR / "long_term_memory_eval.json",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=REPORTS_DIR / "long_term_memory_eval.md",
    )
    args = parser.parse_args(argv)

    if args.suite not in {"extraction", "all"}:
        print(f"Suite {args.suite!r} not implemented yet", file=sys.stderr)
        return 2

    metrics, code = run_eval(
        args.fixture,
        case_id=args.case_id,
        split=args.split,
        extractor_name=args.extractor,
        held_out_run=args.held_out_run,
        verbose=args.case_id is not None,
    )

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    from memory_eval.run_extraction import _write_markdown_report

    _write_markdown_report(args.md_out, metrics)
    print(f"Wrote {args.json_out}")
    print(f"Wrote {args.md_out}")
    print(
        f"Recall={metrics.recall:.3f} Precision={metrics.precision:.3f} "
        f"Faithfulness={metrics.faithfulness:.3f} UnsafeReject={metrics.unsafe_rejection_rate:.3f}"
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
