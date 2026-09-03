from __future__ import annotations

import argparse
import json
from pathlib import Path

from e2e_eval.asyncio_compat import run_async

from e2e_eval.human_export import export_review, import_human_scores
from e2e_eval.report import write_summary_report
from e2e_eval.schema import DEFAULT_FIXTURE_DIR, load_case, load_cases_from_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run E2E evaluation for the travel agent.")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run one or all E2E cases")
    run_parser.add_argument("--case", help="Case id or YAML path")
    run_parser.add_argument("--all", action="store_true", help="Run all manifest cases")
    run_parser.add_argument("--fixtures", default=str(DEFAULT_FIXTURE_DIR))
    run_parser.add_argument("--reports-dir", default="reports/e2e_runs")
    run_parser.add_argument(
        "--fresh-seed",
        action="store_true",
        help="Delete seeded memories for this case before insert (default: upsert, keep existing rows)",
    )
    run_parser.add_argument(
        "--keep-db",
        action="store_true",
        help="Keep E2E Postgres rows after the run (default: delete all case DB artifacts when done)",
    )

    export_parser = sub.add_parser("export-review", help="Export human review markdown")
    export_parser.add_argument("trace", help="Path to trace JSON")
    export_parser.add_argument("--case", help="Optional case YAML path")

    import_parser = sub.add_parser("import-scores", help="Import human review scores JSON")
    import_parser.add_argument("trace", help="Path to trace JSON")
    import_parser.add_argument("scores", help="Path to scores JSON")

    score_parser = sub.add_parser("score", help="Aggregate metrics from run traces")
    score_parser.add_argument("--runs", default="reports/e2e_runs")
    score_parser.add_argument("--output", default="reports")

    run_parser.add_argument("-v", "--verbose", action="store_true")

    return parser


async def _run_cases(args: argparse.Namespace) -> int:
    from e2e_eval.runner import run_case

    reports_dir = Path(args.reports_dir)
    teardown = not args.keep_db
    cases = []
    if args.all:
        cases = load_cases_from_dir(args.fixtures)
    elif args.case:
        case_path = Path(args.case)
        if case_path.exists():
            cases = [load_case(case_path)]
        else:
            cases = [load_case(Path(args.fixtures) / f"{args.case}.yaml")]
    else:
        raise SystemExit("Specify --case or --all")

    results = []
    for case in cases:
        print(f"Running {case.id}...", flush=True)
        result = await run_case(
            case,
            reports_dir=reports_dir,
            verbose=args.verbose,
            teardown=teardown,
            fresh_seed=args.fresh_seed,
        )
        print(f"  trace: {result.trace_path}")
        print(f"  review: {result.trace_path.with_suffix('.review.md')}")
        integrity = (result.auto_scores.get("trace_integrity") or {}).get("status")
        print(f"  trace_integrity: {integrity}")
        if teardown:
            print(f"  postgres: cleaned up (case={case.id})", flush=True)
        else:
            print(
                f"  postgres: kept (user_id={result.trace['metadata']['user_id']}, "
                f"thread_id={result.trace['metadata']['thread_id']})",
                flush=True,
            )
        results.append(result)

    print(json.dumps([item.case_id for item in results], ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return run_async(_run_cases(args))
    if args.command == "export-review":
        path = export_review(args.trace, case_path=args.case)
        print(path)
        return 0
    if args.command == "import-scores":
        scores = json.loads(Path(args.scores).read_text(encoding="utf-8"))
        import_human_scores(args.trace, scores)
        return 0
    if args.command == "score":
        json_path, md_path = write_summary_report(args.runs, output_dir=args.output)
        print(json_path)
        print(md_path)
        return 0
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
