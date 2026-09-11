import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import parse_qs

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from agents.primary.agent import build_primary_graph
from dependencies import get_primary_graph
from infrastructure.postgres import open_postgres
from memory.commit import MemoryCommitAdapter
from memory.embeddings import MemoryEmbeddingService
from memory.verifier import build_memory_verifier
from memory.worker import MemoryWorker
from repositories.conversations import ConversationsRepository
from repositories.long_term_memory import PostgresLongTermMemoryRepository
from repositories.result_store import ResultStoreRepository
from services.auth import (
    AuthRepository,
    AuthUser,
    DuplicateEmailError,
    InvalidCredentialsError,
    SESSION_COOKIE_NAME,
)
from services.long_term_memory import MemoryService
from settings import get_settings
from utils.tracing import with_trace_config

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    msg: str = Field(min_length=1)
    thread_id: str | None = None
    # NOTE: `user_id` is intentionally NOT a field here. The server no longer
    # trusts a client-supplied user id; identity is resolved server-side from
    # the session cookie or a server-issued anonymous id. Any `user_id` in the
    # request body is ignored (pydantic drops unknown fields by default).


# Cookie carrying a server-issued anonymous identity for unauthenticated chat.
ANON_COOKIE_NAME = "viettrip_anon_id"


def _is_valid_anon_id(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.version == 4


def _resolve_anonymous_identity(request: Request) -> tuple[str, str, bool]:
    """Return (cookie_value, user_id, is_new).

    Reuses a valid server-issued anonymous id from the cookie, otherwise mints
    a fresh one. Never falls back to a shared global identifier.
    """
    existing = request.cookies.get(ANON_COOKIE_NAME)
    if _is_valid_anon_id(existing):
        cookie_value = str(existing)
        return cookie_value, f"anon-{cookie_value}", False
    cookie_value = str(uuid.uuid4())
    return cookie_value, f"anon-{cookie_value}", True


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with open_postgres(settings) as postgres:
        repo = ResultStoreRepository(postgres.pool)
        memory_repo = PostgresLongTermMemoryRepository(postgres.pool)
        embedding_service = MemoryEmbeddingService(settings=settings)
        memory_worker = MemoryWorker(
            pool=postgres.pool,
            settings=settings,
            repository=memory_repo,
            commit_adapter=MemoryCommitAdapter(
                repository=memory_repo,
                verifier=build_memory_verifier(settings),
                embedding_service=embedding_service,
            ),
            embedding_service=embedding_service,
        )
        memory_service = MemoryService(
            settings=settings,
            repository=memory_repo,
            processor=memory_worker,
            embedding_service=embedding_service,
        )
        app.state.settings = settings
        app.state.database_pool = postgres.pool
        app.state.checkpointer = postgres.checkpointer
        app.state.result_store = repo
        app.state.auth_repo = AuthRepository(postgres.pool)
        app.state.conversations_repo = ConversationsRepository(postgres.pool)
        app.state.long_term_memory = memory_service
        app.state.primary_graph = await build_primary_graph(
            checkpointer=postgres.checkpointer,
            repo=repo,
            memory_service=memory_service,
        )
        yield


app = FastAPI(title="Travel Customer Support Agent", lifespan=lifespan)

@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _form_data(request: Request) -> dict[str, str]:
    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}

def get_auth_repo(request: Request) -> AuthRepository:
    return request.app.state.auth_repo

def get_conversations_repo(request: Request) -> ConversationsRepository:
    return request.app.state.conversations_repo

async def get_current_user(
    request: Request,
    auth_repo: AuthRepository = Depends(get_auth_repo),
) -> AuthUser | None:
    return await auth_repo.resolve_session(request.cookies.get(SESSION_COOKIE_NAME))

def _cookie_max_age(expires_at: datetime) -> int:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))

def _set_session_cookie(response: RedirectResponse, *, token: str, settings, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME, token, max_age=max_age, httponly=True,
        secure=settings.cookie_secure, samesite="lax",
    )

@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    current_user: AuthUser | None = Depends(get_current_user),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="chat.html", context={"current_user": current_user}
    )

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="login.html", context={"error": None, "email": ""}
    )

@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, auth_repo: AuthRepository = Depends(get_auth_repo)):
    form = await _form_data(request)
    email, password = form.get("email", "").strip(), form.get("password", "")
    try:
        user = await auth_repo.verify_credentials(email=email, password=password)
    except InvalidCredentialsError:
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "Email hoặc mật khẩu không đúng.", "email": email},
            status_code=400,
        )
    session = await auth_repo.create_session(user_id=user.user_id, remember="remember" in form)
    response = RedirectResponse(url="/", status_code=303)
    _set_session_cookie(response, token=session.token, settings=request.app.state.settings, max_age=_cookie_max_age(session.expires_at))
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="register.html", context={"error": None, "full_name": "", "email": ""}
    )

@app.post("/register", response_class=HTMLResponse)
async def register_submit(request: Request, auth_repo: AuthRepository = Depends(get_auth_repo)):
    form = await _form_data(request)
    full_name, email = form.get("full_name", "").strip(), form.get("email", "").strip()
    password, confirm_password = form.get("password", ""), form.get("confirm_password", "")
    context = {"full_name": full_name, "email": email}
    error = None
    if not full_name or not email or not password:
        error = "Vui lòng nhập đầy đủ thông tin."
    elif password != confirm_password:
        error = "Mật khẩu xác nhận không khớp."
    elif len(password) < 8:
        error = "Mật khẩu cần ít nhất 8 ký tự."
    if error:
        return templates.TemplateResponse(request=request, name="register.html", context={**context, "error": error}, status_code=400)
    try:
        user = await auth_repo.create_user(email=email, full_name=full_name, password=password)
    except DuplicateEmailError:
        return templates.TemplateResponse(request=request, name="register.html", context={**context, "error": "Email này đã được đăng ký."}, status_code=400)
    session = await auth_repo.create_session(user_id=user.user_id)
    response = RedirectResponse(url="/", status_code=303)
    _set_session_cookie(response, token=session.token, settings=request.app.state.settings, max_age=_cookie_max_age(session.expires_at))
    return response

@app.post("/logout")
async def logout(request: Request, auth_repo: AuthRepository = Depends(get_auth_repo)):
    await auth_repo.revoke_session(request.cookies.get(SESSION_COOKIE_NAME))
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response

@app.get("/conversations")
async def list_conversations(
    current_user: AuthUser | None = Depends(get_current_user),
    conversations_repo: ConversationsRepository = Depends(get_conversations_repo),
) -> list[dict]:
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    conversations = await conversations_repo.list_by_user(current_user.user_id)
    return [
        {
            "thread_id": c.thread_id,
            "title": c.title,
            "preview": c.preview,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in conversations
    ]

@app.get("/conversations/{thread_id}")
async def get_conversation(
    thread_id: str,
    current_user: AuthUser | None = Depends(get_current_user),
    conversations_repo: ConversationsRepository = Depends(get_conversations_repo),
    primary_graph=Depends(get_primary_graph),
) -> dict:
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    owner = await conversations_repo.get_owner(thread_id)
    if owner is None or owner != current_user.user_id:
        # 404 (not 403) so a non-owner cannot probe which threads exist.
        raise HTTPException(status_code=404, detail="Not found")
    config = {"configurable": {"thread_id": thread_id, "user_id": current_user.user_id}}
    snapshot = await primary_graph.aget_state(config)
    stored = snapshot.values.get("messages", []) if snapshot.values else []
    messages: list[dict] = []
    for msg in stored:
        role = getattr(msg, "type", None)
        if role not in ("human", "ai", "assistant"):
            continue
        content = _message_content_text(getattr(msg, "content", ""))
        if not content:
            continue
        if content == "Proceeding with the next requested task.":
            continue
        messages.append(
            {"role": "user" if role == "human" else "ai", "content": content}
        )
    return {"thread_id": thread_id, "messages": messages}


def _require_debug_access(
    request: Request, current_user: AuthUser | None
) -> None:
    """Gate debug endpoints behind the flag AND authentication.

    Returns 404 (not 401/403) when the flag is off or the caller is
    unauthenticated, so the endpoints do not reveal their existence or leak
    cross-user identifiers to anonymous callers.
    """
    settings = request.app.state.settings
    if not settings.long_term_memory_debug_enabled or current_user is None:
        raise HTTPException(status_code=404, detail="Not found")


@app.get("/debug/memory/jobs")
async def debug_memory_jobs(
    request: Request,
    current_user: AuthUser | None = Depends(get_current_user),
) -> list[dict]:
    _require_debug_access(request, current_user)
    async with request.app.state.database_pool.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT job_id, user_id, thread_id, status, attempts,
                       error_summary, created_at, updated_at
                FROM memory_jobs
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/debug/memory/audit")
async def debug_memory_audit(
    request: Request,
    current_user: AuthUser | None = Depends(get_current_user),
) -> list[dict]:
    _require_debug_access(request, current_user)
    async with request.app.state.database_pool.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT audit_id, job_id, user_id, thread_id, decision,
                       affected_memory_ids, created_at
                FROM memory_audit_records
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
        ).fetchall()
    return [dict(row) for row in rows]


def _message_content_text(content: object) -> str:
    """Normalize LangChain string or structured content blocks for `/chat`."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content) if content is not None else ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _messages_since_last_human(messages: list) -> list:
    for index in range(len(messages) - 1, -1, -1):
        if getattr(messages[index], "type", None) in ("human", "user"):
            return list(messages[index + 1 :])
    return list(messages)


def _turn_messages(final_messages: list, old_messages: list) -> list:
    """Return the messages produced by the current turn.

    `summarize_conversation` prunes older messages through `RemoveMessage`, so
    the final list can be shorter than the pre-turn one and positional slicing
    would skip past the new answer entirely.
    """
    old_ids = {
        getattr(message, "id", None)
        for message in old_messages
        if getattr(message, "id", None) is not None
    }
    if old_ids:
        new_messages = [
            message
            for message in final_messages
            if getattr(message, "id", None) not in old_ids
        ]
        if new_messages:
            return new_messages

    old_count = len(old_messages)
    if len(final_messages) > old_count:
        return list(final_messages[old_count:])
    return _messages_since_last_human(final_messages)


@app.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    response: Response,
    primary_graph=Depends(get_primary_graph),
    current_user: AuthUser | None = Depends(get_current_user),
    conversations_repo: ConversationsRepository = Depends(get_conversations_repo),
) -> dict[str, str]:
    settings = request.app.state.settings
    thread_id = payload.thread_id or str(uuid.uuid4())
    if current_user:
        user_id = current_user.user_id
    else:
        anon_cookie, user_id, is_new = _resolve_anonymous_identity(request)
        if is_new:
            response.set_cookie(
                ANON_COOKIE_NAME,
                anon_cookie,
                max_age=60 * 60 * 24 * 30,
                httponly=True,
                secure=settings.cookie_secure,
                samesite="lax",
            )
    config = with_trace_config(
        {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id,
            }
        },
        run_name="customer_support_agent",
        tags=["customer-support", "primary"],
        metadata={"thread_id": thread_id, "user_id": user_id},
    )

    snapshot = await primary_graph.aget_state(config)
    old_messages = list(snapshot.values.get("messages", [])) if snapshot.values else []
    old_count = len(old_messages)

    # Record the conversation for authenticated users so it can be listed and
    # reopened later. Anonymous callers get no conversation record. The title is
    # set from the first user message; later turns only refresh preview/updated.
    if current_user:
        try:
            await conversations_repo.upsert(
                thread_id=thread_id,
                user_id=user_id,
                title=payload.msg if old_count == 0 else None,
                preview=payload.msg,
            )
        except Exception as exc:  # pragma: no cover - non-fatal bookkeeping
            logger.warning("conversation upsert failed: %s", exc)

    result = await primary_graph.ainvoke(
        {
            "messages": ("user", payload.msg),
            "user_id": user_id,
            "thread_id": thread_id,
        },
        config,
    )

    final_messages = list(result["messages"])
    new_messages = _turn_messages(final_messages, old_messages)
    ai_responses: list[str] = []
    for msg in new_messages:
        if msg.type in ("ai", "assistant") and msg.content:
            content = _message_content_text(msg.content)
            if content and "Proceeding with the next requested task" not in content:
                ai_responses.append(content)

    if not ai_responses:
        logger.warning(
            "no assistant text for thread_id=%s (before=%d, after=%d, turn=%d)",
            thread_id,
            old_count,
            len(final_messages),
            len(new_messages),
        )

    response = (
        "\n\n".join(ai_responses)
        if ai_responses
        else "Sorry, I couldn't get a response."
    )
    return {"response": response, "thread_id": thread_id, "user_id": user_id}


if __name__ == "__main__":
    import asyncio
    import os
    import sys

    # Local dev entrypoint (cross-platform): `python src/app.py`.
    #
    # uvicorn >= 0.36 builds the loop via asyncio.run(..., loop_factory=...),
    # which hard-codes ProactorEventLoop on Windows and ignores any event-loop
    # policy. psycopg's async pool requires a SelectorEventLoop, so on Windows
    # we run the server ourselves with an explicit SelectorEventLoop factory.
    # Linux/macOS use the normal uvicorn.run(); production (uvicorn app:app on
    # Linux via the start script) never executes this __main__ block.
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))

    if sys.platform == "win32":
        import selectors

        def _selector_loop() -> asyncio.AbstractEventLoop:
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

        server = uvicorn.Server(uvicorn.Config(app, host=host, port=port))
        asyncio.run(server.serve(), loop_factory=_selector_loop)
    else:
        uvicorn.run(app, host=host, port=port)
