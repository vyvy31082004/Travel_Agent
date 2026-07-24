import json
import os
from pathlib import Path
from typing import Any
import unicodedata
import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env")

def remove_vietnamese_accents(text: str) -> str:
    text = text.replace("Đ", "D").replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(
        char for char in text
        if unicodedata.category(char) != "Mn"
    )
    return text

def get_weather_from_api(
    location: str,
    days: int = 3,
) -> dict[str, Any]:
    """
    Lấy thời tiết hiện tại và dự báo bằng WeatherAPI.

    Args:
        location: Tên thành phố, sân bay hoặc tọa độ.
        days: Số ngày dự báo 

    Returns:
        Dữ liệu thời tiết đã được rút gọn cho AI agent.
    """
    weather_api_key = (os.getenv("WEATHER_API_KEY") or "").strip()
    if not weather_api_key:
        raise ValueError(
            "Chưa thiết lập biến môi trường WEATHER_API_KEY."
        )

    if not location.strip():
        raise ValueError("Địa điểm không được để trống.")

    url = "https://api.weatherapi.com/v1/forecast.json"

    params = {
        "key": weather_api_key,
        "q": remove_vietnamese_accents(location.strip()),
        "days": days,
        "aqi": "yes",
        "alerts": "yes",
        "lang": "vi",
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Không thể lấy dữ liệu thời tiết: {exc}"
        ) from exc

    data = response.json()

    return {
        "location": {
            "name": data["location"]["name"],
            "region": data["location"].get("region"),
            "country": data["location"]["country"],
            "localtime": data["location"]["localtime"],
        },
        "current": {
            "temperature_c": data["current"]["temp_c"],
            "feels_like_c": data["current"]["feelslike_c"],
            "condition": data["current"]["condition"]["text"],
            "icon": f"https:{data['current']['condition']['icon']}",
            "humidity": data["current"]["humidity"],
            "wind_kph": data["current"]["wind_kph"],
            "precipitation_mm": data["current"]["precip_mm"],
            "uv": data["current"]["uv"],
        },
        "forecast": [
            {
                "date": item["date"],
                "min_temp_c": item["day"]["mintemp_c"],
                "max_temp_c": item["day"]["maxtemp_c"],
                "condition": item["day"]["condition"]["text"],
                "chance_of_rain": item["day"][
                    "daily_chance_of_rain"
                ],
                "sunrise": item["astro"]["sunrise"],
                "sunset": item["astro"]["sunset"],
            }
            for item in data["forecast"]["forecastday"]
        ],
        "alerts": data.get("alerts", {}).get("alert", []),
    }


# if __name__ == "__main__":
#     result = get_weather_from_api("Hà Nội", days=3)
#     print(json.dumps(result, ensure_ascii=True, indent=2))