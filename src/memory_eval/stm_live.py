"""Live short-term memory evaluation: run primary graph (Gemini) then score STM metrics.

Requires GOOGLE_API_KEY or GEMINI_API_KEY. Outside default CI — use:

    python -m memory_eval_cli --suite stm-live --split development
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from e2e_eval.runner import (
    _invoke_chat_turn,
    build_graph_turn_config,
    make_e2e_settings,
    resolve_relative_dates,
)
from e2e_eval.schema import SeedMemory
from e2e_eval.seed import (
    seed_case_memories,
)
from e2e_eval.teardown import delete_case_memories, teardown_case_run
from e2e_eval.trace_collector import TraceCollector
from infrastructure.postgres import open_postgres
from memory.commit import MemoryCommitAdapter
from memory.embeddings import MemoryEmbeddingService
from memory.verifier import build_memory_verifier
from memory.worker import MemoryWorker
from memory.normalize import TOOL_DOMAIN
from memory_eval.short_term import (
    SuiteReport,
    constraint_values_match,
    evaluate_factual_recall_rows,
    evaluate_reference_rows,
    evaluate_success_rows,
)
from memory_eval.stm_live_schema import (
    DEFAULT_FIXTURE_DIR,
    StmLiveCase,
    load_cases_from_dir,
)
from repositories.long_term_memory import PostgresLongTermMemoryRepository
from repositories.result_store import ResultStoreRepository
from services.long_term_memory import MemoryService
from settings import Settings, get_settings
from agents.primary.agent import build_primary_graph
from e2e_eval.schema import CaseSeed, E2ECase, ThreadStateSeed
from e2e_eval.schema import CaseInput, ExpectedAnswerRubric, ExpectedTrace

# Map constraint keys used in fixtures onto Result Store / MCP query argument names.
_SUCCESS_KEY_ALIASES: dict[str, list[str]] = {
    "destination": ["destination", "location", "arrival_airport", "to"],
    "location": ["location", "destination", "address"],
    "check_in": ["check_in", "checkin_date"],
    "check_out": ["check_out", "checkout_date"],
    "guests": ["guests", "adults", "num_guests", "people"],
    "origin": ["origin", "departure_airport", "from"],
    "date": [
        "date",
        "start_date",
        "departure_date",
        "depart_date",
        "check_in",
        "checkin_date",
        "start_ms",
        "end_ms",
    ],
    "dropoff": [
        "dropoff",
        "drop_off",
        "destination",
        "location",
        "address",
        "user_needs",
    ],
    "pickup": ["pickup", "pickup_location", "location", "address", "user_needs"],
}


def require_gemini_api_key() -> str:
    key = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "STM live requires GOOGLE_API_KEY or GEMINI_API_KEY; "
            "refusing to run without a Gemini API key."
        )
    return key


def _stm_case_as_e2e_shell(case: StmLiveCase) -> E2ECase:
    """Minimal E2ECase shell so seed_case_memories can insert optional LTM rows."""
    memories = [SeedMemory.model_validate(item) for item in case.long_term_memories]
    return E2ECase(
        id=case.id,
        scenario=case.scenario,
        seed=CaseSeed(
            user_id=case.user_id,
            long_term_memories=memories,
            thread_state=ThreadStateSeed(),
        ),
        input=CaseInput(messages=case.messages, force_summarize_penultimate=False),
        expected_trace=ExpectedTrace(expected_route=[]),
        expected_answer_rubric=ExpectedAnswerRubric(),
    )


def _structured_state(final_state: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "requests",
        "request_results",
        "visible_results",
        "selected_items",
        "active_request_id",
        "latest_request_by_domain",
        "summary",
    )
    return {key: final_state.get(key) for key in keys if key in final_state}


def _infer_success_domain(case: StmLiveCase, state: dict[str, Any]) -> str | None:
    if case.success_domain:
        return case.success_domain
    latest = state.get("latest_request_by_domain") or {}
    if len(latest) == 1:
        return next(iter(latest))
    requests = state.get("requests") or {}
    if len(requests) == 1:
        only_payload = next(iter(requests.values()))
        if isinstance(only_payload, dict) and only_payload.get("domain"):
            return str(only_payload["domain"])
    for domain in ("hotel", "flight", "car", "excursion"):
        if domain in latest:
            return domain
    return None


def _tool_domain(entry: dict[str, Any]) -> str:
    domain = str(entry.get("domain") or "")
    if domain == "tour":
        return "excursion"
    if domain:
        return domain
    name = str(entry.get("name") or "")
    mapped = TOOL_DOMAIN.get(name, "")
    return "excursion" if mapped == "tour" else mapped


def _extract_search_arguments(
    tools: list[dict[str, Any]],
    *,
    domain: str | None,
) -> dict[str, Any]:
    """Return arguments from the latest search tool matching domain (if set)."""
    chosen: dict[str, Any] | None = None
    for entry in tools:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        entry_domain = _tool_domain(entry)
        if domain and entry_domain and entry_domain != domain:
            continue
        if name and name not in TOOL_DOMAIN and not entry.get("arguments"):
            continue
        if entry_domain or name in TOOL_DOMAIN:
            chosen = entry
    if not chosen:
        return {}
    arguments = chosen.get("arguments") or {}
    return dict(arguments) if isinstance(arguments, dict) else {}


def _lookup_constraint_value(
    arguments: dict[str, Any],
    key: str,
    *,
    expected: Any | None = None,
) -> Any:
    candidates: list[str] = []
    for candidate in [key, *_SUCCESS_KEY_ALIASES.get(key, [])]:
        if candidate not in candidates:
            candidates.append(candidate)
    fallback: Any | None = None
    for candidate in candidates:
        value = arguments.get(candidate)
        if value is None or str(value).strip() == "":
            continue
        if expected is not None and constraint_values_match(value, expected):
            return value
        if fallback is None:
            fallback = value
    return fallback


def _final_action_from_observation(
    case: StmLiveCase,
    observation: "LiveCaseObservation",
) -> dict[str, Any]:
    """Build success final_action from enriched search tool / Result Store query args."""
    arguments = dict(observation.search_arguments or {})
    action: dict[str, Any] = {}
    for key, expected in (case.constraints or {}).items():
        value = _lookup_constraint_value(arguments, key, expected=expected)
        if value is not None:
            action[key] = value
    domain = case.success_domain or _infer_success_domain(case, observation.final_state)
    selected = observation.final_state.get("selected_items") or {}
    if domain and isinstance(selected.get(domain), dict):
        item_id = selected[domain].get("item_id")
        if item_id is not None:
            action["selected"] = item_id
    return action


@dataclass
class LiveCaseObservation:
    case_id: str
    metrics: list[str]
    final_state: dict[str, Any] = field(default_factory=dict)
    probe_answer: str = ""
    search_arguments: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class LiveCaseRunResult:
    observation: LiveCaseObservation
    scored: dict[str, Any] = field(default_factory=dict)


async def run_live_case(
    case: StmLiveCase,
    *,
    settings: Settings | None = None,
    run_id: str | None = None,
    verbose: bool = False,
    teardown: bool = True,
    model: str | None = None,
) -> LiveCaseObservation:
    require_gemini_api_key()
    active_settings = settings or make_e2e_settings(
        long_term_memory_recall_enabled=bool(case.long_term_memories),
        long_term_memory_write_enabled=False,
        long_term_memory_sync_finalize=False,
    )
    if model:
        active_settings = replace(
            active_settings, long_term_memory_langmem_model=model
        )
    if not active_settings.database_url:
        raise RuntimeError("DATABASE_URL is required for STM live runs")

    active_run_id = run_id or uuid.uuid4().hex[:12]
    e2e_shell = _stm_case_as_e2e_shell(case)

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

        seed_result = await seed_case_memories(
            e2e_shell,
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
            input_messages=case.messages,
            resolved_dates={},
            model=model or active_settings.long_term_memory_langmem_model,
            prompt_version=active_settings.long_term_memory_trustmem_prompt_version,
            git_commit="",
            postgres_persist=not teardown,
            teardown=teardown,
            fresh_seed=False,
        )

        final_state: dict[str, Any] = {}
        last_answer = ""
        last_index = len(case.messages) - 1
        probe_answer = ""

        try:
            for index, raw_message in enumerate(case.messages):
                resolved_message, _ = resolve_relative_dates(raw_message)
                is_last = index == last_index
                summarize_turn = (
                    bool(case.force_summarize_penultimate)
                    and (not is_last)
                    and index == last_index - 1
                )
                config = build_graph_turn_config(
                    thread_id=seed_result.thread_id,
                    user_id=seed_result.case_user_id,
                    case_id=case.id,
                    e2e_run_id=active_run_id,
                    turn=index + 1,
                    summarize_all=summarize_turn,
                    collector=collector,
                )
                if verbose:
                    print(f"  [{case.id}] turn {index + 1}/{last_index + 1}", flush=True)
                final_state, _nodes, last_answer = await _invoke_chat_turn(
                    graph,
                    message=resolved_message,
                    user_id=seed_result.case_user_id,
                    thread_id=seed_result.thread_id,
                    config=config,
                    collector=collector,
                    verbose=verbose,
                )

            if case.probe:
                if case.force_summarize_penultimate and not final_state.get("summary"):
                    # Ensure summary path ran for after-summary probes when only one msg.
                    pass
                config = build_graph_turn_config(
                    thread_id=seed_result.thread_id,
                    user_id=seed_result.case_user_id,
                    case_id=case.id,
                    e2e_run_id=active_run_id,
                    turn=last_index + 2,
                    summarize_all=False,
                    collector=collector,
                )
                if verbose:
                    print(f"  [{case.id}] probe", flush=True)
                final_state, _nodes, probe_answer = await _invoke_chat_turn(
                    graph,
                    message=case.probe,
                    user_id=seed_result.case_user_id,
                    thread_id=seed_result.thread_id,
                    config=config,
                    collector=collector,
                    verbose=verbose,
                )

            if case.reference and case.reference.seed_visible_state:
                read_config = {
                    "configurable": {
                        "thread_id": seed_result.thread_id,
                        "user_id": seed_result.case_user_id,
                    }
                }
                await graph.aupdate_state(
                    read_config,
                    case.reference.seed_visible_state,
                )
                snapshot = await graph.aget_state(read_config)
                final_state = dict(snapshot.values or {})

            structured = _structured_state(final_state)
            search_arguments: dict[str, Any] = {}
            if "success" in case.metrics:
                collector.finalize_trace(
                    final_state=final_state,
                    final_answer=probe_answer or last_answer,
                )
                await collector.enrich_tool_snapshots(result_store)
                search_arguments = _extract_search_arguments(
                    list(collector.trace.get("tools") or []),
                    domain=_infer_success_domain(case, structured),
                )

            return LiveCaseObservation(
                case_id=case.id,
                metrics=list(case.metrics),
                final_state=structured,
                probe_answer=probe_answer or last_answer,
                search_arguments=search_arguments,
            )
        except Exception as exc:  # noqa: BLE001 — surface per-case failure in report
            return LiveCaseObservation(
                case_id=case.id,
                metrics=list(case.metrics),
                final_state=_structured_state(final_state),
                probe_answer=probe_answer,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if teardown:
                await teardown_case_run(
                    pool,
                    case_id=case.id,
                    thread_id=seed_result.thread_id,
                )
                await delete_case_memories(pool, case.id)


def observation_to_score_rows(
    case: StmLiveCase,
    observation: LiveCaseObservation,
) -> dict[str, list[dict[str, Any]]]:
    """Map one live observation into offline scorer row shapes."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "reference": [],
        "factual_recall": [],
        "success": [],
    }
    if observation.error:
        return buckets

    state = observation.final_state
    if "reference" in case.metrics and case.reference is not None:
        ref_state = state
        if case.reference.seed_visible_state:
            # Prefer injected visible results for deterministic gold.
            ref_state = {
                **state,
                **{
                    key: value
                    for key, value in case.reference.seed_visible_state.items()
                    if key
                    in {
                        "visible_results",
                        "active_request_id",
                        "latest_request_by_domain",
                    }
                },
            }
        buckets["reference"].append(
            {
                "case_id": case.id,
                "state": ref_state,
                "args": case.reference.args,
                "gold": case.reference.gold,
            }
        )
    if "factual_recall" in case.metrics:
        buckets["factual_recall"].append(
            {
                "case_id": case.id,
                "predicted_answer": observation.probe_answer,
                "gold_answer": case.gold_answer,
                "position": case.position or "unknown",
                "phase": case.phase or "unknown",
            }
        )
    if "success" in case.metrics and case.constraints:
        buckets["success"].append(
            {
                "case_id": case.id,
                "final_action": _final_action_from_observation(case, observation),
                "constraints": case.constraints,
            }
        )
    return buckets


def score_observations(
    cases: list[StmLiveCase],
    observations: list[LiveCaseObservation],
) -> dict[str, Any]:
    by_id = {obs.case_id: obs for obs in observations}
    reference_rows: list[dict[str, Any]] = []
    factual_rows: list[dict[str, Any]] = []
    success_rows: list[dict[str, Any]] = []
    case_details: list[dict[str, Any]] = []

    for case in cases:
        obs = by_id.get(case.id) or LiveCaseObservation(
            case_id=case.id,
            metrics=list(case.metrics),
            error="missing observation",
        )
        buckets = observation_to_score_rows(case, obs)
        reference_rows.extend(buckets["reference"])
        factual_rows.extend(buckets["factual_recall"])
        success_rows.extend(buckets["success"])
        case_details.append(
            {
                "case_id": case.id,
                "split": case.split,
                "metrics": list(case.metrics),
                "error": obs.error,
                "probe_answer": obs.probe_answer if "factual_recall" in case.metrics else None,
                "search_arguments": (
                    obs.search_arguments if "success" in case.metrics else None
                ),
            }
        )

    empty = SuiteReport(suite="empty", metrics={})
    reference_report = (
        evaluate_reference_rows(reference_rows) if reference_rows else empty
    )
    factual_report = (
        evaluate_factual_recall_rows(factual_rows) if factual_rows else empty
    )
    success_report = evaluate_success_rows(success_rows) if success_rows else empty

    combined = {
        **reference_report.metrics,
        **factual_report.metrics,
        **success_report.metrics,
    }
    return {
        "metrics": {name: metric.to_dict() for name, metric in combined.items()},
        "reference": reference_report.to_dict() if reference_rows else None,
        "factual_recall": factual_report.to_dict() if factual_rows else None,
        "success": success_report.to_dict() if success_rows else None,
        "cases": case_details,
        "errors": [c for c in case_details if c.get("error")],
    }


async def evaluate_stm_live(
    *,
    fixtures: str | Path | None = None,
    split: str = "all",
    verbose: bool = False,
    teardown: bool = True,
    model: str | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    require_gemini_api_key()
    root = Path(fixtures or DEFAULT_FIXTURE_DIR)
    cases = load_cases_from_dir(root, split=split)
    if case_id:
        cases = [case for case in cases if case.id == case_id]
        if not cases:
            raise ValueError(f"no STM live case id={case_id!r}")

    settings = make_e2e_settings(
        long_term_memory_write_enabled=False,
        long_term_memory_sync_finalize=False,
    )
    observations: list[LiveCaseObservation] = []
    for case in cases:
        if verbose:
            print(f"Running {case.id} ({case.split})", flush=True)
        obs = await run_live_case(
            case,
            settings=settings,
            verbose=verbose,
            teardown=teardown,
            model=model,
        )
        observations.append(obs)

    report = score_observations(cases, observations)
    return {
        "suite": "stm-live",
        "gold_path": str(root),
        "split": split,
        "case_count": len(cases),
        "model": model or get_settings().long_term_memory_langmem_model,
        "report": report,
    }


def score_stm_live_from_observations(
    cases: list[StmLiveCase],
    observations: list[LiveCaseObservation],
    *,
    fixtures: str | Path | None = None,
    split: str = "all",
) -> dict[str, Any]:
    """Score without running Gemini — used by unit tests with mocked observations."""
    report = score_observations(cases, observations)
    return {
        "suite": "stm-live",
        "gold_path": str(fixtures or DEFAULT_FIXTURE_DIR),
        "split": split,
        "case_count": len(cases),
        "report": report,
    }
