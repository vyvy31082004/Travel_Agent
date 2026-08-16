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


BOOKING_HOST = os.getenv(
    "BOOKING_RAPIDAPI_HOST",
    "booking-com15.p.rapidapi.com",
)
BOOKING_BASE_URL = f"https://{BOOKING_HOST}/api/v1"
BOOKING_LANGUAGE_CODE = os.getenv("BOOKING_LANGUAGE_CODE", "vi")
BOOKING_CURRENCY_CODE = os.getenv("BOOKING_CURRENCY_CODE", "VND")
COUNTRY_CODE = os.getenv("COUNTRY_CODE", "VN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

GOOGLE_FLIGHT_HOST = os.getenv("GOOGLE_FLIGHT_RAPIDAPI_HOST", "google-flights4.p.rapidapi.com")
GOOGLE_FLIGHT_BASE_URL = f"https://{GOOGLE_FLIGHT_HOST}"
# =========================
# FLIGHT ENDPOINTS
# Nếu endpoint trên RapidAPI khác, chỉ sửa 3 dòng này
# =========================

# FLIGHT_LOCATION_ENDPOINT = "/flights/searchAirport"
# FLIGHT_SEARCH_ENDPOINT = "/flights/searchFlights"
# FLIGHT_DETAILS_ENDPOINT = "/flights/getFlightDetails"




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


def _booking_get(header: str, path: str, params: dict, retries: int = 2) -> dict | list:
    if header == "booking":
        url = f"{BOOKING_BASE_URL}{path}"
    else:
        url = f"{GOOGLE_FLIGHT_BASE_URL}{path}"

    clean_params = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    print("CALL API:", url)
    print("PARAMS:", clean_params)

    last_exc: Exception = RuntimeError("Unknown error")
    for attempt in range(1, retries + 2):
        try:
            response = requests.get(
                url,
                headers=_get_headers(header),
                params=clean_params,
                timeout=40,
            )

            print("FINAL URL:", response.url)

            if response.status_code == 429:
                raise RuntimeError("RapidAPI bị giới hạn request. Hãy thử lại sau.")

            response.raise_for_status()
            payload = response.json()

            if isinstance(payload, dict) and payload.get("status") is False:
                raise RuntimeError(payload.get("message", "Booking API trả về lỗi."))

            if isinstance(payload, dict):
                return payload.get("data", payload)

            return payload

        except requests.exceptions.Timeout as exc:
            last_exc = exc
            print(f"Timeout on attempt {attempt}/{retries + 1}, retrying...")
            continue
        except requests.exceptions.HTTPError as exc:
            if response.status_code == 400:
                try:
                    error_data = response.json()
                    return {"error": error_data.get("message", "Lỗi từ API")}
                except Exception:
                    pass
            last_exc = exc
            print(f"HTTPError on attempt {attempt}/{retries + 1}: {exc}")
            continue
        except RuntimeError:
            raise

    raise last_exc


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
    """Normalize searchDestination payload to a list of location dicts."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("destinations", "products", "data", "airports"):
            nested = data.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _pick_best_airport(data: Any, query: str) -> dict | None:
    """
    Prefer exact IATA/city code match over Booking's default ranking.

    Booking searchDestination for 'HAN' can rank unrelated metros (e.g. TYO) first.
    """
    items = _as_location_list(data)
    if not items:
        return None

    q = (query or "").strip().upper()
    country = (COUNTRY_CODE or "").strip().upper()

    def _code(item: dict) -> str:
        return str(item.get("code") or item.get("id") or "").strip().upper()

    # Exact IATA / city code match (SGN, HAN, ...)
    if len(q) == 3 and q.isalpha():
        exact = [item for item in items if _code(item) == q]
        if exact:
            if country:
                in_country = [
                    item
                    for item in exact
                    if str(item.get("country") or item.get("countryCode") or "")
                    .strip()
                    .upper()
                    == country
                ]
                if in_country:
                    return in_country[0]
            return exact[0]

    # Prefer same-country results when searching by city name
    if country:
        in_country = [
            item
            for item in items
            if str(item.get("country") or item.get("countryCode") or "")
            .strip()
            .upper()
            == country
        ]
        if in_country:
            return in_country[0]

    return items[0]


def search_flight_location_from_api(
    query: str,
    languagecode: str = BOOKING_LANGUAGE_CODE,
) -> dict:
    """
    Tìm airport/city id cho flight.
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

    # Google Flights accepts IATA/city codes directly — avoid bad ranking from
    # searchDestination when the agent already passed SGN/HAN/etc.
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
            "booking",
            "/flights/searchDestination",
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
        airport_code = airport.get("code")
        airport_name = airport.get("name")
        city = airport.get("city")
        country = airport.get("country")
        return {
            "source": "booking_com15_rapidapi",
            "query": query,
            "id": airport_id,
            "code": airport_code,
            "name": airport_name,
            "city": city,
            "country": country,
            "raw": airport,
        }

    except Exception as e:
        return {
            "error": f"Lỗi khi gọi flight searchDestination: {str(e)}"
        }




def _normalize_flight_offer(choice: 1|2, flight_offers: list[dict], retun_assign: True|False) -> list[dict]:
    """
    Chuẩn hóa flight offers từ Google Flights2 API.

    Cấu trúc thực tế của API:
    - price, detailToken, airlineCode, airlineNames ở cấp offer
    - segments[]: mỗi leg có departureAirportCode/Name, arrivalAirportCode/Name,
                  departureTime (HH:MM), arrivalTime, durationMinutes,
                  airline.flightNumber, aircraftName, overnight
    choice = 1 -> one way
    choice = 2 -> round way
    """
    if not flight_offers:
        return []
    if not choice:
        return [{"error": "Bạn cần chọn loại chuyến bay: 1 -> one way, 2 -> round way"}]
    if choice not in [1, 2]:
        return [{"error": "Bạn cần chọn loại chuyến bay: 1 -> one way, 2 -> round way"}]
    result = []
    for offer in flight_offers:
        segments = offer.get("segments") or []
        if not segments:
            continue
        # first_seg = segments[0]
        # last_seg = segments[-1]
        # first_airline = first_seg.get("airline") or {}
        normalized_segments = [
                {
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
                    "flight_number": (seg.get("airline") or {}).get("flightNumber"),
                    "airline_code": (seg.get("airline") or {}).get("airlineCode"),
                    "airline_name": (seg.get("airline") or {}).get("airlineName"),
                    "aircraftName": seg.get("aircraftName"),
                    "flight_ID": seg.get("flightId"),
                    "seat_width": seg.get("seatWidth"),
                }
                for seg in segments
            ]
        flight_info = {}
        if choice == 1:
            if retun_assign == False:
                offer_id = f"FL-{uuid.uuid4().hex[:6].upper()}"
                flight_info["Offer_ID"] = offer_id
            flight_info.update({
                "price": offer.get("price"),
                "airline_code": offer.get("airlineCode"),
                "airline_name": offer.get("airlineNames"),
                "stops": offer.get("stops"),
                "duration_minutes": offer.get("duration"),
                "departure_time": offer.get("departureTime"),
                "departure_date": offer.get("departureDate"),
                "arrival_time": offer.get("arrivalTime"),
                "arrival_date": offer.get("arrivalDate"),
                "departure_airport_code": offer.get("departureAirportCode"),
                "arrival_airport_code": offer.get("arrivalAirportCode"),
                "segments": normalized_segments,
            })
            # Nếu choice == 1, tạo bản sao (hoặc thêm trực tiếp) khóa detailToken
            result.append({
                **flight_info,
                "detailToken": offer.get("detailToken")
            })
        elif choice == 2:
            flight_info = {
                "price": offer.get("price"),
                "airline_code": offer.get("airlineCode"),
                "airline_name": offer.get("airlineNames"),
                "stops": offer.get("stops"),
                "duration_minutes": offer.get("duration"),
                "departure_time": offer.get("departureTime"),
                "departure_date": offer.get("departureDate"),
                "arrival_time": offer.get("arrivalTime"),
                "arrival_date": offer.get("arrivalDate"),
                "departure_airport_code": offer.get("departureAirportCode"),
                "arrival_airport_code": offer.get("arrivalAirportCode"),
                "segments": normalized_segments,
            }

            result.append({
                **flight_info,
                "returningToken": offer.get("returningToken")
            })
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
    """economy→1, premium_economy→2, business→3, first→4"""
    mapping = {
        "economy": "1",
        "premium economy": "2",
        "premium_economy": "2",
        "business": "3",
        "first": "4",
    }
    return mapping.get(cabin_class.lower().strip(), "1")


def _map_sort_by(sort_by: str) -> str:
    """top/best→1, price→2, departure_time→3, arrival_time→4, duration→5, emissions→6"""
    mapping = {
        "top": "1",
        "best": "1",
        "price": "2",
        "cheap": "2",
        "departure_time": "3",
        "departure": "3",
        "arrival_time": "4",
        "arrival": "4",
        "duration": "5",
        "emissions": "6",
    }
    return mapping.get(sort_by.lower().strip(), "1")



def _parse_flight_time(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%d-%m-%Y %I:%M %p", "%Y-%m-%d %H:%M", "%H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
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
    # preferred_return_departure_time: Optional[str] = None,
    # preferred_return_arrival_time: Optional[str] = None,
    time_tolerance_minutes: int = 60,
    limit: int = 10,
) -> list[dict]:
    """
    Tìm kiếm chuyến bay một chiều.
    cabinClass: economy/premium_economy/business/first → 1/2/3/4
    sort_by: best/price/departure_time/arrival_time/duration/emissions → 1-6
    stops: "0"=any, "1"=nonstop, "2"=1 stop or fewer, "3"=2 stops or fewer
    preferred_departure_time: "HH:MM" — lọc trong khoảng ±time_tolerance_minutes (mặc định ±60 phút)
    preferred_arrival_time: "HH:MM" — lọc trong khoảng ±time_tolerance_minutes
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
            return [{"error": "Không tìm được mã sân bay đi (departureId)."}]
        if not arrival_id:
            return [{"error": "Không tìm được mã sân bay đến (arrivalId)."}]

        params = {
            "departureId":    departure_id,
            "arrivalId":      arrival_id,
            "departureDate":  departure_date,
            "adults":         str(adults),
            "children":       str(children),
            "infantsOnLap":   str(infant_on_lap),
            "infantsInSeat":  str(infant_in_seat),
            "cabinClass":     _map_cabin_class(cabin_class),
            "sort":           _map_sort_by(sort_by),
            "stops":          str(stops),
            "currency":       currency_code,
            "language":       languagecode,
            "location":       countrycode,
            "carryOnBag":     str(carry_on_bag),
            "maxPrice":       str(max_price) if max_price is not None else None,
            "emissions":      str(emissions),
            "alliances":      alliances,
            "airlines":       _resolve_airline_codes(airlines),
            "layoverDuration": layover_duration,
            "airports":       airports,
            "flightDuration": flight_duration,
        }


        data = _booking_get("google_flight", "/flights/search-one-way", params)

        top = _normalize_flight_offer(1, data.get("topFlights") or [], retun_assign=False)
        other = _normalize_flight_offer(1, data.get("otherFlights") or [], retun_assign=False)

        # --- Lọc theo giờ bay nếu user chỉ định ---
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
            "source": "google-flights4.p.rapidapi",
            "topFlights": top,
            "otherFlights": other[:limit],
        }]

    except Exception as e:
        return [{"error": f"Lỗi khi gọi searchFlights: {str(e)}"}]

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
    # --- Lọc theo giờ bay (post-filter) ---
    preferred_departure_time: Optional[str] = None,       # Giờ khởi hành chiều đi
    preferred_arrival_time: Optional[str] = None,         # Giờ hạ cánh chiều đi
    preferred_return_departure_time: Optional[str] = None, # Giờ khởi hành chiều về
    preferred_return_arrival_time: Optional[str] = None,   # Giờ hạ cánh chiều về
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
            return [{"error": "Không tìm được mã sân bay đi (departureId)."}]
        if not arrival_id:
            return [{"error": "Không tìm được mã sân bay đến (arrivalId)."}]

        params = {
            "departureId":    departure_id,
            "arrivalId":      arrival_id,
            "departureDate":  departure_date,
            "arrivalDate":    return_date,
            "adults":         str(adults),
            "children":       str(children),
            "infantsOnLap":   str(infant_on_lap),
            "infantsInSeat":  str(infant_in_seat),
            "cabinClass":     _map_cabin_class(cabin_class),
            "sort":           _map_sort_by(sort_by),
            "stops":          str(stops),
            "currency":       currency_code,
            "language":       languagecode,
            "location":       countrycode,
            "carryOnBag":     str(carry_on_bag),
            "maxPrice":       str(max_price) if max_price is not None else None,
            "emissions":      str(emissions),
            "alliances":      alliances,
            "airlines":       _resolve_airline_codes(airlines),
            "layoverDuration": layover_duration,
            "airports":       airports,
            "flightDuration": flight_duration,
        }
        # params["returnDate"] = return_date

        data = _booking_get("google_flight", "/flights/search-roundtrip", params)

        outbound_top = _normalize_flight_offer(2, data.get("topFlights") or [], retun_assign=True)
        outbound_other = _normalize_flight_offer(2, data.get("otherFlights") or [], retun_assign=True)


        # --- Lọc giờ chiều đi ---
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
                arrival_before=arr_before,) 
        inbound_params_base = {
            "arrivalDate":    return_date,
            "language":       languagecode,
            "location":       countrycode,
            "currency":       currency_code,
            "adults":         str(adults),
            "children":       str(children),
            "infantsOnLap":   str(infant_on_lap),
            "infantsInSeat":  str(infant_in_seat),
            "cabinClass":     _map_cabin_class(cabin_class),
            "sort":           _map_sort_by(sort_by),
            "stops":          str(stops),
            "alliances":      alliances,
            "carryOnBag":     str(carry_on_bag),
            "maxPrice":       str(max_price) if max_price is not None else None,
            "emissions":      str(emissions),
            "airlines":       _resolve_airline_codes(airlines),
            "layoverDuration": layover_duration,
            "airports":       airports,
            "flightDuration": flight_duration,
        }

        #Lọc giờ chiều về
        ret_dep_after = ret_dep_before = ret_arr_after = ret_arr_before = None
        if preferred_return_departure_time:
            ret_dep_after, ret_dep_before = _time_range_from_center(
                preferred_return_departure_time, time_tolerance_minutes
            )
        if preferred_return_arrival_time:
            ret_arr_after, ret_arr_before = _time_range_from_center(
                preferred_return_arrival_time, time_tolerance_minutes
            )


        def _fetch_inbound(outbound_offer: dict) -> dict:
            """Gọi roundtrip-returning và ghép chuyến về vào chuyến đi tương ứng."""
            token = outbound_offer.get("returningToken")
            if not token:
                return {**outbound_offer, "inbound_options": []}
            try:
                ret_data = _booking_get("google_flight", "/flights/roundtrip-returning", {
                    "returningToken": token,
                    **inbound_params_base,
                })
                # inbound = (
                #     _normalize_flight_offer(2, ret_data.get("topFlights") or []) +
                #     _normalize_flight_offer(2, ret_data.get("otherFlights") or [])
                # )
                pairs = []
                inbound = (
                    _normalize_flight_offer(1, ret_data.get("topFlights") or [], retun_assign=True) +
                    _normalize_flight_offer(1, ret_data.get("otherFlights") or [], retun_assign=True)
                )
                if ret_dep_after or ret_dep_before or ret_arr_after or ret_arr_before:
                    inbound = _filter_flights_by_time(
                        inbound,
                        departure_after=ret_dep_after,
                        departure_before=ret_dep_before,
                        arrival_after=ret_arr_after,
                        arrival_before=ret_arr_before,
                    )
                for inb in inbound:
                    offer_id = f"FL-{uuid.uuid4().hex[:6].upper()}"
                    pairs.append({
                        "Offer_ID": offer_id,
                        "price": inb.get("price"),
                        "detailToken": inb.get("detailToken"),
                        "inbound": {
                            k: v for k, v in inb.items()
                            if k not in ("detailToken")
                        },
                        "outbound": {
                            k: v for k, v in outbound_offer.items()
                            if k not in ("returningToken")
                        },
                    })
                


            except Exception as exc:
                inbound = [{"error": f"Không lấy được chuyến bay chiều về: {str(exc)}"}]
            return pairs 

        # paired_top   = [_fetch_inbound(o) for o in outbound_top]
        paired_top = []
        for o in outbound_top:
            paired_top.extend(_fetch_inbound(o))
        paired_other = []
        for o in outbound_other:
            paired_other.extend(_fetch_inbound(o))

       

        # # --- Lọc giờ chiều về (bên trong inbound_options của mỗi cặp) ---
        # ret_dep_after = ret_dep_before = ret_arr_after = ret_arr_before = None
        # if preferred_return_departure_time:
        #     ret_dep_after, ret_dep_before = _time_range_from_center(
        #         preferred_return_departure_time, time_tolerance_minutes
        #     )
        # if preferred_return_arrival_time:
        #     ret_arr_after, ret_arr_before = _time_range_from_center(
        #         preferred_return_arrival_time, time_tolerance_minutes
        #     )

        # if ret_dep_after or ret_dep_before or ret_arr_after or ret_arr_before:
        #     for pair in paired_top + paired_other:
        #         pair["inbound_options"] = _filter_flights_by_time(
        #             pair.get("inbound_options") or [],
        #             outbound_departure_after=ret_dep_after,
        #             outbound_departure_before=ret_dep_before,
        #             outbound_arrival_after=ret_arr_after,
        #             outbound_arrival_before=ret_arr_before,
        #         )
        return [{
            "source": "google-flights4.p.rapidapi",
            "topFlights": paired_top,
            "otherFlights": paired_other,
        }]

    except Exception as e:
        return [{"error": f"Lỗi khi gọi searchFlights: {str(e)}"}]

def _normalize_get_booking_result(data: dict) -> dict:
    if "error" in data:
        return data
    options = data.get("bookingOptions") or []
    result = []
    for op in options:
        booking_link = op.get("bookingLink") or []
        for link in booking_link:
            booking_price = op.get("listedPrice") or {}
            result.append({
                "bookingLink": link.get("link"),
                "bookingPrice": booking_price.get("price") or op.get("totalPrice"),
                "bookingCurrency": booking_price.get("currency") or "VND",
                "airlineName": op.get("airlineName"),
                "flightNumber": op.get("flightNumber"),
                "domain": op.get("domain"),
            })
    return {
        "source": "google-flights4.p.rapidapi",
        "booking_options": result,
        "status": data.get("status"),
        "message": data.get("message"),
    }

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
    Lấy kết quả booking từ API.
    """
    if not detailToken:
        return [{"error": "Bạn cần cung cấp detailToken."}]
    try:
        params = {
            "detailToken": detailToken,
            "language": language,
            "location": location,
            "currency": currency,
            "adults": str(adults),
            "children": str(children),
            "infantsOnLap": str(infantsOnLap),
            "infantsInSeat": str(infantsInSeat),
            "cabinClass": _map_cabin_class(cabinClass),
            "alliances": alliances,
            "airlines": _resolve_airline_codes(airlines),
            "carryOnBag": str(carryOnBag),
            "maxPrice": str(maxPrice) if maxPrice is not None else None,
        }
        data = _booking_get("google_flight", "/flights/get-booking-results", params)
        return _normalize_get_booking_result(data)
    except Exception as e:
        return [{"error": f"Lỗi khi gọi get-booking-results: {str(e)}"}] 