import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("GOOGLE_API_KEY", "test-gemini-key")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/database")
os.environ.setdefault("COOKIE_SECRET", "test-cookie-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app as app_module
from dependencies import get_primary_graph
from services.auth import (
    AuthUser,
    CreatedSession,
    DuplicateEmailError,
    InvalidCredentialsError,
    SESSION_COOKIE_NAME,
)


class FakeSnapshot:
    values = {"messages": []}


class FakeGraph:
    def __init__(self):
        self.payloads = []
        self.configs = []

    async def aget_state(self, config):
        self.configs.append(config)
        return FakeSnapshot()

    async def ainvoke(self, payload, config):
        self.payloads.append(payload)
        self.configs.append(config)
        return {
            "messages": [
                SimpleNamespace(type="ai", content="Xin chào từ route test.")
            ]
        }


class FakeAuthRepo:
    def __init__(self):
        self.user = AuthUser(
            user_id="auth-user-1",
            email="an@example.com",
            email_normalized="an@example.com",
            full_name="Nguyen An",
        )
        self.created_users = []
        self.revoked = []

    async def resolve_session(self, token):
        return self.user if token == "valid-session" else None

    async def verify_credentials(self, *, email, password):
        if email == "an@example.com" and password == "correct-password":
            return self.user
        raise InvalidCredentialsError("invalid")

    async def create_session(self, *, user_id, remember=False):
        return CreatedSession(
            token="new-session-token",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            user=self.user,
        )

    async def create_user(self, *, email, full_name, password, home_airport=None):
        if email == "taken@example.com":
            raise DuplicateEmailError("duplicate")
        self.created_users.append((email, full_name, password))
        return self.user

    async def revoke_session(self, token):
        self.revoked.append(token)


@pytest.fixture
def client():
    fake_auth = FakeAuthRepo()
    fake_graph = FakeGraph()
    app_module.app.state.settings = SimpleNamespace(cookie_secure=False)
    app_module.app.dependency_overrides[app_module.get_auth_repo] = lambda: fake_auth
    app_module.app.dependency_overrides[get_primary_graph] = lambda: fake_graph
    test_client = TestClient(app_module.app)
    try:
        yield test_client, fake_auth, fake_graph
    finally:
        app_module.app.dependency_overrides.clear()


def test_register_creates_user_and_session_cookie(client):
    test_client, fake_auth, _ = client
    response = test_client.post(
        "/register",
        data={
            "full_name": "Nguyen An",
            "email": "an@example.com",
            "password": "correct-password",
            "confirm_password": "correct-password",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert fake_auth.created_users == [
        ("an@example.com", "Nguyen An", "correct-password")
    ]
    assert SESSION_COOKIE_NAME in response.headers.get("set-cookie", "")


def test_register_duplicate_email_shows_error(client):
    test_client, _, _ = client
    response = test_client.post(
        "/register",
        data={
            "full_name": "Nguyen An",
            "email": "taken@example.com",
            "password": "correct-password",
            "confirm_password": "correct-password",
        },
    )
    assert response.status_code == 400
    assert "Email này đã được đăng ký" in response.text


def test_login_success_and_failure(client):
    test_client, _, _ = client
    ok = test_client.post(
        "/login",
        data={"email": "an@example.com", "password": "correct-password"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    assert SESSION_COOKIE_NAME in ok.headers.get("set-cookie", "")

    bad = test_client.post(
        "/login",
        data={"email": "an@example.com", "password": "wrong-password"},
    )
    assert bad.status_code == 400
    assert "Email hoặc mật khẩu không đúng" in bad.text


def test_logout_revokes_session(client):
    test_client, fake_auth, _ = client
    response = test_client.post(
        "/logout",
        cookies={SESSION_COOKIE_NAME: "valid-session"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert fake_auth.revoked == ["valid-session"]


def test_authenticated_chat_uses_session_user_id(client):
    test_client, _, fake_graph = client
    response = test_client.post(
        "/chat",
        json={"msg": "Xin chào", "thread_id": "thread-1", "user_id": "spoofed"},
        cookies={SESSION_COOKIE_NAME: "valid-session"},
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == "auth-user-1"
    assert fake_graph.payloads[-1]["user_id"] == "auth-user-1"
