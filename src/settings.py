import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    cookie_secret: str
    checkpoint_retention_days: int = 30
    conversation_retention_days: int = 90
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10
    db_pool_timeout_seconds: int = 30
    cookie_secure: bool = False

    def __post_init__(self) -> None:
        if not self.database_url:
            raise ValueError("DATABASE_URL is required")
        if not self.cookie_secret:
            raise ValueError("COOKIE_SECRET is required")
        if self.db_pool_min_size > self.db_pool_max_size:
            raise ValueError("DB_POOL_MIN_SIZE cannot exceed DB_POOL_MAX_SIZE")


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "").strip(),
        cookie_secret=os.getenv("COOKIE_SECRET", "").strip(),
        checkpoint_retention_days=_positive_int("CHECKPOINT_RETENTION_DAYS", 30),
        conversation_retention_days=_positive_int(
            "CONVERSATION_RETENTION_DAYS", 90
        ),
        db_pool_min_size=_positive_int("DB_POOL_MIN_SIZE", 1),
        db_pool_max_size=_positive_int("DB_POOL_MAX_SIZE", 10),
        db_pool_timeout_seconds=_positive_int("DB_POOL_TIMEOUT_SECONDS", 30),
        cookie_secure=os.getenv("COOKIE_SECURE", "false").strip().lower()
        in {"1", "true", "yes", "on"},
    )
