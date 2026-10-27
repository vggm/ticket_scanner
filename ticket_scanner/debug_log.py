"""Registro de depuración de peticiones en SQLite."""

import hashlib
import json
import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS extractions (
    id INTEGER PRIMARY KEY,
    created_at TEXT,
    image_sha256 TEXT,
    image_path TEXT,
    model_used TEXT,
    retried INTEGER,
    fell_back INTEGER,
    status TEXT,
    http_status INTEGER,
    warnings TEXT,
    error TEXT,
    latency_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    raw_extraction TEXT,
    response TEXT
)
"""


@dataclass
class LogEntry:
    image_sha256: str
    http_status: int
    latency_ms: int
    image_path: str | None = None
    model_used: str | None = None
    retried: bool = False
    fell_back: bool = False
    status: str | None = None
    warnings: list[dict] | None = None
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw_extraction: dict | None = None
    response: dict | None = None


def _json(value) -> str | None:
    return None if value is None else json.dumps(value)


def record(db_path: Path, entry: LogEntry) -> None:
    """Inserta una fila en `extractions`. Nunca lanza: los fallos se registran en el log."""
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db_path)) as conn, conn:
            conn.execute(_SCHEMA)
            conn.execute(
                "INSERT INTO extractions (created_at, image_sha256, image_path, model_used, retried,"
                " fell_back, status, http_status, warnings, error, latency_ms, input_tokens,"
                " output_tokens, raw_extraction, response) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(UTC).isoformat(),
                    entry.image_sha256,
                    entry.image_path,
                    entry.model_used,
                    int(entry.retried),
                    int(entry.fell_back),
                    entry.status,
                    entry.http_status,
                    _json(entry.warnings),
                    entry.error,
                    entry.latency_ms,
                    entry.input_tokens,
                    entry.output_tokens,
                    _json(entry.raw_extraction),
                    _json(entry.response),
                ),
            )
    except Exception:
        logger.exception("No se pudo registrar la petición de depuración")


def save_image(images_dir: Path, jpeg: bytes) -> Path:
    """Guarda la imagen como `<sha256>.jpg` y devuelve su ruta."""
    images_dir.mkdir(parents=True, exist_ok=True)
    path = images_dir / f"{hashlib.sha256(jpeg).hexdigest()}.jpg"
    path.write_bytes(jpeg)
    return path
