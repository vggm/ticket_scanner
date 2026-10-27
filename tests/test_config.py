import pytest
from pydantic import ValidationError

from ticket_scanner.config import Settings


def test_defaults(monkeypatch):
    monkeypatch.setenv("API_KEY", "k")
    s = Settings(_env_file=None)
    assert s.ticket_model == "google:gemini-3.5-flash-lite"
    assert s.ticket_retry_model == "google:gemini-3.8-flash"
    assert s.ticket_fallback_model == ""
    assert s.image_max_side == 2048
    assert s.max_upload_mb == 10
    assert s.debug_save_images is False


def test_aistudio_key_from_env(monkeypatch):
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("AISTUDIO_KEY", "g")
    assert Settings(_env_file=None).aistudio_key == "g"


def test_api_key_required(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_api_key_empty_rejected(monkeypatch):
    monkeypatch.setenv("API_KEY", "")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
