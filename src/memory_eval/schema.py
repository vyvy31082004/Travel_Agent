"""JSONL schema validation for long-term memory eval fixtures."""

from __future__ import annotations

from typing import Any

VALID_SPLITS = frozenset({"dev", "held_out"})
VALID_RISK_TYPES = frozenset({"precision", "recall", "faithfulness", "unsafe"})
VALID_REQUIREMENT_IDS = frozenset(
    {
        "LTM-EXT-001",
        "LTM-EXT-002",
        "LTM-EXT-003",
        "LTM-EXT-004",
        "LTM-EXT-005",
        "LTM-EXT-006",
        "LTM-EXT-007",
    }
)


def validate_extraction_case(case: dict[str, Any], *, line_no: int | None = None) -> list[str]:
    errors: list[str] = []
    prefix = f"line {line_no}: " if line_no else ""

    for field in ("case_id", "split", "requirement_id", "risk_type", "rationale", "messages"):
        if field not in case:
            errors.append(f"{prefix}missing required field {field!r}")

    case_id = case.get("case_id")
    if case_id is not None and not str(case_id).strip():
        errors.append(f"{prefix}case_id must be non-empty")

    split = case.get("split")
    if split not in VALID_SPLITS:
        errors.append(f"{prefix}split must be dev or held_out, got {split!r}")

    req = case.get("requirement_id")
    if req not in VALID_REQUIREMENT_IDS:
        errors.append(f"{prefix}invalid requirement_id {req!r}")

    risk = case.get("risk_type")
    if risk not in VALID_RISK_TYPES:
        errors.append(f"{prefix}invalid risk_type {risk!r}")

    rationale = case.get("rationale")
    if not isinstance(rationale, str) or len(rationale.strip()) < 10:
        errors.append(f"{prefix}rationale must be at least 10 characters")

    messages = case.get("messages")
    if not isinstance(messages, list) or not messages:
        errors.append(f"{prefix}messages must be a non-empty list")

    if "expect_extract" not in case:
        errors.append(f"{prefix}missing expect_extract")
    if "unsafe" not in case:
        errors.append(f"{prefix}missing unsafe")

    golds = case.get("gold_memories")
    if golds is None:
        errors.append(f"{prefix}missing gold_memories (use [])")
    elif not isinstance(golds, list):
        errors.append(f"{prefix}gold_memories must be a list")

    expect = bool(case.get("expect_extract"))
    unsafe = bool(case.get("unsafe"))
    if expect and not golds:
        errors.append(f"{prefix}expect_extract=true requires non-empty gold_memories")
    if unsafe and expect:
        errors.append(f"{prefix}unsafe case should have expect_extract=false")

    return errors


def validate_extraction_cases(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    dev_count = 0
    held_count = 0

    for i, case in enumerate(cases, 1):
        case_errors = validate_extraction_case(case, line_no=i)
        errors.extend(case_errors)
        cid = case.get("case_id")
        if cid:
            if cid in seen:
                errors.append(f"line {i}: duplicate case_id {cid!r}")
            seen.add(cid)
        if case.get("split") == "dev":
            dev_count += 1
        elif case.get("split") == "held_out":
            held_count += 1

    if len(cases) != 100:
        errors.append(f"expected 100 cases, got {len(cases)}")
    if dev_count != 60:
        errors.append(f"expected 60 dev cases, got {dev_count}")
    if held_count != 40:
        errors.append(f"expected 40 held_out cases, got {held_count}")

    return errors
