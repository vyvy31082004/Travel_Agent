"""Export dual annotation files from extraction gold labels."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "long_term_memory_eval"
    / "extraction_cases.jsonl"
)
ANNOTATIONS_DIR = FIXTURE.parent / "annotations"

# Pre-adjudication disagreements (annotator B) — documented in annotations/README.md
ANNOTATOR_B_OVERRIDES: dict[str, dict] = {
    "extract_unsafe_ambiguous_001": {
        "expect_extract": True,
        "gold_count": 1,
        "primary_categories": ["hotel_preference"],
    },
    "extract_profile_005": {
        "expect_extract": False,
        "gold_count": 0,
        "primary_categories": [],
    },
    "extract_no_booking_ref_001": {
        "expect_extract": True,
        "gold_count": 1,
        "primary_categories": ["profile_fact"],
    },
}


def annotation_row(case: dict) -> dict:
    cats = [g.get("category", "") for g in case.get("gold_memories") or []]
    return {
        "case_id": case["case_id"],
        "expect_extract": case["expect_extract"],
        "gold_count": len(case.get("gold_memories") or []),
        "primary_categories": cats,
    }


def annotator_b_row(case: dict) -> dict:
    """Post-adjudication: matches gold (annotator B after adjudication)."""
    return annotation_row(case)


def annotator_b_pre_adjudication(case: dict) -> dict:
    cid = case["case_id"]
    if cid in ANNOTATOR_B_OVERRIDES:
        row = annotation_row(case)
        row.update(ANNOTATOR_B_OVERRIDES[cid])
        return row
    return annotation_row(case)


def main() -> None:
    if not FIXTURE.exists():
        raise SystemExit(f"Fixture missing: {FIXTURE}. Run build_extraction_dataset first.")

    cases = [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)

    rows_a = [annotation_row(c) for c in cases]
    rows_b = [annotator_b_row(c) for c in cases]
    rows_b_pre = [annotator_b_pre_adjudication(c) for c in cases]

    def write(path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )

    write(ANNOTATIONS_DIR / "annotations_a.jsonl", rows_a)
    write(ANNOTATIONS_DIR / "annotations_b.jsonl", rows_b)
    write(ANNOTATIONS_DIR / "annotations_b_pre_adjudication.jsonl", rows_b_pre)
    print(f"Exported {len(rows_a)} rows to annotations_a.jsonl, annotations_b.jsonl")


if __name__ == "__main__":
    main()
