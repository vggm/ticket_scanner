"""Validación aritmética y de coherencia de una extracción (función pura)."""

import datetime
from decimal import ROUND_HALF_UP, Decimal

from ticket_scanner.schema import TicketExtraction, TicketWarning, to_cents

TOLERANCIA = 1  # céntimos


def _eur(cents: int) -> str:
    return f"{cents / 100:.2f}".replace(".", ",") + " €"


def check(extraction: TicketExtraction, today: datetime.date) -> list[TicketWarning]:
    warnings: list[TicketWarning] = []
    total = to_cents(extraction.total) or 0

    if not extraction.items:
        warnings.append(TicketWarning(code="no_items", message="El ticket no contiene artículos"))
    if total <= 0:
        warnings.append(
            TicketWarning(
                code="total_not_positive",
                message=f"El total ({_eur(total)}) no es positivo o no se ha leído",
            )
        )

    suma = sum(to_cents(i.amount) for i in extraction.items)
    if abs(suma - total) > TOLERANCIA:
        warnings.append(
            TicketWarning(
                code="sum_mismatch",
                message=f"La suma de las líneas ({_eur(suma)}) no coincide con el total ({_eur(total)})",
            )
        )

    for n, item in enumerate(extraction.items, start=1):
        if item.quantity is None or item.unit_price is None:
            continue
        esperado = int(
            (Decimal(str(item.quantity)) * to_cents(item.unit_price)).quantize(
                Decimal("1"), ROUND_HALF_UP
            )
        )
        real = to_cents(item.amount)
        if abs(esperado - real) > TOLERANCIA:
            warnings.append(
                TicketWarning(
                    code="line_mismatch",
                    message=(
                        f"Línea {n}: {item.quantity} × {_eur(to_cents(item.unit_price))} = "
                        f"{_eur(esperado)}, pero el importe es {_eur(real)}"
                    ),
                )
            )

    fecha = None
    if extraction.date is not None:
        try:
            fecha = datetime.date.fromisoformat(extraction.date)
        except ValueError:
            pass
    if fecha is None:
        warnings.append(
            TicketWarning(
                code="date_invalid",
                message=f"Fecha ausente o no válida: {extraction.date!r}",
            )
        )
    elif fecha > today:
        warnings.append(
            TicketWarning(code="date_future", message=f"La fecha {fecha} es posterior a hoy ({today})")
        )

    if not extraction.legible:
        warnings.append(
            TicketWarning(
                code="low_quality",
                message="La foto no se lee bien: repítela con más luz y enfocada",
            )
        )
    if extraction.multiple_receipts:
        warnings.append(
            TicketWarning(
                code="multiple_receipts",
                message="Hay varios tickets en la foto: se ha extraído solo uno; "
                "fotografía cada ticket por separado",
            )
        )

    return warnings
