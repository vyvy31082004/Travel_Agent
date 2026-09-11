import os
import sys
from pathlib import Path

os.environ.setdefault("RAPIDAPI_KEY", "test-rapidapi-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import utils.api_client_car as car
import utils.api_client_excur as excur


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.url = "https://example/redacted"

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 429:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_car_booking_get_retries_429_via_shared_limiter(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(status_code=429)
        return _Resp(status_code=200, payload={"data": [{"id": "c1"}]})

    # Avoid real sleeps in the shared limiter backoff.
    import utils.rapidapi_limiter as limiter

    monkeypatch.setattr(limiter.time, "sleep", lambda *_: None)
    monkeypatch.setattr(car.requests, "get", fake_get)

    result = car._booking_get("/geocode/search", {"q": "Da Nang"})
    assert result == [{"id": "c1"}]
    assert calls["n"] == 2  # first 429, then success — i.e. it retried


def test_car_booking_get_uses_call_with_rate_limit_retry(monkeypatch):
    used = {"limiter": False}

    import utils.rapidapi_limiter as limiter

    original = limiter.call_with_rate_limit_retry

    def spy(fn, **kwargs):
        used["limiter"] = True
        return original(fn, **kwargs)

    monkeypatch.setattr(limiter, "call_with_rate_limit_retry", spy)
    monkeypatch.setattr(
        car.requests,
        "get",
        lambda *a, **k: _Resp(status_code=200, payload={"data": []}),
    )
    car._booking_get("/geocode/search", {"q": "x"})
    assert used["limiter"] is True


def test_attraction_reviews_malformed_data_returns_structured_error(monkeypatch):
    # Non-list payload with a null rating must not raise through the tool boundary.
    monkeypatch.setattr(
        excur,
        "_booking_get",
        lambda *a, **k: {"unexpected": "shape"},
    )
    out = excur.fetch_attraction_reviews_from_api("attr-1")
    assert isinstance(out, dict)
    # Non-list => treated as no reviews, returns empty lists (not a crash).
    assert out.get("good_reviews") == []
    assert out.get("bad_reviews") == []


def test_attraction_reviews_null_rating_is_skipped(monkeypatch):
    monkeypatch.setattr(
        excur,
        "_booking_get",
        lambda *a, **k: [
            {"content": "great", "numericRating": None},
            {"content": "ok", "numericRating": 4},
            {"content": "bad", "numericRating": 1},
        ],
    )
    out = excur.fetch_attraction_reviews_from_api("attr-1")
    assert out["good_reviews"] == [{"content": "ok", "numericRating": 4}]
    assert out["bad_reviews"] == [{"content": "bad", "numericRating": 1}]


def test_attraction_reviews_upstream_raise_returns_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(excur, "_booking_get", boom)
    out = excur.fetch_attraction_reviews_from_api("attr-1")
    assert "error" in out
    assert "reviews" in out["error"].lower()
