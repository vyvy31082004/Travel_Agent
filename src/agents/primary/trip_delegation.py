"""Deterministic trip-plan delegation for primary orchestrator branches."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from utils.utils import to_date

TRIP_PLAN_KEYWORDS = (
    "lên kế hoạch",
    "len ke hoach",
    "kế hoạch du lịch",
    "ke hoach du lich",
    "lịch trình",
    "lich trinh",
    "itinerary",
    "trip plan",
)

DURATION_RE = re.compile(
    r"(\d+)\s*ngày\s*(\d+)\s*đêm",
    re.IGNORECASE,
)
IATA_PAIR_RE = re.compile(
    r"\b([A-Z]{3})\s*(?:→|->|đến|den|to)\s*([A-Z]{3})\b",
    re.IGNORECASE,
)
BAY_DI_RE = re.compile(
    r"bay\s+đi\s+([A-Z]{3})\s*(?:→|->)\s*([A-Z]{3})",
    re.IGNORECASE,
)
BAY_VE_RE = re.compile(
    r"bay\s+về\s*([A-Z]{3})\s*(?:→|->)\s*([A-Z]{3})",
    re.IGNORECASE,
)
FROM_CITY_RE = re.compile(
    r"từ\s+([^:,\n]+?)(?:\s*:|,|\s+bay\b)",
    re.IGNORECASE,
)
DESTINATION_RE = re.compile(
    r"(?:lên\s+)?(?:kế hoạch|ke hoach|lịch trình|lich trinh)\s+"
    r"(?:\d+\s*ngày\s*\d+\s*đêm\s+)?([^:,\n]+?)(?:\s+từ|\s*:|,|\s+bay\b)",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
CHECKIN_RE = re.compile(r"check-?in\s+(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)
CHECKOUT_RE = re.compile(r"check-?out\s+(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)
ADULTS_RE = re.compile(r"(\d+)\s*người\s*lớn", re.IGNORECASE)

TOOL_TO_DOMAIN = {
    "ToFlightAssistant": "flight",
    "ToHotelAssistant": "hotel",
    "ToExcursionAssistant": "excursion",
    "ToCarAssistant": "car",
}

RECALL_NODE_TO_DOMAIN = {
    "flight_domain_recall": "flight",
    "hotel_domain_recall": "hotel",
    "excursion_domain_recall": "excursion",
    "car_domain_recall": "car",
}

ASSISTANT_NODE_TO_DOMAIN = {
    "flight_assistant": "flight",
    "hotel_assistant": "hotel",
    "excursion_assistant": "excursion",
    "car_assistant": "car",
}

HOTEL_EXCURSION_CONSTRAINT_PATTERNS = (
  re.compile(r"ưu\s*tiên\s*yên\s*tĩnh", re.IGNORECASE),
  re.compile(r"ưu\s*tiên\s*thư\s*giãn", re.IGNORECASE),
  re.compile(r"tránh\s*đông\s*đúc", re.IGNORECASE),
  re.compile(r"không\s*gian\s*yên\s*tĩnh", re.IGNORECASE),
)


@dataclass
class TripPlanFields:
    origin: str | None = None
    origin_code: str | None = None
    destination: str | None = None
    destination_code: str | None = None
    departure_date: str | None = None
    return_date: str | None = None
    checkin_date: str | None = None
    checkout_date: str | None = None
    adults: int = 2
    duration_label: str | None = None
    constraints: list[str] = field(default_factory=list)


def _format_date(value: date | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%d/%m/%Y")


def _first_iata_pair(text: str) -> tuple[str | None, str | None]:
    match = BAY_DI_RE.search(text)
    if match:
        return match.group(1).upper(), match.group(2).upper()
    match = IATA_PAIR_RE.search(text)
    if match:
        return match.group(1).upper(), match.group(2).upper()
    return None, None


def _return_iata_pair(text: str) -> tuple[str | None, str | None]:
    match = BAY_VE_RE.search(text)
    if match:
        return match.group(1).upper(), match.group(2).upper()
    pairs = IATA_PAIR_RE.findall(text)
    if len(pairs) >= 2:
        return pairs[1][0].upper(), pairs[1][1].upper()
    return None, None


def _extract_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    for pattern in HOTEL_EXCURSION_CONSTRAINT_PATTERNS:
        match = pattern.search(text)
        if match:
            constraints.append(match.group(0).strip())
    return constraints


def is_trip_plan_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(keyword in lowered for keyword in TRIP_PLAN_KEYWORDS):
        return True
    return bool(DURATION_RE.search(text))


def parse_trip_plan_fields(text: str) -> TripPlanFields:
    fields = TripPlanFields()
    if not text:
        return fields

    duration_match = DURATION_RE.search(text)
    if duration_match:
        fields.duration_label = (
            f"{duration_match.group(1)} ngày {duration_match.group(2)} đêm"
        )

    origin_code, dest_code = _first_iata_pair(text)
    fields.origin_code = origin_code
    fields.destination_code = dest_code

    return_origin, return_dest = _return_iata_pair(text)
    if return_origin and return_dest:
        fields.origin_code = fields.origin_code or return_dest
        fields.destination_code = fields.destination_code or return_origin

    from_match = FROM_CITY_RE.search(text)
    if from_match:
        fields.origin = from_match.group(1).strip()

    dest_match = DESTINATION_RE.search(text)
    if dest_match:
        fields.destination = dest_match.group(1).strip()

    checkin_match = CHECKIN_RE.search(text)
    checkout_match = CHECKOUT_RE.search(text)
    if checkin_match:
        fields.checkin_date = _format_date(to_date(checkin_match.group(1)))
    if checkout_match:
        fields.checkout_date = _format_date(to_date(checkout_match.group(1)))

    all_dates = DATE_RE.findall(text)
    parsed_dates = [_format_date(to_date(value)) for value in all_dates]
    parsed_dates = [value for value in parsed_dates if value]
    if parsed_dates:
        fields.departure_date = parsed_dates[0]
        if len(parsed_dates) >= 2:
            fields.return_date = parsed_dates[1]
        if not fields.checkin_date:
            fields.checkin_date = parsed_dates[0]
        if not fields.checkout_date and len(parsed_dates) >= 2:
            fields.checkout_date = parsed_dates[1]

    adults_match = ADULTS_RE.search(text)
    if adults_match:
        fields.adults = int(adults_match.group(1))

    fields.constraints = _extract_constraints(text)
    return fields


def _origin_label(fields: TripPlanFields) -> str:
    if fields.origin_code:
        return fields.origin_code
    if fields.origin:
        return fields.origin
    return "SGN"


def _destination_label(fields: TripPlanFields) -> str:
    if fields.destination:
        return fields.destination
    if fields.destination_code:
        return fields.destination_code
    return "điểm đến"


def _has_minimum_fields(fields: TripPlanFields, domain: str) -> bool:
    if domain == "flight":
        return bool(
            fields.departure_date
            and fields.return_date
            and (_origin_label(fields) and _destination_label(fields))
        )
    if domain == "hotel":
        return bool(
            fields.checkin_date
            and fields.checkout_date
            and _destination_label(fields) != "điểm đến"
        )
    if domain == "excursion":
        return _destination_label(fields) != "điểm đến"
    if domain == "car":
        return bool(
            fields.checkin_date
            and fields.checkout_date
            and _destination_label(fields) != "điểm đến"
        )
    return False


def build_domain_request(domain: str, fields: TripPlanFields) -> str:
    origin = _origin_label(fields)
    destination = _destination_label(fields)
    adults = fields.adults

    if domain == "flight":
        return (
            f"Tìm vé khứ hồi {origin}→{destination}, "
            f"đi ngày {fields.departure_date}, "
            f"về ngày {fields.return_date}, {adults} người lớn."
        )
    if domain == "hotel":
        return (
            f"Tìm khách sạn tại {destination}, "
            f"check-in {fields.checkin_date}, check-out {fields.checkout_date}, "
            f"{adults} người lớn."
        )
    if domain == "excursion":
        duration = fields.duration_label or "trong chuyến đi"
        return (
            f"Gợi ý tour và hoạt động tham quan tại {destination} "
            f"({duration}), {adults} người lớn."
        )
    if domain == "car":
        return (
            f"Thuê xe tại {destination} từ {fields.checkin_date} "
            f"đến {fields.checkout_date}."
        )
    return ""


def domain_turn_constraints(domain: str, fields: TripPlanFields) -> list[str]:
    if domain not in {"hotel", "excursion"}:
        return []
    return list(fields.constraints)


def _resolve_domain(
    *,
    tool_name: str | None = None,
    recall_node: str | None = None,
    assistant_node: str | None = None,
) -> str | None:
    if recall_node:
        domain = RECALL_NODE_TO_DOMAIN.get(recall_node)
        if domain:
            return domain
    if assistant_node:
        domain = ASSISTANT_NODE_TO_DOMAIN.get(assistant_node)
        if domain:
            return domain
    if tool_name:
        return TOOL_TO_DOMAIN.get(tool_name)
    return None


def resolve_delegated_request(
    domain: str,
    llm_request: str,
    user_message: str,
    turn_constraints: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Force scoped delegation for trip-plan branches (safety net)."""
    if not domain or not is_trip_plan_message(user_message):
        return llm_request, list(turn_constraints or [])

    fields = parse_trip_plan_fields(user_message)
    if not _has_minimum_fields(fields, domain):
        constraints = domain_turn_constraints(domain, fields)
        return llm_request, constraints or list(turn_constraints or [])

    request = build_domain_request(domain, fields)
    constraints = domain_turn_constraints(domain, fields)
    return request, constraints or list(turn_constraints or [])


def normalize_branch_request(
    tool_name: str,
    llm_request: str,
    user_message: str,
    *,
    recall_node: str | None = None,
    assistant_node: str | None = None,
) -> tuple[str, list[str]]:
    """Return scoped delegated request and turn_constraints for a branch."""
    domain = _resolve_domain(
        tool_name=tool_name,
        recall_node=recall_node,
        assistant_node=assistant_node,
    )
    if not domain:
        return llm_request, []
    return resolve_delegated_request(domain, llm_request, user_message)


def normalize_branch_args(
    tool_name: str,
    args: dict,
    user_message: str,
    *,
    recall_node: str | None = None,
    assistant_node: str | None = None,
) -> dict:
    """Normalize delegation tool args for trip-plan branches."""
    llm_constraints = list(args.get("turn_constraints") or [])
    request, constraints = normalize_branch_request(
        tool_name,
        str(args.get("request") or ""),
        user_message,
        recall_node=recall_node,
        assistant_node=assistant_node,
    )
    normalized = dict(args)
    normalized["request"] = request
    normalized["turn_constraints"] = constraints or llm_constraints
    return normalized
