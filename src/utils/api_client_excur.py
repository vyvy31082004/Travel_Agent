import os
import requests
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, Range
from sentence_transformers import SentenceTransformer
import uuid
from utils.utils import to_date, convert_to_vnd
# Load environment variables from .env file
load_dotenv()
from functools import lru_cache
from datetime import date, datetime
from typing import Optional
import unicodedata 
from utils.excur_helper import _normalize_text_for_search, _get_review_text, _extract_review_items , _match_tour_name, _find_url_recursive, _parse_date
# Get credentials from environment variables
BIN_ID_EXCUR = os.getenv("BIN_ID_EXCUR")
API_KEY_EXCUR = os.getenv("API_KEY")
USE_QDRANT = os.getenv("USE_QDRANT", "true").lower() == "true"  # Toggle Qdrant on/off
API_URL = f'https://api.jsonbin.io/v3/b/{BIN_ID_EXCUR}'
HEADERS = {
  'Content-Type': 'application/json',
  'X-Master-Key': API_KEY_EXCUR
}

# --- Caching Mechanism ---
# This cache will hold the data in memory to avoid repeated API calls.
_cache = None
_qdrant_client = None
_embedder = None
_qdrant_initialized = False

def _get_qdrant_client():
    """Khởi tạo Qdrant client (kết nối tới instance persistent)"""
    global _qdrant_client
    if _qdrant_client is None:
        
        _qdrant_client = QdrantClient(host="localhost", port=6333)
    return _qdrant_client

def _get_embedder():
    """Khởi tạo sentence transformer model (multilingual)"""
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    return _embedder

def _init_qdrant_collections():
    """Tạo collections 'trips' và 'trip_bookings' trong Qdrant nếu chưa tồn tại."""
    global _qdrant_initialized
    if _qdrant_initialized:
        return
    
    client = _get_qdrant_client()
    embedder = _get_embedder()
    vector_size = embedder.get_sentence_embedding_dimension()
    collection_names = ["trips", "trip_bookings"]
    for collection_name in collection_names:
        try:
            client.get_collection(collection_name=collection_name)
            print(f"Collection '{collection_name}' already exists. Skipping creation.")
        except Exception:
            print(f"Collection '{collection_name}' not found. Creating...")
            try:
                client.recreate_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
                print(f" Successfully created collection '{collection_name}'.")
            except Exception as e:
                print(f"Error: Could not create collection '{collection_name}': {e}")
    
    _qdrant_initialized = True

def _index_data_to_qdrant(data):
    """
    Index chỉ những dữ liệu mới vào Qdrant.
    """
    if not USE_QDRANT:
        return
    
    client = _get_qdrant_client()
    embedder = _get_embedder()
    _init_qdrant_collections()

    collection_name_tours = "trips"
    try:
        existing_tours_points = client.scroll(
            collection_name=collection_name_tours,
            limit=10000,  
            with_payload=False,
            with_vectors=False
        )[0]
        existing_tours_ids = {point.id for point in existing_tours_points}
        print(f"Found {len(existing_tours_ids)} existing tours points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing tours points (collection might be new): {e}")
        existing_tours_ids = set()

    tours = data.get("tours", [])
    new_tours = [tour for tour in tours if tour.get('id') not in existing_tours_ids]
    
    if not new_tours:
        print(" Qdrant (Tours) is up-to-date. No new tours to index.")
    else:
        print(f"⏳ Indexing {len(new_tours)} tours...")
        tour_points = []
        for tour in new_tours:
            text = f" {tour.get('name', '')} {tour.get('location', '')} {tour.get('keywords', '')} {tour.get('details', '')}"
            vector = embedder.encode(text).tolist()
            tour_points.append(PointStruct(id=tour.get('id'), vector=vector, payload=tour))
        
        if tour_points:
            try:
                client.upsert(collection_name=collection_name_tours, points=tour_points)
                print(f" Successfully indexed {len(tour_points)} tours to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new tours: {e}")

    # --- Index trip bookings ---
    collection_name_bookings = "trip_bookings"
    try:
        existing_bookings_points = client.scroll(
            collection_name=collection_name_bookings,
            with_payload=False,
            with_vectors=False
        )[0]
        existing_bookings_ids = {point.id for point in existing_bookings_points}
        print(f"Found {len(existing_bookings_ids)} existing bookings points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing bookings points (collection might be new): {e}")
        existing_bookings_ids = set()

    bookings = data.get("tourBookings", [])
    new_bookings = [booking for booking in bookings if booking.get('booking_id') not in existing_bookings_ids]

    if not new_bookings:
        print(" Qdrant (Bookings) is up-to-date. No new bookings to index.")
    else:
        print(f"⏳ Indexing {len(new_bookings)} bookings...")
        booking_points = []
        for booking in new_bookings:
            text = f"{booking.get('excur_id')} {booking.get('date')} {booking.get('people')} {booking.get('total_price')} {booking.get('status')}"
            vector = embedder.encode(text).tolist()
            booking_points.append(PointStruct(id=booking.get('booking_id'), vector=vector, payload=booking))

        if booking_points:
            try:
                client.upsert(collection_name=collection_name_bookings, points=booking_points)
                print(f" Successfully indexed {len(booking_points)} bookings to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new bookings: {e}")

def _load_data():
    """
    Tải dữ liệu từ cloud. Sử dụng cache trong bộ nhớ để tăng tốc độ cho các lần gọi sau.
    Cache sẽ được xóa khi có thao tác ghi dữ liệu.
    """
    global _cache
    if _cache:
        return _cache

    if not BIN_ID_EXCUR or not API_KEY_EXCUR:
        raise ValueError("BIN_ID và API_KEY chưa được thiết lập trong file .env")
    
    response = requests.get(f"{API_URL}/latest", headers=HEADERS)
    response.raise_for_status() 
    
    data = response.json()['record']
    _cache = data  
    
    if USE_QDRANT:
        _index_data_to_qdrant(data)
    
    return data

def _save_data(data):
    """Lưu dữ liệu lên cloud và xóa cache để đảm bảo dữ liệu luôn mới."""
    global _cache, _qdrant_initialized
    if not BIN_ID_EXCUR or not API_KEY_EXCUR:
        raise ValueError("BIN_ID và API_KEY chưa được thiết lập trong file .env")

    response = requests.put(API_URL, json=data, headers=HEADERS)
    response.raise_for_status()
    
    _cache = None
    _qdrant_initialized = False  
    
    if USE_QDRANT:
        _index_data_to_qdrant(data)

def _normalize_number(value, value_type="float"):
    """
    Normalize number from various formats (handles Vietnamese comma format).
    Examples: "8,4" -> 8.4, "1.5" -> 1.5, 5 -> 5
    """
    if value is None:
        return None
    
    try:
        normalized = str(value).replace(',', '.')
        
        if value_type == "int":
            return int(float(normalized))  
        else:
            return float(normalized)
    except (ValueError, TypeError):
        return None

BOOKING_HOST = os.getenv("BOOKING_RAPIDAPI_HOST", "booking-com15.p.rapidapi.com")
BOOKING_BASE_URL = f"https://{BOOKING_HOST}/api/v1"
BOOKING_LANGUAGE_CODE = os.getenv("BOOKING_LANGUAGE_CODE", "vi")
BOOKING_CURRENCY_CODE = os.getenv("BOOKING_CURRENCY_CODE", "VND")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

# def search_trip_from_api(
# location: str | None = None, 
# name: str | None = None,
# keywords: str | None = None, 
# details: str | None = None,
# price: int | None = None, 
# price_min: int | None = None, 
# price_max: int | None = None) -> list[dict]:
#     """
#     Hybrid search: Kết hợp semantic search (Qdrant) với exact filters.
#     - Nếu có 'name' hoặc 'location' hoặc 'keywords' → dùng semantic search
#     - Luôn apply exact filters (price, price_min, price_max)
#     """
#     data = _load_data()
    
#     if not USE_QDRANT or (not name and not location and not keywords and not details):
#         return _search_trip_exact(data, location, name, keywords, details, price, price_min, price_max)
    
#     # --- Semantic Search với Qdrant ---
#     try:
#         client = _get_qdrant_client()
#         embedder = _get_embedder()
        
#         query_parts = []
#         if name:
#             query_parts.append(name)
#         if location:
#             query_parts.append(location)
#         if keywords:
#             query_parts.append(keywords)
#         if details:
#             query_parts.append(details)
#         query_text = " ".join(query_parts)
        
#         query_vector = embedder.encode(query_text).tolist()
        
#         must_conditions = []
#         if price:
#             must_conditions.append(
#                 FieldCondition(key="price", range=Range(lte=price))
#             )
#         if price_min:
#             must_conditions.append(
#                 FieldCondition(key="price", range=Range(gte=price_min))
#             )
#         if price_max:
#             must_conditions.append(
#                 FieldCondition(key="price", range=Range(lte=price_max))
#             )
#         search_result = client.search(
#             collection_name="trips",
#             query_vector=query_vector,
#             query_filter=Filter(must=must_conditions) if must_conditions else None,
#             limit=50  
#         )
        
#         results = [hit.payload for hit in search_result]
        
#         print(f" Qdrant semantic search: Found {len(results)} results")
#         return results
        
#     except Exception as e:
#         print(f" Qdrant search failed: {e}, falling back to exact search")
#         return _search_trip_exact(data, location, name, keywords, details, price, price_min, price_max)



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


def _get_first_list(data: dict | list, keys: list[str]) -> list:
    """
    Response của RapidAPI đôi khi thay đổi cấu trúc.
    Hàm này giúp lấy list an toàn từ nhiều key khác nhau.
    """
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value

    # Trường hợp data lồng thêm 1 lớp
    nested_data = data.get("data")
    if isinstance(nested_data, dict):
        for key in keys:
            value = nested_data.get(key)
            if isinstance(value, list):
                return value

    if isinstance(nested_data, list):
        return nested_data

    return []


def _pick_first_location(data: dict | list) -> dict | None:
    """
    searchLocation có thể trả destinations hoặc products.
    Theo docs, id có thể nằm trong products hoặc destinations.
    """
    candidates = _get_first_list(
        data,
        keys=["destinations", "products", "locations", "results"],
    )

    if candidates:
        return candidates[0]

    if isinstance(data, dict) and data.get("id"):
        return data

    return None


def _extract_price(product: dict) -> tuple[float | None, str | None]:
    """
    Cố gắng lấy giá từ nhiều cấu trúc response khác nhau.
    """
    price_candidates = [
        product.get("representativePrice"),
        product.get("price"),
        product.get("priceInfo"),
        product.get("pricing"),
    ]

    for price_obj in price_candidates:
        if isinstance(price_obj, dict):
            value = (
                price_obj.get("value")
                or price_obj.get("amount")
                or price_obj.get("price")
                or price_obj.get("publicAmount")
            )

            currency = (
                price_obj.get("currency")
                or price_obj.get("currencyCode")
                or price_obj.get("currency_code")
            )

            if value is not None:
                return float(value), currency

        elif isinstance(price_obj, (int, float)):
            return float(price_obj), None

    return None, None


def _normalize_attraction(product: dict) -> dict:
    price, currency = _extract_price(product)
    price, currency = convert_to_vnd(price, currency)

    image = None
    image_obj = product.get("primaryPhoto") or product.get("image") or product.get("photo")

    if isinstance(image_obj, dict):
        image = (
            image_obj.get("small")
            or image_obj.get("medium")
            or image_obj.get("large")
            or image_obj.get("url")
        )
    elif isinstance(image_obj, str):
        image = image_obj

    # Lấy mã product/tour/attraction từ nhiều field có thể có
    product_id = (
        product.get("id")
        or product.get("productId")
        or product.get("attractionId")
    )

    # Lấy rating từ nhiều field có thể có
    rating = (
        product.get("reviewScore")
        or product.get("rating")
        or product.get("averageRating")
        or product.get("score")
    )

    review_count = (
        product.get("reviewCount")
        or product.get("reviewsCount")
        or product.get("numberOfReviews")
    )

    return {
        "source": "booking_com15_rapidapi",

        # ID chính của product/tour/attraction
        # Dùng ID này để gọi getAttractionReviews
        "product_id": product_id,
        "external_attraction_id": product_id,

        # Slug dùng cho getAttractionDetails và getAvailability
        "slug": (
            product.get("slug")
            or product.get("productSlug")
        ),

        "name": (
            product.get("name")
            or product.get("title")
            or product.get("displayName")
        ),

        "description": (
            product.get("shortDescription")
            or product.get("description")
            or product.get("summary")
        ),

        "category": (
            product.get("category")
            or product.get("type")
        ),

        "rating": rating,
        "review_count": review_count,

        "price": price,
        "currency": currency,

        "image": image,

        "duration": (
            product.get("duration")
            or product.get("durationLabel")
        ),

        "location": (
            product.get("city")
            or product.get("location")
            or product.get("ufiName")
        ),

        # Giữ raw để debug nếu cần
        "raw": product,
    }


@lru_cache(maxsize=256)
def search_attraction_location_from_api(
    query: str,
    languagecode: str = BOOKING_LANGUAGE_CODE,
) -> dict:
    """
    Search địa điểm cho attraction.
    Ví dụ: Hà Nội, Đà Lạt, Tokyo, Bangkok.
    """
    try:
        data = _booking_get(
            "/attraction/searchLocation",
            {
                "query": query,
                "languagecode": languagecode,
            },
        )

        location = _pick_first_location(data)

        if not location:
            return {
                "error": f"Không tìm thấy địa điểm attraction phù hợp với '{query}'.",
                "raw": data,
            }

        return {
            "id": location.get("id"),
            "name": (
                location.get("name")
                or location.get("title")
                or location.get("displayName")
            ),
            "product_slug": location.get("productSlug") or location.get("slug"),
            "raw": location,
        }

    except Exception as e:
        return {
            "error": f"Lỗi khi search attraction location: {str(e)}"
        }


def search_attractions_from_api(
    location: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sort_by: str = "trending",
    page: int = 1,
    currency_code: str = BOOKING_CURRENCY_CODE,
    languagecode: str = BOOKING_LANGUAGE_CODE,
    type_filters: Optional[str] = None,
    price_filters: Optional[str] = None,
    ufi_filters: Optional[str] = None,
    label_filters: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """
    Search attractions / activities / tours theo địa điểm.

    Flow:
    1. location -> /attraction/searchLocation -> lấy id
    2. id -> /attraction/searchAttractions -> lấy danh sách attraction

    Không tự gán ngày mặc định.
    Nếu có start_date/end_date thì API có thể lọc theo ngày.
    """

    if not location:
        return [
            {
                "error": "Bạn cần cung cấp location để tìm attraction."
            }
        ]

    try:
        parsed_start_date = _parse_date(start_date)
        parsed_end_date = _parse_date(end_date)

        if parsed_start_date and parsed_end_date:
            if parsed_end_date < parsed_start_date:
                return [
                    {
                        "error": "end_date phải sau hoặc bằng start_date."
                    }
                ]

        location_info = search_attraction_location_from_api(
            location,
            languagecode,
        )

        if location_info.get("error"):
            return [location_info]

        location_id = location_info.get("id")

        if not location_id:
            return [
                {
                    "error": f"Không lấy được attraction location id cho '{location}'.",
                    "raw": location_info,
                }
            ]

        data = _booking_get(
            "/attraction/searchAttractions",
            {
                "id": location_id,
                "startDate": parsed_start_date,
                "endDate": parsed_end_date,
                "sortBy": sort_by,
                "page": page,
                "currency_code": currency_code,
                "languagecode": languagecode,
                "typeFilters": type_filters,
                "priceFilters": price_filters,
                "ufiFilters": ufi_filters,
                "labelFilters": label_filters,
            },
        )

        products = _get_first_list(
            data,
            keys=["products", "attractions", "results", "items"],
        )

        attractions = [
            _normalize_attraction(product)
            for product in products
        ]

        return attractions[:limit]

    except Exception as e:
        return [
            {
                "error": f"Lỗi khi gọi searchAttractions: {str(e)}"
            }
        ]



def fetch_attraction_details_from_api(
    slug: str,
    languagecode: str = BOOKING_LANGUAGE_CODE,
) -> dict:
    """
    Lấy chi tiết attraction.
    slug lấy từ field productSlug/slug của searchAttractions.
    """
    if not slug:
        return {
            "error": "Bạn cần cung cấp slug của attraction."
        }

    try:
        data = _booking_get(
            "/attraction/getAttractionDetails",
            {
                "slug": slug,
                "languagecode": languagecode,
            },
        )

        booking_url = _find_url_recursive(data)

        return {
            "source": "booking_com15_rapidapi",
            "slug": slug,
            "booking_url": booking_url,
            "details": data,
        }

    except Exception as e:
        return {
            "error": f"Lỗi khi lấy attraction details: {str(e)}"
        }






# def _search_trip_exact(data, location, name, keywords, details, price, price_min, price_max):
#     """Fallback: Exact search với list comprehension (optimized single-pass)"""
#     results = data.get("tours", [])
    
#     # Normalize rating if provided
#     price_float = _normalize_number(price, "float") if price else None
#     price_min_float = _normalize_number(price_min, "float") if price_min else None
#     price_max_float = _normalize_number(price_max, "float") if price_max else None
#     if price and price_float is None:
#         print(f" Warning: Could not parse price '{price}'")
#     if price_min and price_min_float is None:
#         print(f" Warning: Could not parse price_min '{price_min}'")
#     if price_max and price_max_float is None:
#         print(f" Warning: Could not parse price_max '{price_max}'")
    
#     # Single-pass filter
#     filtered = [
#         r for r in results
#         if (not location or location.lower() in r.get('location', '').lower())
#         and (not name or name.lower() in r.get('name', '').lower())
#         and (not keywords or keywords.lower() in (r.get('name', '') + ' ' + r.get('location', '')).lower())
#         and (not details or details.lower() in r.get('details', '').lower())
#         and (not price_float or r.get('price', 0) <= price_float)
#         and (not price_min_float or r.get('price', 0) >= price_min_float)
#         and (not price_max_float or r.get('price', 0) <= price_max_float)       
#     ]
    
#     print(f"🔍 Exact search (tours): Found {len(filtered)} results")
#     return filtered

def fetch_excursion_info_from_api(tour_name: str) -> int | None:
    """Lấy id của đại lý cho thuê xe từ tên (từ API cloud)."""
    data = _load_data()
    tour = data.get("tours", [])
    info = next((tr for tr in tour if tour_name.lower() in tr.get('name', '').lower()), None)
    if not info:
        return {}
    return {
        "id": info.get('id'),
        "name": info.get('name'),
        "location": info.get('location'),
        "keywords": info.get('keywords'),
        "details": info.get('details'),
        "price": info.get('price')    }

def book_excursion_in_api(
    excur_id: int,
    tour_date: str,
    people: int,
    total_price: int,
) -> dict:
    """Book an excursion and save it to the cloud API."""
    data = _load_data()
    tour_bookings = data.get("tourBookings", [])

    new_booking_id = (max([b.get('booking_id', 0) for b in tour_bookings]) + 1) if tour_bookings else 1
    
    new_booking = {
        "booking_id": new_booking_id,
        "excur_id": excur_id,
        "date": to_date(tour_date).isoformat() if to_date(tour_date) else None,
        "people": people,
        "total_price": total_price,
        "status": "confirmed"
    }
    tour_bookings.append(new_booking)
    data["tourBookings"] = tour_bookings
    
    _save_data(data)
    
    return new_booking


def cancel_tour_booking_in_api(booking_id: int) -> bool:
    """Cancel a tour booking in the cloud API."""
    all_data = _load_data()
    tour_bookings = all_data.get("tourBookings", [])
    
    if not booking_id:
        return "Please provide a booking id."
    bookings_map = {b.get('booking_id'): b for b in tour_bookings}
    booking_to_cancel = bookings_map.get(booking_id)
    if not booking_to_cancel:
        return "Please provide a valid booking id."
    if booking_to_cancel['status'] == "confirmed":
        booking_to_cancel['status'] = "cancelled"
    _save_data(all_data)
    return f"Đã hủy thành công mã đặt phòng {booking_id}."




# def fetch_car_info_from_api(car_name: str, car_rental_id: int) -> dict:
#     """Lấy thông tin xe từ tên xe và id đại lý (từ API cloud)."""
#     data = _load_data()
#     car_details = data.get("CAR_DETAILS", [])
#     car = next((
#         cd for cd in car_details
#         if car_name.lower() in cd.get('car_name', '').lower()
#         and str(cd.get('rental_id')) == str(car_rental_id)
#     ), None)
#     if not car:
#         return {}
#     return {
#         "car_id": car.get('id'),
#         "car_name": car.get('car_name'),
#         "car_price": car.get('car_price'),
#         "car_capacity": car.get('car_capacity')
#     }



def update_tour_booking_in_api(booking_id: int, new_people: int | None = None, new_date: str | None = None) -> dict | None:
    """Update a tour booking in the cloud API."""
    if not booking_id:
        return "Please provide a booking id."
    if not (new_people or new_date):
        return "Please provide a new people or new date."
    data = _load_data()
    bookings = data.get("tourBookings", [])
    new_booking = next((b for b in bookings if b.get('booking_id') == booking_id), None)
    if not new_booking:
        return "Please provide a valid booking id."
    if new_people:
        new_booking['people'] = new_people
    if new_date:
        new_booking['date'] = to_date(new_date).isoformat() if to_date(new_date) else None
    
    data["tourBookings"] = bookings
    _save_data(data)
    return "Cập nhật thành công cho mã đặt tour {booking_id}."


