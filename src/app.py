import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from agents.primary.agent import build_primary_graph
from dependencies import get_primary_graph
from infrastructure.postgres import open_postgres
from repositories.long_term_memory import PostgresLongTermMemoryRepository
from repositories.result_store import ResultStoreRepository
from services.long_term_memory import MemoryService
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
        memory_repo = PostgresLongTermMemoryRepository(postgres.pool)
        memory_service = MemoryService(settings=settings, repository=memory_repo)
        app.state.settings = settings
        app.state.database_pool = postgres.pool
        app.state.checkpointer = postgres.checkpointer
        app.state.result_store = repo
        app.state.long_term_memory = memory_service
        app.state.primary_graph = await build_primary_graph(
            checkpointer=postgres.checkpointer,
            repo=repo,
            memory_service=memory_service,
        )
        yield


app = FastAPI(title="Travel Customer Support Agent", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="chat.html")


@app.get("/debug/memory/jobs")
async def debug_memory_jobs(request: Request) -> list[dict]:
    settings = request.app.state.settings
    if not settings.long_term_memory_debug_enabled:
        raise HTTPException(status_code=404, detail="Not found")
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
async def debug_memory_audit(request: Request) -> list[dict]:
    settings = request.app.state.settings
    if not settings.long_term_memory_debug_enabled:
        raise HTTPException(status_code=404, detail="Not found")
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


@app.post("/chat")
async def chat(
    payload: ChatRequest,
    primary_graph=Depends(get_primary_graph),
) -> dict[str, str]:
    thread_id = payload.thread_id or str(uuid.uuid4())
    user_id = payload.user_id or "dev-user"
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
