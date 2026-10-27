"""Esquemas de extracción (modelo) y de respuesta (API, importes en céntimos)."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ExtractedItem(BaseModel):
    description: str = Field(description="Descripción del artículo tal como aparece en el ticket")
    quantity: float | None = Field(
        description="Cantidad comprada; en kg si el artículo es de peso. null si no se ve"
    )
    unit_price: float | None = Field(
        description="Precio por unidad (o por kg) en euros. null si no se ve"
    )
    amount: float = Field(
        description="Importe total de la línea en euros; negativo si es un descuento"
    )


class TicketExtraction(BaseModel):
    is_receipt: bool = Field(description="true si la imagen es un ticket de compra, si no false")
    store_name: str | None = Field(description="Nombre del comercio. null si no se lee")
    store_tax_id: str | None = Field(description="NIF/CIF del comercio. null si no se lee")
    date: str | None = Field(
        description="Fecha del ticket en formato AAAA-MM-DD. null si no se lee"
    )
    total: float | None = Field(
        description="Total pagado en euros, positivo. null si no se lee"
    )
    items: list[ExtractedItem] = Field(
        description="Líneas de artículos; los descuentos van como líneas con importe negativo"
    )


class TicketWarning(BaseModel):
    code: str
    message: str


class Store(BaseModel):
    name: str | None
    tax_id: str | None


class ResponseItem(BaseModel):
    description: str
    quantity: float | None
    unit_price_cents: int | None
    amount_cents: int


class TicketResponse(BaseModel):
    status: Literal["ok", "revisar"]
    warnings: list[TicketWarning]
    store: Store
    date: str | None
    currency: Literal["EUR"] = "EUR"
    total_cents: int
    items: list[ResponseItem]
    model: str


def to_cents(value: float | None) -> int | None:
    """Euros a céntimos enteros (redondeo half-up vía Decimal)."""
    if value is None:
        return None
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), ROUND_HALF_UP))


def build_response(
    extraction: TicketExtraction, warnings: list[TicketWarning], model: str
) -> TicketResponse:
    return TicketResponse(
        status="revisar" if warnings else "ok",
        warnings=warnings,
        store=Store(name=extraction.store_name, tax_id=extraction.store_tax_id),
        date=extraction.date,
        total_cents=to_cents(extraction.total) or 0,
        items=[
            ResponseItem(
                description=i.description,
                quantity=i.quantity,
                unit_price_cents=to_cents(i.unit_price),
                amount_cents=to_cents(i.amount),
            )
            for i in extraction.items
        ],
        model=model,
    )
