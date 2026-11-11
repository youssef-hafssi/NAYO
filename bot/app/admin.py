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

log = logging.getLogger("nayo.admin")

COOKIE = "nayo_admin"
STATUS_FILTERS = {"all", "needs_human", "confirmed", "cancelled"}
SETTABLE_STATUSES = {"confirmed", "cancelled", "needs_human"}
ALL_STATUSES = ("new", "awaiting_details", "confirmed", "cancelled", "needs_human")


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
    status: str


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
        admin = svc().store.get_admin(admin_id) if admin_id else None
        if not admin:
            raise HTTPException(401, "not logged in")
        svc().store.touch_admin(admin["id"])
        return admin

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
        return {"name": admin["name"], "email": admin["email"], "online": svc().store.admins_online()}

    # -- inbox --------------------------------------------------------------------------------
    @router.get("/conversations")
    def conversations(filter: str = "all", admin: dict = Depends(current_admin)) -> dict[str, Any]:
        if filter not in STATUS_FILTERS:
            raise HTTPException(400, "bad filter")
        items = []
        for row in svc().store.conversation_rows():
            conv = row["conv"]
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
        # Read up to the newest message shown (robust to clock differences between servers).
        store.update_conv(p, admin_read_at=max([time.time()] + [m["at"] for m in messages]))
        return {
            "conversation": {"phone": p, "taken_over_by": conv.taken_over_by, "internal_notes": conv.internal_notes or "",
                             **_window(conv)},
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
        svc().store.update_conv(_phone(phone), taken_over_by=admin["name"])
        return {"taken_over_by": admin["name"]}

    @router.post("/conversations/{phone}/release")
    def release(phone: str, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        svc().store.update_conv(_phone(phone), taken_over_by=None)
        return {"taken_over_by": None}

    @router.post("/conversations/{phone}/notes")
    def notes(phone: str, body: NotesIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        svc().store.update_conv(_phone(phone), internal_notes=body.notes)
        return {"ok": True}

    @router.post("/order/{order_number}/status")
    def set_status(order_number: str, body: StatusIn, admin: dict = Depends(current_admin)) -> dict[str, Any]:
        if body.status not in SETTABLE_STATUSES:
            raise HTTPException(400, "status must be confirmed, cancelled or needs_human")
        orders = svc().orders
        o = orders.get(order_number)
        if not o:
            raise HTTPException(404, "order not found")
        old = (o.get("notes") or "").strip()
        note = f"[{admin['name']}] statut → {body.status}"
        orders.update(o["order_number"], status=body.status, notes=f"{old} | {note}" if old else note)
        return {"order_number": o["order_number"], "status": body.status}

    return router
