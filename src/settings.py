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


def _non_negative_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be zero or greater")
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}

def _float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < 0:
        raise ValueError(f"{name} must be zero or greater")
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
    long_term_memory_recall_enabled: bool = False
    long_term_memory_write_enabled: bool = False
    long_term_memory_sync_finalize: bool = False
    long_term_memory_recall_limit: int = 5
    long_term_memory_worker_retry_limit: int = 3
    long_term_memory_text_search_limit: int = 50
    long_term_memory_embedding_model: str = "models/gemini-embedding-001"
    long_term_memory_vector_dims: int = 3072
    long_term_memory_vector_search_enabled: bool = False
    long_term_memory_vector_fallback_enabled: bool = True
    long_term_memory_vector_distance_threshold: float = 0.35
    long_term_memory_embedding_backfill_batch_size: int = 100
    long_term_memory_debug_enabled: bool = False
    long_term_memory_extractor: str = "deterministic"
    long_term_memory_langmem_model: str = "gemini-3.6-flash"
    long_term_memory_verifier: str = "trustmem"
    long_term_memory_trustmem_model: str = "gemini-2.5-flash"
    long_term_memory_trustmem_prompt_version: str = "trustmem-verifier-v2"
    long_term_memory_trustmem_timeout_seconds: int = 90
    long_term_memory_trustmem_coverage_threshold: float = 0.80
    long_term_memory_trustmem_preservation_threshold: float = 0.90
    long_term_memory_trustmem_faithfulness_threshold: float = 0.95
    long_term_memory_transition_path: str = "llm"
    long_term_memory_transition_model: str = "gemini-2.5-flash"
    long_term_memory_transition_confidence_threshold: float = 0.85
    long_term_memory_transition_batch_size: int = 10
    long_term_memory_domain_candidate_limit: int = 50
    long_term_memory_action_inference_enabled: bool = False
    long_term_memory_applicability_judge_enabled: bool = True
    long_term_memory_applicability_batch_size: int = 10

    def __post_init__(self) -> None:
        if not self.database_url:
            raise ValueError("DATABASE_URL is required")
        if not self.cookie_secret:
            raise ValueError("COOKIE_SECRET is required")
        if self.db_pool_min_size > self.db_pool_max_size:
            raise ValueError("DB_POOL_MIN_SIZE cannot exceed DB_POOL_MAX_SIZE")
        if not self.long_term_memory_embedding_model:
            raise ValueError("LONG_TERM_MEMORY_EMBEDDING_MODEL is required")
        if self.long_term_memory_vector_dims < 1:
            raise ValueError("LONG_TERM_MEMORY_VECTOR_DIMS must be greater than zero")
        if not 0 <= self.long_term_memory_vector_distance_threshold <= 2:
            raise ValueError(
                "LONG_TERM_MEMORY_VECTOR_DISTANCE_THRESHOLD must be between 0 and 2"
            )
        if self.long_term_memory_extractor not in {
            "deterministic",
            "langmem",
            "compare",
        }:
            raise ValueError(
                "LONG_TERM_MEMORY_EXTRACTOR must be deterministic, langmem, or compare"
            )
        if self.long_term_memory_verifier not in {
            "deterministic",
            "trustmem",
            "trustmem-dry-run",
        }:
            raise ValueError(
                "LONG_TERM_MEMORY_VERIFIER must be deterministic, trustmem, or trustmem-dry-run"
            )
        if self.long_term_memory_transition_path not in {
            "lexical",
            "llm",
            "policy-mock",
        }:
            raise ValueError(
                "LONG_TERM_MEMORY_TRANSITION_PATH must be lexical, llm, or policy-mock"
            )
        if self.long_term_memory_transition_batch_size < 1:
            raise ValueError(
                "LONG_TERM_MEMORY_TRANSITION_BATCH_SIZE must be greater than zero"
            )
        for name, value in {
            "LONG_TERM_MEMORY_TRUSTMEM_COVERAGE_THRESHOLD": self.long_term_memory_trustmem_coverage_threshold,
            "LONG_TERM_MEMORY_TRUSTMEM_PRESERVATION_THRESHOLD": self.long_term_memory_trustmem_preservation_threshold,
            "LONG_TERM_MEMORY_TRUSTMEM_FAITHFULNESS_THRESHOLD": self.long_term_memory_trustmem_faithfulness_threshold,
            "LONG_TERM_MEMORY_TRANSITION_CONFIDENCE_THRESHOLD": self.long_term_memory_transition_confidence_threshold,
        }.items():
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


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
        cookie_secure=_bool_env("COOKIE_SECURE", False),
        long_term_memory_recall_enabled=_bool_env(
            "LONG_TERM_MEMORY_RECALL_ENABLED", False
        ),
        long_term_memory_write_enabled=_bool_env(
            "LONG_TERM_MEMORY_WRITE_ENABLED", False
        ),
        long_term_memory_sync_finalize=_bool_env(
            "LONG_TERM_MEMORY_SYNC_FINALIZE", False
        ),
        long_term_memory_recall_limit=_positive_int(
            "LONG_TERM_MEMORY_RECALL_LIMIT", 5
        ),
        long_term_memory_worker_retry_limit=_positive_int(
            "LONG_TERM_MEMORY_WORKER_RETRY_LIMIT", 3
        ),
        long_term_memory_text_search_limit=_positive_int(
            "LONG_TERM_MEMORY_TEXT_SEARCH_LIMIT", 50
        ),
        long_term_memory_embedding_model=os.getenv(
            "LONG_TERM_MEMORY_EMBEDDING_MODEL", "models/gemini-embedding-001"
        ).strip(),
        long_term_memory_vector_dims=_positive_int(
            "LONG_TERM_MEMORY_VECTOR_DIMS", 3072
        ),
        long_term_memory_vector_search_enabled=_bool_env(
            "LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED", False
        ),
        long_term_memory_vector_fallback_enabled=_bool_env(
            "LONG_TERM_MEMORY_VECTOR_FALLBACK_ENABLED", True
        ),
        long_term_memory_vector_distance_threshold=_float_env(
            "LONG_TERM_MEMORY_VECTOR_DISTANCE_THRESHOLD", 0.35
        ),
        long_term_memory_embedding_backfill_batch_size=_positive_int(
            "LONG_TERM_MEMORY_EMBEDDING_BACKFILL_BATCH_SIZE", 100
        ),
        long_term_memory_debug_enabled=_bool_env(
            "LONG_TERM_MEMORY_DEBUG_ENABLED", False
        ),
        long_term_memory_extractor=os.getenv(
            "LONG_TERM_MEMORY_EXTRACTOR", "deterministic"
        ).strip().lower(),
        long_term_memory_langmem_model=os.getenv(
            "LONG_TERM_MEMORY_LANGMEM_MODEL", "gemini-3.6-flash"
        ).strip(),
        long_term_memory_verifier=os.getenv(
            "LONG_TERM_MEMORY_VERIFIER", "trustmem"
        ).strip().lower(),
        long_term_memory_trustmem_model=os.getenv(
            "LONG_TERM_MEMORY_TRUSTMEM_MODEL", "gemini-2.5-flash"
        ).strip(),
        long_term_memory_trustmem_prompt_version=os.getenv(
            "LONG_TERM_MEMORY_TRUSTMEM_PROMPT_VERSION", "trustmem-verifier-v2"
        ).strip(),
        long_term_memory_trustmem_timeout_seconds=_positive_int(
            "LONG_TERM_MEMORY_TRUSTMEM_TIMEOUT_SECONDS", 90
        ),
        long_term_memory_trustmem_coverage_threshold=_float_env(
            "LONG_TERM_MEMORY_TRUSTMEM_COVERAGE_THRESHOLD", 0.80
        ),
        long_term_memory_trustmem_preservation_threshold=_float_env(
            "LONG_TERM_MEMORY_TRUSTMEM_PRESERVATION_THRESHOLD", 0.90
        ),
        long_term_memory_trustmem_faithfulness_threshold=_float_env(
            "LONG_TERM_MEMORY_TRUSTMEM_FAITHFULNESS_THRESHOLD", 0.95
        ),
        long_term_memory_transition_path=os.getenv(
            "LONG_TERM_MEMORY_TRANSITION_PATH", "llm"
        ).strip().lower(),
        long_term_memory_transition_model=os.getenv(
            "LONG_TERM_MEMORY_TRANSITION_MODEL", "gemini-2.5-flash"
        ).strip(),
        long_term_memory_transition_confidence_threshold=_float_env(
            "LONG_TERM_MEMORY_TRANSITION_CONFIDENCE_THRESHOLD", 0.85
        ),
        long_term_memory_transition_batch_size=_positive_int(
            "LONG_TERM_MEMORY_TRANSITION_BATCH_SIZE", 10
        ),
        long_term_memory_domain_candidate_limit=_positive_int(
            "LONG_TERM_MEMORY_DOMAIN_CANDIDATE_LIMIT", 50
        ),
        long_term_memory_action_inference_enabled=_bool_env(
            "LONG_TERM_MEMORY_ACTION_INFERENCE_ENABLED", False
        ),
        long_term_memory_applicability_judge_enabled=_bool_env(
            "LONG_TERM_MEMORY_APPLICABILITY_JUDGE_ENABLED", True
        ),
        long_term_memory_applicability_batch_size=_positive_int(
            "LONG_TERM_MEMORY_APPLICABILITY_BATCH_SIZE", 10
        ),
    )
