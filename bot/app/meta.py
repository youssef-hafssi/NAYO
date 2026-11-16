"""Meta Conversions API (server side of the Pixel).

The website fires the browser Pixel event and sends the same event_id with the order; this module sends the server
event, so Meta counts it once (deduplication on event_name + event_id). Customer data is normalized then SHA-256
hashed before it leaves the bot (never sent in clear). The access token travels in the request body, never in a URL,
and is never logged. A failure here never blocks an order: it is logged (without personal data) and ignored.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from typing import Any, Callable

log = logging.getLogger("nayo.meta")

CURRENCY = "MAD"
CONTENT_ID = "nayo-deodorant"
TIMEOUT_S = 3.0  # inline on serverless: keep it short


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


def purchase_event(*, event_id: str, value: int, quantity: int, order_number: str, source_url: str,
                   ud: dict[str, Any], at: float | None = None) -> dict[str, Any]:
    return {
        "event_name": "Purchase",
        "event_time": int(at or time.time()),
        "event_id": event_id,
        "action_source": "website",
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
