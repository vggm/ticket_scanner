import hashlib
import logging
import sqlite3

from ticket_scanner.debug_log import LogEntry, record, save_image


def test_record_creates_db_and_row(tmp_path):
    db = tmp_path / "sub" / "debug.db"
    record(db, LogEntry(image_sha256="abc", http_status=200, latency_ms=5, warnings=[{"code": "x"}], response={"a": 1}))
    row = sqlite3.connect(db).execute("select image_sha256, http_status, warnings, response from extractions").fetchone()
    assert row == ("abc", 200, '[{"code": "x"}]', '{"a": 1}')


def test_record_never_raises(tmp_path, caplog):
    bad = tmp_path / "file"
    bad.write_text("x")
    with caplog.at_level(logging.ERROR):
        record(bad / "debug.db", LogEntry(image_sha256="a", http_status=200, latency_ms=1))
    assert any(
        r.levelno == logging.ERROR and "No se pudo registrar la petición de depuración" in r.getMessage()
        for r in caplog.records
    )


def test_save_image(tmp_path):
    p = save_image(tmp_path / "imgs", b"jpegdata")
    assert p.name == hashlib.sha256(b"jpegdata").hexdigest() + ".jpg" and p.read_bytes() == b"jpegdata"
