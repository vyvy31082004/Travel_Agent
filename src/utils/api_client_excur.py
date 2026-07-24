import os
import requests
from dotenv import load_dotenv
# from qdrant_client import QdrantClient
# from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, Range
# from sentence_transformers import SentenceTransformer
import uuid
from utils.utils import to_date, convert_to_vnd
# Load environment variables from .env file
load_dotenv()
from functools import lru_cache
from datetime import date, datetime
from typing import Optional
import unicodedata 
from utils.excur_helper import _normalize_text_for_search, _get_review_text, _extract_review_items , _match_tour_name, _find_url_recursive, _parse_date

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




def _booking_headers() -> dict:
    if not RAPIDAPI_KEY:
        raise RuntimeError("Thiếu RAPIDAPI_KEY trong file .env")

    return {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": BOOKING_HOST,
    }


def _booking_get(path: str, params: dict, retries: int = 1) -> dict | list:
    import time

    url = f"{BOOKING_BASE_URL}{path}"

    clean_params = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    print("CALL API:", url)
    print("PARAMS:", clean_params)

    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        response = requests.get(
            url,
            headers=_booking_headers(),
            params=clean_params,
            timeout=20,
        )

        print("FINAL URL:", response.url)

        if response.status_code == 429:
            last_error = RuntimeError(
                "RapidAPI bị giới hạn request. Hãy thử lại sau."
            )
            if attempt <= retries:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay_seconds = min(max(float(retry_after), 0), 10)
                except (TypeError, ValueError):
                    delay_seconds = 2 * attempt
                print(
                    f"429 on attempt {attempt}/{retries + 1}, "
                    f"retrying after {delay_seconds:g}s..."
                )
                time.sleep(delay_seconds)
                continue
            raise last_error

        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, dict) and payload.get("status") is False:
            raise RuntimeError(payload.get("message", "Booking API trả về lỗi."))

        if isinstance(payload, dict):
            return payload.get("data", payload)

        return payload

    raise last_error or RuntimeError("Booking API thất bại.")


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
            languagecode=BOOKING_LANGUAGE_CODE,
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
                "currency_code": BOOKING_CURRENCY_CODE,
                "languagecode": BOOKING_LANGUAGE_CODE,
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


def _normalize_attraction_details(data: dict) -> dict:
    representative_price = data.get("representativePrice")
    price = representative_price.get("chargeAmount") or representative_price.get("publicAmount")
    currency = representative_price.get("currency")
    price, currency = convert_to_vnd(price, currency)
    reviewsStats = data.get("reviewsStats")
    combinedNumericStats = reviewsStats.get("combinedNumericStats")
    applicableTerms = data.get("applicableTerms")
    cancellationPolicy = data.get("cancellationPolicy")
    reviews = data.get("reviews")
    reviews_items = reviews.get("reviews")
    real_reviews = []   
    for rev in reviews_items:
        if rev.get("content")!=None:
            real_reviews.append(rev.get("content"))
    return {
        "slug": data.get("slug"),
        "Price": price,
        "Currency": currency,
        "AverageScore": combinedNumericStats.get("average") ,
        "TotalReviews": combinedNumericStats.get("total"),
        "Included": data.get("whatsIncluded"),
        "applicableTerms": applicableTerms[0].get("termsUrl"),
        "cancellationPolicy": cancellationPolicy.get("hasFreeCancellation"),
        "notincluded": data.get("notIncluded"),
        "guideSupportedLanguages": data.get("guideSupportedLanguages"),
        "additionalInfo": data.get("additionalInfo"),
        "description": data.get("description"),
        "Reviews": real_reviews

    }

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
                "currency_code": BOOKING_CURRENCY_CODE,
            },
        )


        return {
            "source": "booking_com15_rapidapi",
            "slug": slug,
            "details": _normalize_attraction_details(data),
        }

    except Exception as e:
        return {
            "error": f"Lỗi khi lấy attraction details: {str(e)}"
        }


def fetch_attraction_reviews_from_api(
    id: str ,
    languagecode: str = BOOKING_LANGUAGE_CODE,
) -> dict:
    """
    Lấy reviews của attraction.
    """
    if not id:
        return {
            "error": "Bạn cần cung cấp id của attraction."
        }
    data = _booking_get(
        "/attraction/getAttractionReviews",
        {
            "id": id,
        },
    )
    limit = 5 
    good_reviews =[]
    bad_reviews =[]
    for rev in data:
        if isinstance(rev, dict):
            if rev.get("content")!=None and float(rev.get("numericRating")) >= 3:
                good_reviews.append({"content": rev.get("content"), "numericRating": rev.get("numericRating")})
            if rev.get("content")!=None and float(rev.get("numericRating")) <= 2:
                bad_reviews.append({"content": rev.get("content"), "numericRating": rev.get("numericRating")})
    return {
        "source": "booking_com15_rapidapi",
        "id": id,
        "good_reviews": good_reviews[:limit],
        "bad_reviews": bad_reviews[:limit],

    }
