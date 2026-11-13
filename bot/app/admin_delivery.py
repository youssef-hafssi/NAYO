"""Admin delivery & COD API.

Everyone (owner + agents): carriers' names, the delivery board, bulk carrier / status changes, delivery slips.
Owner only: carrier fees and settings, cash held by carriers, reconciliation (remittances), returns with losses.
"""

from __future__ import annotations

from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .delivery import Delivery, DeliveryError

BOARD_STATUSES = ("confirmed", "shipped", "delivered", "returned")


class CarrierIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(default="", max_length=30)
    fee_delivered: float = Field(default=0, ge=0, le=10_000)
    fee_returned: float = Field(default=0, ge=0, le=10_000)
    remit_delay_days: int = Field(default=7, ge=0, le=120)


class CarrierEditIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=30)
    fee_delivered: float | None = Field(default=None, ge=0, le=10_000)
    fee_returned: float | None = Field(default=None, ge=0, le=10_000)
    remit_delay_days: int | None = Field(default=None, ge=0, le=120)
    active: bool | None = None


class BulkIn(BaseModel):
    model_config = {"extra": "forbid"}
    order_numbers: list[str] = Field(min_length=1, max_length=200)
    carrier_id: int | None = Field(default=None, ge=0)  # 0 = remove the carrier
    status: Literal["shipped", "delivered", "returned"] | None = None
    return_reason: str | None = Field(default=None, max_length=300)
    recoverable: bool = True


class RemitIn(BaseModel):
    model_config = {"extra": "forbid"}
    carrier_id: int = Field(ge=1)
    order_numbers: list[str] = Field(min_length=1, max_length=500)
    amount_received: float = Field(ge=0, le=10_000_000)
    note: str = Field(default="", max_length=300)


def add_delivery_routes(router: APIRouter, svc: Callable[[], Any], current_admin: Any, owner_only: Any,
                        audit: Callable[..., None], delivery: Callable[[], Delivery], apply_status: Callable[..., Any],
                        update_order: Callable[..., None]) -> None:
    def run(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except DeliveryError as e:
            raise HTTPException(409, str(e))

    def _public(c: dict[str, Any], admin: dict) -> dict[str, Any]:
        if admin.get("role") == "owner":
            return c
        return {k: c[k] for k in ("id", "name", "phone", "active")}

    # ---------------------------------------------------------------- carriers
    @router.get("/carriers")
    def carriers(include_inactive: bool = False, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        return {"items": [_public(c, admin) for c in delivery().carriers(include_inactive)]}

    @router.post("/carriers")
    def create_carrier(body: CarrierIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        c = run(lambda: delivery().create_carrier(
            name=body.name, phone=body.phone, fee_delivered_cents=round(body.fee_delivered * 100),
            fee_returned_cents=round(body.fee_returned * 100), remit_delay_days=body.remit_delay_days))
        audit(admin, "carrier.create", "carrier", str(c["id"]), c["name"])
        return c

    @router.patch("/carriers/{cid}")
    def edit_carrier(cid: int, body: CarrierEditIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        raw = body.model_dump(exclude_none=True)
        changes = {(f"{k}_cents" if k in ("fee_delivered", "fee_returned") else k):
                   (round(v * 100) if k in ("fee_delivered", "fee_returned") else v) for k, v in raw.items()}
        c = run(lambda: delivery().update_carrier(cid, **changes))
        if changes:
            audit(admin, "carrier.edit", "carrier", str(cid), ", ".join(f"{k}: {v}" for k, v in changes.items())[:300])
        return c

    # ---------------------------------------------------------------- board
    @router.get("/delivery")
    def board(status: str = "confirmed", carrier_id: int | None = None, limit: int = 50, offset: int = 0,
              admin: dict = Depends(current_admin)) -> dict[str, Any]:
        if status not in BOARD_STATUSES:
            raise HTTPException(400, "statut invalide")
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(400, "pagination invalide")
        page = delivery().board(status, carrier_id, limit, offset)
        if admin.get("role") != "owner":
            for o in page["items"]:
                o.pop("carrier_fee_cents", None)
        return page

    @router.post("/delivery/bulk")
    def bulk(body: BulkIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        """Assign a carrier and/or change the status of several orders. Each order goes through the normal path
        (stock, Sheet mirror, COD fields, audit). Returns what succeeded and what was refused, per order."""
        if body.carrier_id is None and body.status is None:
            raise HTTPException(422, "rien à faire")
        carrier = None
        if body.carrier_id:
            carrier = delivery().carrier(body.carrier_id)
            if not carrier or not carrier["active"]:
                raise HTTPException(422, "livreur introuvable ou désactivé")
        orders = svc().orders
        done, errors = [], {}
        for number in dict.fromkeys(n.strip() for n in body.order_numbers if n.strip()):
            o = orders.get(number)
            if not o:
                errors[number] = "introuvable"
                continue
            try:
                if body.carrier_id is not None:
                    new_id = str(carrier["id"]) if carrier else ""
                    if new_id != str(o.get("carrier_id") or ""):
                        if o.get("cod_status") == "remitted":
                            raise HTTPException(409, "déjà encaissée")
                        update_order(o["order_number"], admin, carrier_id=new_id, carrier=carrier["name"] if carrier else "")
                        audit(admin, "order.edit", "order", o["order_number"],
                              f"carrier: {o.get('carrier', '') or ''} → {carrier['name'] if carrier else ''}")
                        o = orders.get(number)
                if body.status and body.status != o.get("status"):
                    if body.status in ("delivered", "returned") and o.get("status") not in ("confirmed", "shipped", "delivered", "returned"):
                        raise HTTPException(409, "commande pas encore confirmée")
                    apply_status(o, body.status, admin, return_reason=body.return_reason, recoverable=body.recoverable)
                done.append(o["order_number"])
            except HTTPException as e:
                errors[number] = str(e.detail)
        return {"done": done, "errors": errors}

    @router.get("/delivery/slips")
    def slips(numbers: str, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        items = delivery().slips(numbers.split(","))
        store = svc().store
        company = store.get_settings(("company_name", "company_address", "company_phone"))
        return {"items": items, "company": {"name": company.get("company_name") or "NAYO",
                                            "address": company.get("company_address", ""),
                                            "phone": company.get("company_phone", "")}}

    # ---------------------------------------------------------------- cash on delivery (owner)
    @router.get("/cod/summary")
    def cod_summary(admin: dict = Depends(owner_only)) -> dict[str, Any]:
        held = delivery().held_by_carrier()
        return {"carriers": held, "total_cents": sum(c["expected_cents"] for c in held),
                "late_carriers": sum(1 for c in held if c["late"])}

    @router.get("/cod/pending")
    def cod_pending(carrier_id: int, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        return {"items": run(lambda: delivery().pending(carrier_id))}

    @router.post("/remittances")
    def remit(body: RemitIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        r = run(lambda: delivery().remit(body.carrier_id, body.order_numbers, round(body.amount_received * 100),
                                         admin["name"], body.note))
        audit(admin, "cod.remittance", "remittance", str(r["id"]),
              f"{r['orders']} commande(s), attendu {r['expected_cents'] / 100:.2f}, reçu {r['amount_received_cents'] / 100:.2f}, "
              f"écart {r['difference_cents'] / 100:+.2f} MAD")
        return r

    @router.get("/remittances")
    def remittances(carrier_id: int | None = None, limit: int = 50, offset: int = 0,
                    admin: dict = Depends(owner_only)) -> dict[str, Any]:
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(400, "pagination invalide")
        return delivery().remittances(carrier_id, limit, offset)

    @router.get("/returns")
    def returns(limit: int = 50, offset: int = 0, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(400, "pagination invalide")
        if getattr(svc().orders, "stock", None) is None:
            from .stock import Stock

            Stock(svc().store)  # the returns query reads stock_movements
        return delivery().returns(limit, offset)
