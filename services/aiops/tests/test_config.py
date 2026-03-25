import os
import pydantic
import pytest
from app.config import Settings


def test_settings_defaults():
    os.environ["OPENAI_API_KEY"] = "test-key"
    s = Settings()
    assert s.OPENAI_MODEL == "gpt-5.4"
    assert s.KEEP_API_URL == "http://keep-api:8080"
    assert s.CHROMA_URL == "http://chromadb:8000"
    assert s.SQLITE_PATH == "/data/aiops.db"
    assert s.DRAIN_SIMILARITY == 0.4
    assert s.ANOMALY_WINDOW_SECONDS == 300


def test_settings_requires_api_key():
    os.environ.pop("OPENAI_API_KEY", None)
    with pytest.raises(pydantic.ValidationError):
        Settings()


def test_settings_has_fallback_model():
    os.environ["OPENAI_API_KEY"] = "test-key"
    s = Settings()
    assert s.OPENAI_FALLBACK_MODEL == "gpt-4.1"
