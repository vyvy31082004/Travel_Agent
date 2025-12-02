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
BIN_ID_HOTEL = os.getenv("BIN_ID_HOTEL")
API_KEY = os.getenv("API_KEY")
USE_QDRANT = os.getenv("USE_QDRANT", "true").lower() == "true"  
API_URL = f'https://api.jsonbin.io/v3/b/{BIN_ID_HOTEL}'
HEADERS = {
  'Content-Type': 'application/json',
  'X-Master-Key': API_KEY
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
        # Kết nối tới Qdrant chạy trên Docker
        _qdrant_client = QdrantClient(host="localhost", port=6333)
    return _qdrant_client

def _get_embedder():
    """Khởi tạo sentence transformer model (multilingual)"""
    global _embedder
    if _embedder is None:
        # Model hỗ trợ tiếng Việt, nhẹ, nhanh
        _embedder = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    return _embedder

def _init_qdrant_collections():
    """Tạo các collection trong Qdrant nếu chưa tồn tại."""
    global _qdrant_initialized
    if _qdrant_initialized:
        return
    
    client = _get_qdrant_client()
    embedder = _get_embedder()
    
    vector_size = embedder.get_sentence_embedding_dimension()
    collection_names = ["hotels", "rooms", "hotel_bookings"]
    
    for collection_name in collection_names:
        try:
            client.get_collection(collection_name=collection_name)
            print(f"Collection '{collection_name}' already exists. Skipping creation.")
        except Exception:
            print(f"Collection '{collection_name}' not found. Creating...")
            try:
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
                print(f" Collection '{collection_name}' created successfully.")
            except Exception as e:
                print(f"Error: Could not create collection '{collection_name}': {e}")
    
    _qdrant_initialized = True

def _index_data_to_qdrant(data):
    """
    Index chỉ những dữ liệu mới vào Qdrant.
    Hàm này sẽ kiểm tra các ID đã có và chỉ nạp những hotels/rooms chưa tồn tại.
    """
    if not USE_QDRANT:
        return
    
    client = _get_qdrant_client()
    embedder = _get_embedder()
    _init_qdrant_collections()

    # --- Index Hotels ---
    collection_name_hotels = "hotels"
    try:
        existing_hotel_points = client.scroll(
            collection_name=collection_name_hotels,
            limit=10000,  
            with_payload=False,
            with_vectors=False
        )[0]
        existing_hotel_ids = {point.id for point in existing_hotel_points}
        print(f"Found {len(existing_hotel_ids)} existing hotel points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing hotel points (collection might be new): {e}")
        existing_hotel_ids = set()

    hotels = data.get("hotels", [])
    new_hotels = [hotel for hotel in hotels if hotel.get('id') not in existing_hotel_ids]
    
    if not new_hotels:
        print(" Qdrant (Hotels) is up-to-date. No new hotels to index.")
    else:
        print(f"⏳ Found {len(new_hotels)} new hotels to index...")
        hotel_points = []
        for hotel in new_hotels:
            text = f"{hotel.get('name', '')} {hotel.get('location', '')} {hotel.get('price_tier', '')} {hotel.get('rating', '')}"
            vector = embedder.encode(text).tolist()
            hotel_points.append(PointStruct(id=hotel.get('id'), vector=vector, payload=hotel))
        
        if hotel_points:
            try:
                client.upsert(collection_name=collection_name_hotels, points=hotel_points)
                print(f" Successfully indexed {len(hotel_points)} new hotels to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new hotels: {e}")

    # --- Index Rooms ---
    collection_name_rooms = "rooms"
    try:
        existing_room_points = client.scroll(
            collection_name=collection_name_rooms,
            limit=10000,
            with_payload=False,
            with_vectors=False
        )[0]
        existing_room_ids = {point.id for point in existing_room_points}
        print(f"Found {len(existing_room_ids)} existing room points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing room points (collection might be new): {e}")
        existing_room_ids = set()

    rooms = data.get("rooms", [])
    new_rooms = [room for room in rooms if room.get('room_id') not in existing_room_ids]

    if not new_rooms:
        print(" Qdrant (Rooms) is up-to-date. No new rooms to index.")
    else:
        print(f"⏳ Found {len(new_rooms)} new rooms to index...")
        room_points = []
        for room in new_rooms:
            text = f"{room.get('room_type', '')}"
            vector = embedder.encode(text).tolist()
            room_points.append(PointStruct(id=room.get('room_id'), vector=vector, payload=room))

        if room_points:
            try:
                client.upsert(collection_name=collection_name_rooms, points=room_points)
                print(f" Successfully indexed {len(room_points)} new rooms to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new rooms: {e}")

    # --- Index Bookings ---
    collection_name_bookings = "hotel_bookings"
    try:
        existing_booking_points = client.scroll(
            collection_name=collection_name_bookings,
            limit=10000,
            with_payload=False,
            with_vectors=False
        )[0]
        existing_booking_ids = {point.id for point in existing_booking_points}
        print(f"Found {len(existing_booking_ids)} existing booking points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing booking points (collection might be new): {e}")
        existing_booking_ids = set()

    bookings = data.get("HOTEL_BOOKINGS", [])
    # Always upsert all bookings to ensure updates (like status changes) are reflected in Qdrant.
    # The previous logic only handled new additions, not modifications.
    if not bookings:
        print(" Qdrant (Bookings) is up-to-date. No bookings to index.")
    else:
        print(f"⏳ Indexing {len(bookings)} bookings...")
        booking_points = []
        for booking in bookings:
            # Lấy thông tin chi tiết để tạo vector giàu ngữ nghĩa
            text = f" {booking.get('status')}"
            vector = embedder.encode(text).tolist()
            booking_points.append(PointStruct(id=booking.get('booking_id'), vector=vector, payload=booking))

        if booking_points:
            try:
                client.upsert(collection_name=collection_name_bookings, points=booking_points)
                print(f" Successfully indexed {len(booking_points)} bookings to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new bookings: {e}")


def _load_data():
    global _cache
    if _cache:
        return _cache

    if not BIN_ID_HOTEL or not API_KEY:
        raise ValueError("BIN_ID và API_KEY chưa    được thiết lập trong file .env")
    
    response = requests.get(f"{API_URL}/latest", headers=HEADERS)
    response.raise_for_status() 
    
    data = response.json()['record']
    _cache = data  
    
    if USE_QDRANT:
        _index_data_to_qdrant(data)
    
    return data

def _save_data(data):
    global _cache, _qdrant_initialized
    if not BIN_ID_HOTEL or not API_KEY:
        raise ValueError("BIN_ID và API_KEY chưa được thiết lập trong file .env")

    response = requests.put(API_URL, json=data, headers=HEADERS)
    response.raise_for_status()
    
    _cache = None
    _qdrant_initialized = False  
    
    if USE_QDRANT:
        _index_data_to_qdrant(data)

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

def search_hotel_from_api(
location: str | None = None, 
name: str | None = None,
price_tier: str | None = None,
rating: float | None = None) -> list[dict]:
    """
    Hybrid search: Combine semantic search (Qdrant) with exact filters.
    - If 'name' or 'location' or 'price_tier' is provided, use semantic search
    - Always apply exact filters (price_tier, rating)
    """
    data = _load_data()
    if not USE_QDRANT or (not name and not location and not price_tier):
        return _search_hotel_exact(data, location, name, price_tier, rating)
    
    try:
        client = _get_qdrant_client()
        embedder = _get_embedder()
        query_parts = []
        if name:
            query_parts.append(name)
        if location:
            query_parts.append(location)
        if price_tier:
            query_parts.append(price_tier)
        query_text = " ".join(query_parts)
        
        query_vector = embedder.encode(query_text).tolist()
        
        must_conditions = []
        if rating:
            must_conditions.append(
                FieldCondition(key="rating", range=Range(gt=rating))
            )
        if location:
            must_conditions.append(
                FieldCondition(key="location", match=MatchValue(value=location))
            )
        search_result = client.search(
            collection_name="hotels",
            query_vector=query_vector,
            query_filter=Filter(must=must_conditions) if must_conditions else None,
            limit=50  
        )
        
        results = [hit.payload for hit in search_result]
        
        print(f" Qdrant semantic search: Found {len(results)} results")
        return results
        
    except Exception as e:
        print(f" Qdrant search failed: {e}, falling back to exact search")
        return _search_hotel_exact(data, location, name, price_tier, rating)

def _search_hotel_exact(data, location, name, price_tier, rating):

    results = data.get("hotels", [])
    filtered = [
        r for r in results
        if (not location or location.lower() in r.get('location', '').lower())
        and (not name or name.lower() in r.get('name', '').lower())
        and (not price_tier or price_tier.lower() == r.get('price_tier', '').lower())
        and (not rating or r.get('rating', 0) > rating)
    ]
    
    print(f" Exact search (hotels): Found {len(filtered)} results")
    return filtered

def fetch_hotel_info_from_api(hotel_name: str) -> dict | None:
    try:
        client = _get_qdrant_client()
        embedder = _get_embedder()
        query_vector=embedder.encode(hotel_name).tolist()

        search_result = client.search(
            collection_name="hotels",
            query_vector=query_vector,
            limit=1,
            score_threshold=0.7,
        )
        if search_result:
            return search_result[0].payload
    except Exception as e:
        print(f" Qdrant search failed: {e}, falling back to exact search")
        data = _load_data()
        results = data.get("hotels", [])
        hotel = next((h for h in results if hotel_name.lower() in h.get('name', '').lower()), None)
        return hotel

def search_hotel_rooms_from_api(hotel_name, room_type, price, price_max, price_min, capacity):
    if not hotel_name:
        return "Please provide a hotel name."
    hotel = fetch_hotel_info_from_api(hotel_name)
    if not hotel:
        return f"Không tìm thấy khách sạn '{hotel_name}'."
    hotel_id = hotel.get('id')
    if not hotel_id:
        return None 
    try:
        client = _get_qdrant_client()
        embedder = _get_embedder()
        query_parts = []
        if room_type:
            query_parts.append(room_type)
        query_text = " ".join(query_parts)
        
        query_vector = embedder.encode(query_text).tolist()
        
        must_conditions = []
        if price:
            must_conditions.append(
                FieldCondition(key="price", range=Range(gt=price))
            )
        if price_max:
            must_conditions.append(
                FieldCondition(key="price", range=Range(lte=price_max))
            )
        if price_min:
            must_conditions.append(
                FieldCondition(key="price", range=Range(gte=price_min))
            )
        if capacity:
            must_conditions.append(
                FieldCondition(key="capacity", range=Range(gte=capacity))
            )   
        must_conditions.append(
            FieldCondition(key="hotel_id", match=MatchValue(value=hotel_id))
        )
        search_result = client.search(
            collection_name="rooms",
            query_vector=query_vector,
            query_filter=Filter(must=must_conditions) if must_conditions else None,
            limit=50
        )
        return [hit.payload for hit in search_result]
    except Exception as e:
        print(f" Qdrant search failed: {e}, falling back to exact search")
        data = _load_data()
        return search_room_exact(data, room_type, price, price_max, price_min, capacity)
        
def search_room_exact(data, room_type, price, price_max, price_min, capacity):
    rooms = data.get("rooms", [])
    filtered = [
        r for r in rooms
        if (not room_type or room_type.lower() in r.get('room_type', '').lower())
        and (not price or r.get('price', 0) > price)
        and (not price_max or r.get('price', 0) <= price_max)
        and (not price_min or r.get('price', 0) >= price_min)
        and (not capacity or r.get('capacity', 0) >= capacity)
    ]
    return filtered

def fetch_hotel_room_info_from_api(hotel_name: str , room_type: str, room_id: int ):
    data = _load_data()
    rooms = data.get("rooms", [])
    if  hotel_name and  room_type and not room_id:
        hotel = fetch_hotel_info_from_api(hotel_name)
        if not hotel:
            return None 
        hotel_id = hotel.get('id')
        try:
            client = _get_qdrant_client()
            embedder = _get_embedder()
            query_vector = embedder.encode(room_type).tolist()
            must_conditions = [FieldCondition(key="hotel_id", match=MatchValue(value=hotel_id))]
            search_result = client.search(
                collection_name="rooms",
                query_vector=query_vector,
                query_filter=Filter(must=must_conditions) if must_conditions else None,
                score_threshold=0.6,
                limit=1,
            )
            if search_result:
                return search_result[0].payload
        except Exception as e:
            print(f" Qdrant search failed: {e}, falling back to exact search")
            room = next((r for r in rooms if room_type.lower() in r.get('room_type', '').lower() and r.get('hotel_id') == hotel_id), None)
            return room
    elif room_id:
        room = None
        if USE_QDRANT:
            try:
                client = _get_qdrant_client()
                # Retrieve the point directly by its ID for high efficiency
                points = client.retrieve(
                    collection_name="rooms",
                    ids=[room_id],
                    with_payload=True
                )
                if points:
                    room = points[0].payload
            except Exception as e:
                print(f" Qdrant retrieve failed: {e}, falling back to exact search")

        # Fallback if Qdrant is disabled, fails, or finds nothing
        if not room:
            room = next((r for r in rooms if r.get('room_id') == room_id), None)
        
        if room:
            return room
        else:
            return None 
    return None 

def check_realse_room_from_api(aim, booking_id, room_id, checkin_date, checkout_date):
    if not aim:
        return "Please provide a valid aim."
    if not checkin_date:
        return "Please provide a checkin date."
    if not checkout_date:
        return "Please provide a checkout date."
    data = _load_data()
    bookings = data.get("HOTEL_BOOKINGS", [])   
    checkin_date = to_date(checkin_date)
    checkout_date = to_date(checkout_date)
    if aim == "book":
        if not room_id:
            return "Please provide a room id."
        unavailable_rooms = [
            b for b in bookings
            if (b.get('room_id') == room_id) 
            and ( b.get('status') != "cancelled" )
            and not (((to_date(b.get('checkin_date')) > checkin_date) 
            and (checkout_date <= to_date(b.get('checkin_date')))) or  checkin_date 
            >= to_date(b.get('checkout_date')) )
        ]
    elif aim == 'update':
        if not booking_id:
            return "Please provide a booking id."
        
        unavailable_rooms = [
            b for b in bookings
            if (b.get('booking_id') != booking_id) 
            and ( b.get('status') != "cancelled" )
            and not (((to_date(b.get('checkin_date')) > checkin_date) 
            and (checkout_date <= to_date(b.get('checkin_date')))) or  checkin_date 
            >= to_date(b.get('checkout_date')) )
        ]
    else:
        return "Please provide a valid aim."
    
    return unavailable_rooms if unavailable_rooms else None

def book_hotel_room_from_api(room_id, hotel_id, checkin_date, checkout_date, total_price):
    if not room_id:
        return "Please provide a room id."
    if not hotel_id:
        return "Please provide a hotel id."
    if not checkin_date:
        return "Please provide a checkin date."
    if not checkout_date:
        return "Please provide a checkout date."
    data = _load_data()
    bookings = data.get("HOTEL_BOOKINGS", [])

    new_booking_id = (max([b.get('booking_id', 0) for b in bookings]) + 1) if bookings else 1
    
    new_booking = {
        "booking_id": new_booking_id,
        "room_id": room_id,
        "hotel_id": hotel_id,
        "checkin_date": checkin_date,
        "checkout_date": checkout_date,
        "total_price": total_price,
        "status": "confirmed"
    }
    bookings.append(new_booking)
    data["HOTEL_BOOKINGS"] = bookings
    
    _save_data(data)
    
    return new_booking

def fetch_booking_info_from_api(booking_id):
    if USE_QDRANT:
        try:
            client = _get_qdrant_client()
            points = client.retrieve(
                collection_name="hotel_bookings",
                ids=[booking_id],
                with_payload=True
            )
            if points:
                print("Using qrant: ")
                return points[0].payload
        except Exception as e:
            print(f" Qdrant retrieve for booking failed: {e}, falling back to exact search")
    
    # Fallback to linear search
    data = _load_data()
    bookings = data.get("HOTEL_BOOKINGS", [])
    booking = next((b for b in bookings if b.get('booking_id') == booking_id), None)
    
    if not booking:
        return "Please provide a valid booking id."
    return booking



def update_hotel_booking_from_api(booking_id, checkin_date, checkout_date, total_price):
    if not booking_id:
        return "Please provide a booking id."
    if not checkin_date:
        return "Please provide a checkin date."
    if not checkout_date:
        return "Please provide a checkout date."
    data = _load_data()
    bookings = data.get("HOTEL_BOOKINGS", [])
    booking_to_update = next((b for b in bookings if b.get('booking_id') == booking_id), None)
    if not booking_to_update:
        return "Please provide a valid booking id."
    if checkin_date:
        booking_to_update['checkin_date'] = checkin_date
    if checkout_date:
        booking_to_update['checkout_date'] = checkout_date
    if total_price:
        booking_to_update['total_price'] = total_price
    _save_data(data)
    return f"Cập nhật thành công cho mã đặt phòng {booking_id}."

def cancel_hotel_booking_from_api(booking_id):
    if not booking_id:
        return "Please provide a booking id."
    data = _load_data()
    bookings = data.get("HOTEL_BOOKINGS", [])
    booking_to_cancel = next((b for b in bookings if b.get('booking_id') == booking_id), None)
    if not booking_to_cancel:
        return "Please provide a valid booking id."
    if booking_to_cancel['status'] == "confirmed":
        booking_to_cancel['status'] = "cancelled"
    _save_data(data)
    return f"Đã hủy thành công mã đặt phòng {booking_id}."

