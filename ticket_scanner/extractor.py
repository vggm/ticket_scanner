"""Extracción de tickets con Pydantic AI: reintento con modelo potente y respaldo."""

import re
from dataclasses import dataclass
from datetime import date

from pydantic_ai import Agent, BinaryContent
from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.output import NativeOutput
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.ollama import OllamaProvider

from .config import Settings
from .prompt import INSTRUCTIONS
from .schema import TicketExtraction, TicketResponse, build_response
from .validation import check

agent = Agent(
    output_type=NativeOutput(TicketExtraction),
    instructions=INSTRUCTIONS,
    retries={"output": 1},
)


@dataclass
class ExtractionResult:
    response: TicketResponse
    raw: TicketExtraction
    model_used: str
    retried: bool
    fell_back: bool
    input_tokens: int
    output_tokens: int


class NotAReceipt(Exception):
    def __init__(self, result: ExtractionResult):
        super().__init__("La imagen no es un ticket")
        self.result = result


class ModelUnavailable(Exception):
    def __init__(self, retry_after: float | None = None):
        super().__init__("Modelo no disponible")
        self.retry_after = retry_after


def build_model(spec: str, settings: Settings) -> Model:
    """'google:<nombre>' u 'ollama:<nombre>' (se parte solo en el primer ':')."""
    prefix, _, name = spec.partition(":")
    if prefix == "google":
        return GoogleModel(name, provider=GoogleProvider(api_key=settings.aistudio_key))
    if prefix == "ollama":
        return OllamaModel(name, provider=OllamaProvider(base_url=settings.ollama_base_url))
    raise ValueError(f"Modelo no soportado: {spec!r}")


def _retry_delay_from_body(body: object) -> float | None:
    """Gemini manda la espera en error.details[] (RetryInfo.retryDelay, p. ej. "17s")."""
    if not isinstance(body, dict):
        return None
    if isinstance(body.get("error"), dict):
        body = body["error"]
    details = body.get("details")
    if not isinstance(details, list):
        return None
    for d in details:
        delay = d.get("retryDelay") if isinstance(d, dict) else None
        if isinstance(delay, str) and re.fullmatch(r"\d+(\.\d+)?s", delay):
            return float(delay[:-1])
    return None


def _retry_after(exc: BaseException) -> float | None:
    """retry_after del primer 429 contenido en la excepción (o grupo)."""
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found = _retry_after(sub)
            if found is not None:
                return found
        return None
    if isinstance(exc, ModelHTTPError) and exc.status_code == 429:
        if exc.retry_after is not None:
            return exc.retry_after
        return _retry_delay_from_body(exc.body)
    return None


def _first_model_name(model: Model) -> str:
    return model.models[0].model_name if isinstance(model, FallbackModel) else model.model_name


class Extractor:
    def __init__(self, primary: Model, retry: Model | None = None):
        self.primary = primary
        self.retry = retry

    async def _call(self, model: Model, jpeg: bytes, today: date):
        """Una extracción con un modelo; devuelve (resultado, avisos, tokens_in, tokens_out)."""
        try:
            run = await agent.run(
                ["Extrae los datos de este ticket.", BinaryContent(data=jpeg, media_type="image/jpeg")],
                model=model,
                model_settings={"temperature": 0},
            )
        except (FallbackExceptionGroup, ModelAPIError, UnexpectedModelBehavior) as exc:
            raise ModelUnavailable(_retry_after(exc)) from exc
        raw = run.output
        warnings = check(raw, today)
        res = ExtractionResult(
            response=build_response(raw, warnings, run.response.model_name),
            raw=raw,
            model_used=run.response.model_name,
            retried=False,
            fell_back=run.response.model_name != _first_model_name(model),
            input_tokens=run.usage.input_tokens,
            output_tokens=run.usage.output_tokens,
        )
        if not raw.is_receipt:
            raise NotAReceipt(res)
        return res

    async def extract(self, jpeg: bytes, today: date) -> ExtractionResult:
        first = await self._call(self.primary, jpeg, today)
        if not first.response.warnings or self.retry is None:
            return first
        first.retried = True
        try:
            second = await self._call(self.retry, jpeg, today)
        except (ModelUnavailable, NotAReceipt):
            return first
        best = first if len(first.response.warnings) < len(second.response.warnings) else second
        best.retried = True
        best.input_tokens = first.input_tokens + second.input_tokens
        best.output_tokens = first.output_tokens + second.output_tokens
        return best


def extractor_from_settings(settings: Settings) -> Extractor:
    def make(spec: str) -> Model:
        model = build_model(spec, settings)
        if settings.ticket_fallback_model:
            return FallbackModel(model, build_model(settings.ticket_fallback_model, settings))
        return model

    retry = make(settings.ticket_retry_model) if settings.ticket_retry_model else None
    return Extractor(make(settings.ticket_model), retry)
