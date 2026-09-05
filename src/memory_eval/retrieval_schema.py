from __future__ import annotations

from typing import Any

APPLICABILITY_LABELS = frozenset({"apply", "overridden", "irrelevant", "uncertain"})
DOMAINS = frozenset({"hotel", "flight", "car", "excursion"})
SPLITS = frozenset({"development", "test"})

SCENARIO_TYPES: tuple[str, ...] = (
    "scope_same_user_same_domain",
    "scope_cross_user",
    "scope_cross_domain",
    "scope_inactive",
    "scope_global_not_in_pool",
    "scope_empty_pool",
    "action_contrast_hotel_search",
    "action_contrast_hotel_details",
    "action_contrast_hotel_select_room",
    "action_contrast_hotel_reviews",
    "action_contrast_flight_search",
    "action_contrast_flight_compare",
    "action_contrast_car_search",
    "action_contrast_car_select",
    "action_contrast_excursion_search",
    "action_contrast_excursion_details",
    "override_flight_time",
    "override_hotel_budget",
    "override_hotel_location_uncertain",
    "override_car_transmission",
    "override_flight_departure",
    "soft_hotel_quiet_uncertain",
    "soft_hotel_avoid_groups_uncertain",
    "soft_hotel_bathtub_uncertain",
    "soft_flight_direct_apply",
    "soft_flight_lowest_price_uncertain",
    "state_hotel_bathtub_apply_with_selection",
    "state_hotel_bathtub_irrelevant_without_selection",
    "state_flight_seat_with_shortlist",
    "state_car_capacity_with_trip_context",
)

GROUP_BY_SCENARIO: dict[str, str] = {
    name: "A_scope_isolation"
    for name in SCENARIO_TYPES[:6]
}
GROUP_BY_SCENARIO.update(
    {name: "B_action_sensitive" for name in SCENARIO_TYPES[6:16]}
)
GROUP_BY_SCENARIO.update(
    {name: "C_explicit_override" for name in SCENARIO_TYPES[16:21]}
)
GROUP_BY_SCENARIO.update(
    {name: "D_soft_preference" for name in SCENARIO_TYPES[21:26]}
)
GROUP_BY_SCENARIO.update(
    {name: "E_domain_state" for name in SCENARIO_TYPES[26:30]}
)

REQUIREMENT_BY_SCENARIO: dict[str, str] = {
    "scope_same_user_same_domain": "REQ-RETR-SCOPE-SAME",
    "scope_cross_user": "REQ-RETR-SCOPE-CROSS-USER",
    "scope_cross_domain": "REQ-RETR-SCOPE-CROSS-DOMAIN",
    "scope_inactive": "REQ-RETR-SCOPE-INACTIVE",
    "scope_global_not_in_pool": "REQ-RETR-SCOPE-GLOBAL",
    "scope_empty_pool": "REQ-RETR-SCOPE-EMPTY",
    "action_contrast_hotel_search": "REQ-RETR-ACTION-HOTEL",
    "action_contrast_hotel_details": "REQ-RETR-ACTION-HOTEL",
    "action_contrast_hotel_select_room": "REQ-RETR-ACTION-HOTEL",
    "action_contrast_hotel_reviews": "REQ-RETR-ACTION-HOTEL",
    "action_contrast_flight_search": "REQ-RETR-ACTION-FLIGHT",
    "action_contrast_flight_compare": "REQ-RETR-ACTION-FLIGHT",
    "action_contrast_car_search": "REQ-RETR-ACTION-CAR",
    "action_contrast_car_select": "REQ-RETR-ACTION-CAR",
    "action_contrast_excursion_search": "REQ-RETR-ACTION-EXCURSION",
    "action_contrast_excursion_details": "REQ-RETR-ACTION-EXCURSION",
    "override_flight_time": "REQ-RETR-OVERRIDE",
    "override_hotel_budget": "REQ-RETR-OVERRIDE",
    "override_hotel_location_uncertain": "REQ-RETR-OVERRIDE",
    "override_car_transmission": "REQ-RETR-OVERRIDE",
    "override_flight_departure": "REQ-RETR-OVERRIDE",
    "soft_hotel_quiet_uncertain": "REQ-RETR-SOFT-PREF",
    "soft_hotel_avoid_groups_uncertain": "REQ-RETR-SOFT-PREF",
    "soft_hotel_bathtub_uncertain": "REQ-RETR-SOFT-PREF",
    "soft_flight_direct_apply": "REQ-RETR-SOFT-PREF",
    "soft_flight_lowest_price_uncertain": "REQ-RETR-SOFT-PREF",
    "state_hotel_bathtub_apply_with_selection": "REQ-RETR-STATE",
    "state_hotel_bathtub_irrelevant_without_selection": "REQ-RETR-STATE",
    "state_flight_seat_with_shortlist": "REQ-RETR-STATE",
    "state_car_capacity_with_trip_context": "REQ-RETR-STATE",
}

REQUIRED_FIELDS = (
    "case_id",
    "split",
    "scenario_type",
    "group",
    "requirement_id",
    "user_id",
    "user_query",
    "domain",
    "memory_store",
    "expected_sql_pool",
    "expected_applicability",
)


def _store_ids(case: dict[str, Any]) -> set[str]:
    return {
        str(item["memory_id"])
        for item in case.get("memory_store") or []
        if item.get("memory_id")
    }


def validate_case(case: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in case:
            errors.append(f"missing field: {field}")
    scenario_type = str(case.get("scenario_type") or "")
    if scenario_type not in SCENARIO_TYPES:
        errors.append(f"unknown scenario_type: {scenario_type}")
    split = str(case.get("split") or "")
    if split not in SPLITS:
        errors.append(f"invalid split: {split}")
    domain = str(case.get("domain") or "")
    if domain not in DOMAINS:
        errors.append(f"invalid domain: {domain}")

    store_ids = _store_ids(case)
    pool = [str(item) for item in case.get("expected_sql_pool") or []]
    applicability = case.get("expected_applicability") or {}
    if not isinstance(applicability, dict):
        errors.append("expected_applicability must be a dict")
        applicability = {}

    for memory_id in pool:
        if memory_id not in store_ids:
            errors.append(f"expected_sql_pool id not in memory_store: {memory_id}")
    for memory_id in applicability:
        if memory_id not in store_ids:
            errors.append(f"expected_applicability id not in memory_store: {memory_id}")
        label = str(applicability[memory_id]).lower()
        if label not in APPLICABILITY_LABELS:
            errors.append(f"invalid applicability label for {memory_id}: {label}")

    for memory_id, label in applicability.items():
        if memory_id not in pool and label != "irrelevant":
            errors.append(
                f"applicability for {memory_id} outside sql pool requires irrelevant label"
            )

    presented = case.get("expected_presented_constraints") or []
    if presented:
        for item in presented:
            if not isinstance(item, dict):
                errors.append("expected_presented_constraints items must be objects")
                continue
            mid = str(item.get("memory_id") or "")
            if mid and applicability.get(mid) not in {"apply", "uncertain", None}:
                if mid in applicability and str(applicability[mid]).lower() not in {
                    "apply",
                    "uncertain",
                }:
                    errors.append(
                        f"presented constraint for non-apply/uncertain memory: {mid}"
                    )

    return errors


def build_coverage_matrix(cases: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {
        scenario: {"development": 0, "test": 0} for scenario in SCENARIO_TYPES
    }
    for case in cases:
        scenario = str(case.get("scenario_type") or "")
        split = str(case.get("split") or "")
        if scenario in matrix and split in matrix[scenario]:
            matrix[scenario][split] += 1
    return matrix


def coverage_gaps(matrix: dict[str, dict[str, int]]) -> list[str]:
    gaps: list[str] = []
    for scenario, counts in matrix.items():
        if counts.get("development", 0) < 1:
            gaps.append(f"{scenario}: missing development")
        if counts.get("test", 0) < 1:
            gaps.append(f"{scenario}: missing test")
    return gaps


def validate_dataset(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    for case in cases:
        case_id = str(case.get("case_id") or "")
        if case_id in seen_ids:
            errors.append(f"duplicate case_id: {case_id}")
        seen_ids.add(case_id)
        errors.extend(f"{case_id}: {msg}" for msg in validate_case(case))

    dev_count = sum(1 for case in cases if case.get("split") == "development")
    test_count = sum(1 for case in cases if case.get("split") == "test")
    if dev_count != 65:
        errors.append(f"expected 65 development cases, got {dev_count}")
    if test_count != 85:
        errors.append(f"expected 85 test cases, got {test_count}")
    if len(cases) != 150:
        errors.append(f"expected 150 total cases, got {len(cases)}")

    matrix = build_coverage_matrix(cases)
    gaps = coverage_gaps(matrix)
    errors.extend(f"coverage gap: {gap}" for gap in gaps)
    return errors


def build_manifest(cases: list[dict[str, Any]]) -> dict[str, Any]:
    matrix = build_coverage_matrix(cases)
    gaps = coverage_gaps(matrix)
    by_group: dict[str, dict[str, int]] = {}
    by_requirement: dict[str, dict[str, int]] = {}
    by_domain: dict[str, dict[str, int]] = {}
    by_label: dict[str, dict[str, int]] = {}
    for case in cases:
        split = str(case.get("split") or "")
        for key, bucket in (
            (str(case.get("group") or ""), by_group),
            (str(case.get("requirement_id") or ""), by_requirement),
            (str(case.get("domain") or ""), by_domain),
        ):
            bucket.setdefault(key, {"development": 0, "test": 0})
            if split in bucket[key]:
                bucket[key][split] += 1
        for label in (case.get("expected_applicability") or {}).values():
            label_key = str(label).lower()
            by_label.setdefault(label_key, {"development": 0, "test": 0})
            if split in by_label[label_key]:
                by_label[label_key][split] += 1

    return {
        "development_count": sum(1 for c in cases if c.get("split") == "development"),
        "test_count": sum(1 for c in cases if c.get("split") == "test"),
        "total": len(cases),
        "mapping": {str(c["case_id"]): str(c["split"]) for c in cases},
        "coverage_matrix": matrix,
        "coverage_gaps": gaps,
        "by_group": by_group,
        "by_requirement": by_requirement,
        "by_domain": by_domain,
        "by_label": by_label,
        "note": (
            "Domain recall eval: SQL candidate pool + applicability judge. "
            "Mirrored full coverage — every scenario_type appears in development and test."
        ),
    }
