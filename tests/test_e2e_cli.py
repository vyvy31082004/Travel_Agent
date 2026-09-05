from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from e2e_eval.cli import _build_parser


def test_cli_defaults_to_postgres_cleanup_after_run() -> None:
    args = _build_parser().parse_args(["run", "--case", "e2e_hotel_001"])
    assert args.keep_db is False


def test_cli_keep_db_opt_out() -> None:
    args = _build_parser().parse_args(["run", "--case", "e2e_hotel_001", "--keep-db"])
    assert args.keep_db is True
