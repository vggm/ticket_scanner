import json
from datetime import date

import pytest
from pydantic_ai.exceptions import ModelHTTPError, ModelTimeoutError
from pydantic_ai.messages import (
    BinaryContent,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.ollama import OllamaModel

from ticket_scanner.config import Settings
from ticket_scanner.extractor import (
    Extractor,
    MODEL_TIMEOUT_S,
    ModelUnavailable,
    NotAReceipt,
    build_model,
)

JPEG = [b"\xff\xd8fake"]
TODAY = date(2026, 10, 27)


def item(desc, qty, price, amount):
    return {"description": desc, "quantity": qty, "unit_price": price, "amount": amount}


GOOD = {
    "is_receipt": True,
    "legible": True,
    "multiple_receipts": False,
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


@pytest.mark.parametrize("body", [
    {"error": {"code": 429, "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"}]}},
    {"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17.5s"}]},
])
async def test_429_retry_delay_from_body(body):
    async def boom(messages, info):
        raise ModelHTTPError(status_code=429, model_name="m", body=body)

    with pytest.raises(ModelUnavailable) as e:
        await Extractor(FunctionModel(boom, model_name="m")).extract(JPEG, TODAY)
    assert e.value.retry_after == float(body.get("error", body)["details"][0]["retryDelay"][:-1])


@pytest.mark.parametrize("body", [None, "texto", [1], {"error": "x"}, {"details": ["x", {"retryDelay": 3}]}])
async def test_429_odd_body_is_ignored(body):
    async def boom(messages, info):
        raise ModelHTTPError(status_code=429, model_name="m", body=body)

    with pytest.raises(ModelUnavailable) as e:
        await Extractor(FunctionModel(boom, model_name="m")).extract(JPEG, TODAY)
    assert e.value.retry_after is None


OVERLAP = "pueden solaparse"


def recording(data: dict, name: str, seen: list) -> FunctionModel:
    def fn(messages, info):
        req = next(m for m in messages if isinstance(m, ModelRequest))
        part = next(p for p in req.parts if isinstance(p, UserPromptPart))
        seen.append(part.content)
        return ModelResponse(parts=[TextPart(json.dumps(data))])

    return FunctionModel(fn, model_name=name)


async def test_two_images_single_request_with_overlap_text():
    seen: list = []
    await Extractor(recording(GOOD, "lite", seen)).extract([b"one", b"two"], TODAY)
    assert len(seen) == 1
    texts = [c for c in seen[0] if isinstance(c, str)]
    blobs = [c.data for c in seen[0] if isinstance(c, BinaryContent)]
    assert blobs == [b"one", b"two"]
    assert len(texts) == 1 and OVERLAP in texts[0]


async def test_one_image_has_no_overlap_text():
    seen: list = []
    await Extractor(recording(GOOD, "lite", seen)).extract([b"one"], TODAY)
    texts = [c for c in seen[0] if isinstance(c, str)]
    assert texts == ["Extrae los datos de este ticket."]


async def test_retry_receives_all_images():
    seen: list = []
    await Extractor(fm(BAD, "lite"), retry=recording(GOOD, "flash", seen)).extract(
        [b"one", b"two"], TODAY
    )
    assert [c.data for c in seen[0] if isinstance(c, BinaryContent)] == [b"one", b"two"]


async def test_not_legible_returns_revisar_with_low_quality():
    r = await Extractor(fm({**GOOD, "legible": False}, "lite")).extract(JPEG, TODAY)
    assert r.response.status == "revisar"
    assert [w.code for w in r.response.warnings] == ["low_quality"]


def test_prompt_mentions_quality_flags():
    from ticket_scanner.prompt import INSTRUCTIONS

    assert "legible" in INSTRUCTIONS and "multiple_receipts" in INSTRUCTIONS


def timing_out(name: str) -> FunctionModel:
    def fn(messages, info):
        raise ModelTimeoutError(name, "timeout")

    return FunctionModel(fn, model_name=name)


async def test_model_settings_include_timeout_and_temperature():
    seen: list = []

    def fn(messages, info):
        seen.append(info.model_settings)
        return ModelResponse(parts=[TextPart(json.dumps(GOOD))])

    await Extractor(FunctionModel(fn, model_name="lite")).extract(JPEG, TODAY)
    assert seen[0]["timeout"] == MODEL_TIMEOUT_S and seen[0]["temperature"] == 0


async def test_primary_timeout_raises_model_unavailable_without_retry_after():
    with pytest.raises(ModelUnavailable) as exc:
        await Extractor(timing_out("lite")).extract(JPEG, TODAY)
    assert exc.value.retry_after is None


async def test_retry_timeout_returns_first_result():
    r = await Extractor(fm(BAD, "lite"), retry=timing_out("flash")).extract(JPEG, TODAY)
    assert r.retried and r.model_used == "lite" and r.response.status == "revisar"
