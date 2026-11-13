"""Admin purchasing API: suppliers, purchase orders, receipts, supplier payments. Owner only (it's all money)."""

from __future__ import annotations

from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .purchasing import PAYMENT_METHODS, PO_STATUSES, Purchasing, PurchasingError, money_cents
from .stock import Stock

MAD = Field(ge=0, le=10_000_000)


class SupplierIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default="", max_length=30)
    city: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=1000)


class SupplierEditIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    city: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=1000)
    active: bool | None = None


class POIn(BaseModel):
    model_config = {"extra": "forbid"}
    supplier_id: int = Field(ge=1)
    quantity: int = Field(ge=1, le=1_000_000)
    unit_cost: float = MAD
    shipping_cost: float = Field(default=0, ge=0, le=10_000_000)
    other_costs: float = Field(default=0, ge=0, le=10_000_000)
    ordered_at: str | None = Field(default=None, max_length=10)
    expected_at: str | None = Field(default=None, max_length=10)
    note: str = Field(default="", max_length=1000)
    status: Literal["draft", "ordered"] = "draft"


class POEditIn(BaseModel):
    model_config = {"extra": "forbid"}
    supplier_id: int | None = Field(default=None, ge=1)
    quantity: int | None = Field(default=None, ge=1, le=1_000_000)
    unit_cost: float | None = Field(default=None, ge=0, le=10_000_000)
    shipping_cost: float | None = Field(default=None, ge=0, le=10_000_000)
    other_costs: float | None = Field(default=None, ge=0, le=10_000_000)
    ordered_at: str | None = Field(default=None, max_length=10)
    expected_at: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=1000)


class POStatusIn(BaseModel):
    status: Literal["ordered", "cancelled"]


class ReceiveIn(BaseModel):
    quantity: int = Field(ge=1, le=1_000_000)
    note: str = Field(default="", max_length=300)


class PaymentIn(BaseModel):
    amount: float = Field(gt=0, le=10_000_000)
    method: Literal["cash", "virement", "chèque", "autre"]
    note: str = Field(default="", max_length=300)
    at: str | None = Field(default=None, max_length=10)


def add_purchasing_routes(router: APIRouter, svc: Callable[[], Any], owner_only: Any,
                          audit: Callable[..., None]) -> None:
    cache: dict[str, Purchasing] = {}

    def purchasing() -> Purchasing:
        s = svc()
        if "p" not in cache or cache["p"].store is not s.store:
            stock = getattr(s.orders, "stock", None) or Stock(s.store)
            cache["p"] = Purchasing(s.store, stock)
        return cache["p"]

    def run(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except PurchasingError as e:
            raise HTTPException(409, str(e))

    def _cents(v: float | None) -> int | None:
        return None if v is None else run(lambda: money_cents(v))

    # ---------------------------------------------------------------- suppliers
    @router.get("/suppliers")
    def suppliers(include_inactive: bool = False, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        return {"items": purchasing().suppliers(include_inactive)}

    @router.post("/suppliers")
    def create_supplier(body: SupplierIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        sup = run(lambda: purchasing().create_supplier(body.name, body.phone, body.city, body.note))
        audit(admin, "supplier.create", "supplier", str(sup["id"]), sup["name"])
        return sup

    @router.patch("/suppliers/{sid}")
    def edit_supplier(sid: int, body: SupplierEditIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        changes = body.model_dump(exclude_none=True)
        sup = run(lambda: purchasing().update_supplier(sid, **changes))
        if changes:
            audit(admin, "supplier.edit", "supplier", str(sid), ", ".join(f"{k}: {v}" for k, v in changes.items())[:300])
        return sup

    # ---------------------------------------------------------------- purchase orders
    @router.get("/purchasing/summary")
    def summary(admin: dict = Depends(owner_only)) -> dict[str, Any]:
        return purchasing().summary()

    @router.get("/purchase-orders")
    def list_pos(status: str | None = None, supplier_id: int | None = None, late: bool = False, limit: int = 50,
                 offset: int = 0, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        if status and status not in PO_STATUSES:
            raise HTTPException(400, "statut invalide")
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(400, "pagination invalide")
        return purchasing().list_pos(status=status, supplier_id=supplier_id, late=late, limit=limit, offset=offset)

    @router.post("/purchase-orders")
    def create_po(body: POIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        po = run(lambda: purchasing().create_po(
            supplier_id=body.supplier_id, quantity=body.quantity, unit_cost_cents=money_cents(body.unit_cost),
            shipping_cost_cents=money_cents(body.shipping_cost), other_costs_cents=money_cents(body.other_costs),
            ordered_at=body.ordered_at, expected_at=body.expected_at, note=body.note, status=body.status,
            admin=admin["name"]))
        audit(admin, "po.create", "purchase_order", po["number"],
              f"{po['quantity']} × {po['unit_cost_cents'] / 100:.2f} MAD, total {po['total_cents'] / 100:.2f} MAD ({po['status']})")
        return po

    @router.get("/purchase-orders/{po_id}")
    def get_po(po_id: int, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        p = purchasing()
        po = p.get_po(po_id)
        if not po:
            raise HTTPException(404, "commande introuvable")
        return {"po": po, "receipts": p.receipts(po_id), "payments": p.payments(po_id),
                "supplier": p.supplier(int(po["supplier_id"]))}

    @router.patch("/purchase-orders/{po_id}")
    def edit_po(po_id: int, body: POEditIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        raw = body.model_dump(exclude_none=True)
        changes: dict[str, Any] = {}
        for k, v in raw.items():
            if k in ("unit_cost", "shipping_cost", "other_costs"):
                changes[f"{k}_cents"] = _cents(v)
            else:
                changes[k] = v
        po = run(lambda: purchasing().update_po(po_id, **changes))
        if changes:
            audit(admin, "po.edit", "purchase_order", po["number"], ", ".join(f"{k}: {v}" for k, v in changes.items())[:300])
        return po

    @router.post("/purchase-orders/{po_id}/status")
    def po_status(po_id: int, body: POStatusIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        po = run(lambda: purchasing().set_status(po_id, body.status))
        audit(admin, "po.status", "purchase_order", po["number"], body.status)
        return po

    @router.post("/purchase-orders/{po_id}/receive")
    def receive(po_id: int, body: ReceiveIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        r = run(lambda: purchasing().receive(po_id, body.quantity, admin["name"], body.note))
        audit(admin, "po.receive", "purchase_order", r["po"]["number"],
              f"+{body.quantity} à {r['landed_unit_cost_cents'] / 100:.2f} MAD (coût rendu)")
        return r

    @router.post("/purchase-orders/{po_id}/payments")
    def pay(po_id: int, body: PaymentIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        if body.method not in PAYMENT_METHODS:
            raise HTTPException(422, "mode de paiement invalide")
        po = run(lambda: purchasing().add_payment(po_id, money_cents(body.amount), body.method, admin["name"],
                                                  body.note, body.at))
        audit(admin, "po.payment", "purchase_order", po["number"], f"{body.amount:.2f} MAD ({body.method})")
        return po
