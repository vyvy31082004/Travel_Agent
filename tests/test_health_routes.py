import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("GOOGLE_API_KEY", "test-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import healthz


def test_healthz_returns_ok_without_lifespan_dependencies():
    assert asyncio.run(healthz()) == {"status": "ok"}
