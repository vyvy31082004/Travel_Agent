import os
import requests
from dotenv import load_dotenv
import uuid
from utils.utils import to_date, convert_to_vnd
load_dotenv()
from functools import lru_cache
from datetime import date, datetime
from typing import Optional
import unicodedata 
def _normalize_text_for_search(text: str | None) -> str:
    """
    Chuyển text về dạng dễ search:
    - chữ thường
    - bỏ dấu tiếng Việt
    - bỏ khoảng trắng thừa
    """
    if not text:
        return ""

    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(
        char for char in text
        if unicodedata.category(char) != "Mn"
    )

    return " ".join(text.split())


def _match_tour_name(attraction: dict, tour_name: str) -> bool:
    """
    Check tên tour user nhập có khớp với name/description/category không.
    """
    keyword = _normalize_text_for_search(tour_name)

    searchable_text = " ".join(
        [
            str(attraction.get("name") or ""),
            str(attraction.get("description") or ""),
            str(attraction.get("category") or ""),
            str(attraction.get("location") or ""),
        ]
    )

    searchable_text = _normalize_text_for_search(searchable_text)

    return keyword in searchable_text


def _extract_review_items(reviews_data) -> list[dict]:
    """
    Lấy list review từ response review.
    Response API có thể nằm trong reviews/results/items/data.
    """
    return _get_first_list(
        reviews_data,
        keys=["reviews", "results", "items", "data"],
    )


def _get_review_text(review: dict) -> str:
    """
    Gom nội dung review thành 1 chuỗi để filter keyword.
    """
    fields = [
        review.get("title"),
        review.get("text"),
        review.get("content"),
        review.get("review"),
        review.get("pros"),
        review.get("cons"),
    ]

    return " ".join(str(field) for field in fields if field)

def _find_url_recursive(obj) -> str | None:
    """
    Tìm URL trong response lồng nhiều cấp.
    Ưu tiên field có tên liên quan booking/product/deeplink/url.
    """
    preferred_keys = {
        "url",
        "bookingUrl",
        "booking_url",
        "deepLink",
        "deeplink",
        "productUrl",
        "product_url",
        "shareUrl",
        "webUrl",
    }

    if isinstance(obj, dict):
        # Ưu tiên key rõ nghĩa trước
        for key in preferred_keys:
            value = obj.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value

        # Nếu không có thì duyệt sâu
        for value in obj.values():
            found = _find_url_recursive(value)
            if found:
                return found

    elif isinstance(obj, list):
        for item in obj:
            found = _find_url_recursive(item)
            if found:
                return found

    return None

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