"""Admin inbox API (/admin/*): the team reads every WhatsApp thread, takes a conversation over from the
bot, replies within WhatsApp's 24h window, changes order statuses and keeps internal notes.

Auth: POST /admin/login sets a signed HttpOnly session cookie (HMAC-SHA256 with ADMIN_SECRET).
Team members are created with `python create_admin.py` (no public sign-up).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .flow import WINDOW_S
from .phone import normalize_phone
from .pricing import MAX_QTY, SHIPPING, UNIT_PRICE, order_total
from .sheets import EXTRA_COLUMNS, STATUSES, now_local
from .stock import InsufficientStock
from .delivery import Delivery, DeliveryError, cod_fields

log = logging.getLogger("nayo.admin")

COOKIE = "nayo_admin"
STATUS_FILTERS = {"all", "needs_human", "confirmed", "cancelled", "shipped", "delivered", "returned"}
SETTABLE_STATUSES = {"confirmed", "shipped", "delivered", "returned", "cancelled", "needs_human"}
ALL_STATUSES = STATUSES
EDITABLE_FIELDS = ("name", "phone", "city", "address", "quantity", "carrier", "tracking", "internal_note")
MIN_PASSWORD = 10


# ---------------------------------------------------------------- passwords & sessions
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        want = _unb64(digest)
        got = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(want))
        return hmac.compare_digest(got, want)
    except Exception:
        return False


_DUMMY_HASH = hash_password(uuid.uuid4().hex)  # same timing whether or not the email exists


def make_session(secret: str, admin_id: str, ttl_s: int, now: float | None = None) -> str:
    payload = _b64(json.dumps({"id": admin_id, "exp": int((now or time.time()) + ttl_s)}).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_session(secret: str, token: str | None, now: float | None = None) -> str | None:
    if not secret or not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except Exception:
        return None
    if data.get("exp", 0) < (now or time.time()):
        return None
    return data.get("id")


# ---------------------------------------------------------------- request bodies
class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class StatusIn(BaseModel):
    status: str = Field(max_length=30)
    return_reason: str | None = Field(default=None, max_length=300)
    force: bool = False  # confirm even beyond the stock ("Confirmer quand même ?")
    recoverable: bool = True  # returned: the product goes back to stock (untick = written off)


class OrderEditIn(BaseModel):
    """Every field optional: only the ones sent are changed (and each change is audited)."""

    model_config = {"extra": "forbid"}
    name: str | None = Field(default=None, min_length=2, max_length=80)
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    city: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=300)
    quantity: int | None = Field(default=None, ge=1, le=MAX_QTY)
    carrier: str | None = Field(default=None, max_length=60)
    carrier_id: int | None = Field(default=None, ge=0)  # 0 = no carrier
    carrier_fee: float | None = Field(default=None, ge=0, le=100_000)  # MAD, owner only
    tracking: str | None = Field(default=None, max_length=80)
    internal_note: str | None = Field(default=None, max_length=2000)
    force: bool = False  # quantity increase on a confirmed order beyond the stock


class PasswordIn(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=MIN_PASSWORD, max_length=200)


class NotesIn(BaseModel):
    notes: str = Field(max_length=5000)


# ---------------------------------------------------------------- router
def build_admin_router(svc: Callable[[], Any], settings: Any) -> APIRouter:
    router = APIRouter(prefix="/admin")
    ttl = int(getattr(settings, "admin_session_days", 7)) * 86400

    def _secure(request: Request) -> bool:
        return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"

    def current_admin(request: Request) -> dict[str, Any]:
        if not settings.admin_secret:
            raise HTTPException(503, "admin disabled (ADMIN_SECRET not set)")
        admin_id = read_session(settings.admin_secret, request.cookies.get(COOKIE))
        # One statement: load the admin and refresh last_seen_at (at most every 30 s).
        admin = svc().store.auth_admin(admin_id) if admin_id else None
        if not admin:
            raise HTTPException(401, "not logged in")
        return admin

    def owner_only(admin: dict = Depends(current_admin)) -> dict[str, Any]:
        """Owner-only actions (stock adjust, revenue, exports, team, settings), enforced server-side."""
        if admin.get("role") != "owner":
            raise HTTPException(403, "Réservé au propriétaire.")
        return admin

    def _audit(admin: dict, action: str, entity: str, entity_id: str = "", details: str = "") -> None:
        svc().store.audit(admin["name"], action, entity, entity_id, details)

    # shared with the routers of the next phases
    router.current_admin = current_admin  # type: ignore[attr-defined]
    router.owner_only = owner_only  # type: ignore[attr-defined]
    router.audit = _audit  # type: ignore[attr-defined]

    def _phone(raw: str) -> str:
        p = normalize_phone(raw)
        if not p:
            raise HTTPException(400, "bad phone")
        return p

    def _order_for(conv: Any, phone: str) -> dict[str, Any] | None:
        orders = svc().orders
        if conv.order_number:
            o = orders.get(conv.order_number)
            if o:
                return o
        return orders.find_open_by_phone(phone, ALL_STATUSES)

    def _order_view(o: dict[str, Any] | None) -> dict[str, Any] | None:
        if not o:
            return None
        try:
            qty = int(str(o.get("quantity") or 1))
        except ValueError:
            qty = 1
        return {
            "order_number": o["order_number"], "status": o.get("status", ""), "name": o.get("name", ""),
            "phone": o.get("phone", ""), "quantity": qty, "unit_price": UNIT_PRICE, "shipping": SHIPPING,
            "total": order_total(qty) if 1 <= qty <= MAX_QTY else o.get("total"), "city": o.get("city", ""),
            "address": o.get("address", ""), "created_at": o.get("created_at", ""),
        }

    def _window(conv: Any) -> dict[str, Any]:
        expires = (conv.last_client_at + WINDOW_S) if conv.last_client_at else None
        return {"window_open": bool(expires and expires > time.time()), "window_expires_at": expires}

    # -- auth ---------------------------------------------------------------------------------
    @router.post("/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
        if not settings.admin_secret:
            raise HTTPException(503, "admin disabled (ADMIN_SECRET not set)")
        store = svc().store
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
              or (request.client.host if request.client else "?"))
        if store.count(f"login:{ip}", 900) >= 10:
            raise HTTPException(429, "Trop de tentatives, réessayez dans 15 minutes.")
        admin = store.get_admin_by_email(body.email)
        ok = verify_password(body.password, admin["password_hash"] if admin else _DUMMY_HASH)
        if not (ok and admin):
            store.hit(f"login:{ip}")
            log.warning("admin login failed")
            raise HTTPException(401, "Email ou mot de passe incorrect.")
        response.set_cookie(COOKIE, make_session(settings.admin_secret, admin["id"], ttl), max_age=ttl, httponly=True,
                            secure=_secure(request), samesite="lax", path="/")
        store.touch_admin(admin["id"])
        log.info("admin login: %s", admin["name"])
        return {"name": admin["name"], "email": admin["email"]}

    @router.post("/logout")
    def logout(response: Response) -> dict[str, Any]:
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @router.get("/me")
    def me(admin: dict = Depends(current_admin)) -> dict[str, Any]:
        return {"name": admin["name"], "email": admin["email"], "role": admin["role"],
                "online": svc().store.admins_online()}

    @router.post("/me/password")
    def change_password(body: PasswordIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        if not verify_password(body.current, admin["password_hash"]):
            raise HTTPException(400, "Mot de passe actuel incorrect.")
        if body.new == body.current:
            raise HTTPException(400, "Le nouveau mot de passe doit être différent.")
        svc().store.set_admin_password(admin["id"], hash_password(body.new))
        _audit(admin, "password.change", "admin_user", admin["id"])
        return {"ok": True}

    # -- inbox --------------------------------------------------------------------------------
    @router.get("/conversations")
    def conversations(filter: str = "all", admin: dict = Depends(current_admin)) -> dict[str, Any]:
        if filter not in STATUS_FILTERS:
            raise HTTPException(400, "bad filter")
        items = []
        rows = svc().store.conversation_rows()
        # All the orders of the listed conversations in ONE query (no query per row).
        batch = getattr(svc().orders, "for_conversations", None)
        by_number: dict[str, dict[str, Any]] = {}
        by_phone: dict[str, dict[str, Any]] = {}
        if callable(batch):
            found = batch([r["conv"].phone for r in rows],
                          [r["conv"].order_number for r in rows if r["conv"].order_number])
            for o in found:  # newest first
                by_number.setdefault(o["order_number"].upper(), o)
                if o.get("status") in ALL_STATUSES:
                    by_phone.setdefault(o["phone"], o)
        for row in rows:
            conv = row["conv"]
            if callable(batch):
                order = (by_number.get((conv.order_number or "").upper()) if conv.order_number else None) \
                    or by_phone.get(conv.phone)
            else:
                order = _order_for(conv, conv.phone)
            status = order.get("status", "") if order else ""
            if filter != "all" and status != filter:
                continue
            items.append({
                "phone": conv.phone, "name": (order or {}).get("name", ""),
                "order_number": (order or {}).get("order_number"), "status": status,
                "last_message": row["last_text"], "last_role": row["last_role"], "last_at": row["last_at"],
                "unread": row["unread"], "taken_over_by": conv.taken_over_by,
            })
        return {"items": items, "online": svc().store.admins_online()}

    @router.get("/conversations/{phone}/messages")
    def thread(phone: str, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        p = _phone(phone)
        store = svc().store
        conv = store.get_conv(p)
        messages = store.thread(p)
        # Mark as read only when there is something new (robust to clock differences between servers).
        newest = max((m["at"] for m in messages), default=0)
        if newest > (conv.admin_read_at or 0):
            store.update_conv(p, admin_read_at=max(time.time(), newest))
        return {
            "conversation": {"phone": p, "taken_over_by": conv.taken_over_by, "internal_notes": conv.internal_notes or "",
                             "opted_out": router.crm().opted_out(p), **_window(conv)},  # type: ignore[attr-defined]
            "order": _order_view(_order_for(conv, p)),
            "messages": messages,
        }

    @router.post("/conversations/{phone}/send")
    def send(phone: str, body: SendIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        p = _phone(phone)
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "empty message")
        result = svc().bot.send_as_agent(p, text, admin["name"])
        if result == "window_closed":
            raise HTTPException(409, "La fenêtre de 24h est fermée : le client doit écrire en premier.")
        if result == "failed":
            raise HTTPException(502, "WhatsApp a refusé le message (token expiré ?).")
        log.info("agent %s replied", admin["name"])
        return {"ok": True, "taken_over_by": admin["name"]}

    @router.post("/conversations/{phone}/takeover")
    def takeover(phone: str, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        p = _phone(phone)
        svc().store.update_conv(p, taken_over_by=admin["name"])
        _audit(admin, "conversation.takeover", "conversation", p)
        return {"taken_over_by": admin["name"]}

    @router.post("/conversations/{phone}/release")
    def release(phone: str, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        p = _phone(phone)
        svc().store.update_conv(p, taken_over_by=None)
        _audit(admin, "conversation.release", "conversation", p)
        return {"taken_over_by": None}

    @router.post("/conversations/{phone}/notes")
    def notes(phone: str, body: NotesIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        p = _phone(phone)
        svc().store.update_conv(p, internal_notes=body.notes)
        _audit(admin, "conversation.note", "conversation", p, body.notes[:200])
        return {"ok": True}

    @router.post("/order/{order_number}/status")
    def set_status(order_number: str, body: StatusIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        if body.status not in SETTABLE_STATUSES:
            raise HTTPException(400, "statut invalide")
        o = svc().orders.get(order_number)
        if not o:
            raise HTTPException(404, "order not found")
        return apply_status(o, body.status, admin, return_reason=body.return_reason, force=body.force,
                            recoverable=body.recoverable)

    def _update_order(number: str, admin: dict, *, force: bool = False, recoverable: bool = True, **fields: Any) -> None:
        """orders.update with the stock rules (409 'Stock insuffisant : il reste N' unless force)."""
        orders = svc().orders
        extra = ({"stock_check": not force, "recoverable": recoverable, "stock_admin": admin["name"]}
                 if getattr(orders, "stock", None) is not None else {})
        try:
            orders.update(number, **fields, **extra)
        except InsufficientStock as e:
            raise HTTPException(409, str(e))

    router.update_order = _update_order  # type: ignore[attr-defined]

    _delivery: dict[str, Delivery] = {}

    def delivery() -> Delivery:
        s = svc()
        if "d" not in _delivery or _delivery["d"].store is not s.store:
            _delivery["d"] = Delivery(s.store)
        return _delivery["d"]

    router.delivery = delivery  # type: ignore[attr-defined]

    def apply_status(o: dict[str, Any], status: str, admin: dict, *, return_reason: str | None = None,
                     force: bool = False, recoverable: bool = True) -> dict[str, Any]:
        """The single admin path for a status change (Sheet mirror and stock follow through orders.update,
        cash-on-delivery fields from delivery.cod_fields)."""
        old_status = o.get("status", "")
        old = (o.get("notes") or "").strip()
        note = f"[{admin['name']}] statut → {status}"
        fields: dict[str, Any] = {"status": status, "notes": f"{old} | {note}" if old else note}
        try:
            fields.update(cod_fields(o, status, delivery().carrier(o.get("carrier_id")) if o.get("carrier_id") else None))
        except DeliveryError as e:
            raise HTTPException(409, str(e))
        if status == "delivered":
            fields["delivered_at"] = now_local()
        if status == "shipped":
            fields["shipped_at"] = now_local()
        if status == "returned":
            fields["returned_at"] = now_local()
        reason = (return_reason or "").strip()
        if status == "returned" and reason:
            fields["return_reason"] = reason
        _update_order(o["order_number"], admin, force=force, recoverable=recoverable, **fields)
        _audit(admin, "order.status", "order", o["order_number"],
               f"{old_status} → {status}" + (f" ({reason})" if status == "returned" and reason else "")
               + (" — produit non récupérable" if status == "returned" and not recoverable else "")
               + (" — forcé malgré le stock" if force else ""))
        return {"order_number": o["order_number"], "status": status}

    router.apply_status = apply_status  # type: ignore[attr-defined]

    MONEY_ONLY_OWNER = ("carrier_fee_cents", "cod_amount_cents", "remittance_id")

    def _full_order(o: dict[str, Any], admin: dict | None = None) -> dict[str, Any]:
        view = _order_view(o) or {}
        view.update({k: o.get(k, "") or "" for k in EXTRA_COLUMNS})
        view.update({"notes": o.get("notes", ""), "updated_at": o.get("updated_at", ""),
                     "whatsapp_from": o.get("whatsapp_from", "")})
        if not admin or admin.get("role") != "owner":  # COD amounts and carrier fees: owner only
            for k in MONEY_ONLY_OWNER:
                view.pop(k, None)
        return view

    @router.get("/orders/{order_number}")
    def get_order(order_number: str, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        o = svc().orders.get(order_number)
        if not o:
            raise HTTPException(404, "order not found")
        history = svc().store.audit_for("order", o["order_number"], 100)
        edits = [h for h in history if h["action"] in ("order.edit", "order.status")]
        stock = getattr(svc().orders, "stock", None)
        moves = stock.order_movements(o["order_number"]) if stock is not None else []
        if admin.get("role") != "owner":
            moves = [{k: v for k, v in m.items() if "cost" not in k} for m in moves]
        crm = router.crm()  # type: ignore[attr-defined]
        c = crm.get_customer(o["phone"]) if o.get("phone") else None
        thread = svc().store.thread(o["phone"])[-6:] if o.get("phone") else []
        return {"order": _full_order(o, admin), "history": history, "last_modified": edits[0] if edits else None,
                "stock_movements": moves, "thread": thread,
                "customer": {"orders_count": c["orders_count"], "returned": c["returned"], "cancelled": c["cancelled"],
                             "segment": c["segment"], "opted_out": c["opted_out"], "tags": c["tags"]} if c else None}

    @router.patch("/orders/{order_number}")
    def edit_order(order_number: str, body: OrderEditIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        orders = svc().orders
        o = orders.get(order_number)
        if not o:
            raise HTTPException(404, "order not found")
        changes: dict[str, Any] = {}
        for field in EDITABLE_FIELDS:
            value = getattr(body, field)
            if value is None:
                continue
            if field == "phone":
                value = normalize_phone(value)
                if not value:
                    raise HTTPException(422, "numéro de téléphone invalide")
            elif isinstance(value, str):
                value = value.strip() if field == "internal_note" else " ".join(value.split())
            if str(value) != str(o.get(field, "") or ""):
                changes[field] = value
        if body.carrier_id is not None and str(body.carrier_id or "") != str(o.get("carrier_id") or ""):
            if body.carrier_id:
                c = delivery().carrier(body.carrier_id)
                if not c:
                    raise HTTPException(422, "livreur introuvable")
                changes["carrier_id"], changes["carrier"] = str(c["id"]), c["name"]
            else:
                changes["carrier_id"], changes["carrier"] = "", ""
        if body.carrier_fee is not None:
            if admin.get("role") != "owner":
                raise HTTPException(403, "Réservé au propriétaire.")
            fee = str(round(body.carrier_fee * 100))
            if fee != str(o.get("carrier_fee_cents") or ""):
                changes["carrier_fee_cents"] = fee
        if o.get("cod_status") == "remitted" and ({"quantity", "carrier_id", "carrier_fee_cents"} & set(changes)):
            raise HTTPException(409, "Commande déjà encaissée auprès du livreur : quantité, livreur et frais sont verrouillés.")
        if "quantity" in changes:
            changes["total"] = order_total(changes["quantity"])
            if o.get("cod_status") == "with_carrier":
                changes["cod_amount_cents"] = str(changes["total"] * 100)
        if not changes:
            return {"order": _full_order(o, admin), "changed": []}
        _update_order(o["order_number"], admin, force=body.force, **changes)
        for field, value in changes.items():
            if field != "total":
                _audit(admin, "order.edit", "order", o["order_number"], f"{field}: {o.get(field, '') or ''} → {value}")
        return {"order": _full_order(orders.get(o["order_number"]), admin), "changed": [k for k in changes if k != "total"]}

    from .admin_stock import add_stock_routes

    add_stock_routes(router, svc, current_admin, owner_only, _audit)
    from .admin_purchasing import add_purchasing_routes

    add_purchasing_routes(router, svc, owner_only, _audit)
    from .admin_delivery import add_delivery_routes

    add_delivery_routes(router, svc, current_admin, owner_only, _audit, delivery, apply_status, _update_order)
    from .admin_finance import add_finance_routes

    add_finance_routes(router, svc, owner_only, _audit, delivery)
    from .admin_crm import add_crm_routes

    add_crm_routes(router, svc, current_admin, owner_only, _audit, delivery, apply_status, _update_order)
    from .admin_reports import add_reports_routes

    add_reports_routes(router, svc, current_admin, owner_only, _audit, delivery)
    return router
