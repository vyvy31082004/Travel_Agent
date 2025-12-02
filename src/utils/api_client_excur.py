import os
import requests
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, Range
from sentence_transformers import SentenceTransformer
import uuid
from utils.utils import to_date
# Load environment variables from .env file
load_dotenv()

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

    bookings = data.get("TRIP_BOOKINGS", [])
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
    
    # Critical step: Invalidate the cache after a successful write operation.
    # This ensures the next _load_data() call will fetch the fresh data.
    _cache = None
    _qdrant_initialized = False  # Re-index after save
    
    # Re-index vào Qdrant
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
        # Convert to string and replace comma with dot
        normalized = str(value).replace(',', '.')
        
        if value_type == "int":
            return int(float(normalized))  # float first to handle "5.0" -> 5
        else:
            return float(normalized)
    except (ValueError, TypeError):
        return None


def search_trip_from_api(
location: str | None = None, 
name: str | None = None,
keywords: str | None = None, 
details: str | None = None,
price: int | None = None, 
price_min: int | None = None, 
price_max: int | None = None) -> list[dict]:
    """
    Hybrid search: Kết hợp semantic search (Qdrant) với exact filters.
    - Nếu có 'name' hoặc 'location' hoặc 'keywords' → dùng semantic search
    - Luôn apply exact filters (price, price_min, price_max)
    """
    data = _load_data()
    
    # Nếu không bật Qdrant hoặc không có query text → fallback về list comprehension
    if not USE_QDRANT or (not name and not location and not keywords and not details):
        return _search_trip_exact(data, location, name, keywords, details, price, price_min, price_max)
    
    # --- Semantic Search với Qdrant ---
    try:
        client = _get_qdrant_client()
        embedder = _get_embedder()
        
        # Tạo query text từ các tham số
        query_parts = []
        if name:
            query_parts.append(name)
        if location:
            query_parts.append(location)
        if keywords:
            query_parts.append(keywords)
        if details:
            query_parts.append(details)
        query_text = " ".join(query_parts)
        
        query_vector = embedder.encode(query_text).tolist()
        
        # Build Qdrant filters cho exact match
        must_conditions = []
        if price:
            must_conditions.append(
                FieldCondition(key="price", range=Range(lte=price))
            )
        if price_min:
            must_conditions.append(
                FieldCondition(key="price", range=Range(gte=price_min))
            )
        if price_max:
            must_conditions.append(
                FieldCondition(key="price", range=Range(lte=price_max))
            )
        # Search trong Qdrant
        search_result = client.search(
            collection_name="trips",
            query_vector=query_vector,
            query_filter=Filter(must=must_conditions) if must_conditions else None,
            limit=50  # Lấy top 50 kết quả
        )
        
        # Extract payloads
        results = [hit.payload for hit in search_result]
        
        print(f" Qdrant semantic search: Found {len(results)} results")
        return results
        
    except Exception as e:
        print(f" Qdrant search failed: {e}, falling back to exact search")
        return _search_trip_exact(data, location, name, keywords, details, price, price_min, price_max)

def _search_trip_exact(data, location, name, keywords, details, price, price_min, price_max):
    """Fallback: Exact search với list comprehension (optimized single-pass)"""
    results = data.get("tours", [])
    
    # Normalize rating if provided
    price_float = _normalize_number(price, "float") if price else None
    price_min_float = _normalize_number(price_min, "float") if price_min else None
    price_max_float = _normalize_number(price_max, "float") if price_max else None
    if price and price_float is None:
        print(f" Warning: Could not parse price '{price}'")
    if price_min and price_min_float is None:
        print(f" Warning: Could not parse price_min '{price_min}'")
    if price_max and price_max_float is None:
        print(f" Warning: Could not parse price_max '{price_max}'")
    
    # Single-pass filter
    filtered = [
        r for r in results
        if (not location or location.lower() in r.get('location', '').lower())
        and (not name or name.lower() in r.get('name', '').lower())
        and (not keywords or keywords.lower() in (r.get('name', '') + ' ' + r.get('location', '')).lower())
        and (not details or details.lower() in r.get('details', '').lower())
        and (not price_float or r.get('price', 0) <= price_float)
        and (not price_min_float or r.get('price', 0) >= price_min_float)
        and (not price_max_float or r.get('price', 0) <= price_max_float)       
    ]
    
    print(f"🔍 Exact search (tours): Found {len(filtered)} results")
    return filtered

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
    date: str,
    people: int,
    total_price: int,
) -> dict:
    """Book an excursion and save it to the cloud API."""
    data = _load_data()
    tour_bookings = data.get("TRIP_BOOKINGS", [])

    new_booking_id = (max([b.get('booking_id', 0) for b in tour_bookings]) + 1) if tour_bookings else 1
    
    new_booking = {
        "booking_id": new_booking_id,
        "excur_id": excur_id,
        "date": to_date(date).isoformat() if to_date(date) else None,
        "people": people,
        "total_price": total_price,
        "status": "confirmed"
    }
    tour_bookings.append(new_booking)
    data["TRIP_BOOKINGS"] = tour_bookings
    
    _save_data(data)
    
    return new_booking


def cancel_tour_booking_in_api(booking_id: int) -> bool:
    """Cancel a tour booking in the cloud API."""
    all_data = _load_data()
    tour_bookings = all_data.get("TRIP_BOOKINGS", [])
    
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
    bookings = data.get("TRIP_BOOKINGS", [])
    new_booking = next((b for b in bookings if b.get('booking_id') == booking_id), None)
    if not new_booking:
        return "Please provide a valid booking id."
    if new_people:
        new_booking['people'] = new_people
    if new_date:
        new_booking['date'] = to_date(new_date).isoformat() if to_date(new_date) else None
    
    data["TRIP_BOOKINGS"] = bookings
    _save_data(data)
    return "Cập nhật thành công cho mã đặt tour {booking_id}."


