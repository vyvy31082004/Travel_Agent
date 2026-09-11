from __future__ import annotations

import json
from typing import Any, Optional

SEARCH_TOOL_NAMES = {
    "search_hotels_tool",
    "search_one_way_flights_tool",
    "search_round_trip_flights_tool",
    "search_attractions_tool",
    "search_cars_tool",
}

TOOL_DOMAIN = {
    "search_hotels_tool": "hotel",
    "search_one_way_flights_tool": "flight",
    "search_round_trip_flights_tool": "flight",
    "search_attractions_tool": "tour",
    "search_cars_tool": "car",
}


def parse_tool_content(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    if isinstance(content, list):
        texts: list[Any] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(parse_tool_content(block.get("text")))
            else:
                texts.append(block)
        if len(texts) == 1:
            return texts[0]
        return texts
    return content


def _as_list(raw: Any, *keys: str) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in keys:
            value = raw.get(key)
            if isinstance(value, list):
                return value
        return [raw]
    return []


def normalize_flight_offers(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    candidates = _as_list(raw)
    flattened: list[Any] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            top = candidate.get("topFlights")
            other = candidate.get("otherFlights")
            if isinstance(top, list) or isinstance(other, list):
                if isinstance(top, list):
                    flattened.extend(top)
                if isinstance(other, list):
                    flattened.extend(other)
                continue
        flattened.append(candidate)

    for index, flight in enumerate(flattened, start=1):
        if not isinstance(flight, dict) or flight.get("error"):
            continue
        outbound = flight.get("outbound")
        if not isinstance(outbound, dict):
            outbound = {}
        display = {**outbound, **flight}
        item_id = str(
            display.get("Offer_ID")
            or display.get("flight_id")
            or display.get("item_id")
            or f"flight_{index}"
        )
        detail_token = (
            display.get("detailToken")
            or display.get("detail_token")
            or display.get("booking_token")
        )
        if not detail_token and isinstance(flight.get("inbound"), dict):
            inbound = flight["inbound"]
            detail_token = (
                inbound.get("detailToken")
                or inbound.get("detail_token")
                or inbound.get("booking_token")
            )
        payload = {
            "item_id": item_id,
            "offer_id": item_id,
            "airline": display.get("airline_name") or display.get("airline"),
            "airline_code": display.get("airline_code"),
            "flight_number": display.get("flight_number"),
            "departure_airport": display.get("departure_airport_code")
            or display.get("departure_airport"),
            "arrival_airport": display.get("arrival_airport_code")
            or display.get("arrival_airport"),
            "departure_time": display.get("departure_time"),
            "departure_date": display.get("departure_date"),
            "arrival_time": display.get("arrival_time"),
            "arrival_date": display.get("arrival_date"),
            "duration_minutes": display.get("duration_minutes"),
            "stops": display.get("stops"),
            "cabin_class": display.get("cabin_class") or display.get("cabinClass"),
            "price": display.get("total_price") or display.get("price"),
            "currency": display.get("currency") or "VND",
            "segments": display.get("segments"),
            "outbound": outbound or None,
            "inbound": flight.get("inbound"),
            "inbound_options": flight.get("inbound_options") or flight.get("inbound"),
            "warning": flight.get("warning"),
            "complete_roundtrip": bool(outbound and flight.get("inbound")),
            "refundable": display.get("refundable"),
            "baggage": display.get("baggage"),
            # Keep useful display fields without dumping entire provider blob.
            "Offer_ID": item_id,
            "airline_name": display.get("airline_name"),
            "departure_airport_code": display.get("departure_airport_code"),
            "arrival_airport_code": display.get("arrival_airport_code"),
            "total_price": display.get("total_price") or display.get("price"),
        }
        items.append(
            {
                "item_id": item_id,
                "detail_token": detail_token,
                "payload": payload,
            }
        )
    return items


def normalize_hotel_offers(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, hotel in enumerate(_as_list(raw), start=1):
        if not isinstance(hotel, dict):
            continue
        if hotel.get("error"):
            continue
        item_id = str(
            hotel.get("external_hotel_id")
            or hotel.get("hotel_id")
            or hotel.get("item_id")
            or f"hotel_{index}"
        )
        payload = {
            "item_id": item_id,
            "external_hotel_id": item_id,
            "name": hotel.get("name"),
            "location": hotel.get("location") or hotel.get("address"),
            "price_tier": hotel.get("price_tier"),
            "rating": hotel.get("rating"),
            "star": hotel.get("star"),
            "price": hotel.get("price"),
            "currency": hotel.get("currency") or "VND",
            "photo": hotel.get("photo") or hotel.get("image"),
            "address": hotel.get("address"),
            # List of short lines from Booking accessibilityLabel — agent prints each as a bullet
            "accessibilityLabel": hotel.get("accessibilityLabel") or [],
        }
        items.append({"item_id": item_id, "payload": payload})
    return items


def normalize_tour_offers(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, tour in enumerate(_as_list(raw), start=1):
        if not isinstance(tour, dict):
            continue
        if tour.get("error"):
            continue
        item_id = str(
            tour.get("external_attraction_id")
            or tour.get("id")
            or tour.get("item_id")
            or f"tour_{index}"
        )
        payload = {
            "item_id": item_id,
            "external_attraction_id": item_id,
            "name": tour.get("name"),
            "description": tour.get("description"),
            "price": tour.get("price"),
            "currency": tour.get("currency") or "VND",
            "rating": tour.get("rating"),
            "review_count": tour.get("review_count"),
            "image": tour.get("image") or tour.get("photo"),
            "slug": tour.get("slug"),
        }
        items.append({"item_id": item_id, "payload": payload})
    return items


def normalize_car_offers(raw: Any) -> list[dict[str, Any]]:
    cars = raw.get("cars") if isinstance(raw, dict) else None
    source = cars if isinstance(cars, list) else _as_list(raw, "cars")
    items: list[dict[str, Any]] = []
    for index, car in enumerate(source, start=1):
        if not isinstance(car, dict):
            continue
        if car.get("error"):
            continue
        item_id = str(car.get("car_id") or car.get("item_id") or f"car_{index}")
        payload = {
            "item_id": item_id,
            "car_id": item_id,
            "name": car.get("Tên xe") or car.get("name"),
            "Tên xe": car.get("Tên xe") or car.get("name"),
            "price": car.get("Giá sau giảm") or car.get("price"),
            "Giá sau giảm": car.get("Giá sau giảm") or car.get("price"),
            "Giá gốc": car.get("Giá gốc"),
            "Hộp số": car.get("Hộp số"),
            "Số chỗ": car.get("Số chỗ"),
            "Nhiên liệu": car.get("Nhiên liệu"),
            "address": car.get("Địa chỉ") or car.get("address"),
            "Địa chỉ": car.get("Địa chỉ") or car.get("address"),
            "rating": car.get("Rating") or car.get("rating"),
            "Rating": car.get("Rating") or car.get("rating"),
            "Số chuyến": car.get("Số chuyến"),
            "Tags": car.get("Tags"),
            "photo": car.get("Ảnh") or car.get("photo"),
            "Ảnh": car.get("Ảnh") or car.get("photo"),
            "link": car.get("Link") or car.get("link"),
            "Link": car.get("Link") or car.get("link"),
        }
        items.append({"item_id": item_id, "payload": payload})
    return items


def normalize_search_results(domain: str, raw: Any) -> list[dict[str, Any]]:
    if domain == "flight":
        return normalize_flight_offers(raw)
    if domain == "hotel":
        return normalize_hotel_offers(raw)
    if domain == "tour":
        return normalize_tour_offers(raw)
    if domain == "car":
        return normalize_car_offers(raw)
    raise ValueError(f"Unsupported domain: {domain}")


def compact_tool_ref(
    *,
    request_id: str,
    search_id: str,
    domain: str,
    total_results: int,
    displayed_item_ids: list[str],
    labels: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": request_id,
        "search_id": search_id,
        "domain": domain,
        "total_results": total_results,
        "displayed_item_ids": displayed_item_ids,
    }
    if labels is not None:
        payload["labels"] = labels
    return payload


def label_from_normalized(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("payload") or {}
    return {
        "item_id": item.get("item_id") or payload.get("item_id"),
        "name": payload.get("name")
        or payload.get("airline")
        or payload.get("Tên xe")
        or payload.get("offer_id"),
        "price": payload.get("price") or payload.get("total_price"),
        "currency": payload.get("currency") or "VND",
    }
