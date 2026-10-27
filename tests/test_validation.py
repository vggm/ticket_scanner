from datetime import date

from ticket_scanner.schema import ExtractedItem, TicketExtraction
from ticket_scanner.validation import check

TODAY = date(2026, 10, 27)


def ex(**kw):
    """Ticket válido por defecto: LECHE 2×0.95=1.90 + PLATANO 0.532×1.99=1.06, total 2.96."""
    base = dict(
        is_receipt=True,
        legible=True,
        multiple_receipts=False,
        store_name="SUPER",
        store_tax_id="A12345678",
        date="2026-10-27",
        total=2.96,
        items=[
            ExtractedItem(description="LECHE", quantity=2, unit_price=0.95, amount=1.90),
            ExtractedItem(description="PLATANO", quantity=0.532, unit_price=1.99, amount=1.06),
        ],
    )
    base.update(kw)
    return TicketExtraction(**base)


def codes(ws):
    return [w.code for w in ws]


def test_valid_ticket_has_no_warnings():
    assert check(ex(), TODAY) == []


def test_sum_tolerance_one_cent():
    assert check(ex(total=2.97), TODAY) == []


def test_sum_mismatch():
    assert codes(check(ex(total=3.50), TODAY)) == ["sum_mismatch"]


def test_line_mismatch_reports_line_number():
    items = [ExtractedItem(description="LECHE", quantity=2, unit_price=0.95, amount=2.50)]
    ws = check(ex(items=items, total=2.50), TODAY)
    assert codes(ws) == ["line_mismatch"] and "Línea 1" in ws[0].message


def test_line_without_quantity_is_not_checked():
    items = [ExtractedItem(description="PAN", quantity=None, unit_price=None, amount=0.6)]
    assert check(ex(items=items, total=0.6), TODAY) == []


def test_discount_negative_line_sums():
    items = [
        ExtractedItem(description="A", quantity=None, unit_price=None, amount=2.0),
        ExtractedItem(description="DTO", quantity=None, unit_price=None, amount=-0.5),
    ]
    assert check(ex(items=items, total=1.5), TODAY) == []


def test_weighted_item_rounding():
    # 0.532 × 199 = 105.868 → 106
    items = [ExtractedItem(description="PLATANO", quantity=0.532, unit_price=1.99, amount=1.06)]
    assert check(ex(items=items, total=1.06), TODAY) == []


def test_date_future():
    c = codes(check(ex(date="2026-10-28"), TODAY))
    assert c == ["date_future"]


def test_date_wrong_format_is_invalid_not_crash():
    assert "date_invalid" in codes(check(ex(date="27/10/2026"), TODAY))


def test_date_none_is_invalid():
    assert "date_invalid" in codes(check(ex(date=None), TODAY))


def test_empty_ticket_with_null_total():
    c = codes(check(ex(items=[], total=None), TODAY))
    assert "no_items" in c and "total_not_positive" in c


def test_no_items_with_positive_total_also_sum_mismatch():
    c = codes(check(ex(items=[], total=5.0), TODAY))
    assert "no_items" in c and "sum_mismatch" in c


def test_low_quality_when_not_legible():
    assert codes(check(ex(legible=False), TODAY)) == ["low_quality"]


def test_multiple_receipts_warning():
    assert codes(check(ex(multiple_receipts=True), TODAY)) == ["multiple_receipts"]
