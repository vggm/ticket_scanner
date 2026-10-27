import json

from ticket_scanner.schema import (
    ExtractedItem,
    TicketExtraction,
    TicketWarning,
    build_response,
    to_cents,
)


def test_to_cents_rounding():
    assert to_cents(1.9) == 190
    assert to_cents(0.105) == 11  # ROUND_HALF_UP vía Decimal(str())
    assert to_cents(-0.48) == -48
    assert to_cents(None) is None


def test_build_response_ok_and_revisar():
    ex = TicketExtraction(
        is_receipt=True,
        legible=True,
        multiple_receipts=False,
        store_name="Mercadona",
        store_tax_id="A46103834",
        date="2026-10-27",
        total=2.96,
        items=[
            ExtractedItem(description="LECHE", quantity=2, unit_price=0.95, amount=1.9),
            ExtractedItem(description="PLATANO", quantity=0.532, unit_price=1.99, amount=1.06),
        ],
    )
    r = build_response(ex, [], "gemini-3.5-flash-lite")
    assert r.status == "ok" and r.currency == "EUR" and r.total_cents == 296
    assert r.items[1].unit_price_cents == 199 and r.items[1].quantity == 0.532
    assert r.store.tax_id == "A46103834" and r.model == "gemini-3.5-flash-lite"
    r2 = build_response(ex, [TicketWarning(code="sum_mismatch", message="x")], "m")
    assert r2.status == "revisar"


def test_null_total_is_zero_cents():
    ex = TicketExtraction(
        is_receipt=True, legible=True, multiple_receipts=False, store_name=None,
        store_tax_id=None, date=None, total=None, items=[],
    )
    assert build_response(ex, [], "m").total_cents == 0


def test_extraction_schema_amounts_are_numbers():
    props = TicketExtraction.model_json_schema()["properties"]
    assert '"string"' not in json.dumps(props["total"])  # number|null, sin el anyOf de Decimal


def test_extraction_schema_quality_flags_required_booleans():
    schema = TicketExtraction.model_json_schema()
    for campo in ("legible", "multiple_receipts"):
        assert campo in schema["required"]
        assert schema["properties"][campo]["type"] == "boolean"
