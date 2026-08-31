"""Compute Cohen's Kappa from dual annotation files."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ANNOTATIONS_DIR = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "long_term_memory_eval"
    / "annotations"
)


def load_annotations(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        rows[obj["case_id"]] = obj
    return rows


def cohens_kappa(a_labels: list[str], b_labels: list[str]) -> float:
    if len(a_labels) != len(b_labels) or not a_labels:
        return 0.0
    n = len(a_labels)
    agree = sum(1 for x, y in zip(a_labels, b_labels) if x == y)
    p_o = agree / n

    ca = Counter(a_labels)
    cb = Counter(b_labels)
    labels = set(ca) | set(cb)
    p_e = sum((ca[l] / n) * (cb[l] / n) for l in labels)
    if p_e >= 1.0:
        return 1.0
    return (p_o - p_e) / (1.0 - p_e)


def _valid_invalid(row: dict[str, Any]) -> str:
    return "valid" if row.get("expect_extract") else "invalid"


def _category_key(row: dict[str, Any]) -> str:
    cats = row.get("primary_categories") or []
    return ",".join(sorted(set(cats))) or "none"


def _gold_count_key(row: dict[str, Any]) -> str:
    return str(row.get("gold_count", 0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cohen's Kappa for extraction annotations")
    parser.add_argument(
        "--a",
        type=Path,
        default=ANNOTATIONS_DIR / "annotations_a.jsonl",
    )
    parser.add_argument(
        "--b",
        type=Path,
        default=ANNOTATIONS_DIR / "annotations_b.jsonl",
    )
    parser.add_argument("--min-kappa", type=float, default=0.80)
    args = parser.parse_args(argv)

    if not args.a.exists() or not args.b.exists():
        print("Annotation files missing. Run: python -m memory_eval.export_annotations", file=sys.stderr)
        return 2

    ann_a = load_annotations(args.a)
    ann_b = load_annotations(args.b)
    overlap = sorted(set(ann_a) & set(ann_b))
    if len(overlap) < 30:
        print(f"Warning: only {len(overlap)} overlap cases (target >= 30)", file=sys.stderr)

    dimensions = {
        "valid_invalid": (_valid_invalid, "Valid/invalid memory"),
        "gold_count": (_gold_count_key, "Gold memory count"),
        "category_domain": (_category_key, "Category/domain"),
    }

    all_pass = True
    print(f"Overlap cases: {len(overlap)}")
    print(f"Target Kappa:  >= {args.min_kappa:.2f}\n")

    for dim_key, (fn, label) in dimensions.items():
        a_labels = [fn(ann_a[cid]) for cid in overlap]
        b_labels = [fn(ann_b[cid]) for cid in overlap]
        kappa = cohens_kappa(a_labels, b_labels)
        status = "PASS" if kappa >= args.min_kappa else "FAIL"
        if kappa < args.min_kappa:
            all_pass = False
        print(f"{label}: Kappa={kappa:.3f}  [{status}]")

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
