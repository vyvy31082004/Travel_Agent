import os
import requests
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, Range
from sentence_transformers import SentenceTransformer
import uuid
import unicodedata
from utils.utils import to_date
# Load environment variables from .env file
from datetime import datetime, timedelta
load_dotenv()
from functools import lru_cache
from datetime import date, datetime
from typing import Any, Optional
import unicodedata 

# =========================
# BOOKING / RAPIDAPI CONFIG
# =========================

BOOKING_HOST = os.getenv(
    "BOOKING_RAPIDAPI_HOST",
    "booking-com15.p.rapidapi.com",
)
BOOKING_BASE_URL = f"https://{BOOKING_HOST}/api/v1"
BOOKING_LANGUAGE_CODE = os.getenv("BOOKING_LANGUAGE_CODE", "vi")
BOOKING_CURRENCY_CODE = os.getenv("BOOKING_CURRENCY_CODE", "VND")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")


# =========================
# FLIGHT ENDPOINTS
# Nếu endpoint trên RapidAPI khác, chỉ sửa 3 dòng này
# =========================

FLIGHT_LOCATION_ENDPOINT = "/flights/searchDestination"
FLIGHT_SEARCH_ENDPOINT = "/flights/searchFlights"
FLIGHT_DETAILS_ENDPOINT = "/flights/getFlightDetails"


# =========================
# COMMON HELPERS
# =========================

def _compact_params(params: dict[str, Any]) -> dict[str, Any]:
    """
    Bỏ các param None, "", [] để tránh gửi query rỗng lên API.
    """
    return {
        key: value
        for key, value in params.items()
        if value is not None and value != "" and value != []
    }


def _booking_headers() -> dict:
    if not RAPIDAPI_KEY:
        raise RuntimeError("Thiếu RAPIDAPI_KEY trong file .env")

    return {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": BOOKING_HOST,
    }


def _booking_get(path: str, params: dict) -> dict | list:
    url = f"{BOOKING_BASE_URL}{path}"

    clean_params = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    print("CALL API:", url)
    print("PARAMS:", clean_params)

    response = requests.get(
        url,
        headers=_booking_headers(),
        params=clean_params,
        timeout=20,
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


def _pick_first_value(data: Any, keys: list[str], default: Any = None) -> Any:
    """
    Lấy giá trị đầu tiên tồn tại trong dict.
    """
    if not isinstance(data, dict):
        return default

    for key in keys:
        value = data.get(key)
        if value is not None:
            return value

    return default


def _get_first_list(data: Any, keys: list[str]) -> list:
    """
    Lấy list từ response có cấu trúc thay đổi.
    Chỉ tìm ở level hiện tại và data level.
    """
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value

    nested_data = data.get("data")

    if isinstance(nested_data, list):
        return nested_data

    if isinstance(nested_data, dict):
        for key in keys:
            value = nested_data.get(key)
            if isinstance(value, list):
                return value

    return []


def _find_first_list_recursive(data: Any, keys: list[str]) -> list:
    """
    Tìm list trong response JSON, kể cả khi list nằm sâu nhiều lớp.
    """
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value

        for value in data.values():
            result = _find_first_list_recursive(value, keys)
            if result:
                return result

    elif isinstance(data, list):
        for item in data:
            result = _find_first_list_recursive(item, keys)
            if result:
                return result

    return []


def _find_url_recursive(data: Any) -> Optional[str]:
    """
    Tìm booking_url/url/deeplink trong response.
    """
    url_keys = [
        "url",
        "booking_url",
        "bookingUrl",
        "deeplink",
        "deepLink",
        "shareUrl",
        "share_url",
        "link",
    ]

    if isinstance(data, dict):
        for key in url_keys:
            value = data.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value

        for value in data.values():
            result = _find_url_recursive(value)
            if result:
                return result

    elif isinstance(data, list):
        for item in data:
            result = _find_url_recursive(item)
            if result:
                return result

    return None


# =========================
# FLIGHT LOCATION
# =========================

def search_flight_location_from_api(
    query: str,
    languagecode: str = BOOKING_LANGUAGE_CODE,
) -> dict:
    """
    Tìm airport/city id cho flight.

    Ví dụ:
    - query = "Ho Chi Minh"
    - query = "SGN"
    - query = "Da Nang"
    - query = "DAD"
    """

    if not query:
        return {
            "error": "Bạn cần cung cấp điểm đi hoặc điểm đến."
        }

    try:
        data = _booking_get(
            FLIGHT_LOCATION_ENDPOINT,
            _compact_params(
                {
                    "query": query,
                    "languagecode": languagecode,
                }
            ),
        )

        locations = _find_first_list_recursive(
            data,
            keys=[
                "data",
                "results",
                "items",
                "airports",
                "destinations",
                "locations",
            ],
        )

        if not locations:
            return {
                "error": f"Không tìm được flight location cho '{query}'.",
                "raw": data,
            }

        best = locations[0]

        location_id = _pick_first_value(
            best,
            [
                "id",
                "dest_id",
                "destination_id",
                "airport_id",
                "city_id",
                "code",
                "iataCode",
                "iata",
            ],
        )

        code = _pick_first_value(
            best,
            [
                "code",
                "iataCode",
                "iata",
                "airportCode",
            ],
        )

        return {
            "source": "booking_com15_rapidapi",
            "query": query,
            "id": location_id,
            "code": code,
            "name": _pick_first_value(
                best,
                [
                    "name",
                    "displayName",
                    "cityName",
                    "airportName",
                    "label",
                ],
            ),
            "city": _pick_first_value(
                best,
                [
                    "city",
                    "cityName",
                ],
            ),
            "country": _pick_first_value(
                best,
                [
                    "country",
                    "countryName",
                ],
            ),
            "raw": best,
        }

    except Exception as e:
        return {
            "error": f"Lỗi khi gọi flight searchDestination: {str(e)}"
        }


# =========================
# NORMALIZE FLIGHT RESULT
# =========================

def _normalize_flight_segment(segment: Any) -> dict:
    """
    Chuẩn hóa từng chặng bay nhỏ.
    Ví dụ: SGN -> HAN.
    """

    if not isinstance(segment, dict):
        return {
            "raw": segment
        }

    return {
        "airline": _pick_first_value(
            segment,
            [
                "airline",
                "airlineName",
                "carrierName",
                "marketingCarrier",
            ],
        ),
        "flight_number": _pick_first_value(
            segment,
            [
                "flightNumber",
                "flight_number",
                "number",
            ],
        ),
        "departure_airport": _pick_first_value(
            segment,
            [
                "departureAirport",
                "departure_airport",
                "from",
                "origin",
            ],
        ),
        "arrival_airport": _pick_first_value(
            segment,
            [
                "arrivalAirport",
                "arrival_airport",
                "to",
                "destination",
            ],
        ),
        "departure_time": _pick_first_value(
            segment,
            [
                "departureTime",
                "departure_time",
                "departTime",
                "depart_at",
            ],
        ),
        "arrival_time": _pick_first_value(
            segment,
            [
                "arrivalTime",
                "arrival_time",
                "arriveTime",
                "arrive_at",
            ],
        ),
        "duration": _pick_first_value(
            segment,
            [
                "duration",
                "durationMinutes",
                "durationInMinutes",
            ],
        ),
        "raw": segment,
    }


def _normalize_flight_offer(offer: Any) -> dict:
    """
    Chuẩn hóa một flight offer.
    Giữ raw để debug vì mỗi API có thể trả field khác nhau.
    """

    if not isinstance(offer, dict):
        return {
            "raw": offer
        }

    detail_token = _pick_first_value(
        offer,
        [
            "token",
            "flightToken",
            "bookingToken",
            "itineraryToken",
            "detailToken",
        ],
    )

    offer_id = _pick_first_value(
        offer,
        [
            "id",
            "offerId",
            "flightId",
            "itineraryId",
            "token",
            "flightToken",
            "bookingToken",
        ],
    )

    segments_raw = _find_first_list_recursive(
        offer,
        keys=[
            "segments",
            "legs",
            "routes",
            "flights",
        ],
    )

    segments = [
        _normalize_flight_segment(segment)
        for segment in segments_raw
    ]

    return {
        "source": "booking_com15_rapidapi",
        "offer_id": offer_id,
        "detail_token": detail_token,
        "airline": _pick_first_value(
            offer,
            [
                "airline",
                "airlineName",
                "carrierName",
                "mainAirline",
            ],
        ),
        "departure_time": _pick_first_value(
            offer,
            [
                "departureTime",
                "departure_time",
                "departTime",
            ],
        ),
        "arrival_time": _pick_first_value(
            offer,
            [
                "arrivalTime",
                "arrival_time",
                "arriveTime",
            ],
        ),
        "duration": _pick_first_value(
            offer,
            [
                "duration",
                "durationMinutes",
                "durationInMinutes",
            ],
        ),
        "stops": _pick_first_value(
            offer,
            [
                "stops",
                "numberOfStops",
                "stopCount",
            ],
        ),
        "price": _pick_first_value(
            offer,
            [
                "price",
                "totalPrice",
                "total_price",
                "priceBreakdown",
                "amount",
            ],
        ),
        "currency": _pick_first_value(
            offer,
            [
                "currency",
                "currencyCode",
                "currency_code",
            ],
        ),
        "booking_url": _find_url_recursive(offer),
        "segments": segments,
        "raw": offer,
    }


# =========================
# SEARCH FLIGHTS
# =========================

def search_flights_from_api(
    origin: str,
    destination: str,
    departure_date: Optional[str] = None,
    return_date: Optional[str] = None,
    trip_type: str = "one_way",
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    cabin_class: str = "economy",
    sort_by: str = "best",
    page: int = 1,
    currency_code: str = BOOKING_CURRENCY_CODE,
    languagecode: str = BOOKING_LANGUAGE_CODE,
    limit: int = 10,
) -> list[dict]:
    """
    Search flights theo điểm đi, điểm đến, ngày bay.

    Flight khác attraction:
    - Không search nếu thiếu departure_date.
    - Không tự gán ngày mặc định.
    - Nếu user chưa nhập ngày, trả error để agent hỏi lại ngày bay.

    Flow:
    1. origin -> /flights/searchDestination -> lấy origin id/code
    2. destination -> /flights/searchDestination -> lấy destination id/code
    3. gọi /flights/searchFlights
    4. normalize kết quả flight offers
    """

    if not origin:
        return [
            {
                "error": "Bạn cần cung cấp điểm đi."
            }
        ]

    if not destination:
        return [
            {
                "error": "Bạn cần cung cấp điểm đến."
            }
        ]

    if not departure_date:
        return [
            {
                "error": "Bạn cần cung cấp ngày bay departure_date để tìm chuyến bay."
            }
        ]

    if adults < 1:
        return [
            {
                "error": "Số người lớn adults phải >= 1."
            }
        ]

    if page < 1:
        return [
            {
                "error": "page phải >= 1."
            }
        ]

    if limit < 1:
        return [
            {
                "error": "limit phải >= 1."
            }
        ]

    try:
        parsed_departure_date = _parse_date(departure_date)
        parsed_return_date = _parse_date(return_date)

        if trip_type not in ["one_way", "round_trip"]:
            return [
                {
                    "error": "trip_type chỉ nhận 'one_way' hoặc 'round_trip'."
                }
            ]

        if trip_type == "round_trip":
            if not parsed_return_date:
                return [
                    {
                        "error": "Vé khứ hồi cần có return_date."
                    }
                ]

            if parsed_return_date < parsed_departure_date:
                return [
                    {
                        "error": "return_date phải sau hoặc bằng departure_date."
                    }
                ]

        origin_info = search_flight_location_from_api(
            origin,
            languagecode=languagecode,
        )

        if origin_info.get("error"):
            return [origin_info]

        destination_info = search_flight_location_from_api(
            destination,
            languagecode=languagecode,
        )

        if destination_info.get("error"):
            return [destination_info]

        origin_id = origin_info.get("id") or origin_info.get("code")
        destination_id = destination_info.get("id") or destination_info.get("code")

        if not origin_id:
            return [
                {
                    "error": f"Không lấy được origin id/code cho '{origin}'.",
                    "raw": origin_info,
                }
            ]

        if not destination_id:
            return [
                {
                    "error": f"Không lấy được destination id/code cho '{destination}'.",
                    "raw": destination_info,
                }
            ]

        params = _compact_params(
            {
                "fromId": origin_id,
                "toId": destination_id,
                "departDate": parsed_departure_date,
                "returnDate": parsed_return_date if trip_type == "round_trip" else None,
                "tripType": trip_type,
                "adults": adults,
                "children": children,
                "infants": infants,
                "cabinClass": cabin_class,
                "sortBy": sort_by,
                "page": page,
                "currency_code": currency_code,
                "languagecode": languagecode,
            }
        )

        data = _booking_get(
            FLIGHT_SEARCH_ENDPOINT,
            params,
        )

        offers_raw = _find_first_list_recursive(
            data,
            keys=[
                "flights",
                "flightOffers",
                "offers",
                "itineraries",
                "results",
                "items",
                "data",
            ],
        )

        flights = [
            _normalize_flight_offer(offer)
            for offer in offers_raw
        ]

        return flights[:limit]

    except Exception as e:
        return [
            {
                "error": f"Lỗi khi gọi searchFlights: {str(e)}"
            }
        ]


# =========================
# FLIGHT DETAILS
# =========================

def fetch_flight_details_from_api(
    token: str,
    currency_code: str = BOOKING_CURRENCY_CODE,
    languagecode: str = BOOKING_LANGUAGE_CODE,
) -> dict:
    """
    Lấy chi tiết một flight offer.

    token lấy từ detail_token của kết quả search_flights_from_api.
    Không bắt user nhập token.
    """

    if not token:
        return {
            "error": "Bạn cần cung cấp token/detail_token của flight offer."
        }

    try:
        data = _booking_get(
            FLIGHT_DETAILS_ENDPOINT,
            _compact_params(
                {
                    "token": token,
                    "currency_code": currency_code,
                    "languagecode": languagecode,
                }
            ),
        )

        return {
            "source": "booking_com15_rapidapi",
            "token": token,
            "booking_url": _find_url_recursive(data),
            "details": data,
        }

    except Exception as e:
        return {
            "error": f"Lỗi khi lấy flight details: {str(e)}"
        }





















































# # Namespace for generating deterministic UUIDs from business keys
# NAMESPACE_UUID = uuid.uuid5(uuid.NAMESPACE_DNS, 'customer-support-agent.flight')


# def _normalize_vietnamese(text):
#     """Normalize Vietnamese text by removing diacritics for comparison"""
#     if not text:
#         return ""
#     # Replace Đ/đ with D/d first (these are separate characters, not composed)
#     text = text.replace('Đ', 'D').replace('đ', 'd')
#     # Normalize to NFD (decompose characters)
#     nfd = unicodedata.normalize('NFD', text)
#     # Remove combining characters (diacritics)
#     return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn').lower().strip()


# # Get credentials from environment variables
# BIN_ID_FLIGHT = os.getenv("BIN_ID_FLIGHT")
# API_KEY = os.getenv("API_KEY")
# USE_QDRANT = os.getenv("USE_QDRANT", "true").lower() == "true"  
# API_URL = f'https://api.jsonbin.io/v3/b/{BIN_ID_FLIGHT}'
# HEADERS = {
#   'Content-Type': 'application/json',
#   'X-Master-Key': API_KEY
# }


# # --- Caching Mechanism ---
# # This cache will hold the data in memory to avoid repeated API calls.
# _cache = None
# _qdrant_client = None
# _embedder = None
# _qdrant_initialized = False


# def _get_qdrant_client():
#     """Khởi tạo Qdrant client (kết nối tới instance persistent)"""
#     global _qdrant_client
#     if _qdrant_client is None:
#         # Kết nối tới Qdrant chạy trên Docker
#         _qdrant_client = QdrantClient(host="localhost", port=6333)
#     return _qdrant_client


# def _get_embedder():
#     """Khởi tạo sentence transformer model (multilingual)"""
#     global _embedder
#     if _embedder is None:
#         # Model hỗ trợ tiếng Việt, nhẹ, nhanh
#         _embedder = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
#     return _embedder


# def _init_qdrant_collections():
#     """Tạo các collection trong Qdrant nếu chưa tồn tại."""
#     global _qdrant_initialized
#     if _qdrant_initialized:
#         return
   
#     client = _get_qdrant_client()
#     embedder = _get_embedder()
   
#     vector_size = embedder.get_sentence_embedding_dimension()
#     collection_names = ["flights_v2","flight_prices","passengers","bookings","tickets"]
   
#     for collection_name in collection_names:
#         try:
#             client.get_collection(collection_name=collection_name)
#             print(f"Collection '{collection_name}' already exists. Skipping creation.")
#         except Exception:
#             print(f"Collection '{collection_name}' not found. Creating...")
#             try:
#                 client.create_collection(
#                     collection_name=collection_name,
#                     vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
#                 )
#                 print(f" Collection '{collection_name}' created successfully.")
#             except Exception as e:
#                 print(f"Error: Could not create collection '{collection_name}': {e}")
   
#     _qdrant_initialized = True


# def _index_data_to_qdrant(data):
#     """
#     Index chỉ những dữ liệu mới vào Qdrant.
#     Hàm này sẽ kiểm tra các ID đã có và chỉ nạp những airports/airlines/flights/flight_prices/passengers/bookings/tickets chưa tồn tại.
#     """
#     if not USE_QDRANT:
#         return
   
#     client = _get_qdrant_client()
#     embedder = _get_embedder()
#     _init_qdrant_collections()


#     # --- Index Flights ---
#     collection_name_flights = "flights_v2"
#     try:
#         existing_flights_points = client.scroll(
#             collection_name=collection_name_flights,
#             limit=10000,
#             with_payload=False,
#             with_vectors=False
#         )[0]
#         existing_flights_ids = {point.id for point in existing_flights_points}
#         print(f"Found {len(existing_flights_ids)} existing flights points in Qdrant.")
#     except Exception as e:
#         print(f"Could not fetch existing flights points (collection might be new): {e}")
#         existing_flights_ids = set()


#     flights = data.get("flights", [])
#     # Convert flight_id to UUID for Qdrant compatibility
#     new_flights = []
#     for flight in flights:
#         point_id = str(uuid.uuid5(NAMESPACE_UUID, str(flight.get('flight_id'))))
#         if point_id not in existing_flights_ids:
#             new_flights.append(flight)
   
#     if not new_flights:
#         print(" Qdrant (Flights) is up-to-date. No new flights to index.")
#     else:
#         print(f"Indexing {len(new_flights)} new flights...")
#         flight_points = []
#         for flight in new_flights:
#             # Create a rich text for semantic vector
#             text_parts = [
#                 "chuyen bay",
#                 flight.get('flight_id', ''),
#                 flight.get('airline_id', ''),
#                 "tu", flight.get('city_depart', ''), flight.get('airport_name_depart', ''), flight.get('departure_airport_id', ''),
#                 "den", flight.get('city_arrive', ''), flight.get('airport_name_arrive', ''), flight.get('arrival_airport_id', '')
#             ]
#             text = " ".join(filter(None, text_parts))
#             vector = embedder.encode(text).tolist()
#             point_id = str(uuid.uuid5(NAMESPACE_UUID, str(flight.get('flight_id'))))
            
#             payload = flight.copy()
#             for key in ['departure_time', 'arrival_time']:
#                 if payload.get(key):
#                     try:
#                         # Convert "YYYY-MM-DD HH:MM" to ISO 8601 format "YYYY-MM-DDTHH:MM:SS"
#                         dt_obj = datetime.strptime(payload[key], "%Y-%m-%d %H:%M")
#                         payload[key] = dt_obj.isoformat()
#                     except ValueError:
#                         # Keep original if format is wrong, which will prevent datetime filtering
#                         pass

#             flight_points.append(PointStruct(id=point_id, vector=vector, payload=payload))


#         if flight_points:
#             try:
#                 client.upsert(collection_name=collection_name_flights, points=flight_points)
#                 print(f" Successfully indexed {len(flight_points)} flights to Qdrant.")
#             except Exception as e:
#                 print(f"Warning: Could not index new flights: {e}")


#     collection_name_flight_prices = "flight_prices"
#     try:
#         existing_flight_prices_points = client.scroll(
#             collection_name=collection_name_flight_prices,
#             limit=10000,
#             with_payload=False,
#             with_vectors=False
#         )[0]
#         existing_flight_prices_ids = {point.id for point in existing_flight_prices_points}
#         print(f"Found {len(existing_flight_prices_ids)} existing flight prices points in Qdrant.")
#     except Exception as e:
#         print(f"Could not fetch existing flight prices points (collection might be new): {e}")
#         existing_flight_prices_ids = set()


#     flight_prices = data.get("flightPrices", [])
   
#     new_flight_prices = []
#     for fp in flight_prices:
#         composite_id = f"{fp.get('flight_id')}-{fp.get('seat_type')}"
#         point_id = str(uuid.uuid5(NAMESPACE_UUID, composite_id))
#         if point_id not in existing_flight_prices_ids:
#             new_flight_prices.append(fp)


#     if not new_flight_prices:
#         print(" Qdrant (Flight Prices) is up-to-date. No flight prices to index.")
#     else:
#         print(f" Indexing {len(new_flight_prices)} flight prices...")
#         flight_price_points = []
#         for flight_price in new_flight_prices:
#             # Tạo ID tổng hợp từ flight_id và seat_type
#             composite_id = f"{flight_price.get('flight_id')}-{flight_price.get('seat_type')}"
#             point_id = str(uuid.uuid5(NAMESPACE_UUID, composite_id))
#             # Lấy thông tin chi tiết để tạo vector giàu ngữ nghĩa
#             text = f"{flight_price.get('flight_id')}{flight_price.get('seat_type')} {flight_price.get('price')} {flight_price.get('seat_quota')}"
#             vector = embedder.encode(text).tolist()
#             flight_price_points.append(PointStruct(id=point_id, vector=vector, payload=flight_price))


#         if flight_price_points:
#             try:
#                 client.upsert(collection_name=collection_name_flight_prices, points=flight_price_points)
#                 print(f" Successfully indexed {len(flight_price_points)} flight prices to Qdrant.")
#             except Exception as e:
#                 print(f"Warning: Could not index new flight prices: {e}")


#     # # --- Index Passengers ---
#     # collection_name_passengers = "passengers"
#     # try:
#     #     existing_passengers_points = client.scroll(
#     #         collection_name=collection_name_passengers,
#     #         limit=10000,  
#     #         with_payload=False,
#     #         with_vectors=False
#     #     )[0]
#     #     existing_passengers_ids = {point.id for point in existing_passengers_points}
#     #     print(f"Found {len(existing_passengers_ids)} existing passengers points in Qdrant.")
#     # except Exception as e:
#     #     print(f"Could not fetch existing passengers points (collection might be new): {e}")
#     #     existing_passengers_ids = set()


#     # passengers = data.get("passengers", [])
#     # new_passengers = [
#     #     p for p in passengers
#     #     if str(uuid.uuid5(NAMESPACE_UUID, p.get('passenger_id'))) not in existing_passengers_ids
#     # ]
   
#     # if not new_passengers:
#     #     print(" Qdrant (Passengers) is up-to-date. No new passengers to index.")
#     # else:
#     #     print(f"⏳ Found {len(new_passengers)} new passengers to index...")
#     #     passenger_points = []
#     #     for p in new_passengers:
#     #         text = f"{p.get('passenger_id')} {p.get('passenger_name')} {p.get('contact_data')}"
#     #         vector = embedder.encode(text).tolist()
#     #         point_id = str(uuid.uuid5(NAMESPACE_UUID, p.get('passenger_id')))
#     #         passenger_points.append(PointStruct(id=point_id, vector=vector, payload=p))
       
#     #     if passenger_points:
#     #         try:
#     #             client.upsert(collection_name=collection_name_passengers, points=passenger_points)
#     #             print(f" Successfully indexed {len(passenger_points)} new passengers to Qdrant.")
#     #         except Exception as e:
#     #             print(f"Warning: Could not index new passengers: {e}")


#     #--- Index Bookings ---
#     collection_name_bookings = "bookings"
#     try:
#         existing_bookings_points = client.scroll(
#             collection_name=collection_name_bookings,
#             limit=10000,
#             with_payload=False,
#             with_vectors=False
#         )[0]
#         existing_bookings_ids = {point.id for point in existing_bookings_points}
#         print(f"Found {len(existing_bookings_ids)} existing bookings points in Qdrant.")
#     except Exception as e:
#         print(f"Could not fetch existing bookings points (collection might be new): {e}")
#         existing_bookings_ids = set()


#     bookings = data.get("flightBookings", [])
#     new_bookings = [
#         b for b in bookings
#         if b.get('booking_id') and str(uuid.uuid5(NAMESPACE_UUID, str(b.get('booking_id')))) not in existing_bookings_ids
#     ]


#     if not new_bookings:
#         print(" Qdrant (Bookings) is up-to-date. No new bookings to index.")
#     else:
#         print(f"Indexing {len(new_bookings)} bookings...")
#         booking_points = []
#         for booking in new_bookings:
#             booking_id = booking.get('booking_id')
#             if not booking_id:
#                 print(f"Warning: Skipping booking without booking_id: {booking}")
#                 continue
            
#             text = f"{booking.get('booking_id')} {booking.get('booking_status')}"
#             vector = embedder.encode(text).tolist()
#             point_id = str(uuid.uuid5(NAMESPACE_UUID, str(booking_id)))
#             booking_points.append(PointStruct(id=point_id, vector=vector, payload=booking))


#         if booking_points:
#             try:
#                 client.upsert(collection_name=collection_name_bookings, points=booking_points)
#                 print(f" Successfully indexed {len(booking_points)} bookings to Qdrant.")
#             except Exception as e:
#                 print(f"Warning: Could not index new bookings: {e}")


#     #--- Index Tickets ---
#     collection_name_tickets = "tickets"
#     try:
#         existing_tickets_points = client.scroll(
#             collection_name=collection_name_tickets,
#             limit=10000,
#             with_payload=False,
#             with_vectors=False
#         )[0]
#         existing_tickets_ids = {point.id for point in existing_tickets_points}
#         print(f"Found {len(existing_tickets_ids)} existing tickets points in Qdrant.")
#     except Exception as e:
#         print(f"Could not fetch existing tickets points (collection might be new): {e}")
#         existing_tickets_ids = set()


#     tickets = data.get("tickets", [])
#     new_tickets = [
#         t for t in tickets
#         if t.get('ticket_id') and str(uuid.uuid5(NAMESPACE_UUID, t.get('ticket_id'))) not in existing_tickets_ids
#     ]


#     if not new_tickets:
#         print(" Qdrant (Tickets) is up-to-date. No new tickets to index.")
#     else:
#         print(f"Indexing {len(new_tickets)} tickets...")
#         ticket_points = []
#         for ticket in new_tickets:
#             ticket_id = ticket.get('ticket_id')
#             if not ticket_id:
#                 print(f"Warning: Skipping ticket without ticket_id: {ticket}")
#                 continue
            
#             text = f"{ticket.get('ticket_id')} {ticket.get('flight_id')} {ticket.get('seat_type')} {ticket.get('booking_id')}"
#             vector = embedder.encode(text).tolist()
#             point_id = str(uuid.uuid5(NAMESPACE_UUID, ticket_id))
#             ticket_points.append(PointStruct(id=point_id, vector=vector, payload=ticket))


#         if ticket_points:
#             try:
#                 client.upsert(collection_name=collection_name_tickets, points=ticket_points)
#                 print(f" Successfully indexed {len(ticket_points)} tickets to Qdrant.")
#             except Exception as e:
#                 print(f"Warning: Could not index new tickets: {e}")




# def _load_data():
#     global _cache
#     if _cache:
#         return _cache


#     if not BIN_ID_FLIGHT or not API_KEY:
#         raise ValueError("BIN_ID và API_KEY chưa được thiết lập trong file .env")
   
#     response = requests.get(f"{API_URL}/latest", headers=HEADERS)
#     response.raise_for_status()
   
#     data = response.json()['record']
#     _cache = data  
   
#     if USE_QDRANT:
#         _index_data_to_qdrant(data)
   
#     return data


# def _save_data(data):
#     global _cache, _qdrant_initialized
#     if not BIN_ID_FLIGHT or not API_KEY:
#         raise ValueError("BIN_ID và API_KEY chưa được thiết lập trong file .env")


#     response = requests.put(API_URL, json=data, headers=HEADERS)
#     response.raise_for_status()
   
#     _cache = data
    
#     if USE_QDRANT:
#         _index_data_to_qdrant(data)

# def search_flight_from_api(
#     departure_airport_code: str | None = None,
#     arrival_airport_code: str | None = None,
#     departure_time: str | None = None,
#     arrival_time: str | None = None,
#     city_depart: str| None = None,
#     city_arrive: str| None = None,
#     flight_no: str | None = None,
#     **kwargs
# ) -> list[dict]:
#     """
#     Search for flights based on departure airport name or code
#     or arrival airport name or code,
#     flight_no, city_depart, city_arrive, departure time or arrival time or date.
#     """
#     data = _load_data()
   
#     is_semantic_query = any([ city_depart, city_arrive, departure_time, arrival_time])
#     has_filters = any([departure_airport_code, arrival_airport_code, flight_no])


#     # Fallback if Qdrant is disabled
#     if not USE_QDRANT:
#         return _search_flight_exact(data,  departure_airport_code, arrival_airport_code, departure_time, arrival_time, flight_no, city_depart, city_arrive)
       
#     try:
#         client = _get_qdrant_client()
#         embedder = _get_embedder()


#         # --- Build Qdrant filters for exact match ---
#         must_conditions = []
#         if departure_airport_code:
#             must_conditions.append(
#                 FieldCondition(key="departure_airport_id", match=MatchValue(value=departure_airport_code))
#             )
#         if arrival_airport_code:
#             must_conditions.append(
#                 FieldCondition(key="arrival_airport_id", match=MatchValue(value=arrival_airport_code))
#             )

#         # if departure_time:
#         #     must_conditions.append(
#         #         FieldCondition(key="departure_time", match=MatchValue(value=departure_time))
#         #     )
#         # if arrival_time:
#         #     must_conditions.append(
#         #         FieldCondition(key="arrival_time", match=MatchValue(value=arrival_time))
#         #     )
        
#         if flight_no:
#             # Normalize flight_no before search
#             flight_no_clean = flight_no.strip().upper()
#             must_conditions.append(
#                 FieldCondition(key="flight_id", match=MatchValue(value=flight_no_clean))
#             )


#         # --- Decide Search Strategy ---
#         if is_semantic_query:
#             # 1. Semantic Search + Filtering
#             print("Executing semantic search with filters...")
#             query_parts = []
#             if city_depart: query_parts.append(city_depart)
#             if city_arrive: query_parts.append(city_arrive)
#             if departure_time: query_parts.append(to_date(departure_time))
#             if arrival_time: query_parts.append(to_date(arrival_time))
#             query_text = " ".join(query_parts)
#             query_vector = embedder.encode(query_text).tolist()


#             search_result = client.search(
#                 collection_name="flights_v2",
#                 query_vector=query_vector,
#                 query_filter=Filter(must=must_conditions) if must_conditions else None,
#                 limit=50
#             )
           
#             # Post-filter by city and date for more accurate results
#             results = []
            
#             results = [hit.payload for hit in search_result]
           
#             print(f"Qdrant semantic search: Found {len(results)} results")


#         elif has_filters:
#             # 2. Filter-Only Search
#             print("Executing filter-only search with Qdrant...")
#             scroll_result, _ = client.scroll(
#                 collection_name="flights_v2",
#                 scroll_filter=Filter(must=must_conditions),
#                 limit=200 # Get up to 200 results for filter-only
#             )
#             results = [record.payload for record in scroll_result]
#             print(f"Qdrant filter-only search: Found {len(results)} results")
       
#         else:
#             # 3. No criteria, fallback to exact search (which will return all)
#             return _search_flight_exact(data,  departure_airport_code, arrival_airport_code, departure_time, arrival_time, flight_no, city_depart, city_arrive)


#         return results
           
#     except Exception as e:
#         print(f"Qdrant search failed: {e}, falling back to exact search")
#         return _search_flight_exact(data,  departure_airport_code, arrival_airport_code, departure_time, arrival_time, flight_no, city_depart, city_arrive)


# def _search_flight_exact(data,  departure_airport_code, arrival_airport_code, departure_time, arrival_time, flight_no, city_depart, city_arrive):
#     """Fallback: Exact search with list comprehension (optimized single-pass)"""
#     results = data.get("flights", [])
   
#     # Normalize inputs
#     dep_code = departure_airport_code.upper().strip() if departure_airport_code else None
#     arr_code = arrival_airport_code.upper().strip() if arrival_airport_code else None
#     f_no = flight_no.lower().strip() if flight_no else None
#     dep_date = departure_time.strip() if departure_time else None
#     dep_city = city_depart.lower().strip() if city_depart else None
#     arr_city = city_arrive.lower().strip() if city_arrive else None


#     filtered = [
#         flight for flight in results
#         if (not dep_code or flight.get('departure_airport_id') == dep_code)
#         and (not arr_code or flight.get('arrival_airport_id') == arr_code)
#         and (not dep_city or dep_city in (flight.get('city_depart') or '').lower())
#         and (not arr_city or arr_city in (flight.get('city_arrive') or '').lower())
#         and (not dep_date or str(flight.get('departure_time', '')).startswith(dep_date))
#         and (not f_no or (
#             f_no in str(flight.get('flight_id', '')).lower()
#         ))
#     ]
   
#     print(f"Exact search (flights): Found {len(filtered)} results")
#     return filtered


# def fetch_flight_price_from_api(flight_id: str | None = None, seat_type: str | None = None) -> dict:
#     """
#     Fetch a flight price based on flight_id and seat_type.
#     Returns a single price dict, not a list.
#     """
#     data = _load_data()
#     if not USE_QDRANT:
#         result = _fetch_flight_price_exact(data, flight_id, seat_type)
#         return result[0] if result else {}
#     if not flight_id:
#         return "Please provide a valid flight_id."
#     try:
#         client = _get_qdrant_client()
#         embedder = _get_embedder()
#         if not seat_type:
#             return "Please provide a valid seat_type."
#         query_parts = []
#         query_parts.append(seat_type)
#         query_text = " ".join(query_parts)
#         query_vector = embedder.encode(query_text).tolist()
#         search_result = client.search(
#             collection_name="flight_prices",
#             query_vector=query_vector,
#             query_filter=Filter(must=[FieldCondition(key="flight_id", match=MatchValue(value=flight_id.upper().strip()))]),
#             limit = 1 
#         ) 
#         if search_result:
#            return search_result[0].payload
#     except Exception as e:
#         print(f" Qdrant search failed: {e}, falling back to exact search")
#         result = _fetch_flight_price_exact(data, flight_id, seat_type)
#         return result[0] if result else {}

# def _fetch_flight_price_exact(data, flight_id, seat_type):
#     """Fallback: Exact search with list comprehension (optimized single-pass)"""
#     results = data.get("flightPrices", [])
#     filtered = [
#         fp for fp in results
#         if (not flight_id or fp.get('flight_id') == flight_id)
#         and (not seat_type or seat_type in (fp.get('seat_type') or '').lower())
#     ]
#     print(f"Exact search (flight prices): Found {len(filtered)} results")
#     return filtered


# def search_flight_price_from_api(
#     flight_id: str | None = None,
#     seat_type: str | None = None,
# ) -> list[dict]:
#     """
#     Search for flight prices based on flight_id anf seat_types (eco, business, first). if seat_type is not provided, return all seat types.
#     """
#     data = _load_data()
#     if not USE_QDRANT:
#         return _search_flight_price_exact(data, flight_id, seat_type)
    
#     if not flight_id:
#         return "Please provide a flight_id."
    
#     try:
#         client = _get_qdrant_client()
#         embedder = _get_embedder()
#         query_parts = []
#         if seat_type:
#             query_parts.append(seat_type)
#         query_text = " ".join(query_parts)
        
#         query_vector = embedder.encode(query_text).tolist()
        
#         must_conditions = []
#         if flight_id:
#             must_conditions.append(
#                 FieldCondition(key="flight_id", match=MatchValue(value=flight_id.upper().strip()))
#             )

#         search_result = client.search(
#             collection_name="flight_prices",
#             query_vector=query_vector,
#             query_filter=Filter(must=must_conditions) if must_conditions else None,
#             limit= 1 if seat_type else 50  
#         )
        
#         results = [hit.payload for hit in search_result]
        
#         print(f" Qdrant semantic search: Found {len(results)} results")
#         return results
#     except Exception as e:
#         print(f" Qdrant search failed: {e}, falling back to exact search")
#         return _search_flight_price_exact(data, flight_id, seat_type)


# def _search_flight_price_exact(data, flight_id, seat_type):
#     """Fallback: Exact search with list comprehension (optimized single-pass)"""
#     results = data.get("flightPrices", [])
#     filtered = [
#         fp for fp in results
#         if (not flight_id or fp.get('flight_id') == flight_id)
#         and (not seat_type or seat_type in (fp.get('seat_type') or '').lower())
#     ]
#     print(f"Exact search (flight prices): Found {len(filtered)} results")
#     return filtered


# def generate_next_booking_id(bookings: list[dict], prefix="BKG") -> str:
#     """
#     Tạo booking_id tiếp theo theo định dạng 'BKG001', 'BKG002',...
#     """
#     if not bookings:
#         return f"{prefix}001"
    
#     max_num = 0
#     # Lặp qua các booking để tìm số lớn nhất
#     for b in bookings:
#         booking_id =  b.get('booking_id')
#         if isinstance(booking_id, str) and booking_id.startswith(prefix):
#             try:
#                 num_part = int(booking_id[len(prefix):])
#                 if num_part > max_num:
#                     max_num = num_part
#             except (ValueError, TypeError):
#                 # Bỏ qua nếu phần số không hợp lệ
#                 continue
#         elif isinstance(booking_id, int):
#             # Xử lý trường hợp booking_id cũ là số nguyên
#             if booking_id > max_num:
#                 max_num = booking_id

#     next_num = max_num + 1
#     # Định dạng số với 3 chữ số, ví dụ: 1 -> "001", 12 -> "012"
#     return f"{prefix}{next_num:03d}"





# def generate_next_ticket_no(tickets: list[dict], prefix="T") -> str:
#     """
#     Generate the next ticket number.
#     """
#     if not tickets:
#         return f"{prefix}001"
    
#     max_num = 0
#     for t in tickets:
#         ticket_no = t.get('ticket_no')
#         if isinstance(ticket_no, str) and ticket_no.startswith(prefix):
#             try:
#                 num_part = int(ticket_no[len(prefix):])
#                 if num_part > max_num:
#                     max_num = num_part
#             except (ValueError, TypeError):
#                 continue
    
#     next_num = max_num + 1
#     return f"{prefix}{next_num:03d}"

# def  book_flight_from_api(
#     flight_id: str | None = None,
#     seat_type: str | None = None,
#     passengers: int | None = None,
# ) -> str:
#     """
#     Book a flight based on flight_id and seat_type, passengers and price_per_person.
#     If passengers is not provided, book 1 passenger.
#     """
#     if not flight_id :
#         return "Please provide a valid flight_id."
#     if not seat_type:
#         return "Please provide a valid seat_type."
#     if not passengers or passengers <= 0:
#         passengers = 1

#     # Fetch price information
#     try:
#         price_info = fetch_flight_price_from_api(flight_id, seat_type)
#         print(f"DEBUG: price_info = {price_info}, type = {type(price_info)}")
#     except Exception as e:
#         return f"Error fetching price: {str(e)}"
    
#     if not price_info or isinstance(price_info, str):
#         return f"Could not find price information for flight {flight_id} with seat type {seat_type}."
    
#     total_price = price_info.get("price") * passengers
    
#     data = _load_data()
#     bookings = data.get("flightBookings", [])
#     tickets = data.get("tickets", [])
#     flight_prices = data.get("flightPrices", [])
    
#     new_booking_id = generate_next_booking_id(bookings)
    
#     new_booking = {
#         "booking_id": new_booking_id,
#         "total_price": total_price, 
#         "booking_status": "confirmed",
#         "num_ticket": passengers,
#         "created_at": datetime.now().strftime("%Y-%m-%d"),
        
#     }
#     bookings.append(new_booking)
#     data["flightBookings"] = bookings
    
#     seat_quota = int(price_info.get('seat_quota', 0))
#     if not seat_quota:
#         return f"Seat quota is not available in price_info: {price_info}"
#     if seat_quota < passengers:
#         return f"Seat quota is not enough for {passengers} passengers. Available: {seat_quota}"
#     else:
#         target_flight_id = str(flight_id).strip().upper()
#         target_seat_type = price_info.get('seat_type').strip().lower()
        
#         print(f"DEBUG: Looking for flight_id='{target_flight_id}', seat_type='{target_seat_type}'")
#         print(f"DEBUG: flight_prices has {len(flight_prices)} records")
        
#         updated = False
#         for i, fp in enumerate(flight_prices):
#             fp_flight_id = str(fp.get('flight_id', '')).strip().upper()
#             fp_seat_type = str(fp.get('seat_type', '')).strip().lower()
            
#             # print(f"DEBUG: Checking [{i}] flight_id='{fp_flight_id}', seat_type='{fp_seat_type}'")
            
#             if fp_flight_id == target_flight_id and fp_seat_type == target_seat_type:
#                 # Tìm thấy! Cập nhật trực tiếp vào object này (tham chiếu)
#                 old_quota = fp['seat_quota']
#                 fp['seat_quota'] = int(fp['seat_quota']) - passengers 
#                 updated = True
#                 print(f"DEBUG: FOUND! Updated seat_quota from {old_quota} to {fp['seat_quota']}")
                
#                 # Cập nhật cache ngay sau khi update quota
#                 global _cache
#                 if _cache and "flightPrices" in _cache:
#                     for cache_fp in _cache["flightPrices"]:
#                         if (str(cache_fp.get('flight_id', '')).strip().upper() == target_flight_id and 
#                             str(cache_fp.get('seat_type', '')).strip().lower() == target_seat_type):
#                             cache_fp['seat_quota'] = fp['seat_quota']
#                             print(f"DEBUG: Cache updated for {target_flight_id}/{target_seat_type}")
#                             break
                
#                 # Cập nhật Qdrant collection flight_prices
#                 if USE_QDRANT:
#                     try:
#                         client = _get_qdrant_client()
#                         embedder = _get_embedder()
                        
#                         # Tạo point ID giống như khi index
#                         composite_id = f"{target_flight_id}-{target_seat_type}"
#                         point_id = str(uuid.uuid5(NAMESPACE_UUID, composite_id))
                        
#                         # Tạo vector mới với quota đã cập nhật
#                         text = f"{fp.get('flight_id')}{fp.get('seat_type')} {fp.get('price')} {fp.get('seat_quota')}"
#                         vector = embedder.encode(text).tolist()
                        
#                         # Upsert point với payload mới
#                         client.upsert(
#                             collection_name="flight_prices",
#                             points=[PointStruct(id=point_id, vector=vector, payload=fp)]
#                         )
#                         print(f"DEBUG: Qdrant collection updated for {target_flight_id}/{target_seat_type}")
#                     except Exception as e:
#                         print(f"Warning: Could not update Qdrant collection: {e}")
                
#                 break
        
#         if not updated:
#             return f"Error: Could not find flight price record for {flight_id}/{seat_type} in database."
        
#         _save_data(data)
    
#     # Generate tickets
#     created_tickets = []
    
#     # Pre-fetch the latest ticket ID number to increment properly
#     # Get the max current ticket ID number
#     max_ticket_num = 0
#     if tickets:
#         for t in tickets:
#             t_id = t.get('ticket_id') or t.get('ticket_no') # Handle both keys for robustness
#             if isinstance(t_id, str) and t_id.startswith("T"):
#                 try:
#                     num_part = int(t_id[1:]) # Assuming T001 format
#                     if num_part > max_ticket_num:
#                         max_ticket_num = num_part
#                 except (ValueError, TypeError):
#                     continue
    
#     for i in range(passengers):
#         max_ticket_num += 1
#         new_ticket_no = f"T{max_ticket_num:03d}"
#         print(f"DEBUG: Generated ticket {i+1}: {new_ticket_no}")
        
#         new_ticket = {
#             "ticket_id": new_ticket_no,
#             "flight_id": flight_id,
#             "seat_type": seat_type,
#             "passenger_id": None,  # To be updated later
#             "booking_id": new_booking_id,
#             "ticket_status": "confirmed"
#         }
#         tickets.append(new_ticket)
#         created_tickets.append(new_ticket_no)
    
#     data["tickets"] = tickets
    
#     try:
#         _save_data(data)
#     except Exception as e:
#         return f"Error saving data: {str(e)}"
    
#     tickets_str = ", ".join(str(t) for t in created_tickets if t is not None)
#     return f"Booking confirmed with ID {new_booking_id}. Tickets created: {tickets_str}. Total price: {total_price} . Please provide passenger details for each ticket. The information of the passengers is in the format of a list of dictionaries with the following keys: passenger_name, date_of_birth, id_type, id_number, nationality."


# def generate_next_passenger_id(passengers: list[dict], prefix="P") -> str:
#     """
#     Generate the next passenger ID.
#     """
#     if not passengers:
#         return f"{prefix}001"
    
#     max_num = 0
#     for p in passengers:
#         p_id = p.get('passenger_id')
#         if isinstance(p_id, str) and p_id.startswith(prefix):
#             try:
#                 num_part = int(p_id[len(prefix):])
#                 if num_part > max_num:
#                     max_num = num_part
#             except (ValueError, TypeError):
#                 continue
    
#     next_num = max_num + 1
#     return f"{prefix}{next_num:03d}"


# def fetch_passenger_from_api(id_type: str = None, id_number: str = None, passenger_id: str = None) -> dict:
#     """
#     Fetch passenger information by ID type and number or passenger_id.
#     """
#     data = _load_data()
#     passengers = data.get("passengers", [])
    
#     if passenger_id:
#         passenger = next((p for p in passengers if p.get("passenger_id") == passenger_id), None)
#         return passenger
    
#     if id_type and id_number:
#         passenger = next((p for p in passengers if p.get("id_type") == id_type and p.get("id_number") == id_number), None)
#         return passenger
    
#     return None


# def update_ticket_passenger_from_api( 
#     ticket_no: str,
#     passenger_name: str = None, 
#     date_of_birth: str = None, 
#     id_type: str = None, 
#     id_number: str = None, 
#     nationality: str = None
# ) -> str:
#     """
#     Update passenger details for a specific ticket.
#     Allows incremental updates - only provided fields will be updated.
#     """
#     data = _load_data()
#     tickets = data.get("tickets", [])
#     passengers = data.get("passengers", [])
#     client = _get_qdrant_client()
#     # # Find ticket
#     # scroll_result, _ = client.scroll(
#     #             collection_name="tickets",
#     #             scroll_filter=Filter(must=[FieldCondition(key="ticket_id", match=MatchValue(value=ticket_no))]),
#     #             limit=1
#     #         )
#     # if scroll_result:
#     #     ticket = scroll_result[0]
#     # else:
#     #     return f"Ticket {ticket_no} not found."

#     ticket = next((t for t in tickets if t.get("ticket_id") == ticket_no), None)
#     if not ticket:
#         return f"Ticket {ticket_no} not found."

#     # Determine passenger to update
#     existing_passenger = None
    
#     # Case 1: Ticket already has a passenger_id
#     if ticket.get("passenger_id"):
#         existing_passenger = fetch_passenger_from_api(passenger_id=ticket.get("passenger_id"))
    
#     # Case 2: Search by id_number and id_type
#     elif id_number and id_type:
#         existing_passenger = fetch_passenger_from_api(id_type=id_type, id_number=id_number)
    
#     # Case 3: Use provided passenger_id
#     elif passenger_id:
#         existing_passenger = fetch_passenger_from_api(passenger_id=passenger_id)
    
#     # Update or create passenger
#     if existing_passenger:
#         # Update existing passenger with new information (only non-None fields)
#         if passenger_name:
#             existing_passenger["full_name"] = passenger_name
#         if date_of_birth:
#             existing_passenger["dob"] = to_date(date_of_birth).isoformat() if to_date(date_of_birth) else None
#         if id_type:
#             existing_passenger["id_type"] = id_type
#         if id_number:
#             existing_passenger["id_number"] = id_number
#         if nationality:
#             existing_passenger["nationality"] = nationality
        
#         passenger_id = existing_passenger["passenger_id"]
#     else:
#         # Create new passenger with provided information
#         new_passenger_id = generate_next_passenger_id(passengers)
#         new_passenger = {
#             "passenger_id": new_passenger_id,
#             "full_name": passenger_name or "Unnamed Passenger",
#             "dob": to_date(date_of_birth).isoformat() if date_of_birth and to_date(date_of_birth) else None,
#             "id_type": id_type,
#             "id_number": id_number,
#             "nationality": nationality,
#         }
#         passengers.append(new_passenger)
#         passenger_id = new_passenger_id
    
#     # Update ticket
#     # if passenger_name:
#     #     ticket["full_name"] = passenger_name
#     ticket["passenger_id"] = passenger_id
    
#     # Save all changes
#     data["passengers"] = passengers
#     data["tickets"] = tickets
#     _save_data(data)
    
#     return f"Ticket {ticket_no} updated with passenger {passenger_name or 'information'} (ID: {passenger_id})."


# def update_multiple_tickets_with_passengers(booking_id: str, passengers_info: list[dict]) -> str:
#     """
#     Update multiple tickets with passenger information at once.
    
#     Args:
#         booking_id: The booking reference ID
#             passengers_info: List of dictionaries containing passenger information.
#                             Each dict should have keys: passenger_name, date_of_birth, id_type, 
#                             id_number, nationality
#         """
#     data = _load_data()
#     tickets = data.get("tickets", [])
#     passengers = data.get("passengers", [])
    
#     # Get all tickets for this booking
#     booking_tickets = [t for t in tickets if t.get("booking_id") == booking_id]
    
#     if not booking_tickets:
#         return f"No tickets found for booking {booking_id}."
    
#     if len(passengers_info) != len(booking_tickets):
#         return f"Mismatch: Found {len(booking_tickets)} tickets but {len(passengers_info)} passenger info provided."
    
#     results = []
    
#     # Loop through each passenger info and corresponding ticket
#     for idx, passenger_info in enumerate(passengers_info):
#         ticket = booking_tickets[idx]
#         ticket_id = ticket.get("ticket_id")
        
#         # Extract passenger info
#         passenger_name = passenger_info.get("full_name")
#         date_of_birth = passenger_info.get("dob")
#         id_type = passenger_info.get("id_type")
#         id_number = passenger_info.get("id_number")
#         nationality = passenger_info.get("nationality")
        
#         # Check if passenger already exists (by id_number + id_type)
#         existing_passenger = None
#         if id_number and id_type:
#             existing_passenger = next(
#                 (p for p in passengers if p.get("id_type") == id_type and p.get("id_number") == id_number),
#                 None
#             )
        
#         if existing_passenger:
#             # Passenger exists, just link to ticket
#             passenger_id = existing_passenger["passenger_id"]
#             ticket["passenger_id"] = passenger_id
#             ticket["passenger_name"] = existing_passenger.get("full_name")
#             results.append(f"Ticket {ticket_id}: Linked to existing passenger {passenger_id}")
#         else:
#             # Create new passenger
#             new_passenger_id = generate_next_passenger_id(passengers)
            
#             new_passenger = {
#                 "passenger_id": new_passenger_id,
#                 "full_name": passenger_name or "Unnamed Passenger",
#                 "dob": to_date(date_of_birth).isoformat() if date_of_birth and to_date(date_of_birth) else None,
#                 "id_type": id_type,
#                 "id_number": id_number,
#                 "nationality": nationality,
#             }
#             passengers.append(new_passenger)
            
#             # Link to ticket
#             ticket["passenger_id"] = new_passenger_id
#             ticket["full_name"] = passenger_name
            
#             results.append(f"✓ Ticket {ticket_id}: Created new passenger {new_passenger_id} ({passenger_name})")
    
#     # Save all changes
#     data["passengers"] = passengers
#     data["tickets"] = tickets
#     _save_data(data)
    
#     summary = f"Updated {len(booking_tickets)} tickets for booking {booking_id}:\n" + "\n".join(results)
#     return summary

# def cancel_booking_from_api(booking_id: str) -> str:
#     """
#     Cancel a booking.
#     """
#     data = _load_data()
#     bookings = data.get("flightBookings", [])
#     booking = next((b for b in bookings if b.get("booking_id") == booking_id), None)
    
#     # Check booking tồn tại trước
#     if not booking:
#         return f"Booking {booking_id} not found."

#     if booking['booking_status'] == "confirmed":
#         booking['booking_status'] = "cancelled"
#     _save_data(data)
#     # Lấy flight_price để cập nhật quota
#     # Cập nhật trạng thái tickets
#     tickets = data.get("tickets", [])
#     for ticket in tickets:
#         if ticket.get("booking_id") == booking_id:
#             ticket['ticket_status'] = 'cancelled'
#             flight_id = ticket.get("flight_id")

#     _save_data(data)

#     flight_prices = data.get("flightPrices", [])
#     flight_price = next((fp for fp in flight_prices if fp.get("flight_id") == flight_id), None)
    
#     if not flight_price:
#         return f"Flight price not found for booking {booking_id}."
    
#     # Hoàn trả quota
#     old_quota = flight_price["seat_quota"]
#     flight_price["seat_quota"] = int(flight_price.get('seat_quota')) + int(booking.get("num_ticket"))
#     _save_data(data) 
#     # Cập nhật cache
#     global _cache
#     if _cache and "flightPrices" in _cache:
#         target_flight_id = str(flight_price.get('flight_id', '')).strip().upper()
#         target_seat_type = str(flight_price.get('seat_type', '')).strip().lower()
#         for cache_fp in _cache["flightPrices"]:
#             if (str(cache_fp.get('flight_id', '')).strip().upper() == target_flight_id and 
#                 str(cache_fp.get('seat_type', '')).strip().lower() == target_seat_type):
#                 cache_fp['seat_quota'] = flight_price['seat_quota']
#                 print(f"DEBUG: Cache updated for {target_flight_id}/{target_seat_type} - returned {booking.get('num_ticket')} seats")
#                 break
    
#     # Cập nhật Qdrant collection flight_prices
#     if USE_QDRANT:
#         try:
#             client = _get_qdrant_client()
#             embedder = _get_embedder()
            
#             target_flight_id = str(flight_price.get('flight_id', '')).strip().upper()
#             target_seat_type = str(flight_price.get('seat_type', '')).strip().lower()
            
#             composite_id = f"{target_flight_id}-{target_seat_type}"
#             point_id = str(uuid.uuid5(NAMESPACE_UUID, composite_id))
            
#             text = f"{flight_price.get('flight_id')}{flight_price.get('seat_type')} {flight_price.get('price')} {flight_price.get('seat_quota')}"
#             vector = embedder.encode(text).tolist()
            
#             client.upsert(
#                 collection_name="flight_prices",
#                 points=[PointStruct(id=point_id, vector=vector, payload=flight_price)]
#             )
#             print(f"DEBUG: Qdrant collection updated - quota restored from {old_quota} to {flight_price['seat_quota']}")
#         except Exception as e:
#             print(f"Warning: Could not update Qdrant collection: {e}")
    
#     return f"Booking {booking_id} has been cancelled successfully. {booking.get('num_ticket')} seat(s) have been released."
#     # return f"Booking {booking_id} cancelled."