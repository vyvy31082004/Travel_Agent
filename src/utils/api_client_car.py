import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from urllib.parse import quote
from api.car_api import crawl_mioto_cars, crawl_car_details
from datetime import date, datetime
from zoneinfo import ZoneInfo
import os
import requests
from dotenv import load_dotenv
load_dotenv()
from typing import Optional

MIOTO_FILTER_BASE_URL = "https://www.mioto.vn/find/filter"
GEOCODING_RAPIDAPI_HOST = os.getenv("GEOCODING_RAPIDAPI_HOST", "maps-data.p.rapidapi.com")
GEO_BASE_URL = f"https://{GEOCODING_RAPIDAPI_HOST}"
BOOKING_LANGUAGE_CODE = os.getenv("BOOKING_LANGUAGE_CODE", "vi")
BOOKING_CURRENCY_CODE = os.getenv("BOOKING_CURRENCY_CODE", "VND")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")




def _booking_headers() -> dict:
    if not RAPIDAPI_KEY:
        raise RuntimeError("Thiếu RAPIDAPI_KEY trong file .env")

    return {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": GEOCODING_RAPIDAPI_HOST,
    }


def _booking_get(path: str, params: dict) -> dict | list:
    url = f"{GEO_BASE_URL}{path}"

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
def build_mioto_filter_url(
    start_ms: int | str,
    end_ms: int | str,
    address: str,
    lat: float | str,
    lng: float | str,
    category_id: int | str | None = None,
    address_is_encoded: bool = False,
) -> str:
    """
    Build Mioto search URL from filter parameters.

    Use address_is_encoded=True only when address is already URL encoded.
    """
    required_values = {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "address": address,
        "lat": lat,
        "lng": lng,
    }
    missing_fields = [
        field for field, value in required_values.items() if value is None or value == ""
    ]
    if missing_fields:
        raise ValueError(f"Thiếu tham số: {', '.join(missing_fields)}")

    encoded_address = address if address_is_encoded else quote(str(address), safe="")
    query_parts = [
        f"startDate={start_ms}",
        f"endDate={end_ms}",
        f"address={encoded_address}",
        f"lat={lat}",
        f"lng={lng}",
    ]

    if category_id is not None and category_id != "":
        query_parts.append(f"cateId={category_id}")

    return f"{MIOTO_FILTER_BASE_URL}?{'&'.join(query_parts)}"

def datetime_to_millis(dt: int | float | str, timezone: str = "Asia/Ho_Chi_Minh") -> int:
    """
    Convert datetime input sang Unix milliseconds.

    Input hợp lệ:
    - Unix milliseconds: 1784730600000
    - Unix seconds: 1784730600
    - Datetime string: "2026-07-22 21:30"
    - Date string: "2026-07-22"
    """
    if isinstance(dt, (int, float)):
        timestamp = int(dt)
        return timestamp if timestamp >= 10_000_000_000 else timestamp * 1000

    dt = str(dt).strip()
    if dt.isdigit():
        timestamp = int(dt)
        return timestamp if timestamp >= 10_000_000_000 else timestamp * 1000

    parsed_dt = None
    for parse_format in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed_dt = datetime.strptime(dt, parse_format)
            break
        except ValueError:
            continue

    if parsed_dt is None:
        raise ValueError(
            "Thời gian phải là Unix milliseconds hoặc chuỗi dạng 'YYYY-MM-DD HH:MM'."
        )

    parsed_dt = parsed_dt.replace(tzinfo=ZoneInfo(timezone))
    return int(parsed_dt.timestamp() * 1000)


def _find_coordinates(data: dict | list) -> dict | None:
    if isinstance(data, dict):
        lat = data.get("lat") or data.get("latitude")
        lng = data.get("lng") or data.get("lon") or data.get("longitude")
        if lat is not None and lng is not None:
            return {"lat": lat, "lng": lng}

        for value in data.values():
            coordinates = _find_coordinates(value)
            if coordinates:
                return coordinates

    if isinstance(data, list):
        for item in data:
            coordinates = _find_coordinates(item)
            if coordinates:
                return coordinates

    return None

def _extract_car_id(link: str) -> str:
    if not link:
        return ""
    return link.rstrip("/").split("/")[-1]


def _normalize_mioto_car(raw_car: dict) -> dict:
    link = raw_car.get("Link", "")
    return {
        "car_id": _extract_car_id(link),
        "Tên xe": raw_car.get("Tên xe", ""),
        "Giá sau giảm": raw_car.get("Giá sau giảm", ""),
        "Giá gốc": raw_car.get("Giá gốc", ""),
        "Hộp số": raw_car.get("Hộp số", ""),
        "Số chỗ": raw_car.get("Số chỗ", ""),
        "Nhiên liệu": raw_car.get("Nhiên liệu", ""),
        "Địa chỉ": raw_car.get("Địa chỉ", ""),
        "Rating": raw_car.get("Rating", ""),
        "Số chuyến": raw_car.get("Số chuyến", ""),
        "Tags": raw_car.get("Tags", ""),
        "Ảnh": raw_car.get("Ảnh", ""),
        "Link": link,
    }



import re
import unicodedata
from difflib import SequenceMatcher


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("đ", "d")

    text = unicodedata.normalize("NFD", text)
    text = "".join(
        char for char in text
        if unicodedata.category(char) != "Mn"
    )

    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def map_car_need_to_category_id(car_need: str | int | None) -> int | None:
    """
    Map nhu cầu thuê xe sang cateId của Mioto.

    Ví dụ:
    - "xe điện" -> 4
    - "xe tiết kiệm xăng" -> 2
    - "đi chơi với gia đình" -> 7
    - "người mới lái" -> 15
    """

    if car_need is None:
        return None

    if isinstance(car_need, int):
        return car_need

    if isinstance(car_need, str) and car_need.strip().isdigit():
        return int(car_need.strip())

    query = normalize_text(car_need)

    best_id = None
    best_score = 0

    MIOTO_CATEGORY_ALIASES = {
    4: [
        "xe điện",
        "ô tô điện",
        "oto điện",
        "electric",
        "ev",
        "xe xanh",
        "không xăng",
        "khong xang",
    ],

    2: [
        "xe hybrid",
        "hybrid",
        "xăng điện",
        "xang dien",
        "lai xăng điện",
        "tiết kiệm xăng",
        "tiet kiem xang",
        "ít hao xăng",
        "it hao xang",
    ],

    22: [
        "xe thể thao",
        "xe the thao",
        "sport",
        "sports car",
        "coupe",
        "mui trần",
        "mui tran",
        "xe mạnh",
        "xe dep ca tinh",
    ],

    15: [
        "lái mới",
        "lai moi",
        "người mới lái",
        "nguoi moi lai",
        "mới biết lái",
        "moi biet lai",
        "dễ lái",
        "de lai",
        "xe dễ chạy",
        "xe de chay",
        "tài mới",
        "tai moi",
    ],

    8: [
        "công việc đi lại",
        "cong viec di lai",
        "đi làm",
        "di lam",
        "đi công tác",
        "di cong tac",
        "di chuyển hằng ngày",
        "di chuyen hang ngay",
        "gặp khách hàng",
        "gap khach hang",
        "chạy việc",
        "chay viec",
    ],

    7: [
        "gia đình",
        "gia dinh",
        "đi với gia đình",
        "di voi gia dinh",
        "chở vợ con",
        "cho vo con",
        "chở ba mẹ",
        "cho ba me",
        "có trẻ em",
        "co tre em",
        "xe rộng",
        "xe rong",
        "xe 7 chỗ",
        "xe 7 cho",
    ],

    10: [
        "cắm trại",
        "cam trai",
        "camping",
        "dã ngoại",
        "da ngoai",
        "picnic",
        "đi rừng",
        "di rung",
        "đi núi",
        "di nui",
        "đi phượt",
        "di phuot",
    ],

    9: [
        "nhóm bạn",
        "nhom ban",
        "đi với bạn",
        "di voi ban",
        "bạn bè",
        "ban be",
        "đi chơi nhóm",
        "di choi nhom",
        "team building",
        "đi đông người",
        "di dong nguoi",
    ],

    17: [
        "tiếp khách dự tiệc",
        "tiep khach du tiec",
        "tiếp khách",
        "tiep khach",
        "dự tiệc",
        "du tiec",
        "đi tiệc",
        "di tiec",
        "đám cưới",
        "dam cuoi",
        "sự kiện",
        "su kien",
        "xe sang",
        "sang trọng",
        "sang trong",
        "gặp đối tác",
        "gap doi tac",
        "đón khách",
        "don khach",
    ],
}

    for cate_id, aliases in MIOTO_CATEGORY_ALIASES.items():
        for alias in aliases:
            alias_norm = normalize_text(alias)

            # Match mạnh nhất: alias nằm trong câu user
            if alias_norm in query:
                return cate_id

            # Match gần nghĩa / gần chữ
            score = text_similarity(query, alias_norm)

            query_tokens = set(query.split())
            alias_tokens = set(alias_norm.split())
            overlap = len(query_tokens & alias_tokens)

            score += overlap * 0.15

            if score > best_score:
                best_score = score
                best_id = cate_id

    if best_score >= 0.55:
        return best_id

    return None

def search_address(address: str) -> dict:
    params = {
        "query": address,
        # "lang": BOOKING_LANGUAGE_CODE,
        # "country": "VN",
    }
    address_info = _booking_get(path="/geocoding.php", params=params)
    coordinates = _find_coordinates(address_info)
    if not coordinates:
        raise ValueError(f"Không tìm được tọa độ cho địa chỉ '{address}'.")
    return coordinates

def _normalize_car_details(raw_car: dict) -> dict:
    return {
        "car_id": raw_car.get("car_id", ""),
        "Tên xe": raw_car.get("Tên xe", ""),
        "Giá gốc": raw_car.get("Giá gốc", ""),
        "Hộp số": raw_car.get("Hộp số", ""),
        "Số chỗ": raw_car.get("Số chỗ", ""),
    }
def parse_mioto_price(price_text: str | None) -> int | None:
    if not price_text or price_text.strip() in {"", "Không có", "N/A"}:
        return None

    text = str(price_text).strip().upper().replace(",", ".")
    text = text.replace("Đ", "").replace("VND", "").replace(" ", "")

    multiplier = 1
    if text.endswith("K"):
        multiplier = 1_000
        text = text[:-1]
    elif text.endswith("M") or text.endswith("TR"):
        multiplier = 1_000_000
        text = re.sub(r"(M|TR)$", "", text)

    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def filter_cars_by_price(
    cars: list[dict],
    price_min: int | None = None,
    price_max: int | None = None,
) -> list[dict]:
    # Tool defaults min_price=0 / max_price=0 mean "no price filter".
    if not price_min:
        price_min = None
    if not price_max:
        price_max = None

    if price_min is None and price_max is None:
        return cars

    filtered = []

    for car in cars:
        price = parse_mioto_price(car.get("Giá gốc")) or parse_mioto_price(
            car.get("Giá sau giảm")
        )
        if price is None:
            continue

        if price_min is not None and price < price_min:
            continue
        if price_max is not None and price > price_max:
            continue

        filtered.append(car)

    return filtered
def search_cars_from_api(
    start_ms: int | str,
    end_ms: int | str,
    address: str,
    # category_id: int | str | None = None,
    user_needs: str | None,
    limit: int = 30,
    max_scroll: int = 20,
    max_price: int = 0,
    min_price: int = 0,
    address_is_encoded: bool = False,
) -> list[dict]:
    start_ms = datetime_to_millis(start_ms, timezone="Asia/Ho_Chi_Minh")
    end_ms = datetime_to_millis(end_ms, timezone="Asia/Ho_Chi_Minh")
    now_ms = int(datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).timestamp() * 1000)
    if start_ms < now_ms:
        raise ValueError("Ngày bắt đầu thuê xe phải từ hiện tại trở về sau.")
    if end_ms <= start_ms:
        raise ValueError("Ngày kết thúc thuê xe phải sau ngày bắt đầu.")

    coordinates = search_address(address)
    lat = coordinates["lat"]
    lng = coordinates["lng"]
    if user_needs:
        category_id = map_car_need_to_category_id(user_needs)
    else:
        category_id = None
    url = build_mioto_filter_url(
        start_ms=start_ms,
        end_ms=end_ms,
        address=address,
        lat=lat,
        lng=lng,
        category_id=category_id,
        address_is_encoded=address_is_encoded,
    )
    print("URL:", url)
    cars = crawl_mioto_cars(url, limit=limit, max_scroll=max_scroll)
    cars = [_normalize_mioto_car(car) for car in cars]
    cars = filter_cars_by_price(cars, price_min=min_price, price_max=max_price)
    return cars


def search_car_details(car_name:str , car_id: str) -> dict:
    clean_car_id = str(car_id).strip().strip("/")
    slug = normalize_text(car_name).replace(" ", "-")
    url = f"https://www.mioto.vn/car/{slug}/{clean_car_id}"
    detail = crawl_car_details(url, headless=True)
    detail["car_id"] = clean_car_id
    return detail