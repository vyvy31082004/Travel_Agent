from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from memory.long_term import TravelMemory


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
            if not isinstance(raw, dict) or not str(raw.get("case_id") or "").strip():
                raise ValueError(f"invalid JSONL at line {line_number}: case_id required")
            rows.append(raw)
    return rows


def memory_from_dict(raw: dict[str, Any]) -> TravelMemory:
    data = dict(raw)
    data.pop("relevant", None)
    data.pop("family", None)
    valid_to = data.get("valid_to")
    valid_from = data.get("valid_from")
    if isinstance(valid_to, str):
        data["valid_to"] = datetime.fromisoformat(valid_to)
    if isinstance(valid_from, str):
        data["valid_from"] = datetime.fromisoformat(valid_from)
    return TravelMemory.from_record(data)
