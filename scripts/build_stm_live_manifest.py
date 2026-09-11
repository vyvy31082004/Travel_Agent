#!/usr/bin/env python3
"""Validate STM live manifest counts (20 development / 30 test) and schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from memory_eval.stm_live_schema import (  # noqa: E402
    DEFAULT_FIXTURE_DIR,
    load_cases_from_dir,
    validate_manifest_counts,
)


def main() -> int:
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FIXTURE_DIR
    counts = validate_manifest_counts(directory)
    cases = load_cases_from_dir(directory, split="all")
    print(json.dumps(counts, indent=2))
    print(f"Loaded {len(cases)} cases OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
