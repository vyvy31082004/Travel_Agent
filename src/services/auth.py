from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from psycopg import errors
from psycopg_pool import AsyncConnectionPool

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
SESSION_COOKIE_NAME = "viettrip_session"
SESSION_TTL = timedelta(days=14)
REMEMBER_SESSION_TTL = timedelta(days=30)

class AuthError(Exception):
    """Base auth error."""

class DuplicateEmailError(AuthError):
    """Email is already registered."""

class InvalidCredentialsError(AuthError):
    """Credentials are invalid."""

@dataclass(frozen=True)
class AuthUser:
    user_id: str
    email: str
    email_normalized: str
    full_name: str
    home_airport: Optional[str] = None

@dataclass(frozen=True)
class CreatedSession:
    token: str
    expires_at: datetime
    user: AuthUser

def normalize_email(email: str) -> str:
    return " ".join((email or "").strip().lower().split())

def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if not password:
        raise ValueError("password is required")
    salt = salt or os.urandom(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    hash_b64 = base64.urlsafe_b64encode(derived).decode("ascii")
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt_b64}${hash_b64}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(hash_b64.encode("ascii"))
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        (password or "").encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)

def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def _row_to_user(row: dict[str, Any] | Any) -> AuthUser:
    return AuthUser(
        user_id=str(row["user_id"]),
        email=str(row["email"]),
        email_normalized=str(row["email_normalized"]),
        full_name=str(row["full_name"]),
        home_airport=row.get("home_airport") if isinstance(row, dict) else row["home_airport"],
    )

class AuthRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def create_user(
        self,
        *,
        email: str,
        full_name: str,
        password: str,
        home_airport: str | None = None,
    ) -> AuthUser:
        email_normalized = normalize_email(email)
        if not email_normalized:
            raise ValueError("email is required")
        if not full_name.strip():
            raise ValueError("full_name is required")
        password_hash = hash_password(password)
        user_id = uuid4()
        try:
            async with self._pool.connection() as conn:
                row = await (
                    await conn.execute(
                        """
                        INSERT INTO users (
                            user_id, email, email_normalized, full_name,
                            password_hash, home_airport
                        ) VALUES (
                            %(user_id)s, %(email)s, %(email_normalized)s,
                            %(full_name)s, %(password_hash)s, %(home_airport)s
                        )
                        RETURNING user_id, email, email_normalized, full_name, home_airport
                        """,
                        {
                            "user_id": user_id,
                            "email": email.strip(),
                            "email_normalized": email_normalized,
                            "full_name": full_name.strip(),
                            "password_hash": password_hash,
                            "home_airport": home_airport.strip() if home_airport else None,
                        },
                    )
                ).fetchone()
        except errors.UniqueViolation as exc:
            raise DuplicateEmailError("Email is already registered") from exc
        return _row_to_user(row)

    async def get_user_by_email(self, email: str) -> AuthUser | None:
        email_normalized = normalize_email(email)
        if not email_normalized:
            return None
        async with self._pool.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT user_id, email, email_normalized, full_name, home_airport
                    FROM users
                    WHERE email_normalized = %(email_normalized)s
                    """,
                    {"email_normalized": email_normalized},
                )
            ).fetchone()
        return _row_to_user(row) if row else None

    async def get_user_by_id(self, user_id: str) -> AuthUser | None:
        try:
            parsed_user_id = UUID(str(user_id))
        except ValueError:
            return None
        async with self._pool.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT user_id, email, email_normalized, full_name, home_airport
                    FROM users
                    WHERE user_id = %(user_id)s
                    """,
                    {"user_id": parsed_user_id},
                )
            ).fetchone()
        return _row_to_user(row) if row else None

    async def verify_credentials(self, *, email: str, password: str) -> AuthUser:
        email_normalized = normalize_email(email)
        if not email_normalized:
            raise InvalidCredentialsError("Invalid email or password")
        async with self._pool.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT user_id, email, email_normalized, full_name,
                           home_airport, password_hash
                    FROM users
                    WHERE email_normalized = %(email_normalized)s
                    """,
                    {"email_normalized": email_normalized},
                )
            ).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            raise InvalidCredentialsError("Invalid email or password")
        return _row_to_user(row)

    async def create_session(
        self,
        *,
        user_id: str,
        remember: bool = False,
    ) -> CreatedSession:
        user = await self.get_user_by_id(user_id)
        if not user:
            raise AuthError("Cannot create session for missing user")
        token = secrets.token_urlsafe(32)
        token_hash = session_token_hash(token)
        expires_at = datetime.now(timezone.utc) + (
            REMEMBER_SESSION_TTL if remember else SESSION_TTL
        )
        session_id = uuid4()
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO user_sessions (
                    session_id, user_id, token_hash, expires_at
                ) VALUES (
                    %(session_id)s, %(user_id)s, %(token_hash)s, %(expires_at)s
                )
                """,
                {
                    "session_id": session_id,
                    "user_id": UUID(str(user_id)),
                    "token_hash": token_hash,
                    "expires_at": expires_at,
                },
            )
        return CreatedSession(token=token, expires_at=expires_at, user=user)

    async def resolve_session(self, token: str | None) -> AuthUser | None:
        if not token:
            return None
        token_hash = session_token_hash(token)
        async with self._pool.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT u.user_id, u.email, u.email_normalized,
                           u.full_name, u.home_airport
                    FROM user_sessions s
                    JOIN users u ON u.user_id = s.user_id
                    WHERE s.token_hash = %(token_hash)s
                      AND s.revoked_at IS NULL
                      AND s.expires_at > %(now)s
                    """,
                    {"token_hash": token_hash, "now": datetime.now(timezone.utc)},
                )
            ).fetchone()
        return _row_to_user(row) if row else None

    async def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        token_hash = session_token_hash(token)
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE user_sessions
                SET revoked_at = %(now)s
                WHERE token_hash = %(token_hash)s
                  AND revoked_at IS NULL
                """,
                {"token_hash": token_hash, "now": datetime.now(timezone.utc)},
            )
