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


# Namespace for generating deterministic UUIDs from business keys
NAMESPACE_UUID = uuid.uuid5(uuid.NAMESPACE_DNS, 'customer-support-agent.flight')


def _normalize_vietnamese(text):
    """Normalize Vietnamese text by removing diacritics for comparison"""
    if not text:
        return ""
    # Replace Đ/đ with D/d first (these are separate characters, not composed)
    text = text.replace('Đ', 'D').replace('đ', 'd')
    # Normalize to NFD (decompose characters)
    nfd = unicodedata.normalize('NFD', text)
    # Remove combining characters (diacritics)
    return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn').lower().strip()


# Get credentials from environment variables
BIN_ID_FLIGHT = os.getenv("BIN_ID_FLIGHT")
API_KEY = os.getenv("API_KEY")
USE_QDRANT = os.getenv("USE_QDRANT", "true").lower() == "true"  
API_URL = f'https://api.jsonbin.io/v3/b/{BIN_ID_FLIGHT}'
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
    collection_names = ["flights_v2","flight_prices","passengers","bookings","tickets"]
   
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
    Hàm này sẽ kiểm tra các ID đã có và chỉ nạp những airports/airlines/flights/flight_prices/passengers/bookings/tickets chưa tồn tại.
    """
    if not USE_QDRANT:
        return
   
    client = _get_qdrant_client()
    embedder = _get_embedder()
    _init_qdrant_collections()


    # --- Index Flights ---
    collection_name_flights = "flights_v2"
    try:
        existing_flights_points = client.scroll(
            collection_name=collection_name_flights,
            limit=10000,
            with_payload=False,
            with_vectors=False
        )[0]
        existing_flights_ids = {point.id for point in existing_flights_points}
        print(f"Found {len(existing_flights_ids)} existing flights points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing flights points (collection might be new): {e}")
        existing_flights_ids = set()


    flights = data.get("flights", [])
    # Convert flight_id to UUID for Qdrant compatibility
    new_flights = []
    for flight in flights:
        point_id = str(uuid.uuid5(NAMESPACE_UUID, str(flight.get('flight_id'))))
        if point_id not in existing_flights_ids:
            new_flights.append(flight)
   
    if not new_flights:
        print(" Qdrant (Flights) is up-to-date. No new flights to index.")
    else:
        print(f"Indexing {len(new_flights)} new flights...")
        flight_points = []
        for flight in new_flights:
            # Create a rich text for semantic vector
            text_parts = [
                "chuyen bay",
                flight.get('flight_no', ''),
                flight.get('airline_name', ''),
                "tu", flight.get('city_depart', ''), flight.get('airport_name_depart', ''), flight.get('departure_airport_id', ''),
                "den", flight.get('city_arrive', ''), flight.get('airport_name_arrive', ''), flight.get('arrival_airport_id', '')
            ]
            text = " ".join(filter(None, text_parts))
            vector = embedder.encode(text).tolist()
            point_id = str(uuid.uuid5(NAMESPACE_UUID, str(flight.get('flight_id'))))
            
            # Prepare payload with proper datetime format for Qdrant
            payload = flight.copy()
            for key in ['departure_time', 'arrival_time']:
                if payload.get(key):
                    try:
                        # Convert "YYYY-MM-DD HH:MM" to ISO 8601 format "YYYY-MM-DDTHH:MM:SS"
                        dt_obj = datetime.strptime(payload[key], "%Y-%m-%d %H:%M")
                        payload[key] = dt_obj.isoformat()
                    except ValueError:
                        # Keep original if format is wrong, which will prevent datetime filtering
                        pass

            flight_points.append(PointStruct(id=point_id, vector=vector, payload=payload))


        if flight_points:
            try:
                client.upsert(collection_name=collection_name_flights, points=flight_points)
                print(f" Successfully indexed {len(flight_points)} flights to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new flights: {e}")


    collection_name_flight_prices = "flight_prices"
    try:
        existing_flight_prices_points = client.scroll(
            collection_name=collection_name_flight_prices,
            limit=10000,
            with_payload=False,
            with_vectors=False
        )[0]
        existing_flight_prices_ids = {point.id for point in existing_flight_prices_points}
        print(f"Found {len(existing_flight_prices_ids)} existing flight prices points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing flight prices points (collection might be new): {e}")
        existing_flight_prices_ids = set()


    flight_prices = data.get("flight_prices", [])
   
    new_flight_prices = []
    for fp in flight_prices:
        composite_id = f"{fp.get('flight_id')}-{fp.get('seat_type')}"
        point_id = str(uuid.uuid5(NAMESPACE_UUID, composite_id))
        if point_id not in existing_flight_prices_ids:
            new_flight_prices.append(fp)


    if not new_flight_prices:
        print(" Qdrant (Flight Prices) is up-to-date. No flight prices to index.")
    else:
        print(f" Indexing {len(new_flight_prices)} flight prices...")
        flight_price_points = []
        for flight_price in new_flight_prices:
            # Tạo ID tổng hợp từ flight_id và seat_type
            composite_id = f"{flight_price.get('flight_id')}-{flight_price.get('seat_type')}"
            point_id = str(uuid.uuid5(NAMESPACE_UUID, composite_id))
            # Lấy thông tin chi tiết để tạo vector giàu ngữ nghĩa
            text = f"{flight_price.get('seat_type')} {flight_price.get('price')} {flight_price.get('currency')} {flight_price.get('seat_quota')}"
            vector = embedder.encode(text).tolist()
            flight_price_points.append(PointStruct(id=point_id, vector=vector, payload=flight_price))


        if flight_price_points:
            try:
                client.upsert(collection_name=collection_name_flight_prices, points=flight_price_points)
                print(f" Successfully indexed {len(flight_price_points)} flight prices to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new flight prices: {e}")


    # --- Index Passengers ---
    collection_name_passengers = "passengers"
    try:
        existing_passengers_points = client.scroll(
            collection_name=collection_name_passengers,
            limit=10000,  
            with_payload=False,
            with_vectors=False
        )[0]
        existing_passengers_ids = {point.id for point in existing_passengers_points}
        print(f"Found {len(existing_passengers_ids)} existing passengers points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing passengers points (collection might be new): {e}")
        existing_passengers_ids = set()


    passengers = data.get("passengers", [])
    new_passengers = [
        p for p in passengers
        if str(uuid.uuid5(NAMESPACE_UUID, p.get('passenger_id'))) not in existing_passengers_ids
    ]
   
    if not new_passengers:
        print(" Qdrant (Passengers) is up-to-date. No new passengers to index.")
    else:
        print(f"⏳ Found {len(new_passengers)} new passengers to index...")
        passenger_points = []
        for p in new_passengers:
            text = f"{p.get('passenger_id')} {p.get('passenger_name')} {p.get('contact_data')}"
            vector = embedder.encode(text).tolist()
            point_id = str(uuid.uuid5(NAMESPACE_UUID, p.get('passenger_id')))
            passenger_points.append(PointStruct(id=point_id, vector=vector, payload=p))
       
        if passenger_points:
            try:
                client.upsert(collection_name=collection_name_passengers, points=passenger_points)
                print(f" Successfully indexed {len(passenger_points)} new passengers to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new passengers: {e}")


    # --- Index Bookings ---
    collection_name_bookings = "bookings"
    try:
        existing_bookings_points = client.scroll(
            collection_name=collection_name_bookings,
            limit=10000,
            with_payload=False,
            with_vectors=False
        )[0]
        existing_bookings_ids = {point.id for point in existing_bookings_points}
        print(f"Found {len(existing_bookings_ids)} existing bookings points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing bookings points (collection might be new): {e}")
        existing_bookings_ids = set()


    bookings = data.get("bookings", [])
    new_bookings = [
        b for b in bookings
        if str(uuid.uuid5(NAMESPACE_UUID, str(b.get('book_ref')))) not in existing_bookings_ids
    ]


    if not new_bookings:
        print(" Qdrant (Bookings) is up-to-date. No new bookings to index.")
    else:
        print(f"⏳ Indexing {len(new_bookings)} bookings...")
        booking_points = []
        for booking in new_bookings:
            text = f"Booking reference {booking.get('book_ref')} on {booking.get('book_date')} for total amount {booking.get('total_amount')}"
            vector = embedder.encode(text).tolist()
            point_id = str(uuid.uuid5(NAMESPACE_UUID, str(booking.get('book_ref'))))
            booking_points.append(PointStruct(id=point_id, vector=vector, payload=booking))


        if booking_points:
            try:
                client.upsert(collection_name=collection_name_bookings, points=booking_points)
                print(f" Successfully indexed {len(booking_points)} bookings to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new bookings: {e}")


    # --- Index Tickets ---
    collection_name_tickets = "tickets"
    try:
        existing_tickets_points = client.scroll(
            collection_name=collection_name_tickets,
            limit=10000,
            with_payload=False,
            with_vectors=False
        )[0]
        existing_tickets_ids = {point.id for point in existing_tickets_points}
        print(f"Found {len(existing_tickets_ids)} existing tickets points in Qdrant.")
    except Exception as e:
        print(f"Could not fetch existing tickets points (collection might be new): {e}")
        existing_tickets_ids = set()


    tickets = data.get("tickets", [])
    new_tickets = [
        t for t in tickets
        if str(uuid.uuid5(NAMESPACE_UUID, t.get('ticket_no'))) not in existing_tickets_ids
    ]


    if not new_tickets:
        print(" Qdrant (Tickets) is up-to-date. No new tickets to index.")
    else:
        print(f"⏳ Indexing {len(new_tickets)} tickets...")
        ticket_points = []
        for ticket in new_tickets:
            text = f"Ticket number {ticket.get('ticket_no')} for passenger {ticket.get('passenger_id')}"
            vector = embedder.encode(text).tolist()
            point_id = str(uuid.uuid5(NAMESPACE_UUID, ticket.get('ticket_no')))
            ticket_points.append(PointStruct(id=point_id, vector=vector, payload=ticket))


        if ticket_points:
            try:
                client.upsert(collection_name=collection_name_tickets, points=ticket_points)
                print(f" Successfully indexed {len(ticket_points)} tickets to Qdrant.")
            except Exception as e:
                print(f"Warning: Could not index new tickets: {e}")




def _load_data():
    global _cache
    if _cache:
        return _cache


    if not BIN_ID_FLIGHT or not API_KEY:
        raise ValueError("BIN_ID và API_KEY chưa được thiết lập trong file .env")
   
    response = requests.get(f"{API_URL}/latest", headers=HEADERS)
    response.raise_for_status()
   
    data = response.json()['record']
    _cache = data  
   
    if USE_QDRANT:
        _index_data_to_qdrant(data)
   
    return data


def _save_data(data):
    global _cache, _qdrant_initialized
    if not BIN_ID_FLIGHT or not API_KEY:
        raise ValueError("BIN_ID và API_KEY chưa được thiết lập trong file .env")


    response = requests.put(API_URL, json=data, headers=HEADERS)
    response.raise_for_status()
   
    _cache = None
    _qdrant_initialized = False  
   
    if USE_QDRANT:
        _index_data_to_qdrant(data)




def search_flight_from_api(
    departure_airport_code: str | None = None,
    arrival_airport_code: str | None = None,
    departure_time: str | None = None,
    arrival_time: str | None = None,
    city_depart: str| None = None,
    city_arrive: str| None = None,
    flight_no: str | None = None,
    **kwargs
) -> list[dict]:
    """
    Search for flights based on departure airport name or code
    or arrival airport name or code,
    flight_no, city_depart, city_arrive, departure time or arrival time or date.
    """
    data = _load_data()
   
    is_semantic_query = any([ city_depart, city_arrive])
    has_filters = any([departure_airport_code, arrival_airport_code, departure_time, arrival_time, flight_no])


    # Fallback if Qdrant is disabled
    if not USE_QDRANT:
        return _search_flight_exact(data,  departure_airport_code, arrival_airport_code, departure_time, arrival_time, flight_no, city_depart, city_arrive)
       
    try:
        client = _get_qdrant_client()
        embedder = _get_embedder()


        # --- Build Qdrant filters for exact match ---
        must_conditions = []
        if departure_airport_code:
            must_conditions.append(
                FieldCondition(key="departure_airport_id", match=MatchValue(value=departure_airport_code))
            )
        if arrival_airport_code:
            must_conditions.append(
                FieldCondition(key="arrival_airport_id", match=MatchValue(value=arrival_airport_code))
            )

        # Handle date range for departure_time using DatetimeRange
        if departure_time:
            parsed_date = to_date(departure_time)
            if parsed_date:
                day_start = datetime.combine(parsed_date, datetime.min.time()).isoformat()
                day_end = datetime.combine(parsed_date, datetime.max.time()).isoformat()
                must_conditions.append(
                    FieldCondition(key="departure_time", datetime_range=models.DatetimeRange(gte=day_start, lte=day_end))
                )

        # Handle date range for arrival_time using DatetimeRange
        if arrival_time:
            parsed_date = to_date(arrival_time)
            if parsed_date:
                day_start = datetime.combine(parsed_date, datetime.min.time()).isoformat()
                day_end = datetime.combine(parsed_date, datetime.max.time()).isoformat()
                must_conditions.append(
                    FieldCondition(key="arrival_time", datetime_range=models.DatetimeRange(gte=day_start, lte=day_end))
                )
        
        if flight_no:
            must_conditions.append(
                FieldCondition(key="flight_no", match=MatchValue(value=flight_no))
            )


        # --- Decide Search Strategy ---
        if is_semantic_query:
            # 1. Semantic Search + Filtering
            print("Executing semantic search with filters...")
            query_parts = []
            if city_depart: query_parts.append(city_depart)
            if city_arrive: query_parts.append(city_arrive)
            query_text = " ".join(query_parts)
            query_vector = embedder.encode(query_text).tolist()


            search_result = client.search(
                collection_name="flights_v2",
                query_vector=query_vector,
                query_filter=Filter(must=must_conditions) if must_conditions else None,
                limit=50
            )
           
            # Post-filter by city and date for more accurate results
            results = []
            
            results = [hit.payload for hit in search_result]
           
            print(f"Qdrant semantic search: Found {len(results)} results")


        elif has_filters:
            # 2. Filter-Only Search
            print("Executing filter-only search with Qdrant...")
            scroll_result, _ = client.scroll(
                collection_name="flights_v2",
                scroll_filter=Filter(must=must_conditions),
                limit=200 # Get up to 200 results for filter-only
            )
            results = [record.payload for record in scroll_result]
            print(f"Qdrant filter-only search: Found {len(results)} results")
       
        else:
            # 3. No criteria, fallback to exact search (which will return all)
            return _search_flight_exact(data,  departure_airport_code, arrival_airport_code, departure_time, arrival_time, flight_no, city_depart, city_arrive)


        return results
           
    except Exception as e:
        print(f"Qdrant search failed: {e}, falling back to exact search")
        return _search_flight_exact(data,  departure_airport_code, arrival_airport_code, departure_time, arrival_time, flight_no, city_depart, city_arrive)


def _search_flight_exact(data,  departure_airport_code, arrival_airport_code, departure_time, arrival_time, flight_no, city_depart, city_arrive):
    """Fallback: Exact search with list comprehension (optimized single-pass)"""
    results = data.get("flights", [])
   
    # Normalize inputs
    dep_code = departure_airport_code.upper().strip() if departure_airport_code else None
    arr_code = arrival_airport_code.upper().strip() if arrival_airport_code else None
    f_no = flight_no.lower().strip() if flight_no else None
    dep_date = departure_time.strip() if departure_time else None
    dep_city = city_depart.lower().strip() if city_depart else None
    arr_city = city_arrive.lower().strip() if city_arrive else None


    filtered = [
        flight for flight in results
        if (not dep_code or flight.get('departure_airport_id') == dep_code)
        and (not arr_code or flight.get('arrival_airport_id') == arr_code)
        and (not dep_city or dep_city in (flight.get('city_depart') or '').lower())
        and (not arr_city or arr_city in (flight.get('city_arrive') or '').lower())
        and (not dep_date or str(flight.get('departure_time', '')).startswith(dep_date))
        and (not f_no or (
            f_no in str(flight.get('flight_id', '')).lower() or
            f_no in str(flight.get('flight_no', '')).lower()
        ))
    ]
   
    print(f"Exact search (flights): Found {len(filtered)} results")
    return filtered


def fetch_flight_price_from_api(flight_id: str | None = None, seat_type: str | None = None) -> dict:
    """
    Fetch a flight price based on flight_id and seat_type.
    """
    data = _load_data()
    if not USE_QDRANT:
        return _fetch_flight_price_exact(data, flight_id, seat_type)
    if not flight_id:
        return "Please provide a flight_id."
    if not seat_type:
        return "Please provide seat type you want to fetch."
    try:
        client = _get_qdrant_client()
        embedder = _get_embedder()
        query_vector = embedder.encode(seat_type).tolist()
        must_conditions = [FieldCondition(key="flight_id", match=MatchValue(value=flight_id))]
        search_result = client.search(
            collection_name="flight_prices",
            query_vector=query_vector,
            query_filter=Filter(must=must_conditions) if must_conditions else None,
            limit=1,
            score_threshold=0.7,
        )
        if search_result:
            best_match = search_result[0]
            return best_match.payload
        return {}
    except Exception as e:
        print(f" Qdrant search failed: {e}, falling back to exact search")
        return _fetch_flight_price_exact(data, flight_id, seat_type)

def _fetch_flight_price_exact(data, flight_id, seat_type):
    """Fallback: Exact search with list comprehension (optimized single-pass)"""
    results = data.get("flight_prices", [])
    filtered = [
        fp for fp in results
        if (not flight_id or fp.get('flight_id') == flight_id)
        and (not seat_type or seat_type in (fp.get('seat_type') or '').lower())
    ]
    print(f"Exact search (flight prices): Found {len(filtered)} results")
    return filtered


def search_flight_price_from_api(
    flight_id: str | None = None,
    seat_type: str | None = None,
) -> list[dict]:
    """
    Search for flight prices based on flight_id anf seat_types (eco, business, first). if seat_type is not provided, return all seat types.
    """
    data = _load_data()
    if not USE_QDRANT:
        return _search_flight_price_exact(data, flight_id, seat_type)
    
    if not flight_id:
        return "Please provide a flight_id."
    
    try:
        client = _get_qdrant_client()
        embedder = _get_embedder()
        query_parts = []
        if seat_type:
            query_parts.append(seat_type)
        query_text = " ".join(query_parts)
        
        query_vector = embedder.encode(query_text).tolist()
        
        must_conditions = []
        if flight_id:
            must_conditions.append(
                FieldCondition(key="flight_id", match=MatchValue(value=flight_id))
            )
        search_result = client.search(
            collection_name="flight_prices",
            query_vector=query_vector,
            query_filter=Filter(must=must_conditions) if must_conditions else None,
            limit=50  
        )
        
        results = [hit.payload for hit in search_result]
        
        print(f" Qdrant semantic search: Found {len(results)} results")
        return results
    except Exception as e:
        print(f" Qdrant search failed: {e}, falling back to exact search")
        return _search_flight_price_exact(data, flight_id, seat_type)


def _search_flight_price_exact(data, flight_id, seat_type):
    """Fallback: Exact search with list comprehension (optimized single-pass)"""
    results = data.get("flight_prices", [])
    filtered = [
        fp for fp in results
        if (not flight_id or fp.get('flight_id') == flight_id)
        and (not seat_type or seat_type in (fp.get('seat_type') or '').lower())
    ]
    print(f"Exact search (flight prices): Found {len(filtered)} results")
    return filtered


def generate_next_booking_id(bookings: list[dict], prefix="BKG") -> str:
    """
    Tạo booking_id tiếp theo theo định dạng 'BKG001', 'BKG002',...
    """
    if not bookings:
        return f"{prefix}001"
    
    max_num = 0
    # Lặp qua các booking để tìm số lớn nhất
    for b in bookings:
        booking_id = b.get('booking_id')
        if isinstance(booking_id, str) and booking_id.startswith(prefix):
            try:
                num_part = int(booking_id[len(prefix):])
                if num_part > max_num:
                    max_num = num_part
            except (ValueError, TypeError):
                # Bỏ qua nếu phần số không hợp lệ
                continue
        elif isinstance(booking_id, int):
            # Xử lý trường hợp booking_id cũ là số nguyên
            if booking_id > max_num:
                max_num = booking_id

    next_num = max_num + 1
    # Định dạng số với 3 chữ số, ví dụ: 1 -> "001", 12 -> "012"
    return f"{prefix}{next_num:03d}"





def generate_next_ticket_no(tickets: list[dict], prefix="T") -> str:
    """
    Generate the next ticket number.
    """
    if not tickets:
        return f"{prefix}001"
    
    max_num = 0
    for t in tickets:
        ticket_id = t.get('ticket_id')
        if isinstance(ticket_id, str) and ticket_id.startswith(prefix):
            try:
                num_part = int(ticket_id[len(prefix):])
                if num_part > max_num:
                    max_num = num_part
            except (ValueError, TypeError):
                continue
    
    next_num = max_num + 1
    return f"{prefix}{next_num:03d}"

def  book_flight_from_api(
    flight_id: str | None = None,
    seat_type: str | None = None,
    passengers: int | None = None
) -> str:
    """
    Book a flight based on flight_id and seat_type, passengers and price_per_person.
    If passengers is not provided, book 1 passenger.
    """

    price = fetch_flight_price_from_api(flight_id, seat_type)
    if not price:
        return "Please provide a valid flight_id and seat_type."
    total_price = price * passengers
    if not total_price:
        return "Please provide a valid passengers."
    data = _load_data()
    bookings = data.get("booking", [])
    tickets = data.get("tickets", [])

    new_booking_id = generate_next_booking_id(bookings)
    
    new_booking = {
        "booking_id": new_booking_id,
        "total_price": total_price,
        "booking_status": "confirmed",
        "flight_id": flight_id,
        "book_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    bookings.append(new_booking)
    data["booking"] = bookings
    
    # Generate tickets
    created_tickets = []
    for _ in range(passengers):
        new_ticket_no = generate_next_ticket_no(tickets)
        new_ticket = {
            "ticket_no": new_ticket_no,
            "book_ref": new_booking_id,
            "flight_id": flight_id,
            "seat_type": seat_type,
            "passenger_id": None, # To be updated later
            "passenger_name": None # To be updated later
        }
        tickets.append(new_ticket)
        created_tickets.append(new_ticket_no)
    
    data["tickets"] = tickets
    
    _save_data(data)
    
    return f"Booking confirmed with ID {new_booking_id}. Tickets created: {', '.join(created_tickets)}. Please provide passenger details for each ticket."


def fetch_passenger_from_api(id_type: str, id_number: str) -> dict:
    """
    Fetch a passenger from the API.
    """
    data = _load_data()
    passengers = data.get("passengers", [])
    client = _get_qdrant_client()
    embedder = _get_embedder()
    query_vector = embedder.encode(f"{id_type}").tolist()
    must_conditions = [FieldCondition(key="id_number", match=MatchValue(value=id_number))]
    search_result = client.search(
        collection_name="passengers",
        query_vector=query_vector,
        query_filter=Filter(must=must_conditions) if must_conditions else None,
        limit=1,    
    )
    if not search_result:
        return None
    return search_result[0].payload

def update_ticket_passenger_from_api(ticket_no: str, passenger_name: str, passenger_id: str = None, date_of_birth: str = None, id_type: str = None, id_number: str = None, nationality: str = None) -> str:
    """
    Update passenger details for a specific ticket.

    """
    data = _load_data()
    tickets = data.get("tickets", [])
    client = _get_qdrant_client()
    embedder = _get_embedder()
    passenger_info = fetch_passenger_from_api(id_type, id_number)
    if not passenger_info:
        return f"Passenger {id_type} {id_number} not found."
    ticket = next((t for t in tickets if t.get("ticket_no") == ticket_no), None)
    if not ticket:
        return f"Ticket {ticket_no} not found."
    ticket["passenger_id"] = passenger_info.get("passenger_id")
    
    passengers = data.get("passengers", [])
    if not passenger_id and not ticket.get("passenger_id"):
        passenger_id = generate_next_passenger_id(passengers)
        ticket["passenger_id"] = passenger_id
        
        # Add to passengers list
        new_passenger = {
            "passenger_id": new_p_id,
            "passenger_name": passenger_name,
            "dob": to_date(date_of_birth).isoformat(),
            "id_type": id_type,
            "id_number": id_number,
            "nationality": nationality
        }
        passengers.append(new_passenger)
        data["passengers"] = passengers
    
    # Save
    data["tickets"] = tickets
    _save_data(data)
    
    return f"Ticket {ticket_no} updated with passenger {passenger_name}."
