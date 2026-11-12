"""Website → bot: create an order row. Idempotent per clientId, so browser retries never duplicate an order."""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .phone import is_moroccan_mobile_or_landline, normalize_phone
from .pricing import MAX_QTY, PRODUCT_NAME, order_total
from .sheets import OrdersRepo, now_local
from .store import Store

log = logging.getLogger("nayo.orders")

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class OrderIn(BaseModel):
    """Exactly what the checkout sends. Prices from the browser are accepted but ignored (recomputed here)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    clientId: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    orderNumber: str | None = Field(default=None, pattern=r"^NAYO-W\d{6}$")  # website fallback number
    name: str = Field(min_length=3, max_length=80)
    phone: str = Field(min_length=9, max_length=20)
    quantity: int = Field(ge=1, le=MAX_QTY)
    product: str | None = Field(default=None, max_length=60)
    unitPrice: int | None = None
    subtotal: int | None = None
    shipping: int | None = None
    total: int | None = None
    currency: str | None = Field(default=None, pattern=r"^MAD$")
    payment: str | None = Field(default=None, pattern=r"^cash_on_delivery$")
    status: str | None = Field(default=None, pattern=r"^new$")
    createdAt: str | None = Field(default=None, max_length=40)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(_CONTROL.sub(" ", v).split())
        if len(v) < 3 or v[0] in "=+-@":  # also blocks spreadsheet formula injection
            raise ValueError("invalid name")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        n = normalize_phone(v)
        if not is_moroccan_mobile_or_landline(n):
            raise ValueError("invalid Moroccan phone number")
        return n  # type: ignore[return-value]


class OrderOut(BaseModel):
    orderNumber: str
    quantity: int
    total: int


def create_order(body: OrderIn, orders: OrdersRepo, store: Store) -> OrderOut:
    total = order_total(body.quantity)
    if body.total is not None and body.total != total:
        log.warning("client total %s differs from computed %s — using computed", body.total, total)

    existing = store.get_request(body.clientId)
    if existing is None:
        number = body.orderNumber or f"NAYO-{store.next_order_number()}"
        if not store.claim_request(body.clientId, number):  # lost a race with an identical request
            existing = store.get_request(body.clientId)
        else:
            existing = (number, False)

    number, written = existing  # type: ignore[misc]
    if body.orderNumber and body.orderNumber != number:
        # A first request succeeded server-side but the browser timed out and showed a fallback number.
        store.add_alias(body.orderNumber, number)
        log.info("alias %s → %s", body.orderNumber, number)

    if not written:
        orders.append(
            order_row(number, body.name, body.phone, body.quantity, "new",
                      "" if not body.orderNumber else "numéro de secours (site)", source="website")
        )
        store.mark_written(body.clientId)
        log.info("order %s created (qty %d, %d MAD)", number, body.quantity, total)
    return OrderOut(orderNumber=number, quantity=body.quantity, total=total)


def order_row(number: str, name: str, phone: str, quantity: int, status: str, notes: str = "", source: str = "") -> dict:
    """One order row, identical whether it comes from the website or from WhatsApp."""
    return {
        "order_number": number,
        "created_at": now_local(),
        "name": name,
        "phone": phone,
        "quantity": quantity,
        "total": order_total(quantity),
        "status": status,
        "notes": notes,
        "updated_at": now_local(),
        "source": source,  # database-only column (website | whatsapp)
    }


def create_bot_order(orders: OrdersRepo, store: Store, *, name: str, phone: str, quantity: int = 1) -> dict:
    """A client asks for an additional order on WhatsApp: same numbering and same store as POST /orders
    (so it is also mirrored to the Google Sheet). Status awaiting_details: the bot collects the rest."""
    number = f"NAYO-{store.next_order_number()}"
    row = order_row(number, name, phone, quantity, "awaiting_details", "[bot] commande créée par WhatsApp", source="whatsapp")
    orders.append(row)
    log.info("order %s created from WhatsApp (qty %d)", number, quantity)
    return {**row, "city": "", "address": "", "whatsapp_from": phone}


__all__ = ["OrderIn", "OrderOut", "create_order", "create_bot_order", "order_row", "PRODUCT_NAME"]
