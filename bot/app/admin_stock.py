"""Admin stock API (/admin/stock*). Agents see units only; costs, value and every write are owner-only."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .sheets import CONFIRMED_LIKE
from .stock import MAX_UNITS, Stock, mad_to_cents

COST_KEYS = ("avg_cost_cents", "stock_value_cents")


class OpeningIn(BaseModel):
    quantity: int = Field(ge=0, le=MAX_UNITS)
    unit_cost: float = Field(ge=0, le=100_000)  # MAD, up to 2 decimals


class RestockIn(BaseModel):
    quantity: int = Field(ge=1, le=MAX_UNITS)
    unit_cost: float = Field(ge=0, le=100_000)
    note: str = Field(default="", max_length=300)


class AdjustIn(BaseModel):
    new_quantity: int = Field(ge=0, le=MAX_UNITS)
    note: str = Field(min_length=3, max_length=300)


class ThresholdIn(BaseModel):
    value: int = Field(ge=0, le=MAX_UNITS)


def add_stock_routes(router: APIRouter, svc: Callable[[], Any], current_admin: Any, owner_only: Any,
                     audit: Callable[..., None]) -> None:
    def stock() -> Stock:
        s = getattr(svc().orders, "stock", None)
        return s if s is not None else Stock(svc().store)

    def _strip_costs(d: dict[str, Any], admin: dict) -> dict[str, Any]:
        if admin.get("role") == "owner":
            return d
        return {k: v for k, v in d.items() if k not in COST_KEYS and "cost" not in k}

    @router.get("/stock")
    def get_stock(admin: dict = Depends(current_admin)) -> dict[str, Any]:
        return _strip_costs(stock().summary(), admin)

    @router.get("/stock/movements")
    def movements(cursor: int | None = None, limit: int = 50, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise HTTPException(400, "limit 1..200")
        page = stock().movements(cursor, limit)
        page["items"] = [_strip_costs(m, admin) for m in page["items"]]
        return page

    @router.post("/stock/opening")
    def opening(body: OpeningIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        orders = svc().orders
        units_in = getattr(orders, "units_in", None)
        confirmed = units_in(CONFIRMED_LIKE) if callable(units_in) else []
        try:
            stock().open(body.quantity, mad_to_cents(body.unit_cost), admin["name"], confirmed)
        except ValueError as e:
            raise HTTPException(409, str(e))
        audit(admin, "stock.opening", "stock", "", f"{body.quantity} unités à {body.unit_cost:.2f} MAD "
              f"({len(confirmed)} commande(s) déjà confirmée(s) exclues)")
        return stock().summary()

    @router.post("/stock/restock")
    def restock(body: RestockIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        try:
            r = stock().receive(body.quantity, mad_to_cents(body.unit_cost), reason="restock_manual",
                                admin=admin["name"], note=body.note.strip())
        except ValueError as e:
            raise HTTPException(409, str(e))
        audit(admin, "stock.restock", "stock", str(r["id"]), f"+{body.quantity} à {body.unit_cost:.2f} MAD"
              + (f" — {body.note.strip()}" if body.note.strip() else ""))
        return stock().summary()

    @router.post("/stock/adjust")
    def adjust(body: AdjustIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        try:
            r = stock().adjust(body.new_quantity, body.note, admin["name"])
        except ValueError as e:
            raise HTTPException(409, str(e))
        if r:
            audit(admin, "stock.adjust", "stock", str(r["id"]),
                  f"{r['delta']:+d} → {body.new_quantity} — {body.note.strip()}")
        return stock().summary()

    @router.post("/stock/threshold")
    def threshold(body: ThresholdIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        stock().set_threshold(body.value)
        audit(admin, "stock.threshold", "stock", "", str(body.value))
        return stock().summary()
