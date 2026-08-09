import os
import requests
from dotenv import load_dotenv
# from qdrant_client import QdrantClient
# from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, Range
#from sentence_transformers import SentenceTransformer
import uuid
from utils.utils import to_date, convert_to_vnd
from datetime import date, datetime, timedelta
from functools import lru_cache
# Load environment variables from .env file
load_dotenv()

# # Get credentials from environment variables
# BIN_ID_HOTEL = os.getenv("BIN_ID_HOTEL")
# API_KEY = os.getenv("API_KEY")
# USE_QDRANT = os.getenv("USE_QDRANT", "true").lower() == "true"  
# API_URL = f'https://api.jsonbin.io/v3/b/{BIN_ID_HOTEL}'
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
#     collection_names = ["hotels", "rooms", "hotelBookings"]
    
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
#     Hàm này sẽ kiểm tra các ID đã có và chỉ nạp những hotels/rooms chưa tồn tại.
#     """
#     if not USE_QDRANT:
#         return
    
#     client = _get_qdrant_client()
#     embedder = _get_embedder()
#     _init_qdrant_collections()

#     # --- Index Hotels ---
#     collection_name_hotels = "hotels"
#     try:
#         existing_hotel_points = client.scroll(
#             collection_name=collection_name_hotels,
#             limit=10000,  
#             with_payload=False,
#             with_vectors=False
#         )[0]
#         existing_hotel_ids = {point.id for point in existing_hotel_points}
#         print(f"Found {len(existing_hotel_ids)} existing hotel points in Qdrant.")
#     except Exception as e:
#         print(f"Could not fetch existing hotel points (collection might be new): {e}")
#         existing_hotel_ids = set()

#     hotels = data.get("hotels", [])
#     new_hotels = [hotel for hotel in hotels if hotel.get('id') not in existing_hotel_ids]
    
#     if not new_hotels:
#         print(" Qdrant (Hotels) is up-to-date. No new hotels to index.")
#     else:
#         print(f"⏳ Found {len(new_hotels)} new hotels to index...")
#         hotel_points = []
#         for hotel in new_hotels:
#             text = f"{hotel.get('name', '')} {hotel.get('location', '')} {hotel.get('price_tier', '')} {hotel.get('rating', '')}"
#             vector = embedder.encode(text).tolist()
#             hotel_points.append(PointStruct(id=hotel.get('id'), vector=vector, payload=hotel))
        
#         if hotel_points:
#             try:
#                 client.upsert(collection_name=collection_name_hotels, points=hotel_points)
#                 print(f" Successfully indexed {len(hotel_points)} new hotels to Qdrant.")
#             except Exception as e:
#                 print(f"Warning: Could not index new hotels: {e}")

#     # --- Index Rooms ---
#     collection_name_rooms = "rooms"
#     try:
#         existing_room_points = client.scroll(
#             collection_name=collection_name_rooms,
#             limit=10000,
#             with_payload=False,
#             with_vectors=False
#         )[0]
#         existing_room_ids = {point.id for point in existing_room_points}
#         print(f"Found {len(existing_room_ids)} existing room points in Qdrant.")
#     except Exception as e:
#         print(f"Could not fetch existing room points (collection might be new): {e}")
#         existing_room_ids = set()

#     rooms = data.get("rooms", [])
#     new_rooms = [room for room in rooms if room.get('room_id') not in existing_room_ids]

#     if not new_rooms:
#         print(" Qdrant (Rooms) is up-to-date. No new rooms to index.")
#     else:
#         print(f"⏳ Found {len(new_rooms)} new rooms to index...")
#         room_points = []
#         for room in new_rooms:
#             text = f"{room.get('room_type', '')}"
#             vector = embedder.encode(text).tolist()
#             room_points.append(PointStruct(id=room.get('room_id'), vector=vector, payload=room))

#         if room_points:
#             try:
#                 client.upsert(collection_name=collection_name_rooms, points=room_points)
#                 print(f" Successfully indexed {len(room_points)} new rooms to Qdrant.")
#             except Exception as e:
#                 print(f"Warning: Could not index new rooms: {e}")

#     # --- Index Bookings ---
#     collection_name_bookings = "hotelBookings"
#     try:
#         existing_booking_points = client.scroll(
#             collection_name=collection_name_bookings,
#             limit=10000,
#             with_payload=False,
#             with_vectors=False
#         )[0]
#         existing_booking_ids = {point.id for point in existing_booking_points}
#         print(f"Found {len(existing_booking_ids)} existing booking points in Qdrant.")
#     except Exception as e:
#         print(f"Could not fetch existing booking points (collection might be new): {e}")
#         existing_booking_ids = set()

#     bookings = data.get("hotelBookings", [])
#     # Always upsert all bookings to ensure updates (like status changes) are reflected in Qdrant.
#     # The previous logic only handled new additions, not modifications.
#     if not bookings:
#         print(" Qdrant (Bookings) is up-to-date. No bookings to index.")
#     else:
#         print(f"⏳ Indexing {len(bookings)} bookings...")
#         booking_points = []
#         for booking in bookings:
#             # Lấy thông tin chi tiết để tạo vector giàu ngữ nghĩa
#             text = f" {booking.get('status')}"
#             vector = embedder.encode(text).tolist()
#             booking_points.append(PointStruct(id=booking.get('booking_id'), vector=vector, payload=booking))

#         if booking_points:
#             try:
#                 client.upsert(collection_name=collection_name_bookings, points=booking_points)
#                 print(f" Successfully indexed {len(booking_points)} bookings to Qdrant.")
#             except Exception as e:
#                 print(f"Warning: Could not index new bookings: {e}")


# def _load_data():
#     global _cache
#     if _cache:
#         return _cache

#     if not BIN_ID_HOTEL or not API_KEY:
#         raise ValueError("BIN_ID và API_KEY chưa    được thiết lập trong file .env")
    
#     response = requests.get(f"{API_URL}/latest", headers=HEADERS)
#     response.raise_for_status() 
    
#     data = response.json()['record']
#     _cache = data  
    
#     if USE_QDRANT:
#         _index_data_to_qdrant(data)
    
#     return data

# def _save_data(data):
#     global _cache, _qdrant_initialized
#     if not BIN_ID_HOTEL or not API_KEY:
#         raise ValueError("BIN_ID và API_KEY chưa được thiết lập trong file .env")

#     response = requests.put(API_URL, json=data, headers=HEADERS)
#     response.raise_for_status()
    
#     _cache = None
#     _qdrant_initialized = False  
    
#     if USE_QDRANT:
#         _index_data_to_qdrant(data)

# def _normalize_number(value, value_type="float"):
#     if value is None:
#         return None
    
#     try:
#         normalized = str(value).replace(',', '.')
        
#         if value_type == "int":
#             return int(float(normalized))  
#         else:
#             return float(normalized)
#     except (ValueError, TypeError):
#         return None

# def search_hotel_from_api(
# location: str | None = None, 
# name: str | None = None,
# price_tier: str | None = None,
# rating: float | None = None) -> list[dict]:
#     """
#     Hybrid search: Combine semantic search (Qdrant) with exact filters.
#     - If 'name' or 'location' or 'price_tier' is provided, use semantic search
#     - Always apply exact filters (price_tier, rating)
#     """
#     data = _load_data()
#     if not USE_QDRANT or (not name and not location and not price_tier):
#         return _search_hotel_exact(data, location, name, price_tier, rating)
    
#     try:
#         client = _get_qdrant_client()
#         embedder = _get_embedder()
#         query_parts = []
#         if name:
#             query_parts.append(name)
#         if location:
#             query_parts.append(location)
#         if price_tier:
#             query_parts.append(price_tier)
#         query_text = " ".join(query_parts)
        
#         query_vector = embedder.encode(query_text).tolist()
        
#         must_conditions = []
#         if rating:
#             must_conditions.append(
#                 FieldCondition(key="rating", range=Range(gt=rating))
#             )
#         if location:
#             must_conditions.append(
#                 FieldCondition(key="location", match=MatchValue(value=location))
#             )
#         search_result = client.search(
#             collection_name="hotels",
#             query_vector=query_vector,
#             query_filter=Filter(must=must_conditions) if must_conditions else None,
#             limit=50  
#         )
        
#         results = [hit.payload for hit in search_result]
        
#         print(f" Qdrant semantic search: Found {len(results)} results")
#         return results
        
#     except Exception as e:
#         print(f" Qdrant search failed: {e}, falling back to exact search")
#         return _search_hotel_exact(data, location, name, price_tier, rating)



def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else value


BOOKING_HOST = _env("BOOKING_RAPIDAPI_HOST", "booking-com15.p.rapidapi.com")
BOOKING_BASE_URL = f"https://{BOOKING_HOST}/api/v1"
BOOKING_LANGUAGE_CODE = _env("BOOKING_LANGUAGE_CODE", "vi")
BOOKING_CURRENCY_CODE = _env("BOOKING_CURRENCY_CODE", "VND")
RAPIDAPI_KEY = _env("RAPIDAPI_KEY")


def _booking_headers() -> dict:
    if not RAPIDAPI_KEY:
        raise RuntimeError("Thiếu RAPIDAPI_KEY trong file .env")

    return {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": BOOKING_HOST,
    }


def _booking_get(path: str, params: dict) -> dict:
    url = f"{BOOKING_BASE_URL}{path}"

    clean_params = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    response = requests.get(
        url,
        headers=_booking_headers(),
        params=clean_params,
        timeout=20,
    )

    if response.status_code == 429:
        raise RuntimeError("RapidAPI bị giới hạn request. Hãy thử lại sau.")

    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, dict) and payload.get("status") is False:
        raise RuntimeError(payload.get("message", "Booking API trả về lỗi."))

    if isinstance(payload, dict):
        return payload.get("data", payload)

    return payload


# def _parse_search_date(value: str | None) -> date:
#     if value is None:
#         raise ValueError("Ngày không được để trống.")

#     if isinstance(value, date):
#         return value

#     return datetime.strptime(value, "%Y-%m-%d").date()


def _resolve_search_dates(
    checkin_date: str | None,
    checkout_date: str | None,
) -> tuple[str, str, int]:
    """
    Nếu user không nhập ngày thì mặc định:
    checkin = ngày mai
    checkout = ngày kia
    """
    if checkin_date:
        checkin = to_date(checkin_date)
    else:
        checkin = date.today() + timedelta(days=1)

    if checkout_date:
        checkout = to_date(checkout_date)
    else:
        checkout = checkin + timedelta(days=1)

    if checkin < date.today():
        raise ValueError("Ngày nhận phòng phải từ hôm nay trở về sau.")

    if checkout <= checkin:
        raise ValueError("Ngày trả phòng phải sau ngày nhận phòng.")

    nights = (checkout - checkin).days

    return checkin.isoformat(), checkout.isoformat(), nights


@lru_cache(maxsize=256)
def _search_booking_destination(query: str, languagecode: str = BOOKING_LANGUAGE_CODE) -> dict | None:
    """
    Booking.com15 cần gọi searchDestination trước để lấy dest_id và search_type.
    """
    data = _booking_get(
        "/hotels/searchDestination",
        {
            "query": query,
            "languagecode": languagecode,
        },
    )

    if isinstance(data, list) and len(data) > 0:
        return data[0]

    return None


def _normalize_price_tier(price_tier: str | None) -> str | None:
    if not price_tier:
        return None

    text = price_tier.lower().strip()

    mapping = {
        "cheap": "budget",
        "budget": "budget",
        "low": "budget",
        "giá rẻ": "budget",
        "gia re": "budget",
        "rẻ": "budget",
        "re": "budget",

        "mid": "mid",
        "medium": "mid",
        "trung bình": "mid",
        "trung binh": "mid",
        "vừa phải": "mid",
        "vua phai": "mid",
        "hợp lý": "mid",
        "hop ly": "mid",

        "luxury": "luxury",
        "cao cấp": "luxury",
        "cao cap": "luxury",
        "sang trọng": "luxury",
        "sang trong": "luxury",
    }

    return mapping.get(text, text)


def _infer_price_tier(price_per_night: float | int | None) -> str | None:
    """
    Chia tier demo theo VND/đêm.
    Bạn có thể chỉnh lại theo logic project.
    """
    if price_per_night is None:
        return None

    price = float(price_per_night)

    if price < 700_000:
        return "budget"

    if price < 1_500_000:
        return "mid"

    return "luxury"


def _split_accessibility_label(label: str | None) -> list[str]:
    """Tách accessibilityLabel thành từng dòng dễ đọc."""
    if not label:
        return []

    text = (
        str(label)
        .replace("\u200e", "")
        .replace("\u202c", "")
        .replace("\u202a", "")
        .replace("\u202b", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    lines: list[str] = []
    for chunk in text.split("\n"):
        chunk = chunk.strip(" \t•")
        if not chunk:
            continue
        # Một số label gộp nhiều câu bằng ". " trên cùng 1 dòng
        parts = chunk.split(". ") if ". " in chunk else [chunk]
        for part in parts:
            part = part.strip(" \t.•")
            if part:
                lines.append(part)
    return lines


def _normalize_booking_hotel(raw_hotel: dict, nights: int) -> dict:
    prop = raw_hotel.get("property", {}) or {}
    # priceBreakdown nằm TRONG property, không phải nằm ngoài raw_hotel
    price_breakdown = prop.get("priceBreakdown", {}) or {}

    gross_price = price_breakdown.get("grossPrice", {}) or {}
    total_price = gross_price.get("value")
    currency = gross_price.get("currency")
    total_price, currency = convert_to_vnd(total_price, currency)

    price_per_night = None
    if total_price is not None and nights > 0:
        price_per_night = round(float(total_price) / nights)

    photo_urls = prop.get("photoUrls") or []
    access_lines = _split_accessibility_label(
        raw_hotel.get("accessibilityLabel") or prop.get("accessibilityLabel")
    )

    return {
        "source": "booking_com15_rapidapi",

        # ID ngoài Booking.com, không phải hotel_id nội bộ DB của bạn
        "external_hotel_id": raw_hotel.get("hotel_id"),

        "name": prop.get("name"),
        # List từng dòng — agent in mỗi phần tử một dòng cho dễ nhìn
        "accessibilityLabel": access_lines,
        "location": (
            prop.get("wishlistName")
            or prop.get("city")
            or prop.get("countryCode")
        ),

        "rating": prop.get("reviewScore"),
        "rating_word": prop.get("reviewScoreWord"),
        "review_count": prop.get("reviewCount"),
        "star": prop.get("propertyClass"),

        # price = giá trung bình mỗi đêm để agent dễ lọc/rank
        "price": price_per_night,
        "price_per_night": price_per_night,
        "total_price": total_price,
        "currency": currency,
        "price_tier": _infer_price_tier(price_per_night),

        "latitude": prop.get("latitude"),
        "longitude": prop.get("longitude"),
        "photo": photo_urls[0] if photo_urls else None,

        "raw": raw_hotel,
    }


def search_hotel_from_api(
    location: str | None = None,
    name: str | None = None,
    price_tier: str | None = None,
    price: int | None = None,
    rating: float | None = None,
    checkin_date: str | None = None,
    checkout_date: str | None = None,
    adults: int = 2,
    children_age: str | None = None,
    room_qty: int = 1,
    price_min: int | None = None,
    price_max: int | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    Search hotel realtime.

    Flow:
    1. location/name -> searchDestination
    2. dest_id + ngày nhận/trả phòng -> searchHotels
    3. Chuẩn hóa response cho agent dùng

    Lưu ý:
    - Nếu không truyền checkin_date/checkout_date, mặc định search ngày mai -> ngày kia.
    - external_hotel_id là ID từ Booking.com, không phải hotel_id trong DB nội bộ.
    """

    query = location or name

    if not query:
        return [
            {
                "error": "Bạn cần cung cấp location hoặc name để tìm khách sạn."
            }
        ]

    try:
        checkin, checkout, nights = _resolve_search_dates(
            checkin_date,
            checkout_date,
        )

        destination = _search_booking_destination(query)

        if not destination:
            return [
                {
                    "error": f"Không tìm thấy điểm đến phù hợp với '{query}'."
                }
            ]

        data = _booking_get(
            "/hotels/searchHotels",
            {
                "dest_id": destination.get("dest_id"),
                "search_type": destination.get("search_type"),
                "arrival_date": checkin,
                "departure_date": checkout,
                "adults": adults,
                "children_age": children_age,
                "room_qty": room_qty,
                "page_number": 1,
                "price_min": price_min,
                "price_max": price_max,
                "languagecode": BOOKING_LANGUAGE_CODE,
                "currency_code": BOOKING_CURRENCY_CODE,
            },
        )

        raw_hotels = data.get("hotels", []) if isinstance(data, dict) else []

        hotels = [
            _normalize_booking_hotel(raw_hotel, nights)
            for raw_hotel in raw_hotels
        ]

        # Lọc theo tên nếu user nhập tên khách sạn cụ thể
        if name:
            name_lower = name.lower()
            hotels = [
                hotel
                for hotel in hotels
                if hotel.get("name")
                and name_lower in hotel["name"].lower()
            ]

        # Lọc rating >= yêu cầu
        if rating is not None:
            hotels = [
                hotel
                for hotel in hotels
                if hotel.get("rating") is not None
                and float(hotel["rating"]) >= float(rating)
            ]

        if price is not None:
            hotels = [
                hotel
                for hotel in hotels
                if hotel.get("total_price") is not None
                and float(hotel["total_price"]) <= float(price)
            ]

        if price_min is not None:
            hotels = [
                hotel
                for hotel in hotels
                if hotel.get("total_price") is not None
                and float(hotel["total_price"]) >= float(price_min)
            ]
        
        if price_max is not None:
            hotels = [
                hotel
                for hotel in hotels
                if hotel.get("total_price") is not None
                and float(hotel["total_price"]) <= float(price_max)
            ]

        # Lọc phân khúc giá
        normalized_tier = _normalize_price_tier(price_tier)

        if normalized_tier:
            hotels = [
                hotel
                for hotel in hotels
                if hotel.get("price_tier") == normalized_tier
            ]

        return hotels[:limit]

    except Exception as e:
        return [
            {
                "error": f"Lỗi khi gọi Booking.com15 RapidAPI: {str(e)}"
            }
        ]




# def _extract_room_blocks(data) -> list[dict]:
#     """Lấy danh sách block phòng từ nhiều kiểu response Booking có thể trả."""
#     if not data:
#         return []

#     if isinstance(data, list):
#         blocks = []
#         for item in data:
#             if isinstance(item, dict):
#                 blocks.extend(item.get("block") or item.get("blocks") or [])
#                 if item.get("block_id") or item.get("room_id"):
#                     blocks.append(item)
#         return blocks

#     if isinstance(data, dict):
#         for key in ("block", "blocks", "room_list", "rooms", "available_rooms"):
#             value = data.get(key)
#             if isinstance(value, list) and value:
#                 return value

#         # Một số response bọc thêm 1 lớp data
#         nested = data.get("data")
#         if nested and nested is not data:
#             return _extract_room_blocks(nested)

#     return []


def _extract_room_blocks(data) -> list[dict]:
    """Lấy danh sách block phòng từ nhiều kiểu response Booking có thể trả."""
    if not data:
        return []

    if isinstance(data, list):
        blocks = []
        for item in data:
            if isinstance(item, dict):
                blocks.extend(item.get("block") or item.get("blocks") or [])
                if item.get("block_id") or item.get("room_id"):
                    blocks.append(item)
        return blocks

    if isinstance(data, dict):
        for key in ("block", "blocks", "room_list", "rooms", "available_rooms"):
            value = data.get(key)
            if isinstance(value, list) and value:
                return value

        # Một số response bọc thêm 1 lớp data
        nested = data.get("data")
        if nested and nested is not data:
            return _extract_room_blocks(nested)

    return []
def _normalize_booking_room(raw_block: dict, nights: int, hotel_id: str | int) -> dict:
    meta = raw_block.get("_room_meta") or {}
    name = meta.get("name") or raw_block.get("room_name") or raw_block.get("name")

    price_breakdown = (
        raw_block.get("product_price_breakdown")
        or raw_block.get("priceBreakdown")
        or {}
    )

    total_price = None
    currency = raw_block.get("currency")

    # Chỉ dùng các key là giá TỔNG thực sự (không dùng discount/tax/strikethrough)
    for key in (
        "all_inclusive_amount",
        "all_inclusive_amount_hotel_currency",
        "gross_amount",
        "gross_amount_hotel_currency",
        "net_amount",
        "grossPrice",
        "all_inclusive_price",
    ):
        amount_obj = price_breakdown.get(key) or {}
        if amount_obj.get("value") is not None:
            total_price = amount_obj["value"]
            currency = amount_obj.get("currency") or currency
            break

    if total_price is None:
        total_price = raw_block.get("amount_unrounded") or raw_block.get("amount_rounded")

    total_price, currency = convert_to_vnd(total_price, currency)

    price_per_night = None
    if total_price is not None and nights > 0:
        price_per_night = round(float(total_price) / nights)

    # Giá gốc (trước giảm giá)
    original_price = None
    sp = price_breakdown.get("strikethrough_amount") or {}
    if sp.get("value") is not None:
        original_price, _ = convert_to_vnd(sp["value"], sp.get("currency") or currency)

    # Số tiền được giảm
    discount_amount = None
    da = price_breakdown.get("discounted_amount") or {}
    if da.get("value") is not None:
        discount_amount, _ = convert_to_vnd(da["value"], da.get("currency") or currency)

    # Ưu tiên bản đã điền sẵn
    policy_details = raw_block.get("policy_display_details") or {}
    cancellation = policy_details.get("cancellation") or {}
    title = cancellation.get("title_details") or {}
    cancellation_policy = title.get("translation")

    # Fallback: template từ transactional_policy_objects
    if not cancellation_policy:
        for p in raw_block.get("transactional_policy_objects") or []:
            if p.get("key") == "FreeCancellationKey":
                cancellation_policy = p.get("text")
                break

    # # Chính sách hủy phòng
    # policies = raw_block.get("transactional_policy_objects") or []
    # cancellation_policy = None
    # for p in policies:
    #     if isinstance(p, dict) and p.get("key") == "FreeCancellationKey":
    #         cancellation_policy = p.get("text")
    #         break

    # Gói kèm (parking, wifi...)
    bundle = raw_block.get("bundle_extras") or {}
    bundle_name = bundle.get("highlighted_text") or bundle.get("generated_name")

    # Ảnh: ưu tiên lấy từ room_meta, fallback về block
    photos = (
        meta.get("photos")
        or raw_block.get("photos")
        or raw_block.get("roomPhotos")
        or []
    )
    photo = None
    if photos:
        first = photos[0]
        photo = first.get("url_original") or first.get("url") if isinstance(first, dict) else first

    return {
        "source": "booking_com15_rapidapi",
        "external_hotel_id": hotel_id,
        "block_id": raw_block.get("block_id") or raw_block.get("id"),
        "room_id": raw_block.get("room_id"),
        "name": name,
        "description": meta.get("description"),
        "rate_name": raw_block.get("name"),
        "room_surface_m2": raw_block.get("room_surface_in_m2") or meta.get("room_surface_in_m2"),
        "max_occupancy": raw_block.get("max_occupancy") or meta.get("max_persons") or raw_block.get("nr_adults"),
        "adults": raw_block.get("nr_adults"),
        "children": raw_block.get("nr_children"),
        "smoking": bool(raw_block.get("smoking")),
        "all_inclusive": bool(raw_block.get("all_inclusive")),
        "is_dormitory": bool(raw_block.get("is_dormitory")),
        "is_block_fit": raw_block.get("is_block_fit"),
        "fit_status": raw_block.get("fit_status"),
        "refundable": raw_block.get("refundable"),
        "breakfast_included": raw_block.get("breakfast_included"),
        "mealplan": raw_block.get("mealplan"),
        "room_count_available": raw_block.get("room_count_available") or raw_block.get("room_count"),
        "cancellation_policy": cancellation_policy,
        "bundle_extras": bundle_name,
        "price": price_per_night,
        "price_per_night": price_per_night,
        "total_price": total_price,
        "original_price": original_price,
        "discount_amount": discount_amount,
        "currency": currency,
        "photo": photo,
    }


def get_hotel_room_list_from_api(
    hotel_id: str | int,
    checkin_date: str,
    checkout_date: str,
    adults: int = 2,
    children_age: str | None = None,
    room_qty: int = 1,
    price: int | None = None,
    price_max: int | None = None,
    price_min: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Lấy danh sách phòng của 1 khách sạn qua Booking.com15 getRoomList.

    hotel_id = external_hotel_id từ searchHotels.
    """
    if not hotel_id:
        return [{"error": "Bạn cần cung cấp hotel_id (external_hotel_id)."}]

    if not checkin_date or not checkout_date:
        return [{"error": "Bạn cần cung cấp checkin_date và checkout_date."}]

    try:
        checkin, checkout, nights = _resolve_search_dates(checkin_date, checkout_date)

        data = _booking_get(
            "/hotels/getRoomList",
            {
                "hotel_id": str(hotel_id),
                "arrival_date": checkin,
                "departure_date": checkout,
                "adults": adults,
                "children_age": children_age,
                "room_qty": room_qty,
                "units": "metric",
                "temperature_unit": "c",
                "languagecode": BOOKING_LANGUAGE_CODE,
                "currency_code": BOOKING_CURRENCY_CODE,
            },
        )
        # Lấy room metadata (tên phòng, mô tả, ảnh...)
        rooms_meta = {}
        if isinstance(data, dict):
            rooms_raw = data.get("rooms") or {}
            if isinstance(rooms_raw, dict):
                rooms_meta = rooms_raw  # keyed by room_id
        raw_blocks = _extract_room_blocks(data)

        # Merge room metadata vào từng block
        for block in raw_blocks:
            room_id = str(block.get("room_id", ""))
            if room_id in rooms_meta:
                block["_room_meta"] = rooms_meta[room_id]
        rooms = [
            _normalize_booking_room(block, nights, hotel_id)
            for block in raw_blocks
            if isinstance(block, dict)
        ]

        # Nếu API trả fit_status → chỉ giữ fit_status=2 (recommended hoàn toàn)
        # Nếu API không trả fit_status → lấy hết, không lọc
        has_fit_status = any(
            r.get("fit_status") not in (None, "")
            for r in rooms
        )
        if has_fit_status:
            recommended = [r for r in rooms if r.get("fit_status") == 2]
            if recommended:
                rooms = recommended

        if price is not None:
            rooms = [
                r for r in rooms
                if r.get("total_price") is not None
                and float(r["total_price"]) <= float(price)
            ]

        if price_min is not None:
            rooms = [
                r for r in rooms
                if r.get("total_price") is not None
                and float(r["total_price"]) >= float(price_min)
            ]

        if price_max is not None:
            rooms = [
                r for r in rooms
                if r.get("total_price") is not None
                and float(r["total_price"]) <= float(price_max)
            ]

        return rooms[:limit]

    except Exception as e:
        return [{"error": f"Lỗi khi gọi getRoomList: {str(e)}"}]

def _normalize_booking_review(raw_review: dict) -> dict:
    """Chuẩn hóa 1 review từ getHotelReviews."""
    stayed = raw_review.get("stayed_room_info") or {}
    photo = stayed.get("photo") or {}

    return {
        "source": "booking_com15_rapidapi",

        "date": raw_review.get("date"),
        "travel_purpose": raw_review.get("travel_purpose"),
        "country_code": raw_review.get("countrycode"),

        "pros": raw_review.get("pros"),
        "cons": raw_review.get("cons"),
        "pros_translated": raw_review.get("pros_translated"),
        "cons_translated": raw_review.get("cons_translated"),

        "title": raw_review.get("title"),
        "reviewer_name": raw_review.get("author", {}).get("name") if isinstance(raw_review.get("author"), dict) else raw_review.get("author"),
        "anonymous": bool(raw_review.get("anonymous")),
        "tags": raw_review.get("tags") or [],
        "helpful_vote_count": raw_review.get("helpful_vote_count", 0),
        "hotelier_response": raw_review.get("hotelier_response"),

        "room_name": stayed.get("room_name"),
        "room_id": stayed.get("room_id"),
        "checkin": stayed.get("checkin"),
        "checkout": stayed.get("checkout"),
        "num_nights": stayed.get("num_nights"),
        "room_photo": photo.get("url_max300") or photo.get("url_original"),

        "is_incentivised": bool(raw_review.get("is_incentivised")),
        "is_moderated": bool(raw_review.get("is_moderated")),

        "raw": raw_review,
    }


def get_hotel_reviews_from_api(
    hotel_id: str | int,
    page_number: int = 1,
    sort_option_id: str = "sort_most_relevant",
    limit: int = 10,
) -> dict:
    """
    Lấy đánh giá khách sạn qua Booking.com15 getHotelReviews.

    hotel_id = external_hotel_id từ search_hotel_from_api.
    """
    if not hotel_id:
        return {"error": "Bạn cần cung cấp hotel_id (external_hotel_id)."}

    try:
        data = _booking_get(
            "/hotels/getHotelReviews",
            {
                "hotel_id": str(hotel_id),
                "page_number": page_number,
                "sort_option_id": sort_option_id,
            },
        )

        # API trả result là list reviews
        raw_reviews = []
        if isinstance(data, dict):
            raw_reviews = data.get("result") or data.get("reviews") or []
        elif isinstance(data, list):
            raw_reviews = data

        reviews = [
            _normalize_booking_review(item)
            for item in raw_reviews
            if isinstance(item, dict)
        ]

        if limit and len(reviews) > limit:
            reviews = reviews[:limit]

        return {
            "source": "booking_com15_rapidapi",
            "external_hotel_id": str(hotel_id),
            "page": page_number,
            "sort_option_id": sort_option_id,
            "review_count": len(reviews),
            "reviews": reviews,
        }

    except Exception as e:
        return {
            "error": f"Lỗi khi gọi getHotelReviews: {str(e)}"
        }

def _normalize_booking_facility(raw_facility: dict) -> dict:
    rs =[]
    instances = raw_facility.get("instances") or []
    for inst in instances:
        if not isinstance(inst,dict):
            continue
        payment = inst.get("paymentInfo") or {}
        rs.append(
            {
                "title": inst.get("title"),
                "charge_mode": payment.get("chargeMode"),  
                "sub_facilities": [
                    sf.get("title")
                    for sf in (inst.get("subFacilities") or [])
                    if isinstance(sf, dict) and sf.get("title")
                ],
            }
        )
    return {
        "id": raw_facility.get("id"),
        "group_id": raw_facility.get("groupId"),
        "instances": rs
    }
def get_hotel_facility_from_api(
    hotel_id: str | int,
) -> dict:
    """
    Lấy tiện ích/facilities khách sạn qua Booking.com15 getHotelFacilities.
    hotel_id = external_hotel_id từ search_hotel_from_api.
    """
    if not hotel_id:
        return {"error": "Bạn cần cung cấp hotel_id (external_hotel_id)."}
    try:
        params = {
            "hotel_id": str(hotel_id),
            "languagecode": BOOKING_LANGUAGE_CODE,
        }
        data = _booking_get("/hotels/getHotelFacilities", params)
        raw_highlights = []
        raw_facilities = []
        if isinstance(data, dict):
            raw_highlights = (
                data.get("accommodationHighlights")
                or data.get("accommodation_highlights")
                or []
            )
            raw_facilities = data.get("facilities") or []
        highlights = [
            item.get("title")
            for item in raw_highlights
            if isinstance(item, dict) and item.get("title")
        ]
        facilities = [
            _normalize_booking_facility(item)
            for item in raw_facilities
            if isinstance(item, dict)
        ]
        # Flat list tiện ích (dễ cho agent đọc)
        facility_titles = []
        for fac in facilities:
            for inst in fac.get("instances", []):
                title = inst.get("title")
                if title:
                    facility_titles.append(title)
                facility_titles.extend(inst.get("sub_facilities") or [])
        # Loại trùng, giữ thứ tự
        seen = set()
        unique_titles = []
        for t in facility_titles:
            if t not in seen:
                seen.add(t)
                unique_titles.append(t)
        return {
            "external_hotel_id": str(hotel_id),
            "highlights": highlights,
            "facility_count": len(unique_titles),
            "facility_titles": unique_titles,
            "facilities": facilities,
        }
    except Exception as e:
        return {
            "error": f"Lỗi khi gọi getHotelFacilities: {str(e)}"
        }

def _normalize_booking_policy(raw_policy: dict) -> dict:
    
    if not isinstance(raw_policy, dict):
        return None 
    
    description = raw_policy.get("content") or {}
    first = description[0] if description else {}
    return{
            "type": raw_policy.get("type"),
            "description": first.get("text")if isinstance(first, dict) else None,
    }






def get_hotel_policy_from_api(hotel_id: str | int) -> dict:
    """
    Lấy chính sách khách sạn qua Booking.com15 getHotelPolicies.
    hotel_id = external_hotel_id từ search_hotel_from_api.
    """
    if not hotel_id:
        return {"error": "Bạn cần cung cấp hotel_id (external_hotel_id)."}
    try:
        params = {
            "hotel_id": str(hotel_id),
            "languagecode": BOOKING_LANGUAGE_CODE,
        }
        data = _booking_get("/hotels/getHotelPolicies", params)

        policies = [
            _normalize_booking_policy(item)
            for item in data.get("policy") or []
            if isinstance(item, dict)
        ]
        return{
            "external_hotel_id": str(hotel_id),
            "policies": policies,
            "policy_count": len(policies),
            "policy_titles": [policy.get("type") for policy in policies],
            "policy_descriptions": [policy.get("description") if policy.get("description") else None for policy in policies],
        }
    except Exception as e:
        return {
            "error": f"Lỗi khi gọi getHotelPolicies: {str(e)}"
        }


