import os
import requests
from dotenv import load_dotenv
import uuid
import unicodedata
from utils.utils import to_date
# Load environment variables from .env file
from datetime import datetime, timedelta
from utils.utils import to_date, convert_to_vnd
load_dotenv()
from functools import lru_cache
from datetime import date, datetime
from typing import Any, Optional

from utils.rapidapi_limiter import call_with_rate_limit_retry


BOOKING_HOST = os.getenv(
    "BOOKING_RAPIDAPI_HOST",
    "booking-com15.p.rapidapi.com",
)
BOOKING_BASE_URL = f"https://{BOOKING_HOST}/api/v1"
BOOKING_LANGUAGE_CODE = os.getenv("BOOKING_LANGUAGE_CODE", "vi")
BOOKING_CURRENCY_CODE = os.getenv("BOOKING_CURRENCY_CODE", "VND")
COUNTRY_CODE = os.getenv("COUNTRY_CODE", "VN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

GOOGLE_FLIGHT_HOST = os.getenv("GOOGLE_FLIGHT_RAPIDAPI_HOST", "google-flights2.p.rapidapi.com")
GOOGLE_FLIGHT_BASE_URL = f"https://{GOOGLE_FLIGHT_HOST}"
# =========================
# FLIGHT ENDPOINTS
# Nếu endpoint trên RapidAPI khác, chỉ sửa 3 dòng này
# =========================

FLIGHT_LOCATION_ENDPOINT = "/api/v1/searchAirport"
FLIGHT_SEARCH_ENDPOINT = "/api/v1/searchFlights"
FLIGHT_NEXT_ENDPOINT = "/api/v1/getNextFlights"
FLIGHT_BOOKING_DETAILS_ENDPOINT = "/api/v1/getBookingDetails"
FLIGHT_BOOKING_URL_ENDPOINT = "/api/v1/getBookingURL"




def _get_headers(header: str) -> dict:
    if not RAPIDAPI_KEY:
        raise RuntimeError("Thiếu RAPIDAPI_KEY trong file .env")
    if header == "booking":
        return {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": BOOKING_HOST,
        }
    return {
        "X-RapidAPI-Key": RAPIDAPI_KEY, 
        "X-RapidAPI-Host": GOOGLE_FLIGHT_HOST,
    }


def _serialize_param_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value


def _clean_request_params(params: dict) -> dict:
    return {
        key: _serialize_param_value(value)
        for key, value in params.items()
        if value is not None and value != ""
    }


def _booking_get(header: str, path: str, params: dict, retries: int = 2) -> dict | list:
    if header == "booking":
        url = f"{BOOKING_BASE_URL}{path}"
    else:
        url = f"{GOOGLE_FLIGHT_BASE_URL}{path}"

    clean_params = _clean_request_params(params)

    print("CALL API:", url)
    print("PARAMS:", clean_params)

    def _do_request() -> dict | list:
        response = requests.get(
            url,
            headers=_get_headers(header),
            params=clean_params,
            timeout=40,
        )

        print("FINAL URL:", response.url)

        if response.status_code == 429:
            raise RuntimeError("RapidAPI bị giới hạn request. Hãy thử lại sau.")

        if response.status_code == 400:
            try:
                error_data = response.json()
                return {"error": error_data.get("message", "Lỗi từ API")}
            except Exception:
                pass

        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, dict) and payload.get("status") is False:
            raise RuntimeError(payload.get("message", "Booking API trả về lỗi."))

        if isinstance(payload, dict):
            return payload.get("data", payload)

        return payload

    def _on_retry(attempt: int, delay: float, exc: BaseException) -> None:
        print(
            f"429 on attempt {attempt}/{retries + 1}, "
            f"retrying after {delay:g}s..."
        )

    return call_with_rate_limit_retry(
        _do_request,
        retries=retries,
        on_retry=_on_retry,
    )


def _parse_date(value: Optional[str]) -> Optional[str]:
    """
    Validate date dạng YYYY-MM-DD.
    Không tự default ngày.
    """
    if not value:
        return None

    parsed = datetime.strptime(value, "%Y-%m-%d").date()

    if parsed < date.today():
        raise ValueError("Ngày tìm attraction phải từ hôm nay trở về sau.")

    return parsed.isoformat()


def remove_vietnamese_accents(text: str) -> str:
    text = text.replace("Đ", "D").replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(
        char for char in text
        if unicodedata.category(char) != "Mn"
    )
    return text

def _as_location_list(data: Any) -> list[dict]:
    """Normalize searchAirport payload to a list of location dicts."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("destinations", "products", "data", "airports"):
            nested = data.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _pick_best_airport(data: Any, query: str = "") -> dict | None:
    """
    Always take data[0] — Google Flights searchAirport ranks the best match first.
    """
    items = _as_location_list(data)
    if not items:
        return None
    return items[0]


def search_flight_location_from_api(
    query: str,
    languagecode: str = BOOKING_LANGUAGE_CODE,
) -> dict:
    """
    Resolve place name / city to IATA via Google Flights searchAirport (data[0].id).
    """

    if not query:
        return {
            "error": "Bạn cần cung cấp điểm đi hoặc điểm đến."
        }

    query = remove_vietnamese_accents(query).strip()
    query_upper = query.upper()

    if query_upper == "SAI GON":
        query = "Ho Chi Minh"
        query_upper = "HO CHI MINH"

    # Google Flights accepts IATA/city codes directly.
    if len(query_upper) == 3 and query_upper.isalpha():
        return {
            "source": "iata_passthrough",
            "query": query,
            "id": query_upper,
            "code": query_upper,
            "name": query_upper,
            "city": None,
            "country": COUNTRY_CODE,
            "raw": None,
        }

    try:
        data = _booking_get(
            "google_flight",
            FLIGHT_LOCATION_ENDPOINT,
            {
                "query": query,
                "language_code": languagecode,
                "country_code": COUNTRY_CODE,
            },
        )

        airport = _pick_best_airport(data, query)

        if not airport:
            return {
                "error": f"Không tìm được flight location cho '{query}'.",
                "raw": data,
            }

        airport_id = airport.get("id")
        return {
            "source": "google_flights2_searchAirport",
            "query": query,
            "id": airport_id,
            "code": airport_id,
            "name": airport.get("title") or airport.get("name"),
            "city": airport.get("city"),
            "country": COUNTRY_CODE,
            "raw": airport,
        }

    except Exception as e:
        return {
            "error": f"Lỗi khi gọi flight searchAirport: {str(e)}"
        }




def _extract_top_other(data: Any) -> tuple[list[dict], list[dict]]:
    """Pull topFlights/otherFlights from data or data.itineraries."""
    if not isinstance(data, dict):
        return [], []
    if "topFlights" in data or "otherFlights" in data:
        top = data.get("topFlights") or []
        other = data.get("otherFlights") or []
        return (
            [x for x in top if isinstance(x, dict)],
            [x for x in other if isinstance(x, dict)],
        )
    itineraries = data.get("itineraries")
    if isinstance(itineraries, dict):
        top = itineraries.get("topFlights") or []
        other = itineraries.get("otherFlights") or []
        return (
            [x for x in top if isinstance(x, dict)],
            [x for x in other if isinstance(x, dict)],
        )
    if isinstance(itineraries, list):
        return [x for x in itineraries if isinstance(x, dict)], []
    return [], []


def _build_search_flights_params(
    *,
    departure_id: str,
    arrival_id: str,
    outbound_date: date | str,
    return_date: date | str | None = None,
    adults: int = 1,
    children: int = 0,
    infant_on_lap: int = 0,
    infant_in_seat: int = 0,
    cabin_class: str = "economy",
    sort_by: str = "best",
    currency_code: str = BOOKING_CURRENCY_CODE,
    languagecode: str = BOOKING_LANGUAGE_CODE,
    countrycode: str = COUNTRY_CODE,
    show_hidden: str = "1",
) -> dict:
    return {
        "departure_id": departure_id,
        "arrival_id": arrival_id,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "adults": str(adults),
        "children": str(children),
        "infant_on_lap": str(infant_on_lap),
        "infant_in_seat": str(infant_in_seat),
        "travel_class": _map_cabin_class(cabin_class),
        "search_type": _map_search_type(sort_by),
        "show_hidden": str(show_hidden),
        "currency": currency_code,
        "language_code": languagecode,
        "country_code": countrycode,
    }


def _build_next_flights_params(
    next_token: str,
    *,
    currency_code: str = BOOKING_CURRENCY_CODE,
    languagecode: str = BOOKING_LANGUAGE_CODE,
    countrycode: str = COUNTRY_CODE,
    show_hidden: str = "1",
) -> dict:
    return {
        "next_token": next_token,
        "show_hidden": str(show_hidden),
        "currency": currency_code,
        "language_code": languagecode,
        "country_code": countrycode,
    }


def _airline_code_from_flight_number(flight_number: Any) -> str | None:
    if not flight_number:
        return None
    token = str(flight_number).strip().split()[0]
    # Keep alphanumeric designator (B6, VN, 3K, ...)
    code = "".join(ch for ch in token if ch.isalnum())
    return code.upper() or None


def _split_airport_time(value: Any) -> tuple[str | None, str | None]:
    """Split '2025-2-1 08:34' or '2025-02-01 08:34' into (date, time)."""
    if not value:
        return None, None
    text = str(value).strip()
    parts = text.split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    if "T" in text:
        date_part, time_part = text.split("T", 1)
        return date_part, time_part[:5] if time_part else None
    return None, text


def _duration_minutes(duration: Any) -> int | None:
    if isinstance(duration, dict):
        raw = duration.get("raw")
        return int(raw) if raw is not None else None
    if isinstance(duration, (int, float)):
        return int(duration)
    return None


def _normalize_flight_offer(
    choice: int,
    flight_offers: list[dict],
    retun_assign: bool = False,
) -> list[dict]:
    """
    Normalize Google Flights2 searchFlights / getNextFlights offers.

    Offer shape:
    - flights[]: departure_airport / arrival_airport / airline / flight_number / duration
    - duration: {raw, text} at offer level
    - next_token for roundtrip follow-up via getNextFlights
    """
    if not flight_offers:
        return []
    if choice not in (1, 2):
        return [{"error": "Bạn cần chọn loại chuyến bay: 1 -> one way, 2 -> round way"}]

    result: list[dict] = []
    for offer in flight_offers:
        legs = offer.get("flights") or offer.get("segments") or []
        if not legs:
            continue

        normalized_segments = []
        for seg in legs:
            dep = seg.get("departure_airport") or {}
            arr = seg.get("arrival_airport") or {}
            # Legacy camelCase segments (fallback)
            if not dep and seg.get("departureAirportCode"):
                airline = seg.get("airline") or {}
                normalized_segments.append({
                    "departure_airport_code": seg.get("departureAirportCode"),
                    "departure_airport_name": seg.get("departureAirportName"),
                    "arrival_airport_code": seg.get("arrivalAirportCode"),
                    "arrival_airport_name": seg.get("arrivalAirportName"),
                    "departure_time": seg.get("departureTime"),
                    "departure_date": seg.get("departureDate"),
                    "arrival_time": seg.get("arrivalTime"),
                    "arrival_date": seg.get("arrivalDate"),
                    "cabin_class": seg.get("cabinClass"),
                    "duration_minutes": seg.get("durationMinutes"),
                    "flight_number": airline.get("flightNumber") if isinstance(airline, dict) else None,
                    "airline_code": airline.get("airlineCode") if isinstance(airline, dict) else None,
                    "airline_name": airline.get("airlineName") if isinstance(airline, dict) else airline,
                    "aircraftName": seg.get("aircraftName") or seg.get("aircraft"),
                    "flight_ID": seg.get("flightId"),
                    "seat_width": seg.get("seatWidth") or seg.get("legroom"),
                })
                continue

            dep_date, dep_time = _split_airport_time(dep.get("time"))
            arr_date, arr_time = _split_airport_time(arr.get("time"))
            flight_number = seg.get("flight_number")
            airline_name = seg.get("airline")
            if isinstance(airline_name, dict):
                flight_number = flight_number or airline_name.get("flightNumber")
                airline_code = airline_name.get("airlineCode")
                airline_name = airline_name.get("airlineName") or airline_name.get("airline")
            else:
                airline_code = _airline_code_from_flight_number(flight_number)

            normalized_segments.append({
                "departure_airport_code": dep.get("airport_code"),
                "departure_airport_name": dep.get("airport_name"),
                "arrival_airport_code": arr.get("airport_code"),
                "arrival_airport_name": arr.get("airport_name"),
                "departure_time": dep_time,
                "departure_date": dep_date,
                "arrival_time": arr_time,
                "arrival_date": arr_date,
                "cabin_class": seg.get("cabin_class") or seg.get("seat"),
                "duration_minutes": _duration_minutes(seg.get("duration")) or seg.get("duration"),
                "flight_number": flight_number,
                "airline_code": airline_code,
                "airline_name": airline_name,
                "aircraftName": seg.get("aircraft"),
                "flight_ID": seg.get("flight_id") or seg.get("flightId"),
                "seat_width": seg.get("legroom") or seg.get("seat"),
            })

        first = normalized_segments[0]
        last = normalized_segments[-1]
        offer_airline = offer.get("airline") or offer.get("airlineNames")
        offer_flight_number = first.get("flight_number")
        airline_code = (
            offer.get("airlineCode")
            or _airline_code_from_flight_number(offer_flight_number)
            or first.get("airline_code")
        )

        booking_token = offer.get("booking_token")
        flight_info: dict[str, Any] = {
            "price": offer.get("price"),
            "airline_code": airline_code,
            "airline_name": offer_airline or first.get("airline_name"),
            "stops": offer.get("stops"),
            "duration_minutes": _duration_minutes(offer.get("duration")) or offer.get("duration"),
            "departure_time": offer.get("departure_time") or first.get("departure_time"),
            "departure_date": offer.get("departure_date") or first.get("departure_date"),
            "arrival_time": offer.get("arrival_time") or last.get("arrival_time"),
            "arrival_date": offer.get("arrival_date") or last.get("arrival_date"),
            "departure_airport_code": (
                offer.get("departureAirportCode")
                or first.get("departure_airport_code")
            ),
            "arrival_airport_code": (
                offer.get("arrivalAirportCode")
                or last.get("arrival_airport_code")
            ),
            "segments": normalized_segments,
            "next_token": offer.get("next_token"),
            "booking_token": booking_token,
            "detailToken": booking_token,
        }

        if choice == 1 and not retun_assign:
            flight_info["Offer_ID"] = f"FL-{uuid.uuid4().hex[:6].upper()}"

        result.append(flight_info)

    return result


_AIRLINE_NAME_TO_CODE: dict[str, str] = {
    # Vietnamese carriers
    "vietjet": "VJ",
    "vietjet air": "VJ",
    "vj": "VJ",
    "vietnam airlines": "VN",
    "vn": "VN",
    "bamboo airways": "QH",
    "bamboo": "QH",
    "qh": "QH",
    "vietravel airlines": "VU",
    "vietravel": "VU",
    "vu": "VU",
    "pacific airlines": "BL",
    "bl": "BL",
    # Common international carriers
    "thai airways": "TG",
    "tg": "TG",
    "singapore airlines": "SQ",
    "sq": "SQ",
    "cathay pacific": "CX",
    "cx": "CX",
    "korean air": "KE",
    "ke": "KE",
    "asiana": "OZ",
    "oz": "OZ",
    "air asia": "AK",
    "airasia": "AK",
    "ak": "AK",
    "qatar airways": "QR",
    "qr": "QR",
    "emirates": "EK",
    "ek": "EK",
    "lufthansa": "LH",
    "lh": "LH",
    "air france": "AF",
    "af": "AF",
    "turkish airlines": "TK",
    "tk": "TK",
}


def _resolve_airline_codes(airlines: Optional[str]) -> Optional[str]:
    """
    Convert airline name(s) to IATA code(s).
    Input can be a comma-separated list of names or codes, e.g. "VietJet,Vietnam Airlines".
    Returns comma-separated IATA codes, e.g. "VJ,VN".
    If a token is already an unknown code it is passed through as-is.
    """
    if not airlines:
        return None
    resolved = []
    for token in airlines.split(","):
        key = token.strip().lower()
        resolved.append(_AIRLINE_NAME_TO_CODE.get(key, token.strip()))
    return ",".join(resolved)


def _map_cabin_class(cabin_class: str) -> str:
    """economy->ECONOMY, premium_economy->PREMIUM_ECONOMY, business->BUSINESS, first->FIRST"""
    mapping = {
        "economy": "ECONOMY",
        "premium economy": "PREMIUM_ECONOMY",
        "premium_economy": "PREMIUM_ECONOMY",
        "business": "BUSINESS",
        "first": "FIRST",
        "ECONOMY": "ECONOMY",
        "PREMIUM_ECONOMY": "PREMIUM_ECONOMY",
        "BUSINESS": "BUSINESS",
        "FIRST": "FIRST",
    }
    key = cabin_class.strip()
    return mapping.get(key, mapping.get(key.lower(), "ECONOMY"))


def _map_search_type(sort_by: str) -> str:
    """best/top -> best; cheap/price -> cheap."""
    key = sort_by.lower().strip()
    if key in ("price", "cheap"):
        return "cheap"
    return "best"


def _map_sort_by(sort_by: str) -> str:
    """Back-compat alias -> search_type."""
    return _map_search_type(sort_by)


def _parse_flight_time(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in (
        "%d-%m-%Y %I:%M %p",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%H:%M",
    ):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    # Handle loosely formatted dates like "2025-2-1 08:34"
    try:
        parts = value.strip().replace("T", " ").split()
        if len(parts) >= 2:
            y, m, d = [int(x) for x in parts[0].split("-")]
            hh, mm = [int(x) for x in parts[1][:5].split(":")]
            return datetime(y, m, d, hh, mm)
    except Exception:
        pass
    return None


def _time_range_from_center(
    center: str,
    tolerance_minutes: int = 60,
) -> tuple[str, str]:
    """
    Tính khoảng [after, before] xung quanh giờ trung tâm.
    Clamp về [00:00, 23:59] để tránh tràn ngày.
    Ví dụ: center="08:30", tolerance=60 → ("07:30", "09:30")
    """
    center_lower = center.strip().lower()
    if center_lower in ["morning", "sáng", "buổi sáng"]:
        center = "08:00"
        tolerance_minutes = max(tolerance_minutes, 240) # 04:00 to 12:00
    elif center_lower in ["afternoon", "chiều", "buổi chiều"]:
        center = "14:00"
        tolerance_minutes = max(tolerance_minutes, 240)
    elif center_lower in ["evening", "tối", "buổi tối", "đêm"]:
        center = "20:00"
        tolerance_minutes = max(tolerance_minutes, 240)
        
    try:
        base = datetime.strptime(center.strip(), "%H:%M")
    except ValueError:
        # Fallback to a wide range if parsing fails
        return "00:00", "23:59"

    after_dt = base - timedelta(minutes=tolerance_minutes)
    before_dt = base + timedelta(minutes=tolerance_minutes)

    midnight = datetime.strptime("00:00", "%H:%M")
    end_of_day = datetime.strptime("23:59", "%H:%M")

    after_dt = max(after_dt, midnight)
    before_dt = min(before_dt, end_of_day)

    return after_dt.strftime("%H:%M"), before_dt.strftime("%H:%M")


def _time_in_range(dt: datetime | None, after: str | None, before: str | None) -> bool:
    if dt is None:
        return True
    if after:
        after_t = datetime.strptime(after, "%H:%M").time()
        if dt.time() < after_t:
            return False
    if before:
        before_t = datetime.strptime(before, "%H:%M").time()
        if dt.time() > before_t:
            return False
    return True


def _filter_flights_by_time(
    flights: list[dict],
    departure_after: Optional[str] = None,
    departure_before: Optional[str] = None,
    arrival_after: Optional[str] = None,
    arrival_before: Optional[str] = None,
) -> list[dict]:
    """
    Lọc danh sách flight offers theo giờ bay (chỉ xét chiều đi):
    - departure_time trong khoảng departure_after/before
    - arrival_time trong khoảng arrival_after/before
    """
    if not flights:
        return []

    filtered = []
    for offer in flights:
        departure = _parse_flight_time(offer.get("departure_time"))
        arrival = _parse_flight_time(offer.get("arrival_time"))

        if not _time_in_range(departure, departure_after, departure_before):
            continue
        if not _time_in_range(arrival, arrival_after, arrival_before):
            continue

        filtered.append(offer)

    return filtered

def search_one_way_flights_from_api(
    origin: str,
    destination: str,
    departure_date: Optional[str] = None,
    adults: int = 1,
    children: int = 0,
    infant_on_lap: int = 0,
    infant_in_seat: int = 0,
    cabin_class: str = "economy",
    currency_code: str = BOOKING_CURRENCY_CODE,
    languagecode: str = BOOKING_LANGUAGE_CODE,
    countrycode: str = COUNTRY_CODE,
    sort_by: str = "best",
    stops: str = "0",
    alliances: Optional[str] = None,
    airlines: Optional[str] = None,
    carry_on_bag: int = 0,
    max_price: Optional[int] = None,
    emissions: int = 0,
    layover_duration: Optional[str] = None,
    airports: Optional[str] = None,
    flight_duration: Optional[str] = None,
    # --- Lọc theo giờ bay (post-filter) ---
    preferred_departure_time: Optional[str] = None,
    preferred_arrival_time: Optional[str] = None,
    time_tolerance_minutes: int = 60,
    limit: int = 10,
) -> list[dict]:
    """
    Tìm kiếm chuyến bay một chiều via /api/v1/searchFlights.
    travel_class: economy/premium_economy/business/first → ECONOMY/...
    search_type: best | cheap (from sort_by)
    preferred_departure_time / preferred_arrival_time: post-filter ±tolerance
    """
    if not origin:
        return [{"error": "Bạn cần cung cấp điểm đi."}]
    if not destination:
        return [{"error": "Bạn cần cung cấp điểm đến."}]
    if not departure_date:
        return [{"error": "Bạn cần cung cấp ngày bay departure_date để tìm chuyến bay."}]
    if adults < 1:
        return [{"error": "Số người lớn adults phải >= 1."}]

    departure_date = to_date(departure_date) if departure_date else None

    if departure_date and departure_date < date.today():
        return [{"error": "departure_date phải từ hôm nay trở về sau."}]

    try:
        origin_info = search_flight_location_from_api(origin)
        destination_info = search_flight_location_from_api(destination)

        if origin_info.get("error"):
            return [origin_info]
        if destination_info.get("error"):
            return [destination_info]

        departure_id = origin_info.get("code") or origin_info.get("id")
        arrival_id = destination_info.get("code") or destination_info.get("id")

        if not departure_id:
            return [{"error": "Không tìm được mã sân bay đi (departure_id)."}]
        if not arrival_id:
            return [{"error": "Không tìm được mã sân bay đến (arrival_id)."}]

        params = _build_search_flights_params(
            departure_id=departure_id,
            arrival_id=arrival_id,
            outbound_date=departure_date,
            adults=adults,
            children=children,
            infant_on_lap=infant_on_lap,
            infant_in_seat=infant_in_seat,
            cabin_class=cabin_class,
            sort_by=sort_by,
            currency_code=currency_code,
            languagecode=languagecode,
            countrycode=countrycode,
        )

        data = _booking_get("google_flight", FLIGHT_SEARCH_ENDPOINT, params)
        if isinstance(data, dict) and data.get("error"):
            return [{"error": data["error"]}]

        top_raw, other_raw = _extract_top_other(data)
        top = _normalize_flight_offer(1, top_raw, retun_assign=False)
        other = _normalize_flight_offer(1, other_raw, retun_assign=False)

        if max_price is not None:
            top = [f for f in top if (f.get("price") or 0) <= max_price]
            other = [f for f in other if (f.get("price") or 0) <= max_price]

        dep_after = dep_before = arr_after = arr_before = None
        if preferred_departure_time:
            dep_after, dep_before = _time_range_from_center(
                preferred_departure_time, time_tolerance_minutes
            )
        if preferred_arrival_time:
            arr_after, arr_before = _time_range_from_center(
                preferred_arrival_time, time_tolerance_minutes
            )

        if any([dep_after, arr_after]):
            top = _filter_flights_by_time(
                top,
                departure_after=dep_after,
                departure_before=dep_before,
                arrival_after=arr_after,
                arrival_before=arr_before,
            )
            other = _filter_flights_by_time(
                other,
                departure_after=dep_after,
                departure_before=dep_before,
                arrival_after=arr_after,
                arrival_before=arr_before,
            )

        return [{
            "source": "google_flights2_searchFlights",
            "topFlights": top,
            "otherFlights": other[:limit],
        }]

    except Exception as e:
        return [{"error": f"Lỗi khi gọi searchFlights: {str(e)}"}]


def _outbound_only_pair(outbound_offer: dict, warning: str | None = None) -> dict:
    offer_id = f"FL-{uuid.uuid4().hex[:6].upper()}"
    pair = {
        "Offer_ID": offer_id,
        "price": outbound_offer.get("price"),
        "outbound": {
            key: value
            for key, value in outbound_offer.items()
            if key not in ("returningToken", "next_token")
        },
        "inbound": None,
    }
    if warning:
        pair["warning"] = warning
    return pair


def _flatten_one_way_result(result: list[dict]) -> list[dict]:
    if not result:
        return []
    if isinstance(result[0], dict) and result[0].get("error"):
        return []
    payload = result[0]
    return list(payload.get("topFlights") or []) + list(payload.get("otherFlights") or [])


def _pair_one_way_legs(outbound_flights: list[dict], inbound_flights: list[dict]) -> list[dict]:
    pairs: list[dict] = []
    if not outbound_flights or not inbound_flights:
        return pairs
    for outbound in outbound_flights:
        for inbound in inbound_flights:
            offer_id = f"FL-{uuid.uuid4().hex[:6].upper()}"
            outbound_price = outbound.get("price") or 0
            inbound_price = inbound.get("price") or 0
            pairs.append({
                "Offer_ID": offer_id,
                "price": outbound_price + inbound_price,
                "booking_token": (
                    inbound.get("booking_token")
                    or inbound.get("detailToken")
                    or outbound.get("booking_token")
                    or outbound.get("detailToken")
                ),
                "detailToken": (
                    inbound.get("booking_token")
                    or inbound.get("detailToken")
                    or outbound.get("booking_token")
                    or outbound.get("detailToken")
                ),
                "next_token": inbound.get("next_token") or outbound.get("next_token"),
                "outbound": {
                    key: value
                    for key, value in outbound.items()
                    if key not in ("detailToken", "returningToken", "next_token", "booking_token")
                },
                "inbound": {
                    key: value
                    for key, value in inbound.items()
                    if key not in ("detailToken", "next_token", "booking_token")
                },
            })
    return pairs


def _roundtrip_one_way_fallback(
    *,
    origin: str,
    destination: str,
    departure_date: date,
    return_date: date,
    adults: int,
    children: int,
    infant_on_lap: int,
    infant_in_seat: int,
    cabin_class: str,
    sort_by: str,
    stops: str,
    limit: int,
    **search_kwargs: Any,
) -> list[dict]:
    shared = {
        "adults": adults,
        "children": children,
        "infant_on_lap": infant_on_lap,
        "infant_in_seat": infant_in_seat,
        "cabin_class": cabin_class,
        "sort_by": sort_by,
        "stops": stops,
        **search_kwargs,
    }
    outbound_result = search_one_way_flights_from_api(
        origin=origin,
        destination=destination,
        departure_date=departure_date.isoformat(),
        limit=limit,
        **shared,
    )
    if outbound_result and outbound_result[0].get("error"):
        return outbound_result

    inbound_result = search_one_way_flights_from_api(
        origin=destination,
        destination=origin,
        departure_date=return_date.isoformat(),
        limit=limit,
        **shared,
    )
    if inbound_result and inbound_result[0].get("error"):
        return inbound_result

    outbound_flights = _flatten_one_way_result(outbound_result)
    inbound_flights = _flatten_one_way_result(inbound_result)
    paired = _pair_one_way_legs(outbound_flights[:limit], inbound_flights[:limit])
    if not paired:
        return [{"error": "Không tìm thấy chuyến bay khứ hồi từ tìm kiếm một chiều."}]

    return [{
        "source": "google_flights2_searchFlights",
        "fallback": "one_way",
        "warnings": [
            "Roundtrip API không trả cặp khứ hồi; đã ghép từ hai lần tìm một chiều.",
        ],
        "topFlights": paired[:limit],
        "otherFlights": paired[limit:],
    }]


def search_roundtrip_flights_from_api(
    origin: str,
    destination: str,
    departure_date: Optional[str] = None,
    return_date: Optional[str] = None,
    adults: int = 1,
    children: int = 0,
    infant_on_lap: int = 0,
    infant_in_seat: int = 0,
    cabin_class: str = "economy",
    currency_code: str = BOOKING_CURRENCY_CODE,
    languagecode: str = BOOKING_LANGUAGE_CODE,
    countrycode: str = COUNTRY_CODE,
    sort_by: str = "best",
    stops: str = "0",
    alliances: Optional[str] = None,
    airlines: Optional[str] = None,
    carry_on_bag: int = 0,
    max_price: Optional[int] = None,
    emissions: int = 0,
    layover_duration: Optional[str] = None,
    airports: Optional[str] = None,
    flight_duration: Optional[str] = None,
    preferred_departure_time: Optional[str] = None,
    preferred_arrival_time: Optional[str] = None,
    preferred_return_departure_time: Optional[str] = None,
    preferred_return_arrival_time: Optional[str] = None,
    time_tolerance_minutes: int = 90,
    limit: int = 2,
):
    if not origin:
        return [{"error": "Bạn cần cung cấp điểm đi."}]
    if not destination:
        return [{"error": "Bạn cần cung cấp điểm đến."}]
    if not departure_date:
        return [{"error": "Bạn cần cung cấp ngày bay departure_date để tìm chuyến bay."}]
    if not return_date:
        return [{"error": "Bạn cần cung cấp ngày bay return_date để tìm chuyến bay."}]
    if adults < 1:
        return [{"error": "Số người lớn adults phải >= 1."}]

    departure_date = to_date(departure_date) if departure_date else None
    return_date = to_date(return_date) if return_date else None

    if departure_date and departure_date < date.today():
        return [{"error": "departure_date phải từ hôm nay trở về sau."}]

    if return_date and return_date < departure_date:
        return [{"error": "Ngày về (return_date) phải sau hoặc bằng ngày đi."}]

    try:
        origin_info = search_flight_location_from_api(origin)
        destination_info = search_flight_location_from_api(destination)

        if origin_info.get("error"):
            return [origin_info]
        if destination_info.get("error"):
            return [destination_info]

        departure_id = origin_info.get("code") or origin_info.get("id")
        arrival_id = destination_info.get("code") or destination_info.get("id")

        if not departure_id:
            return [{"error": "Không tìm được mã sân bay đi (departure_id)."}]
        if not arrival_id:
            return [{"error": "Không tìm được mã sân bay đến (arrival_id)."}]

        params = _build_search_flights_params(
            departure_id=departure_id,
            arrival_id=arrival_id,
            outbound_date=departure_date,
            return_date=return_date,
            adults=adults,
            children=children,
            infant_on_lap=infant_on_lap,
            infant_in_seat=infant_in_seat,
            cabin_class=cabin_class,
            sort_by=sort_by,
            currency_code=currency_code,
            languagecode=languagecode,
            countrycode=countrycode,
        )

        data = _booking_get("google_flight", FLIGHT_SEARCH_ENDPOINT, params)

        if isinstance(data, dict) and data.get("error"):
            return [{"error": data["error"]}]

        top_raw, other_raw = _extract_top_other(data)
        outbound_top = _normalize_flight_offer(2, top_raw, retun_assign=True)
        outbound_other = _normalize_flight_offer(2, other_raw, retun_assign=True)

        dep_after = dep_before = arr_after = arr_before = None
        if preferred_departure_time:
            dep_after, dep_before = _time_range_from_center(
                preferred_departure_time, time_tolerance_minutes
            )
        if preferred_arrival_time:
            arr_after, arr_before = _time_range_from_center(
                preferred_arrival_time, time_tolerance_minutes
            )

        if dep_after or dep_before or arr_after or arr_before:
            outbound_top = _filter_flights_by_time(
                outbound_top,
                departure_after=dep_after,
                departure_before=dep_before,
                arrival_after=arr_after,
                arrival_before=arr_before,
            )
            outbound_other = _filter_flights_by_time(
                outbound_other,
                departure_after=dep_after,
                departure_before=dep_before,
                arrival_after=arr_after,
                arrival_before=arr_before,
            )

        ret_dep_after = ret_dep_before = ret_arr_after = ret_arr_before = None
        if preferred_return_departure_time:
            ret_dep_after, ret_dep_before = _time_range_from_center(
                preferred_return_departure_time, time_tolerance_minutes
            )
        if preferred_return_arrival_time:
            ret_arr_after, ret_arr_before = _time_range_from_center(
                preferred_return_arrival_time, time_tolerance_minutes
            )

        def _fetch_inbound(outbound_offer: dict) -> list[dict]:
            """Call getNextFlights with next_token and pair return legs."""
            token = outbound_offer.get("next_token")
            if not token:
                return [
                    _outbound_only_pair(
                        outbound_offer,
                        warning="Không có next_token; chỉ hiển thị chiều đi.",
                    )
                ]
            pairs: list[dict] = []
            try:
                ret_data = _booking_get(
                    "google_flight",
                    FLIGHT_NEXT_ENDPOINT,
                    _build_next_flights_params(
                        token,
                        currency_code=currency_code,
                        languagecode=languagecode,
                        countrycode=countrycode,
                    ),
                )
                if isinstance(ret_data, dict) and ret_data.get("error"):
                    return [
                        _outbound_only_pair(
                            outbound_offer,
                            warning=ret_data["error"],
                        )
                    ]
                ret_top, ret_other = _extract_top_other(ret_data)
                inbound = (
                    _normalize_flight_offer(1, ret_top, retun_assign=True)
                    + _normalize_flight_offer(1, ret_other, retun_assign=True)
                )
                if ret_dep_after or ret_dep_before or ret_arr_after or ret_arr_before:
                    inbound = _filter_flights_by_time(
                        inbound,
                        departure_after=ret_dep_after,
                        departure_before=ret_dep_before,
                        arrival_after=ret_arr_after,
                        arrival_before=ret_arr_before,
                    )
                if not inbound:
                    return [
                        _outbound_only_pair(
                            outbound_offer,
                            warning="Không tìm thấy chuyến về phù hợp; chỉ hiển thị chiều đi.",
                        )
                    ]
                for inb in inbound:
                    offer_id = f"FL-{uuid.uuid4().hex[:6].upper()}"
                    booking_token = inb.get("booking_token") or inb.get("detailToken")
                    pairs.append({
                        "Offer_ID": offer_id,
                        "price": inb.get("price"),
                        "booking_token": booking_token,
                        "detailToken": booking_token,
                        "next_token": inb.get("next_token"),
                        "inbound": {
                            key: value for key, value in inb.items()
                            if key not in ("detailToken", "next_token", "booking_token")
                        },
                        "outbound": {
                            key: value for key, value in outbound_offer.items()
                            if key not in ("returningToken", "next_token", "detailToken", "booking_token")
                        },
                    })
            except Exception as exc:
                return [
                    _outbound_only_pair(
                        outbound_offer,
                        warning=f"Không lấy được chuyến bay chiều về: {exc}",
                    )
                ]
            return pairs

        paired_top: list[dict] = []
        for o in outbound_top:
            paired_top.extend(_fetch_inbound(o))
        paired_other: list[dict] = []
        for o in outbound_other:
            paired_other.extend(_fetch_inbound(o))

        if not paired_top and not paired_other:
            if not outbound_top and not outbound_other:
                return _roundtrip_one_way_fallback(
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    return_date=return_date,
                    adults=adults,
                    children=children,
                    infant_on_lap=infant_on_lap,
                    infant_in_seat=infant_in_seat,
                    cabin_class=cabin_class,
                    sort_by=sort_by,
                    stops=stops,
                    limit=limit,
                    currency_code=currency_code,
                    languagecode=languagecode,
                    countrycode=countrycode,
                    alliances=alliances,
                    airlines=airlines,
                    carry_on_bag=carry_on_bag,
                    max_price=max_price,
                    emissions=emissions,
                    layover_duration=layover_duration,
                    airports=airports,
                    flight_duration=flight_duration,
                )

        return [{
            "source": "google_flights2_searchFlights",
            "topFlights": paired_top,
            "otherFlights": paired_other,
        }]

    except Exception as e:
        return [{"error": f"Lỗi khi gọi searchFlights: {str(e)}"}]

def _extract_booking_url(data: Any) -> str | None:
    """getBookingURL returns data as a URL string (sometimes wrapped in an object)."""
    if isinstance(data, str) and data.startswith(("http://", "https://")):
        return data
    if isinstance(data, dict):
        for key in ("url", "booking_url", "bookingLink", "link"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
    return None


def get_booking_link_from_api(
    detailToken: str,
    language: str = BOOKING_LANGUAGE_CODE,
    location: str = COUNTRY_CODE,
    currency: str = BOOKING_CURRENCY_CODE,
    adults: int = 1,
    children: int = 0,
    infantsOnLap: int = 0,
    infantsInSeat: int = 0,
    cabinClass: str = "economy",
    alliances: Optional[str] = None,
    airlines: Optional[str] = None,
    carryOnBag: int = 0,
    maxPrice: Optional[int] = None,
) -> dict:
    """
    Resolve partner booking links via getBookingDetails + getBookingURL.

    detailToken is the search/getNextFlights booking_token (kept name for agent compat).
    Extra kwargs (adults/cabin/...) are accepted but unused by the new API.
    """
    _ = (
        adults,
        children,
        infantsOnLap,
        infantsInSeat,
        cabinClass,
        alliances,
        airlines,
        carryOnBag,
        maxPrice,
    )

    if not detailToken:
        return {"error": "Bạn cần cung cấp detailToken (booking_token)."}

    try:
        details = _booking_get(
            "google_flight",
            FLIGHT_BOOKING_DETAILS_ENDPOINT,
            {
                "booking_token": detailToken,
                "currency": currency,
                "language_code": language,
                "country_code": location,
            },
        )
        if isinstance(details, dict) and details.get("error"):
            return {"error": details["error"]}

        partners: list[dict] = []
        if isinstance(details, list):
            partners = [p for p in details if isinstance(p, dict)]
        elif isinstance(details, dict):
            nested = details.get("data") or details.get("partners") or []
            if isinstance(nested, list):
                partners = [p for p in nested if isinstance(p, dict)]

        if not partners:
            return {
                "source": "google_flights2_getBookingDetails",
                "error": "Không tìm thấy đối tác booking cho chuyến bay này.",
                "booking_options": [],
            }

        options: list[dict] = []
        for partner in partners:
            partner_token = partner.get("token")
            if not partner_token:
                continue
            try:
                url_data = _booking_get(
                    "google_flight",
                    FLIGHT_BOOKING_URL_ENDPOINT,
                    {"token": partner_token},
                )
            except Exception:
                continue
            booking_link = _extract_booking_url(url_data)
            if not booking_link:
                continue
            title = partner.get("title") or partner.get("partner") or partner.get("id")
            website = partner.get("website") or partner.get("domain")
            options.append({
                "partner": title,
                "airlineName": title,
                "airline_id": partner.get("id"),
                "domain": website,
                "website": website,
                "bookingPrice": partner.get("price"),
                "bookingCurrency": currency,
                "is_airline": partner.get("is_airline"),
                "bookingLink": booking_link,
            })

        if not options:
            return {
                "source": "google_flights2_getBookingDetails",
                "error": "Không lấy được booking URL từ các đối tác.",
                "booking_options": [],
            }

        return {
            "source": "google_flights2_getBookingDetails",
            "booking_options": options,
        }
    except Exception as e:
        return {"error": f"Lỗi khi gọi getBookingDetails/getBookingURL: {str(e)}"}
