import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import parse_qs

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from agents.primary.agent import build_primary_graph
from dependencies import get_primary_graph
from infrastructure.postgres import open_postgres
from repositories.result_store import ResultStoreRepository
from services.auth import (
    AuthRepository,
    AuthUser,
    DuplicateEmailError,
    InvalidCredentialsError,
    SESSION_COOKIE_NAME,
)
from settings import get_settings
from utils.tracing import with_trace_config

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

class ChatRequest(BaseModel):
    msg: str = Field(min_length=1)
    thread_id: str | None = None
    user_id: str | None = None

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with open_postgres(settings) as postgres:
        repo = ResultStoreRepository(postgres.pool)
        auth_repo = AuthRepository(postgres.pool)
        app.state.settings = settings
        app.state.database_pool = postgres.pool
        app.state.checkpointer = postgres.checkpointer
        app.state.result_store = repo
        app.state.auth_repo = auth_repo
        app.state.primary_graph = await build_primary_graph(
            checkpointer=postgres.checkpointer,
            repo=repo,
        )
        yield

app = FastAPI(title="Travel Customer Support Agent", lifespan=lifespan)

async def _form_data(request: Request) -> dict[str, str]:
    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}

def get_auth_repo(request: Request) -> AuthRepository:
    return request.app.state.auth_repo

async def get_current_user(
    request: Request,
    auth_repo: AuthRepository = Depends(get_auth_repo),
) -> AuthUser | None:
    return await auth_repo.resolve_session(request.cookies.get(SESSION_COOKIE_NAME))

def _cookie_max_age(expires_at) -> int:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))

def _set_session_cookie(
    response: RedirectResponse,
    *,
    token: str,
    settings,
    max_age: int,
) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )

@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    current_user: AuthUser | None = Depends(get_current_user),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context={"current_user": current_user},
    )

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None, "email": ""},
    )

@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    auth_repo: AuthRepository = Depends(get_auth_repo),
):
    form = await _form_data(request)
    email = form.get("email", "").strip()
    password = form.get("password", "")
    remember = "remember" in form
    try:
        user = await auth_repo.verify_credentials(email=email, password=password)
    except InvalidCredentialsError:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Email hoặc mật khẩu không đúng.",
                "email": email,
            },
            status_code=400,
        )

    session = await auth_repo.create_session(
        user_id=user.user_id,
        remember=remember,
    )
    response = RedirectResponse(url="/", status_code=303)
    _set_session_cookie(
        response,
        token=session.token,
        settings=request.app.state.settings,
        max_age=_cookie_max_age(session.expires_at),
    )
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"error": None, "full_name": "", "email": ""},
    )

@app.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    auth_repo: AuthRepository = Depends(get_auth_repo),
):
    form = await _form_data(request)
    full_name = form.get("full_name", "").strip()
    email = form.get("email", "").strip()
    password = form.get("password", "")
    confirm_password = form.get("confirm_password", "")
    context = {"full_name": full_name, "email": email}

    if not full_name or not email or not password:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={**context, "error": "Vui lòng nhập đầy đủ thông tin."},
            status_code=400,
        )
    if password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={**context, "error": "Mật khẩu xác nhận không khớp."},
            status_code=400,
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={**context, "error": "Mật khẩu cần ít nhất 8 ký tự."},
            status_code=400,
        )

    try:
        user = await auth_repo.create_user(
            email=email,
            full_name=full_name,
            password=password,
        )
    except DuplicateEmailError:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={**context, "error": "Email này đã được đăng ký."},
            status_code=400,
        )

    session = await auth_repo.create_session(user_id=user.user_id, remember=False)
    response = RedirectResponse(url="/", status_code=303)
    _set_session_cookie(
        response,
        token=session.token,
        settings=request.app.state.settings,
        max_age=_cookie_max_age(session.expires_at),
    )
    return response

@app.post("/logout")
async def logout(
    request: Request,
    auth_repo: AuthRepository = Depends(get_auth_repo),
):
    await auth_repo.revoke_session(request.cookies.get(SESSION_COOKIE_NAME))
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response

@app.post("/chat")
async def chat(
    payload: ChatRequest,
    primary_graph=Depends(get_primary_graph),
    current_user: AuthUser | None = Depends(get_current_user),
) -> dict[str, str]:
    thread_id = payload.thread_id or str(uuid.uuid4())
    user_id = current_user.user_id if current_user else (payload.user_id or "dev-user")
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
    old_count = len(snapshot.values.get("messages", [])) if snapshot.values else 0

    result = await primary_graph.ainvoke(
        {
            "messages": ("user", payload.msg),
            "user_id": user_id,
            "thread_id": thread_id,
        },
        config,
    )

    new_messages = result["messages"][old_count:]
    ai_responses = []
    for msg in new_messages:
        if msg.type in ("ai", "assistant") and msg.content:
            if "Proceeding with the next requested task" not in msg.content:
                ai_responses.append(msg.content)

    response = (
        "\n\n".join(ai_responses)
        if ai_responses
        else "Sorry, I couldn't get a response."
    )
    return {"response": response, "thread_id": thread_id, "user_id": user_id}

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=5000, reload=True)
