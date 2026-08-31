import os
import sys
from pathlib import Path

os.environ.setdefault("GOOGLE_API_KEY", "test-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import _message_content_text


def test_message_content_text_preserves_plain_text():
    assert _message_content_text("OK") == "OK"


def test_message_content_text_extracts_structured_text_blocks():
    content = [
        {"type": "text", "text": "O"},
        {"type": "text", "text": "K"},
    ]

    assert _message_content_text(content) == "OK"


def test_message_content_text_ignores_non_text_blocks():
    content = [
        {"type": "thinking", "thinking": "hidden"},
        {"type": "text", "text": "Visible"},
    ]

    assert _message_content_text(content) == "Visible"
