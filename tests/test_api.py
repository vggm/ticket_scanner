import io
import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ticket_scanner import api as api_module
from ticket_scanner.api import create_app
from ticket_scanner.config import Settings
from ticket_scanner.extractor import ExtractionResult, ModelUnavailable, NotAReceipt
from ticket_scanner.schema import Store, TicketExtraction, TicketResponse


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, "JPEG")
    return buf.getvalue()


JPEG = _jpeg()


def _result(status="ok") -> ExtractionResult:
    return ExtractionResult(
        response=TicketResponse(
            status=status, warnings=[], store=Store(name="X", tax_id=None), date="2026-10-01",
            total_cents=296, items=[], model="lite",
        ),
        raw=TicketExtraction(
            is_receipt=True, store_name="X", store_tax_id=None, date="2026-10-01",
            total=2.96, items=[],
        ),
        model_used="lite", retried=False, fell_back=False, input_tokens=10, output_tokens=5,
    )


class FakeExtractor:
    def __init__(self, exc: Exception | None = None):
        self.exc = exc

    async def extract(self, jpeg, today):
        if self.exc:
            raise self.exc
        return _result()


@pytest.fixture
def db(tmp_path):
    return tmp_path / "d.db"


def make_client(tmp_path, exc=None, **kw):
    settings = Settings(_env_file=None, api_key="k", debug_db_path=tmp_path / "d.db", **kw)
    return TestClient(create_app(settings, FakeExtractor(exc)))


@pytest.fixture
def client(tmp_path):
    return make_client(tmp_path)


def post(client, data, key="k"):
    headers = {"X-API-Key": key} if key else {}
    return client.post(
        "/v1/tickets/extract", files={"image": ("t.jpg", data, "image/jpeg")}, headers=headers
    )


def rows(db):
    return sqlite3.connect(db).execute(
        "select http_status, error, model_used, image_path from extractions"
    ).fetchall()


def test_health_no_auth(client):
    assert client.get("/health").json() == {
        "status": "ok", "model": "google:gemini-3.5-flash-lite"
    }


def test_requires_api_key(client, db):
    r = client.post("/v1/tickets/extract", files={"image": ("t.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 401 and r.json()["error"] == "unauthorized"
    assert post(client, JPEG, key="bad").status_code == 401
    assert not db.exists()


def test_ok_returns_ticket_and_logs(client, db):
    r = post(client, JPEG)
    assert r.status_code == 200 and r.json()["total_cents"] == 296 and r.json()["status"] == "ok"
    assert sqlite3.connect(db).execute(
        "select http_status, model_used from extractions"
    ).fetchone() == (200, "lite")


def test_invalid_image_400(client, db):
    r = post(client, b"xx")
    assert r.status_code == 400 and r.json()["error"] == "invalid_image"
    assert rows(db)[0][:2] == (400, "invalid_image")


def test_empty_upload_400(client):
    assert post(client, b"").status_code == 400


def test_missing_field_400(client):
    r = client.post("/v1/tickets/extract", headers={"X-API-Key": "k"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_image"


def test_too_large_413(tmp_path):
    client = make_client(tmp_path, max_upload_mb=1)
    r = post(client, b"\0" * (1024 * 1024 + 1))
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    assert rows(tmp_path / "d.db")[0][:2] == (413, "too_large")


def test_not_a_receipt_422(tmp_path):
    client = make_client(tmp_path, exc=NotAReceipt(_result()))
    r = post(client, JPEG)
    assert r.status_code == 422 and r.json()["error"] == "not_a_receipt"
    assert rows(tmp_path / "d.db")[0] == (422, "not_a_receipt", "lite", None)


def test_model_unavailable_503_with_retry_after(tmp_path):
    client = make_client(tmp_path, exc=ModelUnavailable(retry_after=29.2))
    r = post(client, JPEG)
    assert r.status_code == 503 and r.headers["retry-after"] == "30"
    assert r.json()["error"] == "model_unavailable"
    assert rows(tmp_path / "d.db")[0][:2] == (503, "model_unavailable")


def test_model_unavailable_without_retry_after(tmp_path):
    r = post(make_client(tmp_path, exc=ModelUnavailable()), JPEG)
    assert r.status_code == 503 and "retry-after" not in r.headers


def test_save_images_when_enabled(tmp_path):
    images = tmp_path / "img"
    client = make_client(tmp_path, debug_save_images=True, debug_images_dir=images)
    assert post(client, JPEG).status_code == 200
    path = rows(tmp_path / "d.db")[0][3]
    assert path and path.startswith(str(images)) and (images / path.split("/")[-1]).exists()


def test_save_image_failure_does_not_break_response(tmp_path, monkeypatch, caplog):
    def boom(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(api_module, "save_image", boom)
    client = make_client(tmp_path, debug_save_images=True, debug_images_dir=tmp_path / "img")
    with caplog.at_level(logging.ERROR):
        r = post(client, JPEG)
    assert r.status_code == 200
    assert rows(tmp_path / "d.db")[0][3] is None
    assert "disco lleno" in caplog.text


def test_logging_failure_does_not_break_response(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    settings = Settings(_env_file=None, api_key="k", debug_db_path=blocker / "d.db")
    client = TestClient(create_app(settings, FakeExtractor()))
    assert post(client, JPEG).status_code == 200


def test_text_field_named_image_is_400_invalid_image(client):
    r = client.post("/v1/tickets/extract", data={"image": "texto"}, headers={"X-API-Key": "k"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_image"
