"""Meta Conversions API (server side of the Pixel), for cash on delivery.

Events, each sent at most once per order:
- Lead            at order placement — browser Pixel + server, same event_id (the order number) → counted once.
- Purchase        server only, when the order becomes confirmed (value = total, MAD).
- OrderDelivered  server only, when it is delivered.
- OrderReturned   server only, when it is returned.
An event whose moment (confirmed / delivered / returned time) is more than 7 days old is never sent (Meta's limit,
and a back-dated status must not create a fresh conversion).

Customer data is normalized then SHA-256 hashed before it leaves the bot. The access token travels in the request
body, never in a URL, and is never logged. A failure never blocks an order or a status change.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from datetime import datetime
from typing import Any, Callable

log = logging.getLogger("nayo.meta")

CURRENCY = "MAD"
CONTENT_ID = "nayo-deodorant"
TIMEOUT_S = 3.0  # inline on serverless: keep it short
MAX_AGE_S = 7 * 24 * 3600
STATUS_EVENTS = {"confirmed": "Purchase", "delivered": "OrderDelivered", "returned": "OrderReturned"}
STATUS_TIME_FIELD = {"confirmed": "confirmed_at", "delivered": "delivered_at", "returned": "returned_at"}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _plain(s: str) -> str:
    """Lowercase, no accents, no spaces or punctuation (Meta's normalization for names and cities)."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9؀-ۿ]", "", s.casefold())


def user_data(*, phone: str = "", name: str = "", city: str = "", ip: str = "", user_agent: str = "",
              fbp: str = "", fbc: str = "", external_id: str = "") -> dict[str, Any]:
    """Meta "user_data": hashed identifiers + the browser's technical data (IP, user agent, cookies: not hashed)."""
    ud: dict[str, Any] = {"country": [_sha("ma")]}
    digits = re.sub(r"\D", "", phone or "")
    if digits:
        ud["ph"] = [_sha(digits)]  # already international (2126…): country code included, no "+"
    parts = [p for p in (name or "").split() if p]
    if parts:
        ud["fn"] = [_sha(_plain(parts[0]))]
        if len(parts) > 1:
            ud["ln"] = [_sha(_plain(parts[-1]))]
    if _plain(city):
        ud["ct"] = [_sha(_plain(city))]
    if external_id:
        ud["external_id"] = [_sha(external_id)]
    if ip:
        ud["client_ip_address"] = ip
    if user_agent:
        ud["client_user_agent"] = user_agent[:500]
    if fbp:
        ud["fbp"] = fbp
    if fbc:
        ud["fbc"] = fbc
    return ud


def order_event(name: str, *, order_number: str, value: int, quantity: int, ud: dict[str, Any],
                action_source: str = "system_generated", source_url: str = "", at: float | None = None) -> dict[str, Any]:
    """One event about an order. event_id = the order number (the browser Lead uses the same one)."""
    return {
        "event_name": name,
        "event_time": int(at or time.time()),
        "event_id": order_number,
        "action_source": action_source,
        "event_source_url": source_url or None,
        "user_data": ud,
        "custom_data": {
            "currency": CURRENCY,
            "value": value,
            "content_type": "product",
            "content_ids": [CONTENT_ID],
            "contents": [{"id": CONTENT_ID, "quantity": quantity}],
            "num_items": quantity,
            "order_id": order_number,
        },
    }


class MetaCapi:
    def __init__(self, pixel_id: str, token: str, graph_version: str, test_event_code: str = "",
                 post: Callable[..., Any] | None = None):
        self.pixel_id, self.token, self.version, self.test_code = pixel_id.strip(), token.strip(), graph_version, test_event_code.strip()
        self._post = post

    @property
    def enabled(self) -> bool:
        return bool(self.pixel_id and self.token)

    def send(self, events: list[dict[str, Any]]) -> bool:
        if not self.enabled or not events:
            return False
        body: dict[str, Any] = {"data": [{k: v for k, v in e.items() if v is not None} for e in events],
                                "access_token": self.token}
        if self.test_code:
            body["test_event_code"] = self.test_code  # shows in Events Manager → "Événements de test"
        url = f"https://graph.facebook.com/{self.version}/{self.pixel_id}/events"
        try:
            post = self._post
            if post is None:
                import httpx

                post = httpx.Client(timeout=TIMEOUT_S).post
            r = post(url, json=body)
            ok = getattr(r, "status_code", 200) < 400
            if not ok:
                # Never log the body we sent (token, hashes); Meta's error message is safe and useful.
                log.warning("Meta CAPI refused %s: HTTP %s %s", events[0].get("event_name"), getattr(r, "status_code", "?"),
                            str(getattr(r, "text", ""))[:200])
            return ok
        except Exception as e:
            log.warning("Meta CAPI unreachable for %s: %s", events[0].get("event_name"), type(e).__name__)
            return False


def _ts(local: str) -> float | None:
    """'YYYY-MM-DD HH:MM:SS' (Casablanca) → epoch seconds."""
    from .sheets import TZ

    try:
        return datetime.strptime(local[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ).timestamp()
    except (TypeError, ValueError):
        return None


class MetaTracker:
    """Once-per-order bookkeeping (meta_events) + the browser data kept from the Lead (meta_orders: _fbp / _fbc),
    so later server events still match the same person."""

    SCHEMA_VERSION = 1

    def __init__(self, store: Any, capi: MetaCapi, clock: Callable[[], float] = time.time):
        self.store, self.capi, self.clock = store, capi, clock
        if store.needs_schema("meta", self.SCHEMA_VERSION):
            for ddl in (
                "CREATE TABLE IF NOT EXISTS meta_orders (order_number TEXT PRIMARY KEY, fbp TEXT NOT NULL DEFAULT '', "
                "fbc TEXT NOT NULL DEFAULT '', created_at DOUBLE PRECISION NOT NULL)",
                "CREATE TABLE IF NOT EXISTS meta_events (order_number TEXT NOT NULL, event_name TEXT NOT NULL, "
                "sent_at DOUBLE PRECISION NOT NULL, ok INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (order_number, event_name))",
            ):
                store._exec(ddl)
            if store.backend == "postgres":
                for t in ("meta_orders", "meta_events"):
                    store._exec(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
            store.schema_done("meta", self.SCHEMA_VERSION)

    @property
    def enabled(self) -> bool:
        return self.capi.enabled

    def _claim(self, order_number: str, event: str) -> bool:
        """True only the first time (the primary key decides, even with concurrent requests)."""
        row = self.store._exec(
            "INSERT INTO meta_events (order_number, event_name, sent_at) VALUES (?, ?, ?) "
            "ON CONFLICT (order_number, event_name) DO NOTHING RETURNING order_number",
            (order_number, event, self.clock()), fetch="one")
        return bool(row)

    def _send(self, order_number: str, event: dict[str, Any]) -> bool:
        ok = self.capi.send([event])
        if ok:
            self.store._exec("UPDATE meta_events SET ok = 1 WHERE order_number = ? AND event_name = ?",
                             (order_number, event["event_name"]))
        return ok

    # ------------------------------------------------------------------ Lead (order placed on the website)
    def lead(self, *, order_number: str, total: int, quantity: int, phone: str, name: str, city: str, ip: str,
             user_agent: str, fbp: str, fbc: str, source_url: str) -> bool:
        if not self.enabled or not self._claim(order_number, "Lead"):
            return False
        self.store._exec("INSERT INTO meta_orders (order_number, fbp, fbc, created_at) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT (order_number) DO NOTHING", (order_number, fbp, fbc, self.clock()))
        ud = user_data(phone=phone, name=name, city=city, ip=ip, user_agent=user_agent, fbp=fbp, fbc=fbc,
                       external_id=phone)
        return self._send(order_number, order_event("Lead", order_number=order_number, value=total, quantity=quantity,
                                                    ud=ud, action_source="website", source_url=source_url))

    # ------------------------------------------------------------------ Purchase / OrderDelivered / OrderReturned
    def status_changed(self, order: dict[str, Any], status: str) -> bool:
        name = STATUS_EVENTS.get(status)
        if not name or not self.enabled:
            return False
        number = order.get("order_number", "")
        at = _ts(str(order.get(STATUS_TIME_FIELD[status]) or "")) or self.clock()
        if self.clock() - at > MAX_AGE_S:
            log.info("%s not sent for %s: older than 7 days", name, number)
            return False
        if not self._claim(number, name):
            return False
        kept = self.store._exec("SELECT fbp, fbc FROM meta_orders WHERE order_number = ?", (number,), fetch="one")
        try:
            qty = int(str(order.get("quantity") or 1))
            total = int(str(order.get("total") or 0))
        except ValueError:
            qty, total = 1, 0
        ud = user_data(phone=order.get("phone", ""), name=order.get("name", ""), city=order.get("city", ""),
                       fbp=kept[0] if kept else "", fbc=kept[1] if kept else "", external_id=order.get("phone", ""))
        return self._send(number, order_event(name, order_number=number, value=total, quantity=qty, ud=ud, at=at))


class TrackedOrders:
    """Outermost orders wrapper: every status change (WhatsApp bot, admin, bulk) that reaches confirmed / delivered /
    returned sends its Meta event once. Never lets Meta break the status change itself."""

    def __init__(self, inner: Any, tracker: MetaTracker):
        self.inner, self.meta = inner, tracker

    def update(self, order_number: str, **fields: Any) -> None:
        status = fields.get("status")
        before = self.inner.get(order_number) if status in STATUS_EVENTS and self.meta.enabled else None
        self.inner.update(order_number, **fields)
        if before is not None and before.get("status") != status:
            try:
                after = self.inner.get(order_number) or {**before, **fields}
                self.meta.status_changed(after, status)
            except Exception as e:  # tracking must never break an order flow
                log.warning("Meta event after %s on %s failed: %s", status, order_number, type(e).__name__)

    def append(self, order: dict[str, Any]) -> None:
        self.inner.append(order)

    def get(self, order_number: str) -> dict[str, Any] | None:
        return self.inner.get(order_number)

    def find_open_by_phone(self, phone: str, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return self.inner.find_open_by_phone(phone, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:  # stock, for_conversations, units_in… of the inner stores
        return getattr(self.inner, name)
