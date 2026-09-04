from __future__ import annotations

from typing import Any

from e2e_eval.schema import (
    AutoScores,
    E2ECase,
    ExpectedFinalizeMemory,
    FinalizeAction,
    MetricScore,
    ScoreStatus,
)

APPLY_LABELS = {"apply", "overridden", "uncertain"}

# Canonical E2E argument names -> MCP / Result Store query keys.
_ARGUMENT_ALIASES: dict[str, list[str]] = {
    "destination": ["destination", "location"],
    "location": ["location", "address", "destination"],
    "check_in": ["check_in", "checkin_date"],
    "check_out": ["check_out", "checkout_date"],
    "pickup_date": ["pickup_date", "start_ms", "pickup_ms"],
    "return_date": ["return_date", "end_ms", "return_ms"],
    "departure_date": ["departure_date", "depart_date"],
    "date": ["date", "start_date", "end_date"],
    "origin": ["origin", "departure_airport", "from"],
    "adults": ["adults", "guests", "num_guests", "people"],
}

NOOP_REASON_ALIASES = {
    "exact_duplicate",
    "relation_equivalent",
    "duplicate_active_memory",
}


def _argument_value(arguments: dict[str, Any], key: str) -> Any:
    candidates = [key, *_ARGUMENT_ALIASES.get(key, [])]
    for candidate in candidates:
        value = arguments.get(candidate)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _pass(detail: str = "", **evidence: Any) -> MetricScore:
    return MetricScore(status=ScoreStatus.PASS, detail=detail, evidence=evidence)


def _fail(detail: str = "", **evidence: Any) -> MetricScore:
    return MetricScore(status=ScoreStatus.FAIL, detail=detail, evidence=evidence)


def _skip(detail: str = "") -> MetricScore:
    return MetricScore(status=ScoreStatus.SKIP, detail=detail)


def score_routing(case: E2ECase, trace: dict[str, Any]) -> MetricScore:
    expected = set(case.expected_trace.expected_route)
    actual = set(trace.get("primary_route", {}).get("delegated_domains") or [])
    if expected == actual:
        return _pass("delegated domains match", expected=sorted(expected), actual=sorted(actual))
    return _fail(
        "delegated domains mismatch",
        expected=sorted(expected),
        actual=sorted(actual),
    )


def score_tools(case: E2ECase, trace: dict[str, Any]) -> MetricScore:
    if not case.expected_trace.expected_tools:
        return _skip("no expected tools")
    tool_entries = trace.get("tools") or []
    failures: list[str] = []
    for rule in case.expected_trace.expected_tools:
        matches = [entry for entry in tool_entries if entry.get("name") == rule.name]
        if not matches:
            failures.append(f"missing tool {rule.name}")
            continue
        chosen = matches[-1]
        for entry in reversed(matches):
            arguments = entry.get("arguments") or {}
            if all(
                _argument_value(arguments, key) is not None
                for key in rule.required_arguments
            ):
                chosen = entry
                break
        arguments = chosen.get("arguments") or {}
        for key in rule.required_arguments:
            value = _argument_value(arguments, key)
            if value is None:
                failures.append(f"{rule.name} missing argument {key}")
        for entry in matches:
            arguments = entry.get("arguments") or {}
            for key in rule.forbidden_arguments:
                value = _argument_value(arguments, key)
                if value is not None and str(value).strip() != "":
                    failures.append(f"{rule.name} has forbidden argument {key}")
            blob = _arguments_blob(arguments)
            for needle in rule.forbidden_value_substrings:
                if needle.strip() and needle.lower() in blob:
                    failures.append(
                        f"{rule.name} argument values contain forbidden substring {needle!r}"
                    )
    if failures:
        return _fail("; ".join(failures), tools=tool_entries)
    return _pass("all expected tools called with required arguments")


def score_context(case: E2ECase, trace: dict[str, Any]) -> MetricScore:
    failures: list[str] = []
    for domain, rule in case.expected_trace.expected_context.items():
        recall = (trace.get("domain_recall") or {}).get(domain) or {}
        final_ids = set(recall.get("final_context_ids") or [])
        applicability = recall.get("applicability") or {}

        for fixture_id in rule.must_include:
            if fixture_id not in final_ids and fixture_id not in applicability:
                failures.append(f"{domain}: missing must_include {fixture_id}")
            elif fixture_id in applicability:
                label = str(applicability[fixture_id]).lower()
                if label not in APPLY_LABELS and fixture_id not in final_ids:
                    failures.append(
                        f"{domain}: {fixture_id} label={label} not in context"
                    )

        global_context = (trace.get("global_recall") or {}).get("recalled_fixture_ids") or []
        for fixture_id in rule.must_exclude:
            if fixture_id in final_ids or fixture_id in applicability:
                failures.append(f"{domain}: leaked excluded {fixture_id}")
            if fixture_id in global_context:
                failures.append(f"global: leaked excluded {fixture_id}")

    if failures:
        return _fail("; ".join(failures), domain_recall=trace.get("domain_recall"))
    return _pass("context recall/precision satisfied")


def score_leakage(case: E2ECase, trace: dict[str, Any]) -> MetricScore:
    failures: list[str] = []
    global_ids = set((trace.get("global_recall") or {}).get("recalled_fixture_ids") or [])
    for domain, rule in case.expected_trace.expected_context.items():
        recall = (trace.get("domain_recall") or {}).get(domain) or {}
        seen = set(recall.get("candidate_pool_ids") or [])
        seen.update(recall.get("final_context_ids") or [])
        for fixture_id in rule.must_exclude:
            if fixture_id in seen:
                failures.append(f"{domain}: excluded memory {fixture_id} in recall pool")
            if fixture_id in global_ids:
                failures.append(f"global: excluded memory {fixture_id} recalled")
    if failures:
        return _fail("; ".join(failures))
    return _pass("no cross-user/inactive leakage detected")


def _arguments_blob(arguments: dict[str, Any]) -> str:
    parts = [str(key) for key in arguments]
    parts.extend(str(value) for value in arguments.values())
    return " ".join(parts).lower()


def _fixture_to_uuid(trace: dict[str, Any]) -> dict[str, str]:
    mapping = (trace.get("metadata") or {}).get("fixture_to_uuid") or {}
    return {str(key): str(value) for key, value in mapping.items()}


def _job_status(finalize: dict[str, Any]) -> str:
    job = finalize.get("memory_job") or {}
    return str(job.get("status") or "").lower()


def _flatten_reason_tokens(audit: dict[str, Any]) -> set[str]:
    tokens: list[str] = []
    for blob in (
        (audit.get("proposed_transition") or {}).get("reasons"),
        (audit.get("rule_result") or {}).get("reasons"),
        (audit.get("verifier_result") or {}).get("reasons"),
    ):
        if isinstance(blob, list):
            tokens.extend(str(item) for item in blob)
        elif blob:
            tokens.append(str(blob))
    return {item.lower() for item in tokens}


def _affected_ids(audit: dict[str, Any]) -> set[str]:
    raw = audit.get("affected_memory_ids") or []
    if isinstance(raw, list):
        return {str(item) for item in raw if item is not None}
    return {str(raw)}


def _memory_matches_expected(
    row: dict[str, Any],
    expected: ExpectedFinalizeMemory,
    *,
    fixture_uuids: dict[str, str],
) -> bool:
    text = str(row.get("memory_text") or "").lower()
    if expected.text_contains:
        if any(token.lower() not in text for token in expected.text_contains):
            return False
    if expected.domain and str(row.get("domain") or "").lower() != expected.domain.lower():
        return False
    if expected.category and str(row.get("category") or "").lower() != expected.category.lower():
        return False
    if expected.family and str(row.get("family") or "").lower() != expected.family.lower():
        return False
    if expected.supersedes_fixture_id:
        expected_uuid = fixture_uuids.get(expected.supersedes_fixture_id)
        actual = str(row.get("supersedes_memory_id") or "")
        if not expected_uuid or actual != expected_uuid:
            return False
    return True


def _match_expected_memories(
    new_memories: list[dict[str, Any]],
    expected_memories: list[ExpectedFinalizeMemory],
    *,
    fixture_uuids: dict[str, str],
) -> list[str]:
    failures: list[str] = []
    unused = list(new_memories)
    for index, expected in enumerate(expected_memories):
        match_idx = next(
            (
                idx
                for idx, row in enumerate(unused)
                if _memory_matches_expected(row, expected, fixture_uuids=fixture_uuids)
            ),
            None,
        )
        if match_idx is None:
            failures.append(
                f"expected memory {index} not found "
                f"(domain={expected.domain} category={expected.category} "
                f"text_contains={expected.text_contains})"
            )
            continue
        unused.pop(match_idx)
    if unused:
        extras = [str(row.get("memory_text") or row.get("memory_id")) for row in unused]
        failures.append(f"unexpected extra memory inserts: {extras}")
    return failures


def score_finalize(case: E2ECase, trace: dict[str, Any]) -> MetricScore:
    action = case.expected_finalize.action
    finalize = trace.get("finalize") or {}
    new_memories = list(finalize.get("db_mutations") or [])
    audits = list(finalize.get("audits") or [])
    seeded_status = finalize.get("seeded_status") or {}
    fixture_uuids = _fixture_to_uuid(trace)
    job_status = _job_status(finalize)
    expected_memories = case.expected_finalize.memories

    if action == FinalizeAction.NO_STORE:
        if new_memories:
            return _fail(
                "unexpected memory inserts",
                new_memories=new_memories,
            )
        return _pass("no new long-term memories stored")

    if action == FinalizeAction.STORE:
        if not new_memories:
            return _fail("expected memory store but no inserts detected")
        return _pass("new memories stored", count=len(new_memories))

    if job_status == "skipped":
        return _fail(
            "memory job skipped (no candidates extracted)",
            job_status=job_status,
            new_memories=new_memories,
        )
    if job_status and job_status not in {"completed", ""}:
        return _fail(
            f"memory job status {job_status}",
            job_status=job_status,
            new_memories=new_memories,
        )

    if action == FinalizeAction.NOOP:
        if new_memories:
            return _fail(
                "NOOP expected but new memories were inserted",
                new_memories=new_memories,
            )
        noop_audits = [
            item for item in audits if str(item.get("decision") or "").lower() == "noop"
        ]
        if not noop_audits:
            return _fail(
                "NOOP expected but no audit decision=noop (job must complete, not skip)",
                job_status=job_status,
                audits=audits,
            )
        failures: list[str] = []
        for expected in expected_memories:
            existing_id = expected.existing_fixture_id
            existing_uuid = fixture_uuids.get(existing_id) if existing_id else None
            matched = False
            for audit in noop_audits:
                affected = _affected_ids(audit)
                proposed = audit.get("proposed_transition") or {}
                existing_memory_id = str(proposed.get("existing_memory_id") or "")
                id_ok = True
                if existing_uuid:
                    id_ok = existing_uuid in affected or existing_memory_id == existing_uuid
                if not id_ok:
                    continue
                reasons = _flatten_reason_tokens(audit)
                wanted = {
                    token.lower() for token in (expected.reasons_any or NOOP_REASON_ALIASES)
                }
                if wanted and reasons.isdisjoint(wanted) and expected.reasons_any:
                    continue
                matched = True
                break
            if existing_id and not matched:
                failures.append(
                    f"NOOP audit did not affect {existing_id} with expected reasons"
                )
        if failures:
            return _fail("; ".join(failures), audits=audits, job_status=job_status)
        return _pass("duplicate active memory NOOP", job_status=job_status)

    if action == FinalizeAction.INSERT:
        if not new_memories:
            return _fail("expected INSERT but no new memories stored", job_status=job_status)
        superseded = [
            row
            for row in new_memories
            if row.get("supersedes_memory_id")
        ]
        if superseded:
            return _fail(
                "INSERT expected but rows supersede existing memories",
                new_memories=new_memories,
            )
        if expected_memories:
            failures = _match_expected_memories(
                new_memories,
                expected_memories,
                fixture_uuids=fixture_uuids,
            )
            if failures:
                return _fail("; ".join(failures), new_memories=new_memories)
        return _pass("new memories inserted", count=len(new_memories))

    if action == FinalizeAction.SUPERSEDE:
        if not new_memories:
            return _fail("expected SUPERSEDE but no new memories stored", job_status=job_status)
        if expected_memories:
            for expected in expected_memories:
                fixture_id = expected.supersedes_fixture_id
                if not fixture_id:
                    continue
                status = str(
                    (seeded_status.get(fixture_id) or {}).get("status") or ""
                ).lower()
                if status != "superseded":
                    return _fail(
                        f"{fixture_id} status={status or 'missing'} expected superseded",
                        seeded_status=seeded_status,
                        new_memories=new_memories,
                    )
            failures = _match_expected_memories(
                new_memories,
                expected_memories,
                fixture_uuids=fixture_uuids,
            )
            if failures:
                return _fail("; ".join(failures), new_memories=new_memories)
        return _pass("memory superseded", count=len(new_memories))

    return _skip(f"unsupported finalize action {action}")


def score_applicability(case: E2ECase, trace: dict[str, Any]) -> MetricScore:
    expected_by_domain: dict[str, dict[str, str]] = {}
    for domain, rule in case.expected_trace.expected_context.items():
        if rule.expected_applicability:
            expected_by_domain[domain] = {
                key: value.lower()
                for key, value in rule.expected_applicability.items()
            }
    if not expected_by_domain:
        return _skip("no expected_applicability")

    failures: list[str] = []
    for domain, expected in expected_by_domain.items():
        recall = (trace.get("domain_recall") or {}).get(domain) or {}
        actual = {
            str(key): str(value).lower()
            for key, value in (recall.get("applicability") or {}).items()
        }
        for fixture_id, expected_label in expected.items():
            actual_label = actual.get(fixture_id)
            if actual_label != expected_label:
                failures.append(
                    f"{domain}: {fixture_id} expected={expected_label} actual={actual_label}"
                )
    if failures:
        return _fail("; ".join(failures), domain_recall=trace.get("domain_recall"))
    return _pass("applicability labels match")


def _execution_node_names(trace: dict[str, Any]) -> list[str]:
    path = trace.get("execution_path") or []
    if path:
        names: list[str] = []
        for step in path:
            node = str(step.get("node") or "")
            if node:
                names.append(node)
            for tool in step.get("tools") or []:
                tool_name = str(tool.get("name") or "")
                if tool_name:
                    names.append(tool_name)
                for sub_step in tool.get("sub_steps") or []:
                    names.append(str(sub_step))
        return names
    return list((trace.get("primary_route") or {}).get("node_updates") or [])


def _ordered_subsequence(path: list[str], required: list[str]) -> bool:
    if not required:
        return True
    index = 0
    for node in path:
        if node == required[index]:
            index += 1
            if index == len(required):
                return True
    return False


def score_execution_path(case: E2ECase, trace: dict[str, Any]) -> MetricScore:
    required = case.expected_trace.expected_node_sequence_contains
    if not required:
        return _skip("no expected execution path")
    visited = _execution_node_names(trace)
    if _ordered_subsequence(visited, required):
        return _pass("execution path satisfied", visited=visited, required=required)
    missing = [node for node in required if node not in set(visited)]
    return _fail(
        "execution path missing required nodes or wrong order",
        missing=missing,
        visited=visited,
        required=required,
    )


def score_node_sequence(case: E2ECase, trace: dict[str, Any]) -> MetricScore:
    return score_execution_path(case, trace)


def score_join(case: E2ECase, trace: dict[str, Any]) -> MetricScore:
    expected = set(case.expected_trace.expected_route)
    if len(expected) < 2:
        return _skip("single-domain route")
    join = trace.get("join") or {}
    merged = set(join.get("merged_domains") or [])
    branch_count = join.get("branch_count") or 0
    if merged != expected:
        return _fail(
            "join merged_domains mismatch",
            expected=sorted(expected),
            actual=sorted(merged),
            branch_count=branch_count,
        )
    if branch_count != len(expected):
        return _fail(
            "join branch_count mismatch",
            expected=len(expected),
            actual=branch_count,
        )
    return _pass("join integrity satisfied", merged_domains=sorted(merged))


def score_trace(case: E2ECase, trace: dict[str, Any]) -> AutoScores:
    routing = score_routing(case, trace)
    tools = score_tools(case, trace)
    context = score_context(case, trace)
    applicability = score_applicability(case, trace)
    leakage = score_leakage(case, trace)
    finalize = score_finalize(case, trace)
    execution = score_execution_path(case, trace)
    join = score_join(case, trace)

    components = [routing, tools, context, applicability, leakage, finalize, execution, join]
    if all(item.status in {ScoreStatus.PASS, ScoreStatus.SKIP} for item in components):
        integrity = _pass("all auto checkpoints passed or skipped")
    else:
        failed = [
            name
            for name, item in zip(
                [
                    "routing",
                    "tools",
                    "context",
                    "applicability",
                    "leakage",
                    "finalize",
                    "execution_path",
                    "join",
                ],
                components,
                strict=True,
            )
            if item.status == ScoreStatus.FAIL
        ]
        integrity = _fail(f"failed checkpoints: {', '.join(failed)}")

    return AutoScores(
        routing_accuracy=routing,
        tool_call_correctness=tools,
        context_recall_precision=context,
        applicability_correctness=applicability,
        cross_user_inactive_leakage=leakage,
        finalize_correctness=finalize,
        execution_path=execution,
        join_integrity=join,
        trace_integrity=integrity,
    )
