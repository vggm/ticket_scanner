"""API HTTP: foto de un ticket → JSON. Solo orquesta los demás módulos."""

import hashlib
import logging
import math
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .debug_log import LogEntry, record, save_image
from .extractor import (
    ExtractionResult,
    Extractor,
    ModelUnavailable,
    NotAReceipt,
    extractor_from_settings,
)
from .image import InvalidImage, preprocess

logger = logging.getLogger(__name__)

MAX_IMAGES = 5  # fotos por ticket (un ticket largo se parte en varias)

ZONA_TICKETS = ZoneInfo("Europe/Madrid")  # los tickets son españoles; el contenedor va en UTC


def _error(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        {"error": code, "message": message}, status_code=status, headers=headers
    )


def create_app(settings: Settings | None = None, extractor: Extractor | None = None) -> FastAPI:
    settings = settings or get_settings()
    extractor = extractor or extractor_from_settings(settings)
    app = FastAPI(title="ticket_scanner")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # evita el 422 por defecto de FastAPI, que chocaría con not_a_receipt
        return _error(400, "invalid_image", "Petición no válida: se espera el fichero 'image'")

    @app.get("/health")
    async def health():
        return {"status": "ok", "model": settings.ticket_model}

    @app.post("/v1/tickets/extract")
    async def extract(
        image: list[UploadFile] | None = File(None),
        x_api_key: str | None = Header(None),
    ):
        if x_api_key is None or not secrets.compare_digest(
            x_api_key.encode(), settings.api_key.encode()
        ):
            return _error(401, "unauthorized", "API key ausente o incorrecta")

        start = time.perf_counter()
        originals: list[bytes] = []
        jpegs: list[bytes] = []
        result: ExtractionResult | None = None
        headers: dict | None = None

        try:
            if not image:
                raise InvalidImage("Falta el campo 'image'")
            if len(image) > MAX_IMAGES:
                status, code, message = (
                    400, "too_many_images", f"Demasiadas imágenes: el máximo es {MAX_IMAGES}"
                )
            else:
                limit = settings.max_upload_mb * 1024 * 1024
                too_large = False
                for upload in image:
                    data = await upload.read(limit + 1)
                    originals.append(data)
                    if len(data) > limit:
                        too_large = True
                        break
                if too_large:
                    status, code, message = (
                        413, "too_large", f"La imagen supera el máximo de {settings.max_upload_mb} MB"
                    )
                else:
                    for data in originals:
                        jpegs.append(await run_in_threadpool(preprocess, data, settings.image_max_side))
                    result = await extractor.extract(jpegs, datetime.now(ZONA_TICKETS).date())
                    status, code, message = 200, None, None
        except InvalidImage as exc:
            status, code, message = 400, "invalid_image", f"Imagen no válida: {exc}"
        except NotAReceipt as exc:
            result = exc.result
            status, code, message = 422, "not_a_receipt", "La imagen no parece un ticket de compra"
        except ModelUnavailable as exc:
            status, code, message = (
                503, "model_unavailable", "El modelo no está disponible, inténtalo más tarde"
            )
            if exc.retry_after is not None:
                headers = {"Retry-After": str(int(math.ceil(exc.retry_after)))}

        entry = LogEntry(
            image_sha256=",".join(hashlib.sha256(d).hexdigest() for d in originals),
            http_status=status,
            latency_ms=0,
            error=code,
        )
        if result is not None:
            entry.model_used = result.model_used
            entry.retried = result.retried
            entry.fell_back = result.fell_back
            entry.input_tokens = result.input_tokens
            entry.output_tokens = result.output_tokens
            entry.raw_extraction = result.raw.model_dump(mode="json")
            entry.status = result.response.status
            entry.warnings = [w.model_dump() for w in result.response.warnings]
            if status == 200:
                entry.response = result.response.model_dump(mode="json")
        if jpegs and settings.debug_save_images:
            paths = []
            for jpeg in jpegs:
                try:
                    path = await run_in_threadpool(save_image, settings.debug_images_dir, jpeg)
                    paths.append(str(path))
                except Exception:
                    logger.exception("No se pudo guardar la imagen de depuración")
            entry.image_path = ",".join(paths) or None
        entry.latency_ms = int((time.perf_counter() - start) * 1000)
        await run_in_threadpool(record, settings.debug_db_path, entry)

        if status == 200:
            return result.response.model_dump()
        return _error(status, code, message, headers)

    return app
