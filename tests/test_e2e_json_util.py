from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from e2e_eval.json_util import to_json_safe


def test_to_json_safe_uuid_and_datetime() -> None:
    payload = {
        "job_id": UUID("b1636dff-e070-43b8-afef-85d63dea7786"),
        "created_at": datetime(2026, 9, 1, 10, 30, 0),
        "nested": [{"memory_id": UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")}],
    }
    safe = to_json_safe(payload)
    assert safe["job_id"] == "b1636dff-e070-43b8-afef-85d63dea7786"
    assert safe["created_at"] == "2026-09-01T10:30:00"
    assert safe["nested"][0]["memory_id"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
