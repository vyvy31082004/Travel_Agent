import base64
import hmac
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.auth import (
    SESSION_COOKIE_NAME,
    hash_password,
    normalize_email,
    session_token_hash,
    verify_password,
)


def test_normalize_email_trims_and_lowercases() -> None:
    assert normalize_email("  USER@Example.COM  ") == "user@example.com"


def test_password_hash_does_not_store_raw_password() -> None:
    stored = hash_password("super-secret-password")
    assert "super-secret-password" not in stored
    assert verify_password("super-secret-password", stored)
    assert not verify_password("wrong-password", stored)


def test_session_token_hash_is_sha256_hex() -> None:
    token_hash = session_token_hash("token-value")
    assert len(token_hash) == 64
    assert token_hash == session_token_hash("token-value")
    assert token_hash != "token-value"
