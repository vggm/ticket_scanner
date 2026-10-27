import json
from datetime import date

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.ollama import OllamaModel

from ticket_scanner.config import Settings
from ticket_scanner.extractor import (
    Extractor,
    ModelUnavailable,
    NotAReceipt,
    build_model,
)

JPEG = b"\xff\xd8fake"
TODAY = date(2026, 10, 27)


def item(desc, qty, price, amount):
    return {"description": desc, "quantity": qty, "unit_price": price, "amount": amount}


GOOD = {
    "is_receipt": True,
    "store_name": "SUPER",
    "store_tax_id": "A12345678",
    "date": "2026-10-27",
    "total": 2.96,
    "items": [item("LECHE", 2, 0.95, 1.90), item("PLATANO", 0.532, 1.99, 1.06)],
}
BAD = {**GOOD, "total": 5.00}  # suma no cuadra: 1 aviso
WORSE = {**GOOD, "total": 5.00, "date": "no-fecha"}  # 2 avisos
NOT = {**GOOD, "is_receipt": False}


def fm(data: dict, name: str, calls: list | None = None) -> FunctionModel:
    def fn(messages, info):
        if calls is not None:
            calls.append(name)
        return ModelResponse(parts=[TextPart(json.dumps(data))])

    return FunctionModel(fn, model_name=name)


def failing(status: int, name: str, retry_after: str | None = None) -> FunctionModel:
    def fn(messages, info):
        raise ModelHTTPError(
            status_code=status,
            model_name=name,
            body=None,
            headers={"retry-after": retry_after} if retry_after else None,
        )

    return FunctionModel(fn, model_name=name)


@pytest.fixture
def settings():
    return Settings(_env_file=None, api_key="k", aistudio_key="test")


async def test_valid_extraction():
    r = await Extractor(fm(GOOD, "lite")).extract(JPEG, TODAY)
    assert r.response.status == "ok" and r.model_used == "lite"
    assert not r.retried and not r.fell_back


async def test_not_a_receipt():
    with pytest.raises(NotAReceipt) as e:
        await Extractor(fm(NOT, "lite")).extract(JPEG, TODAY)
    assert e.value.result.raw.is_receipt is False


async def test_retry_used_when_validation_fails_and_better_result_kept():
    r = await Extractor(fm(BAD, "lite"), retry=fm(GOOD, "flash")).extract(JPEG, TODAY)
    assert r.retried and r.model_used == "flash" and r.response.status == "ok"


async def test_retry_worse_keeps_first():
    r = await Extractor(fm(BAD, "lite"), retry=fm(WORSE, "flash")).extract(JPEG, TODAY)
    assert r.retried and r.model_used == "lite"


async def test_retry_tie_prefers_second():
    r = await Extractor(fm(BAD, "lite"), retry=fm(BAD, "flash")).extract(JPEG, TODAY)
    assert r.model_used == "flash"


async def test_retry_quota_exhausted_returns_first_result():
    r = await Extractor(fm(BAD, "lite"), retry=failing(429, "flash")).extract(JPEG, TODAY)
    assert r.retried and r.model_used == "lite" and r.response.status == "revisar"


async def test_no_retry_when_ok():
    calls: list = []
    r = await Extractor(fm(GOOD, "lite"), retry=fm(GOOD, "flash", calls)).extract(JPEG, TODAY)
    assert calls == [] and not r.retried


async def test_tokens_are_summed():
    r = await Extractor(fm(BAD, "lite"), retry=fm(GOOD, "flash")).extract(JPEG, TODAY)
    assert r.input_tokens > 0 and r.output_tokens > 0


async def test_fallback_on_http_error():
    m = FallbackModel(failing(503, "lite"), fm(GOOD, "qwen"))
    r = await Extractor(m).extract(JPEG, TODAY)
    assert r.fell_back and r.model_used == "qwen"


async def test_all_fail_raises_model_unavailable_with_retry_after():
    with pytest.raises(ModelUnavailable) as e:
        await Extractor(failing(429, "lite", retry_after="30")).extract(JPEG, TODAY)
    assert e.value.retry_after == 30.0


async def test_fallback_group_all_fail_takes_retry_after():
    m = FallbackModel(failing(503, "lite"), failing(429, "qwen", retry_after="12"))
    with pytest.raises(ModelUnavailable) as e:
        await Extractor(m).extract(JPEG, TODAY)
    assert e.value.retry_after == 12.0


async def test_non_429_has_no_retry_after():
    with pytest.raises(ModelUnavailable) as e:
        await Extractor(failing(503, "lite", retry_after="30")).extract(JPEG, TODAY)
    assert e.value.retry_after is None


def test_build_model_parsing(settings):
    assert isinstance(build_model("google:gemini-3.5-flash-lite", settings), GoogleModel)
    m = build_model("ollama:qwen3-vl:8b", settings)
    assert isinstance(m, OllamaModel) and m.model_name == "qwen3-vl:8b"
    with pytest.raises(ValueError):
        build_model("openai:gpt", settings)
