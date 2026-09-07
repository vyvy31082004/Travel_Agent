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
from repositories.conversations import ConversationRef
from services.auth import AuthUser


class FakeSnapshot:
    def __init__(self, messages):
        self.values = {"messages": messages}


class FakeGraph:
    def __init__(self, messages=None):
        self._messages = messages or []
        self.invoked = []

    async def aget_state(self, config):
        return FakeSnapshot(self._messages)

    async def ainvoke(self, payload, config):
        self.invoked.append((payload, config))
        # Simulate the checkpointer accumulating messages across turns so a
        # later aget_state reflects prior turns (old_count > 0).
        self._messages = list(self._messages) + [
            SimpleNamespace(type="human", content="user turn"),
            SimpleNamespace(type="ai", content="Xin chào."),
        ]
        return {"messages": [SimpleNamespace(type="ai", content="Xin chào.")]}


class FakeAuthRepo:
    def __init__(self, user):
        self.user = user

    async def resolve_session(self, token):
        return self.user if token == "valid-session" else None


class FakeConversationsRepo:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.upserts: list[dict] = []

    async def upsert(self, *, thread_id, user_id, title=None, preview=None):
        self.upserts.append(
            {"thread_id": thread_id, "user_id": user_id, "title": title, "preview": preview}
        )
        existing = self.rows.get(thread_id)
        if existing is None:
            self.rows[thread_id] = {
                "user_id": user_id,
                "title": title,
                "preview": preview,
                "updated_at": datetime.now(timezone.utc),
            }
        elif existing["user_id"] == user_id:
            if preview is not None:
                existing["preview"] = preview
            existing["updated_at"] = datetime.now(timezone.utc)

    async def list_by_user(self, user_id, *, limit=50):
        items = [
            ConversationRef(
                thread_id=tid,
                title=row["title"],
                preview=row["preview"],
                updated_at=row["updated_at"],
            )
            for tid, row in self.rows.items()
            if row["user_id"] == user_id
        ]
        items.sort(key=lambda c: c.updated_at, reverse=True)
        return items[:limit]

    async def get_owner(self, thread_id):
        row = self.rows.get(thread_id)
        return row["user_id"] if row else None


def _user(uid="auth-user-1"):
    return AuthUser(
        user_id=uid,
        email=f"{uid}@example.com",
        email_normalized=f"{uid}@example.com",
        full_name="Test User",
    )


@pytest.fixture
def client():
    user = _user()
    fake_auth = FakeAuthRepo(user)
    fake_conv = FakeConversationsRepo()
    # State starts empty so /chat's first-turn title logic (old_count == 0) fires.
    fake_graph = FakeGraph(messages=[])
    app_module.app.state.settings = SimpleNamespace(cookie_secure=False)
    app_module.app.dependency_overrides[app_module.get_auth_repo] = lambda: fake_auth
    app_module.app.dependency_overrides[app_module.get_conversations_repo] = lambda: fake_conv
    app_module.app.dependency_overrides[get_primary_graph] = lambda: fake_graph
    test_client = TestClient(app_module.app)
    try:
        yield test_client, fake_conv, user, fake_graph
    finally:
        app_module.app.dependency_overrides.clear()


def _auth(client):
    client.cookies.set("viettrip_session", "valid-session")


# ---- Task 3.2: /chat records conversations ----

def test_authenticated_chat_creates_then_updates_single_record(client):
    test_client, fake_conv, user, fake_graph = client
    _auth(test_client)
    r1 = test_client.post("/chat", json={"msg": "Câu hỏi 1"})
    assert r1.status_code == 200
    thread_id = r1.json()["thread_id"]
    # second turn on the SAME thread
    r2 = test_client.post("/chat", json={"msg": "Câu hỏi 2", "thread_id": thread_id})
    assert r2.status_code == 200
    # exactly one record, two upsert calls
    assert list(fake_conv.rows.keys()) == [thread_id]
    assert len(fake_conv.upserts) == 2
    # first turn carried a title, second did not
    assert fake_conv.upserts[0]["title"] == "Câu hỏi 1"
    assert fake_conv.upserts[1]["title"] is None


def test_anonymous_chat_creates_no_conversation_record(client):
    test_client, fake_conv, _, fake_graph = client
    # no auth cookie -> anonymous
    r = test_client.post("/chat", json={"msg": "Ẩn danh"})
    assert r.status_code == 200
    assert fake_conv.rows == {}
    assert fake_conv.upserts == []


# ---- Task 4.3: list + load endpoints ----

def test_list_conversations_returns_only_own(client):
    test_client, fake_conv, user, fake_graph = client
    _auth(test_client)
    # seed: one owned, one for another user
    fake_conv.rows["t-own"] = {
        "user_id": user.user_id, "title": "A", "preview": "A",
        "updated_at": datetime.now(timezone.utc),
    }
    fake_conv.rows["t-other"] = {
        "user_id": "other-user", "title": "B", "preview": "B",
        "updated_at": datetime.now(timezone.utc) + timedelta(minutes=1),
    }
    r = test_client.get("/conversations")
    assert r.status_code == 200
    threads = [c["thread_id"] for c in r.json()]
    assert threads == ["t-own"]


def test_list_conversations_requires_auth(client):
    test_client, _, _, fake_graph = client
    r = test_client.get("/conversations")
    assert r.status_code == 401


def test_get_conversation_owner_loads_messages(client):
    test_client, fake_conv, user, fake_graph = client
    _auth(test_client)
    fake_graph._messages = [
        SimpleNamespace(type="human", content="Tôi thích bay thẳng"),
        SimpleNamespace(type="ai", content="Đã ghi nhận."),
    ]
    fake_conv.rows["t1"] = {
        "user_id": user.user_id, "title": "x", "preview": "x",
        "updated_at": datetime.now(timezone.utc),
    }
    r = test_client.get("/conversations/t1")
    assert r.status_code == 200
    body = r.json()
    assert body["thread_id"] == "t1"
    assert [m["role"] for m in body["messages"]] == ["user", "ai"]
    assert body["messages"][0]["content"] == "Tôi thích bay thẳng"


def test_get_conversation_non_owner_is_404(client):
    test_client, fake_conv, _, fake_graph = client
    _auth(test_client)
    fake_conv.rows["t-other"] = {
        "user_id": "someone-else", "title": "x", "preview": "x",
        "updated_at": datetime.now(timezone.utc),
    }
    r = test_client.get("/conversations/t-other")
    assert r.status_code == 404


def test_get_conversation_unknown_is_404(client):
    test_client, _, _, fake_graph = client
    _auth(test_client)
    r = test_client.get("/conversations/does-not-exist")
    assert r.status_code == 404


def test_get_conversation_requires_auth(client):
    test_client, fake_conv, user, fake_graph = client
    fake_conv.rows["t1"] = {
        "user_id": user.user_id, "title": "x", "preview": "x",
        "updated_at": datetime.now(timezone.utc),
    }
    r = test_client.get("/conversations/t1")
    assert r.status_code == 401
