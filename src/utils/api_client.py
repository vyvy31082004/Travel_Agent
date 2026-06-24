import os
import requests
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, Range
from sentence_transformers import SentenceTransformer
from utils.utils import to_date
import uuid

# Load environment variables from .env file
load_dotenv()

# Get credentials from environment variables
BIN_ID_CAR = os.getenv("BIN_ID_CAR")
API_KEY = os.getenv("API_KEY")
USE_QDRANT = os.getenv("USE_QDRANT", "true").lower() == "true"  # Toggle Qdrant on/off
API_URL = f'https://api.jsonbin.io/v3/b/{BIN_ID_CAR}'
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
    collection_names = ["car_rentals", "car_details", "car_bookings"]
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

    # --- Index car rentals ---
    collection_name_car_rentals = "car_rentals"
    try:
        existing_car_rentals_points = client.scroll(
            collection_name=collection_name_car_rentals,
            limit=10000,  
            with_payload=False,
            with_vectors=False
        )[0]
        existing_car_rentals_ids = {point.id for point in existing_car_rentals_points}
        print(f"Found {len(existing_car_rentals_ids)} existing car rentals points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing car rentals points (collection might be new): {e}")
        existing_car_rentals_ids = set()

    car_rentals = data.get("carRentals", [])
    new_car_rentals = [car_rental for car_rental in car_rentals if car_rental.get('id') not in existing_car_rentals_ids]
    
    if not new_car_rentals:
        print(" Qdrant (Car Rentals) is up-to-date. No new car rentals to index.")
    else:
        print(f"Found {len(new_car_rentals)} new car rentals to index...")
        car_rental_points = []
        for car_rental in new_car_rentals:
            text = f"{car_rental.get('id', '')} {car_rental.get('name', '')} {car_rental.get('location', '')} {car_rental.get('price_tier', '')} {car_rental.get('rating', '')}"
            vector = embedder.encode(text).tolist()
            car_rental_points.append(PointStruct(id=car_rental.get('id'), vector=vector, payload=car_rental))
        
        if car_rental_points:
            try:
                client.upsert(collection_name=collection_name_car_rentals, points=car_rental_points)
                print(f" Successfully indexed {len(car_rental_points)} car rentals to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new car rentals: {e}")

    collection_name_bookings = "car_bookings"

    details = data.get("carDetails", [])
    collection_name_car_details = "car_details"
    try:
        existing_car_details_points = client.scroll(
            collection_name=collection_name_car_details,
            limit=10000,  
            with_payload=False,
            with_vectors=False
        )[0]
        existing_car_details_ids = {point.id for point in existing_car_details_points}
        print(f"Found {len(existing_car_details_ids)} existing car details points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing car details points (collection might be new): {e}")
        existing_car_details_ids = set()    

    new_details = [detail for detail in details if detail.get('id') not in existing_car_details_ids]
    if not new_details:
        print(" Qdrant (Car Details) is up-to-date. No new car details to index.")
    else:
        print(f"Found {len(new_details)} new car details to index...")
        detail_points = []
        for detail in new_details:
            text = f"{detail.get('car_name', '')} {detail.get('car_type', '')} {detail.get('car_price', '')} {detail.get('car_capacity', '')}"
            vector = embedder.encode(text).tolist()
            detail_points.append(PointStruct(id=detail.get('id'), vector=vector, payload=detail))
        if detail_points:
            try:
                client.upsert(collection_name=collection_name_car_details, points=detail_points)
                print(f" Successfully indexed {len(detail_points)} car details to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new car details: {e}")


    bookings = data.get("carBookings", [])

    # Always upsert ALL bookings so status updates (e.g., cancelled) are reflected
    if not bookings:
        print(" Qdrant (Bookings): No bookings to index.")
    else:
        print(f" Upserting {len(bookings)} bookings (reflect updates)...")
        booking_points = []
        for booking in bookings:
            text = f"{booking.get('booking_id')}"
            vector = embedder.encode(text).tolist()
            booking_points.append(PointStruct(id=booking.get('booking_id'), vector=vector, payload=booking))

        try:
            client.upsert(collection_name=collection_name_bookings, points=booking_points)
            print(f" Successfully upserted {len(booking_points)} bookings to Qdrant.")
        except Exception as e:
            print(f"Warning: Could not upsert bookings: {e}")

def _load_data():
    """
    Tải dữ liệu từ cloud. Sử dụng cache trong bộ nhớ để tăng tốc độ cho các lần gọi sau.
    Cache sẽ được xóa khi có thao tác ghi dữ liệu.
    """
    global _cache
    if _cache:
        return _cache

    if not BIN_ID_CAR or not API_KEY:
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
    if not BIN_ID_CAR or not API_KEY:
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

def search_car_rentals_from_api(
    location: str | None = None,
    name: str | None = None,
    price_tier: str | None = None,
    rating: float | None = None,
) -> list[dict]:
    """
    Hybrid search: Kết hợp semantic search (Qdrant) với exact filters.
    - Nếu có 'name' hoặc 'location' → dùng semantic search
    - Luôn apply exact filters (price_tier, rating)
    """
    data = _load_data()
    
    # Nếu không bật Qdrant hoặc không có query text → fallback về list comprehension
    if not USE_QDRANT or (not name and not location):
        return _search_car_rentals_exact(data, location, name, price_tier, rating)
    
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
        query_text = " ".join(query_parts)
        if price_tier:
            query_parts.append(price_tier)
        
        # Encode query
        query_vector = embedder.encode(query_text).tolist()
        
        # Build Qdrant filters cho exact match
        must_conditions = []
        if rating:
            # Normalize rating: handle both comma and dot (8,4 -> 8.4)
            rating_float = _normalize_number(rating, "float")
            if rating_float is not None:
                must_conditions.append(
                    FieldCondition(key="rating", range=Range(gte=rating_float))
                )
            else:
                print(f"Warning: Could not parse rating '{rating}'")
        
        # Search trong Qdrant
        search_result = client.search(
            collection_name="car_rentals",
            query_vector=query_vector,
            query_filter=Filter(must=must_conditions) if must_conditions else None,
            limit=50  # Lấy top 50 kết quả
        )
        
        # Extract payloads
        results = [hit.payload for hit in search_result]

        results = _filter_car_rentals_results(
            results,
            location=location,
            name=name,
            price_tier=price_tier,
            rating_float=_normalize_number(rating, "float") if rating else None,
        )
        
        print(f"Qdrant semantic search: Found {len(results)} results")
        return results
        
    except Exception as e:
        print(f"Qdrant search failed: {e}, falling back to exact search")
        return _search_car_rentals_exact(data, location, name, price_tier, rating)

def _search_car_rentals_exact(data, location, name, price_tier, rating):
    """Fallback: Exact search với list comprehension (optimized single-pass)"""
    results = data.get("carRentals", [])
    
    rating_float = _normalize_number(rating, "float") if rating else None
    if rating and rating_float is None:
        print(f"Warning: Could not parse rating '{rating}'")
    
    # Single-pass filter
    filtered = _filter_car_rentals_results(
        results,
        location=location,
        name=name,
        price_tier=price_tier,
        rating_float=rating_float,
    )
    
    print(f"Exact search: Found {len(filtered)} results")
    return filtered


def _filter_car_rentals_results(
    results: list[dict],
    location: str | None = None,
    name: str | None = None,
    price_tier: str | None = None,
    rating_float: float | None = None,
) -> list[dict]:
    """Apply Python-side exact filters to car rental results."""
    normalized_price_tier = price_tier.lower() if price_tier else None
    normalized_location = location.lower() if location else None
    normalized_name = name.lower() if name else None

    filtered: list[dict] = []
    for rental in results:
        rental_location = rental.get("location", "")
        rental_name = rental.get("name", "")
        rental_price_tier = rental.get("price_tier", "")
        rental_rating = _normalize_number(rental.get("rating"), "float")

        if normalized_location and normalized_location not in rental_location.lower():
            continue
        if normalized_name and normalized_name not in rental_name.lower():
            continue
        if normalized_price_tier and normalized_price_tier != rental_price_tier.lower():
            continue
        if rating_float is not None and (rental_rating is None or rental_rating < rating_float):
            continue

        filtered.append(rental)

    return filtered

def search_cars_from_api(
    rental_id: int | None = None,
    car_type: str | None = None,
    car_rental_name: str | None = None,
    price: float | None = None,
    capacity: int | None = None,
) -> list[dict]:
    """
    Hybrid search cho cars: Kết hợp semantic search với exact filters.
    - Semantic search: car_type, car_rental_name
    - Exact filters: rental_id, price, capacity
    """
    data = _load_data()
    
    # Nếu có car_rental_name, tìm rental_id trước
    if car_rental_name and not rental_id:
        rental_id = fetch_car_rental_info_from_api(car_rental_name)
        if rental_id:
            print(f"Resolved car_rental_name '{car_rental_name}' -> rental_id {rental_id}")
    
    # Nếu không bật Qdrant hoặc không có bất kỳ text query nào → fallback
    # Cho phép semantic khi chỉ có car_rental_name (không cần car_type)
    if not USE_QDRANT or not (car_type or car_rental_name):
        return _search_cars_exact(data, rental_id, car_type, price, capacity)
    
    # --- Semantic Search với Qdrant ---
    try:
        client = _get_qdrant_client()
        embedder = _get_embedder()
        
        # Encode query từ car_type và/hoặc car_rental_name (nếu thiếu thì dùng từ khóa chung)
        query_parts = []
        if car_type:
            query_parts.append(car_type)
        if car_rental_name:
            query_parts.append(car_rental_name)
        query_text = " ".join(query_parts) if query_parts else "car"
        query_vector = embedder.encode(query_text).tolist()
        
        # Build filters (giữ các filter số trong Qdrant; rental_id filter sẽ xử lý an toàn ở Python)
        must_conditions = []
        if capacity:
            capacity_int = _normalize_number(capacity, "int")
            if capacity_int is not None:
                must_conditions.append(
                    FieldCondition(key="car_capacity", range=Range(gte=capacity_int))
                )
            else:
                print(f"Warning: Could not parse capacity '{capacity}'")
        if price:
            price_float = _normalize_number(price, "float")
            if price_float is not None:
                must_conditions.append(
                    FieldCondition(key="car_price", range=Range(lte=price_float))
                )
            else:
                print(f"Warning: Could not parse price '{price}'")
        
        # Search
        search_result = client.search(
            collection_name="car_details",
            query_vector=query_vector,
            query_filter=Filter(must=must_conditions) if must_conditions else None,
            limit=50
        )
        
        results = [hit.payload for hit in search_result]
        
        # Python-side strict filtering để tránh mismatch kiểu dữ liệu trong payload (str vs int)
        if rental_id is not None:
            results = [
                r for r in results
                if str(r.get('rental_id')) == str(rental_id)
            ]
        if capacity:
            capacity_int = _normalize_number(capacity, "int")
            if capacity_int is not None:
                results = [r for r in results if r.get('car_capacity', 0) >= capacity_int]
        if price:
            price_float = _normalize_number(price, "float")
            if price_float is not None:
                results = [r for r in results if r.get('car_price', 0) <= price_float]
        print(f"Qdrant semantic search (cars): Found {len(results)} results")
        return results
        
    except Exception as e:
        print(f"Qdrant search failed: {e}, falling back to exact search")
        return _search_cars_exact(data, rental_id, car_type, price, capacity)

def _search_cars_exact(data, rental_id, car_type, price, capacity):
    """Fallback: Exact search cho cars"""
    results = data.get("carDetails", [])
    
    # Normalize numeric values
    price_float = _normalize_number(price, "float") if price else None
    capacity_int = _normalize_number(capacity, "int") if capacity else None
    
    if price and price_float is None:
        print(f"Warning: Could not parse price '{price}'")
    if capacity and capacity_int is None:
        print(f"Warning: Could not parse capacity '{capacity}'")
    
    filtered = [
        c for c in results
        if (not rental_id or str(c.get('rental_id')) == str(rental_id))
        and (not car_type or car_type.lower() in c.get('car_type', '').lower())
        and (not price_float or c.get('car_price', 0) <= price_float)
        and (not capacity_int or c.get('car_capacity', 0) >= capacity_int)
    ]
    
    print(f"Exact search (cars): Found {len(filtered)} results")
    return filtered

def fetch_car_rental_info_from_api(car_rental_name: str) -> int | None:
    """Lấy id của đại lý cho thuê xe từ tên (từ API cloud)."""
    # data = _load_data()
    # car_rentals = data.get("CAR_RENTALS", [])
    # rental = next((cr for cr in car_rentals if car_rental_name.lower() in cr.get('name', '').lower()), None)
    # return rental['id'] if rental else None
    try:
        client = _get_qdrant_client()
        embedder = _get_embedder()
        query_vector=embedder.encode(car_rental_name).tolist()

        search_result = client.search(
            collection_name="car_rentals",
            query_vector=query_vector,
            limit=1
        )
        if search_result:
            return search_result[0].payload['id']
    except Exception as e:
        print(f" Qdrant search failed: {e}, falling back to exact search")
        data = _load_data()
        results = data.get("carRentals", [])
        car_rental = next((cr for cr in results if car_rental_name.lower() in cr.get('name', '').lower()), None)
        return car_rental['id'] if car_rental else None

def fetch_car_info_from_api(car_name: str, car_rental_id: int) -> dict:
    """Lấy thông tin xe từ tên xe và id đại lý (từ API cloud)."""
    # data = _load_data()
    # car_details = data.get("CAR_DETAILS", [])
    # car = next((
    #     cd for cd in car_details
    #     if car_name.lower() in cd.get('car_name', '').lower()
    #     and str(cd.get('rental_id')) == str(car_rental_id)
    # ), None)
    # if not car:
    #     return {}
    # return {
    #     "car_id": car.get('id'),
    #     "car_name": car.get('car_name'),
    #     "car_price": car.get('car_price'),
    #     "car_capacity": car.get('car_capacity')
    # }
    try:
        client = _get_qdrant_client()
        embedder = _get_embedder()
        query_vector=embedder.encode(car_name).tolist()
        must_conditions = [FieldCondition(key="rental_id", match=MatchValue(value=car_rental_id))]
        search_result = client.search(
            collection_name="car_details",
            query_vector=query_vector,
            query_filter=Filter(must=must_conditions) if must_conditions else None,
            limit=1,
            score_threshold=0.7,
        )
        if search_result:
            best_match = search_result[0]
            return {
                "car_id": best_match.payload.get('id'),
                "car_name": best_match.payload.get('car_name'),
                "car_price": best_match.payload.get('car_price'),
                "car_capacity": best_match.payload.get('car_capacity')
            }
        return {}
    except Exception as e:
        print(f" Qdrant search failed: {e}, falling back to exact search")
        data = _load_data()
        results = data.get("carDetails", [])
        car = next((c for c in results if car_name.lower() in c.get('car_name', '').lower() and str(c.get('rental_id')) == str(car_rental_id)), None)
        if not car:
            return {}
        return {
            "car_id": car.get('id'),
            "car_name": car.get('car_name'),
            "car_price": car.get('car_price'),
            "car_capacity": car.get('car_capacity')
        }


def check_realse_car_from_api(aim, booking_id, car_id, start_date, end_date):
    if not aim:
        return "Please provide a valid aim."
    if not start_date:
        return "Please provide a start date."
    if not end_date:
        return "Please provide a end date."
    data = _load_data()
    bookings = data.get("carBookings", [])   
    start_date = to_date(start_date)
    end_date = to_date(end_date)
    if aim == "book":
        if not car_id:
            return "Please provide a car id."
        unavailable_cars = [
            b for b in bookings
            if (b.get('car_id') == car_id) 
            and ( b.get('status') != "cancelled" )
            and not (((to_date(b.get('start_date')) > start_date) 
            and (end_date <= to_date(b.get('start_date')))) or  start_date 
            >= to_date(b.get('end_date')) )
        ]
    elif aim == 'update':
        if not booking_id:
            return "Please provide a booking id."
        
        unavailable_cars = [
            b for b in bookings
            if (b.get('booking_id') != booking_id) 
            and ( b.get('status') != "cancelled" )
            and not (((to_date(b.get('start_date')) > start_date) 
            and (end_date <= to_date(b.get('start_date')))) or  start_date 
            >= to_date(b.get('end_date')) )
        ]
    else:
        return "Please provide a valid aim."
    
    return unavailable_cars if unavailable_cars else None







def book_car_rental_in_api(
    rental_id: int,
    car_id: int,
    start_date: str,
    end_date: str,
    number_of_people: int,
    total_price: float,
) -> dict:
    """Book a car rental and save it to the cloud API."""
    all_data = _load_data()
    car_bookings = all_data.get("carBookings", [])

    new_booking_id = (max([b.get('booking_id', 0) for b in car_bookings]) + 1) if car_bookings else 1
    
    new_booking = {
        "booking_id": new_booking_id,
        "car_id": car_id,
        "start_date": start_date,
        "end_date": end_date,
        "people": number_of_people,
        "total_price": total_price,
        "status": "confirmed"
    }
    car_bookings.append(new_booking)
    all_data["carBookings"] = car_bookings
    
    _save_data(all_data)
    
    return new_booking

def update_car_booking_in_api(booking_id: int, new_start_date: str | None = None, new_end_date: str | None = None, total_price: float | None = None) -> dict | None:
    """Update a car booking in the cloud API."""
    all_data = _load_data()
    car_bookings = all_data.get("carBookings", [])
    
    booking_to_update = next((b for b in car_bookings if b.get('booking_id') == booking_id), None)
    
    if booking_to_update:
        if new_start_date:
            booking_to_update['start_date'] = new_start_date
        if new_end_date:
            booking_to_update['end_date'] = new_end_date
        if total_price:
            booking_to_update['total_price'] = total_price
        # all_data["CAR_BOOKINGS"] = car_bookings
        _save_data(all_data)
        return booking_to_update
    return None

def fetch_car_booking_info_from_api(booking_id: int) -> dict:
    if USE_QDRANT:
        try:
            client = _get_qdrant_client()
            points = client.retrieve(
                collection_name="car_bookings",
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
    bookings = data.get("carBookings", [])
    booking = next((b for b in bookings if b.get('booking_id') == booking_id), None)
    
    if not booking:
        return "Please provide a valid booking id."
    return booking

def cancel_car_booking_in_api(booking_id: int) -> bool:
    """Cancel a car booking in the cloud API."""
    if not booking_id:
        return "Please provide a booking id."
    data = _load_data()
    bookings = data.get("carBookings", [])
    booking_to_cancel = next((b for b in bookings if b.get('booking_id') == booking_id), None)
    if not booking_to_cancel:
        return "Please provide a valid booking id."
    if booking_to_cancel['status'] == "confirmed":
        booking_to_cancel['status'] = "cancelled"
    _save_data(data)
    return f"Đã hủy thành công mã đặt xe {booking_id}."
