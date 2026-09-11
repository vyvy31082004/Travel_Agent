from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID


def to_json_safe(value: Any) -> Any:
    """Recursively convert Postgres/LangGraph values to JSON-serializable types."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, set):
        return [to_json_safe(item) for item in sorted(value, key=str)]
    return value


def dumps_json(payload: Any, **kwargs: Any) -> str:
    import json

    return json.dumps(to_json_safe(payload), **kwargs)
