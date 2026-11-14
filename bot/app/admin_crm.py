"""Admin CRM API: orders list / bulk / CSV, customers, follow-up tasks (agents and owner; exports owner only)."""

from __future__ import annotations

import re
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .crm import SEGMENTS, Crm, CrmError, csv_rows, fmt, now_dt
from .phone import normalize_phone
from .pricing import MAX_QTY
from .sheets import STATUSES

DT = r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}(:\d{2})?)?$"
D = r"^\d{4}-\d{2}-\d{2}$"
SETTABLE = ("confirmed", "shipped", "delivered", "returned", "cancelled", "needs_human")
MONEY_ONLY_OWNER = ("carrier_fee_cents",)


class OrdersBulkIn(BaseModel):
    model_config = {"extra": "forbid"}
    order_numbers: list[str] = Field(min_length=1, max_length=200)
    status: str | None = Field(default=None, max_length=30)
    carrier_id: int | None = Field(default=None, ge=0)  # 0 = remove the carrier
    return_reason: str | None = Field(default=None, max_length=300)


class CustomerEditIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=300)
    tags: list[str] | None = Field(default=None, max_length=12)
    internal_note: str | None = Field(default=None, max_length=2000)
    opted_out: bool | None = None


class NewOrderIn(BaseModel):
    model_config = {"extra": "forbid"}
    quantity: int = Field(default=1, ge=1, le=MAX_QTY)
    name: str | None = Field(default=None, min_length=2, max_length=80)


class TaskIn(BaseModel):
    model_config = {"extra": "forbid"}
    title: str = Field(default="", max_length=200)
    due_at: str | None = Field(default=None, pattern=DT)
    customer_phone: str = Field(default="", max_length=20)
    order_number: str = Field(default="", max_length=30)
    assigned_to: str = Field(default="", max_length=80)
    suggestion_key: str | None = Field(default=None, max_length=80)  # accept a computed suggestion


class TaskEditIn(BaseModel):
    model_config = {"extra": "forbid"}
    done: bool | None = None
    due_at: str | None = Field(default=None, pattern=DT)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    assigned_to: str | None = Field(default=None, max_length=80)


class DismissIn(BaseModel):
    model_config = {"extra": "forbid"}
    key: str = Field(min_length=3, max_length=80)


def _dt(v: str) -> str:
    return v if len(v) == 19 else (v + ":00" if len(v) == 16 else v + " 09:00:00")


def add_crm_routes(router: APIRouter, svc: Callable[[], Any], current_admin: Any, owner_only: Any,
                   audit: Callable[..., None], delivery: Callable[[], Any], apply_status: Callable[..., Any],
                   update_order: Callable[..., None]) -> None:
    cache: dict[str, Crm] = {}

    def crm() -> Crm:
        s = svc()
        if "c" not in cache or cache["c"].store is not s.store:
            # Suggestions read carriers / purchase orders / stock: make sure those tables exist.
            from .purchasing import Purchasing
            from .stock import Stock

            Purchasing(s.store, getattr(s.orders, "stock", None) or Stock(s.store))
            delivery()
            cache["c"] = Crm(s.store)
        return cache["c"]

    router.crm = crm  # type: ignore[attr-defined]

    def run(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except CrmError as e:
            raise HTTPException(409, str(e))

    def _page(limit: int, offset: int) -> None:
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(400, "pagination invalide")

    def _phone(raw: str) -> str:
        p = normalize_phone(raw)
        if not p:
            raise HTTPException(400, "numéro invalide")
        return p

    def _filters(q: str, status: str, frm: str, to: str, city: str, carrier_id: str, source: str) -> dict[str, Any]:
        statuses = [s for s in status.split(",") if s]
        if any(s not in STATUSES for s in statuses):
            raise HTTPException(400, "statut invalide")
        for d in (frm, to):
            if d and not re.fullmatch(D, d):
                raise HTTPException(422, "date invalide")
        if carrier_id and not carrier_id.isdigit():
            raise HTTPException(400, "livreur invalide")
        if source and source not in ("website", "whatsapp"):
            raise HTTPException(400, "source invalide")
        return {"q": q[:80], "statuses": statuses, "frm": frm, "to": to, "city": city[:80], "carrier_id": carrier_id,
                "source": source}

    # ================================================================== orders
    @router.get("/orders")
    def list_orders(q: str = "", status: str = "", frm: str = "", to: str = "", city: str = "", carrier_id: str = "",
                    source: str = "", sort: str = "created_at", dir: str = "desc", limit: int = 50, offset: int = 0,
                    admin: dict = Depends(current_admin)) -> dict[str, Any]:
        _page(limit, offset)
        page = run(lambda: crm().search_orders(_filters(q, status, frm, to, city, carrier_id, source), sort,
                                               dir != "asc", limit, offset))
        if admin.get("role") != "owner":
            for o in page["items"]:
                for k in MONEY_ONLY_OWNER:
                    o.pop(k, None)
        return page

    @router.get("/orders.csv")
    def export_orders(q: str = "", status: str = "", frm: str = "", to: str = "", city: str = "", carrier_id: str = "",
                      source: str = "", admin: dict = Depends(owner_only)) -> Response:
        rows = crm().export_orders(_filters(q, status, frm, to, city, carrier_id, source))
        cols = [("order_number", "Commande"), ("created_at", "Créée le"), ("name", "Nom"), ("phone", "Téléphone"),
                ("city", "Ville"), ("address", "Adresse"), ("quantity", "Quantité"), ("total", "Total (MAD)"),
                ("status", "Statut"), ("carrier", "Livreur"), ("tracking", "Suivi"), ("delivered_at", "Livrée le"),
                ("cod_status", "Encaissement"), ("source", "Source"), ("internal_note", "Note interne")]
        audit(admin, "orders.export", "order", "", f"{len(rows)} commandes")
        return Response(csv_rows(rows, cols), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="nayo-commandes-{fmt(now_dt())[:10]}.csv"'})

    @router.post("/orders/bulk")
    def bulk_orders(body: OrdersBulkIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        """Status and/or carrier for several orders, each through the normal single-order path
        (stock, Sheet mirror, COD fields, audit). Stock is never forced in bulk: refused orders are listed."""
        if body.status is None and body.carrier_id is None:
            raise HTTPException(422, "rien à faire")
        if body.status is not None and body.status not in SETTABLE:
            raise HTTPException(400, "statut invalide")
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
                    if body.status in ("shipped", "delivered", "returned") and \
                            o.get("status") not in ("confirmed", "shipped", "delivered", "returned"):
                        raise HTTPException(409, "commande pas encore confirmée")
                    apply_status(o, body.status, admin, return_reason=body.return_reason)
                done.append(o["order_number"])
            except HTTPException as e:
                errors[number] = str(e.detail)
        crm()._cache.clear()
        return {"done": done, "errors": errors}

    # ================================================================== customers
    @router.get("/customers")
    def customers(q: str = "", segment: str = "", tag: str = "", sort: str = "last_order", dir: str = "desc",
                  limit: int = 50, offset: int = 0, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        _page(limit, offset)
        page = run(lambda: crm().list_customers(q[:80], segment, tag[:30], sort, dir != "asc", limit, offset))
        if admin.get("role") != "owner":
            for c in page["items"]:
                c.pop("delivered_cents", None)
        return page

    @router.get("/customers.csv")
    def export_customers(q: str = "", segment: str = "", tag: str = "", admin: dict = Depends(owner_only)) -> Response:
        if segment and segment not in SEGMENTS:
            raise HTTPException(400, "segment invalide")
        items = crm().list_customers(q[:80], segment, tag[:30], "last_order", True, 10000, 0)["items"]
        label = {"new": "Nouveau", "loyal": "Fidèle", "at_risk": "À risque", "inactive": "Inactif"}
        rows = [{**c, "tags": ", ".join(c["tags"]), "segment": label[c["segment"]],
                 "delivered_mad": f"{c['delivered_cents'] / 100:.2f}".replace(".", ","),
                 "opted_out": "oui" if c["opted_out"] else ""} for c in items]
        cols = [("phone", "Téléphone"), ("name", "Nom"), ("city", "Ville"), ("address", "Adresse"),
                ("segment", "Segment"), ("orders_count", "Commandes"), ("delivered", "Livrées"),
                ("delivered_mad", "Valeur livrée (MAD)"), ("returned", "Retours"), ("cancelled", "Annulées"),
                ("last_order", "Dernière commande"), ("tags", "Étiquettes"), ("opted_out", "STOP"),
                ("internal_note", "Note interne")]
        audit(admin, "customers.export", "customer", "", f"{len(rows)} clients")
        return Response(csv_rows(rows, cols), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="nayo-clients-{fmt(now_dt())[:10]}.csv"'})

    @router.get("/customers/{phone}")
    def customer(phone: str, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        p = _phone(phone)
        c = crm().get_customer(p)
        if not c:
            raise HTTPException(404, "client introuvable")
        if admin.get("role") != "owner":
            c.pop("delivered_cents", None)
        conv = svc().store.get_conv(p)
        import time as _t

        from .flow import WINDOW_S

        return {"customer": c, "orders": crm().customer_orders(p),
                "tasks": crm().list_tasks("late", 50, 0, p)["items"] + crm().list_tasks("today", 50, 0, p)["items"]
                + crm().list_tasks("upcoming", 50, 0, p)["items"],
                "window_open": bool(conv.last_client_at and conv.last_client_at + WINDOW_S > _t.time())}

    @router.patch("/customers/{phone}")
    def edit_customer(phone: str, body: CustomerEditIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        p = _phone(phone)
        if not crm().get_customer(p):
            raise HTTPException(404, "client introuvable")
        raw = body.model_dump(exclude_none=True)
        for k in ("name", "city", "address"):
            if k in raw:
                raw[k] = " ".join(raw[k].split())
        if "internal_note" in raw:
            raw["internal_note"] = raw["internal_note"].strip()
        crm().update_customer(p, **raw)
        if raw:
            audit(admin, "customer.edit", "customer", p,
                  ", ".join(f"{k}: {v}" for k, v in raw.items())[:300])
        return {"customer": crm().get_customer(p)}

    @router.post("/customers/{phone}/orders")
    def new_order(phone: str, body: NewOrderIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        """"Nouvelle commande" from a customer's page: same numbering / store / Sheet mirror as the bot."""
        from .orders import create_bot_order

        p = _phone(phone)
        c = crm().get_customer(p)
        if not c:
            raise HTTPException(404, "client introuvable")
        name = " ".join((body.name or c["name"] or "").split())
        if len(name) < 2:
            raise HTTPException(422, "nom du client requis")
        s = svc()
        row = create_bot_order(s.orders, s.store, name=name, phone=p, quantity=body.quantity)
        extra = {k: c[k] for k in ("city", "address") if c.get(k)}
        if extra:
            s.orders.update(row["order_number"], **extra)
        audit(admin, "order.create", "order", row["order_number"], f"depuis la fiche client, quantité {body.quantity}")
        crm()._cache.clear()
        return {"order_number": row["order_number"]}

    # ================================================================== tasks
    @router.get("/tasks")
    def tasks(view: str = "today", limit: int = 50, offset: int = 0, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        _page(limit, offset)
        page = run(lambda: crm().list_tasks(view, limit, offset))
        if view == "today" and offset == 0:
            page["suggestions"] = crm().suggestions(admin.get("role") == "owner")
        return page

    @router.get("/tasks/counts")
    def task_counts(admin: dict = Depends(current_admin)) -> dict[str, Any]:
        c = crm().task_counts()
        c["suggestions"] = len(crm().suggestions(admin.get("role") == "owner"))
        c["badge"] = c["late"] + c["today"] + c["suggestions"]
        return c

    @router.post("/tasks")
    def add_task(body: TaskIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        now = fmt(now_dt())
        if body.suggestion_key:
            s = next((x for x in crm().suggestions(admin.get("role") == "owner", fresh=True)
                      if x["key"] == body.suggestion_key), None)
            if not s:
                raise HTTPException(409, "Cette suggestion n'est plus d'actualité.")
            t = run(lambda: crm().add_task(title=s["title"], due_at=_dt(body.due_at) if body.due_at else now,
                                           admin=admin["name"], customer_phone=s["customer_phone"],
                                           order_number=s["order_number"], assigned_to=body.assigned_to,
                                           suggestion_key=s["key"]))
        else:
            phone = _phone(body.customer_phone) if body.customer_phone else ""
            number = body.order_number.strip().upper()
            if number and not svc().orders.get(number):
                raise HTTPException(422, "commande introuvable")
            t = run(lambda: crm().add_task(title=body.title, due_at=_dt(body.due_at) if body.due_at else now,
                                           admin=admin["name"], customer_phone=phone, order_number=number,
                                           assigned_to=body.assigned_to.strip()))
        audit(admin, "task.create", "task", str(t["id"]), t["title"][:200])
        return t

    @router.post("/tasks/dismiss")
    def dismiss(body: DismissIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        s = next((x for x in crm().suggestions(admin.get("role") == "owner", fresh=True) if x["key"] == body.key), None)
        if not s:
            raise HTTPException(409, "Cette suggestion n'est plus d'actualité.")
        run(lambda: crm().add_task(title=s["title"], due_at=fmt(now_dt()), admin=admin["name"],
                                   customer_phone=s["customer_phone"], order_number=s["order_number"],
                                   suggestion_key=s["key"], done=True, dismissed=True))
        audit(admin, "task.dismiss", "task", s["key"], s["title"][:200])
        return {"ok": True}

    @router.patch("/tasks/{tid}")
    def edit_task(tid: int, body: TaskEditIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        raw = body.model_dump(exclude_none=True)
        if "due_at" in raw:
            raw["due_at"] = _dt(raw["due_at"])
        t = run(lambda: crm().update_task(tid, **raw))
        if raw:
            audit(admin, "task.done" if raw.get("done") else "task.edit", "task", str(tid),
                  ", ".join(f"{k}: {v}" for k, v in raw.items())[:300])
        return t

    @router.get("/team")
    def team(admin: dict = Depends(current_admin)) -> dict[str, Any]:
        """Names only (to assign a follow-up)."""
        rows = svc().store._exec("SELECT name FROM admin_users ORDER BY name", fetch="all")
        return {"names": [r[0] for r in rows]}
