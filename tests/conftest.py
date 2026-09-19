import os
import sys
from pathlib import Path

# GitHub Actions sets DATABASE_URL="" to skip live Postgres. Empty values still
# exist in os.environ, so setdefault() in individual tests never runs and
# importing app/settings raises ValueError. RapidAPI clients also capture
# RAPIDAPI_KEY at import time; other tests may import them first. Force dummy
# values before any test module imports application code.
os.environ["GOOGLE_API_KEY"] = os.environ.get("GOOGLE_API_KEY") or "test-gemini-key"
if not os.environ.get("DATABASE_URL", "").strip():
    os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost/database"
if not os.environ.get("COOKIE_SECRET", "").strip():
    os.environ["COOKIE_SECRET"] = "test-cookie-secret"
if not os.environ.get("RAPIDAPI_KEY", "").strip():
    os.environ["RAPIDAPI_KEY"] = "test-rapidapi-key"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
