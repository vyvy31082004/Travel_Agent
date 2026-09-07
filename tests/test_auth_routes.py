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


class FakeConversationsRepo:
    async def upsert(self, *, thread_id, user_id, title=None, preview=None):
        return None

    async def list_by_user(self, user_id, *, limit=50):
        return []

    async def get_owner(self, thread_id):
        return None


@pytest.fixture
def client():
    fake_auth = FakeAuthRepo()
    fake_graph = FakeGraph()
    app_module.app.state.settings = SimpleNamespace(cookie_secure=False)
    app_module.app.dependency_overrides[app_module.get_auth_repo] = lambda: fake_auth
    app_module.app.dependency_overrides[app_module.get_conversations_repo] = (
        lambda: FakeConversationsRepo()
    )
    app_module.app.dependency_overrides[get_primary_graph] = lambda: fake_graph
    test_client = TestClient(app_module.app)
    try:
        yield test_client, fake_auth, fake_graph
    finally:
        app_module.app.dependency_overrides.clear()


def test_auth_pages_render(client):
    test_client, _, _ = client
    assert test_client.get("/login").status_code == 200
    assert test_client.get("/register").status_code == 200


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
    cookie = response.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


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
    assert response.headers["location"] == "/login"
    assert fake_auth.revoked == ["valid-session"]
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


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

def test_unauthenticated_chat_ignores_client_user_id_and_mints_anon(client):
    test_client, _, fake_graph = client
    response = test_client.post(
        "/chat",
        json={"msg": "Xin chào", "thread_id": "thread-1", "user_id": "auth-user-1"},
    )
    assert response.status_code == 200
    used_user_id = fake_graph.payloads[-1]["user_id"]
    # The spoofed/other-user id must NOT be used; a server-issued anon id is minted.
    assert used_user_id != "auth-user-1"
    assert used_user_id.startswith("anon-")
    # A server-controlled anonymous cookie is set (httponly), not a shared bucket.
    set_cookie = response.headers.get("set-cookie", "")
    assert app_module.ANON_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie

def test_unauthenticated_chat_reuses_valid_anon_cookie(client):
    test_client, _, fake_graph = client
    import uuid as _uuid

    anon = str(_uuid.uuid4())
    response = test_client.post(
        "/chat",
        json={"msg": "Xin chào", "thread_id": "thread-1"},
        cookies={app_module.ANON_COOKIE_NAME: anon},
    )
    assert response.status_code == 200
    assert fake_graph.payloads[-1]["user_id"] == f"anon-{anon}"

def test_unauthenticated_chat_rejects_malformed_anon_cookie(client):
    test_client, _, fake_graph = client
    response = test_client.post(
        "/chat",
        json={"msg": "Xin chào", "thread_id": "thread-1"},
        cookies={app_module.ANON_COOKIE_NAME: "not-a-uuid"},
    )
    assert response.status_code == 200
    used_user_id = fake_graph.payloads[-1]["user_id"]
    assert used_user_id.startswith("anon-")
    assert "not-a-uuid" not in used_user_id
    # A fresh valid id is issued to replace the malformed one.
    set_cookie = response.headers.get("set-cookie", "")
    assert app_module.ANON_COOKIE_NAME in set_cookie


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *args, **kwargs):
        return _FakeCursor(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, rows):
        self._rows = rows

    def connection(self):
        return _FakeConn(self._rows)


@pytest.fixture
def debug_client():
    fake_auth = FakeAuthRepo()
    app_module.app.state.settings = SimpleNamespace(
        cookie_secure=False, long_term_memory_debug_enabled=True
    )
    app_module.app.state.database_pool = _FakePool([{"job_id": "j1", "user_id": "u1"}])
    app_module.app.dependency_overrides[app_module.get_auth_repo] = lambda: fake_auth
    test_client = TestClient(app_module.app)
    try:
        yield test_client
    finally:
        app_module.app.dependency_overrides.clear()


def test_debug_endpoints_require_authentication(debug_client):
    # Unauthenticated -> 404 (does not reveal existence / no data leak).
    for path in ("/debug/memory/jobs", "/debug/memory/audit"):
        anon = debug_client.get(path)
        assert anon.status_code == 404


def test_debug_endpoints_allow_authenticated_when_flag_on(debug_client):
    debug_client.cookies.set(SESSION_COOKIE_NAME, "valid-session")
    resp = debug_client.get("/debug/memory/jobs")
    assert resp.status_code == 200
    assert resp.json() == [{"job_id": "j1", "user_id": "u1"}]


def test_debug_endpoints_404_when_flag_off():
    fake_auth = FakeAuthRepo()
    app_module.app.state.settings = SimpleNamespace(
        cookie_secure=False, long_term_memory_debug_enabled=False
    )
    app_module.app.state.database_pool = _FakePool([])
    app_module.app.dependency_overrides[app_module.get_auth_repo] = lambda: fake_auth
    test_client = TestClient(app_module.app)
    test_client.cookies.set(SESSION_COOKIE_NAME, "valid-session")
    try:
        assert test_client.get("/debug/memory/jobs").status_code == 404
        assert test_client.get("/debug/memory/audit").status_code == 404
    finally:
        app_module.app.dependency_overrides.clear()
