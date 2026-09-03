from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from psycopg_pool import AsyncConnectionPool

from agents.primary.agent import build_primary_graph
from e2e_eval.auto_scorer import score_trace
from e2e_eval.human_export import export_review
from e2e_eval.json_util import dumps_json, to_json_safe
from e2e_eval.schema import E2ECase, WRITE_FINALIZE_ACTIONS, load_case
from e2e_eval.seed import e2e_user_prefix, seed_case_memories
from e2e_eval.teardown import delete_case_memories, teardown_case_run
from e2e_eval.trace_collector import TraceCollector
from infrastructure.postgres import open_postgres
from memory.commit import MemoryCommitAdapter
from memory.embeddings import MemoryEmbeddingService
from memory.verifier import build_memory_verifier
from memory.worker import MemoryWorker
from repositories.long_term_memory import PostgresLongTermMemoryRepository
from repositories.result_store import ResultStoreRepository
from services.long_term_memory import MemoryService
from settings import Settings, get_settings
from utils.tracing import with_trace_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports" / "e2e_runs"


def make_e2e_settings(**overrides: Any) -> Settings:
    """Mirror production recall: SQL candidate pool + applicability judge (no pgvector)."""
    base = get_settings()
    values = replace(
        base,
        long_term_memory_recall_enabled=True,
        long_term_memory_write_enabled=True,
        long_term_memory_sync_finalize=True,
        long_term_memory_vector_search_enabled=False,
        long_term_memory_applicability_judge_enabled=True,
    )
    if overrides:
        values = replace(values, **overrides)
    return values


def resolve_relative_dates(message: str, *, today: date | None = None) -> tuple[str, dict[str, str]]:
    current = today or date.today()
    resolved: dict[str, str] = {"today": current.isoformat()}

    if "thứ Hai" in message or "thu hai" in message.lower():
        days_ahead = (0 - current.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        monday = current + timedelta(days=days_ahead)
        resolved["next_monday"] = monday.isoformat()

    if "mai" in message.lower().split():
        tomorrow = current + timedelta(days=1)
        resolved["tomorrow"] = tomorrow.isoformat()

    if "cuối tuần này" in message.lower():
        days_to_saturday = (5 - current.weekday()) % 7
        saturday = current + timedelta(days=days_to_saturday or 7)
        sunday = saturday + timedelta(days=1)
        resolved["weekend_start"] = saturday.isoformat()
        resolved["weekend_end"] = sunday.isoformat()

    return message, resolved


def _coerce_update_chunk(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, dict):
        return chunk
    if isinstance(chunk, tuple) and chunk:
        data = chunk[-1]
        if not isinstance(data, dict):
            return {}
        if chunk[0] == "values":
            return {}
        if chunk[0] == "updates":
            return data
        return data
    return {}


def build_graph_turn_config(
    *,
    thread_id: str,
    user_id: str,
    case_id: str,
    e2e_run_id: str,
    turn: int,
    summarize_all: bool,
    collector: TraceCollector | None,
) -> dict[str, Any]:
    """Build invoke config for one chat turn.

    Do not put ``run_id`` in LangGraph metadata. Matching checkpoint
    ``metadata.run_id`` makes Pregel treat the call as a resume of the
    previous completed run, so later user messages are ignored.
    """
    configurable: dict[str, Any] = {
        "thread_id": thread_id,
        "user_id": user_id,
    }
    if collector is not None:
        configurable["e2e_trace_collector"] = collector
    if summarize_all:
        configurable["e2e_summarize_all"] = True
    return with_trace_config(
        {"configurable": configurable},
        run_name=f"e2e_{case_id}_turn_{turn}",
        tags=["e2e", case_id],
        metadata={
            "case_id": case_id,
            "e2e_run_id": e2e_run_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "turn": turn,
        },
    )


async def _invoke_chat_turn(
    graph: Any,
    *,
    message: str,
    user_id: str,
    thread_id: str,
    config: dict[str, Any],
    collector: TraceCollector,
    verbose: bool,
) -> tuple[dict[str, Any], list[str], str]:
    read_config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    snapshot = await graph.aget_state(read_config)
    prior_messages = list((snapshot.values or {}).get("messages") or [])
    old_count = len(prior_messages)
    prior_ids = {
        getattr(message_obj, "id", None)
        for message_obj in prior_messages
        if getattr(message_obj, "id", None)
    }
    invoke_input = {
        "messages": ("user", message),
        "user_id": user_id,
        "thread_id": thread_id,
    }

    nodes: list[str] = []
    streamed_answers: list[str] = []
    async for chunk in graph.astream(
        invoke_input,
        config,
        stream_mode="updates",
        durability="sync",
    ):
        for node_name, update in _coerce_update_chunk(chunk).items():
            if not node_name or str(node_name).startswith("__"):
                continue
            payload = update if isinstance(update, dict) else {}
            collector.record_node_update(node_name, payload)
            nodes.append(node_name)
            if node_name == "primary_assistant":
                text = TraceCollector.extract_final_ai_response(
                    list(payload.get("messages") or []),
                    since_index=0,
                )
                if text:
                    streamed_answers.append(text)
            if verbose:
                print(f"  -> {node_name}", flush=True)

    final = await graph.aget_state(read_config)
    final_state = dict(final.values or {})
    messages = final_state.get("messages") or []
    # Summarize may RemoveMessage and shrink the list — that is still a successful turn.
    if not nodes and len(messages) <= old_count:
        if verbose:
            print("  ! no graph progress; retrying ainvoke", flush=True)
        result = await graph.ainvoke(invoke_input, config, durability="sync")
        final_state = dict(result or {})
        messages = final_state.get("messages") or []

    new_messages = [
        item
        for item in messages
        if getattr(item, "id", None) not in prior_ids
    ]
    answer = TraceCollector.extract_final_ai_response(new_messages, since_index=0)
    if not answer and old_count <= len(messages):
        answer = TraceCollector.extract_final_ai_response(
            messages, since_index=old_count
        )
    if not answer and streamed_answers:
        answer = streamed_answers[-1]
    if not answer and "summarize_conversation" in nodes:
        answer = "(đã nén hội thoại vào STM)"
    return final_state, nodes, answer


def git_commit_hash() -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return output.strip()
    except Exception:
        return ""


@dataclass(frozen=True)
class RunResult:
    case_id: str
    run_id: str
    trace_path: Path
    trace: dict[str, Any]
    auto_scores: dict[str, Any]


async def _fetch_user_memories(
    pool: AsyncConnectionPool,
    *,
    user_prefix: str,
) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT memory_id::text, memory_text, source_thread_id, status,
                       category, domain, family, supersedes_memory_id::text
                FROM long_term_memories
                WHERE user_id LIKE %(user_prefix)s
                """,
                {"user_prefix": user_prefix},
            )
        ).fetchall()
    return [dict(row) for row in rows]


async def _count_new_memories(
    pool: AsyncConnectionPool,
    *,
    user_prefix: str,
    seeded_uuids: set[str],
) -> list[dict[str, Any]]:
    rows = await _fetch_user_memories(pool, user_prefix=user_prefix)
    return [row for row in rows if str(row["memory_id"]) not in seeded_uuids]


async def _fetch_memory_audits(
    pool: AsyncConnectionPool,
    *,
    thread_id: str,
) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT audit_id::text, job_id::text, decision,
                       proposed_transition, rule_result, verifier_result,
                       affected_memory_ids, created_at
                FROM memory_audit_records
                WHERE thread_id = %(thread_id)s
                ORDER BY created_at ASC
                """,
                {"thread_id": thread_id},
            )
        ).fetchall()
    return [dict(row) for row in rows]


async def _fetch_memory_job(
    pool: AsyncConnectionPool,
    *,
    thread_id: str,
) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """
                SELECT job_id, status, error_summary, created_at
                FROM memory_jobs
                WHERE thread_id = %(thread_id)s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                {"thread_id": thread_id},
            )
        ).fetchone()
    return dict(row) if row else None


async def run_case(
    case: E2ECase,
    *,
    settings: Settings | None = None,
    run_id: str | None = None,
    reports_dir: Path | None = None,
    verbose: bool = False,
    teardown: bool = True,
    fresh_seed: bool = False,
) -> RunResult:
    extra: dict[str, Any] = {}
    if (
        settings is None
        and case.expected_finalize.action in WRITE_FINALIZE_ACTIONS
    ):
        extra = {
            "long_term_memory_extractor": "langmem",
            "long_term_memory_transition_path": "llm",
            # Sync finalize should reach a terminal job status in one attempt.
            "long_term_memory_worker_retry_limit": 1,
        }
    active_settings = settings or make_e2e_settings(**extra)
    if not active_settings.database_url:
        raise RuntimeError("DATABASE_URL is required for E2E runs")

    active_run_id = run_id or uuid.uuid4().hex[:12]
    output_root = reports_dir or DEFAULT_REPORTS_DIR
    case_dir = output_root / case.id
    case_dir.mkdir(parents=True, exist_ok=True)
    trace_path = case_dir / f"{active_run_id}.json"

    async with open_postgres(active_settings) as postgres:
        pool = postgres.pool
        memory_repo = PostgresLongTermMemoryRepository(pool)
        embedding_service = MemoryEmbeddingService(settings=active_settings)
        memory_worker = MemoryWorker(
            pool=pool,
            settings=active_settings,
            repository=memory_repo,
            commit_adapter=MemoryCommitAdapter(
                repository=memory_repo,
                verifier=build_memory_verifier(active_settings),
                embedding_service=embedding_service,
            ),
            embedding_service=embedding_service,
        )
        memory_service = MemoryService(
            settings=active_settings,
            repository=memory_repo,
            embedding_service=embedding_service,
            processor=memory_worker,
        )
        result_store = ResultStoreRepository(pool)

        if fresh_seed:
            await delete_case_memories(pool, case.id)

        seed_result = await seed_case_memories(
            case,
            pool=pool,
            run_id=active_run_id,
            settings=active_settings,
        )

        graph = await build_primary_graph(
            checkpointer=postgres.checkpointer,
            repo=result_store,
            memory_service=memory_service,
        )

        collector = TraceCollector(
            case_id=case.id,
            run_id=active_run_id,
            user_id=seed_result.case_user_id,
            thread_id=seed_result.thread_id,
            fixture_to_uuid=seed_result.fixture_to_uuid,
            input_messages=case.input.messages,
            resolved_dates={},
            model=active_settings.long_term_memory_langmem_model,
            prompt_version=active_settings.long_term_memory_trustmem_prompt_version,
            git_commit=git_commit_hash(),
            postgres_persist=not teardown,
            teardown=teardown,
            fresh_seed=fresh_seed,
        )

        merged_dates: dict[str, str] = {}
        last_index = len(case.input.messages) - 1
        scored_turn_known_ids = set(seed_result.seeded_uuids)
        last_answer = ""
        final_state: dict[str, Any] = {}

        for index, raw_message in enumerate(case.input.messages):
            resolved_message, resolved_dates = resolve_relative_dates(raw_message)
            merged_dates.update(resolved_dates)
            collector.trace["input"]["resolved_dates"] = dict(merged_dates)

            is_last = index == last_index
            summarize_turn = (not is_last) and index == last_index - 1
            turn_number = index + 1

            if is_last and last_index > 0:
                collector.begin_scored_turn()
                existing = await _count_new_memories(
                    pool,
                    user_prefix=e2e_user_prefix(case.id),
                    seeded_uuids=seed_result.seeded_uuids,
                )
                scored_turn_known_ids = set(seed_result.seeded_uuids) | {
                    str(row["memory_id"]) for row in existing
                }

            config = build_graph_turn_config(
                thread_id=seed_result.thread_id,
                user_id=seed_result.case_user_id,
                case_id=case.id,
                e2e_run_id=active_run_id,
                turn=turn_number,
                summarize_all=summarize_turn,
                collector=collector,
            )

            if verbose:
                print(f"  turn {turn_number}/{last_index + 1}", flush=True)

            final_state, turn_nodes, last_answer = await _invoke_chat_turn(
                graph,
                message=resolved_message,
                user_id=seed_result.case_user_id,
                thread_id=seed_result.thread_id,
                config=config,
                collector=collector,
                verbose=verbose,
            )
            messages = final_state.get("messages") or []
            if summarize_turn and (
                "summarize_conversation" in turn_nodes or final_state.get("summary")
            ):
                collector.trace["stm"]["summarized_after_turn"] = turn_number
            collector.record_turn(
                turn=turn_number,
                user_message=resolved_message,
                answer=last_answer,
                summarize_forced=summarize_turn,
                scored=is_last,
                nodes=turn_nodes,
                message_count=len(messages),
            )

        trace = collector.finalize_trace(
            final_state=final_state,
            final_answer=last_answer,
            expected_finalize_action=case.expected_finalize.action.value,
        )

        await collector.enrich_tool_snapshots(result_store)
        trace = collector.trace

        all_memories = await _fetch_user_memories(
            pool,
            user_prefix=e2e_user_prefix(case.id),
        )
        uuid_to_fixture = {
            str(memory_id): fixture_id
            for fixture_id, memory_id in seed_result.fixture_to_uuid.items()
        }
        new_memories = [
            row
            for row in all_memories
            if str(row["memory_id"]) not in scored_turn_known_ids
        ]
        seeded_status = {
            uuid_to_fixture[str(row["memory_id"])]: {
                "status": row.get("status"),
                "memory_id": row.get("memory_id"),
                "memory_text": row.get("memory_text"),
                "supersedes_memory_id": row.get("supersedes_memory_id"),
            }
            for row in all_memories
            if str(row["memory_id"]) in uuid_to_fixture
        }
        trace["finalize"]["db_mutations"] = to_json_safe(new_memories)
        trace["finalize"]["seeded_status"] = to_json_safe(seeded_status)
        job = await _fetch_memory_job(pool, thread_id=seed_result.thread_id)
        if job:
            trace["finalize"]["memory_job"] = to_json_safe(job)
        audits = await _fetch_memory_audits(pool, thread_id=seed_result.thread_id)
        trace["finalize"]["audits"] = to_json_safe(audits)

        auto_scores = score_trace(case, trace)
        trace["auto_scores"] = auto_scores.model_dump(mode="json")
        trace = to_json_safe(trace)

        trace_path.write_text(
            dumps_json(trace, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        export_review(trace_path)

        if teardown:
            await teardown_case_run(
                pool,
                case_id=case.id,
                thread_id=seed_result.thread_id,
            )

        return RunResult(
            case_id=case.id,
            run_id=active_run_id,
            trace_path=trace_path,
            trace=trace,
            auto_scores=trace["auto_scores"],
        )


async def run_case_file(
    case_path: str | Path,
    **kwargs: Any,
) -> RunResult:
    case = load_case(case_path)
    return await run_case(case, **kwargs)
