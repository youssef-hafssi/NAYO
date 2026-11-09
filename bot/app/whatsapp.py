"""Official WhatsApp Cloud API (Meta). Free-form text replies only — this bot never sends templates."""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger("nayo.whatsapp")


def verify_signature(raw_body: bytes, header: str | None, app_secret: str) -> bool:
    """X-Hub-Signature-256: 'sha256=' + HMAC-SHA256(app secret, raw request body)."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@dataclass
class IncomingMessage:
    id: str
    sender: str  # WhatsApp 'from' (digits, international)
    type: str
    text: str
    profile_name: str = ""


def extract_messages(payload: dict[str, Any]) -> list[IncomingMessage]:
    """Pull client messages out of a webhook payload. Status callbacks (sent/delivered/read) are ignored."""
    out: list[IncomingMessage] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            names = {c.get("wa_id"): (c.get("profile", {}) or {}).get("name", "") for c in value.get("contacts", []) or []}
            for m in value.get("messages", []) or []:
                mtype = m.get("type", "")
                text = ""
                if mtype == "text":
                    text = (m.get("text") or {}).get("body", "")
                elif mtype == "button":
                    text = (m.get("button") or {}).get("text", "")
                elif mtype == "interactive":
                    inter = m.get("interactive") or {}
                    text = (inter.get("button_reply") or inter.get("list_reply") or {}).get("title", "")
                if m.get("id") and m.get("from"):
                    out.append(IncomingMessage(m["id"], m["from"], mtype, text or "", names.get(m["from"], "")))
    return out


class WhatsAppClient:
    def __init__(self, token: str, phone_number_id: str, api_version: str, http: httpx.Client | None = None):
        self._token = token
        self._url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        self._http = http or httpx.Client(timeout=15)

    def send_text(self, to: str, body: str) -> bool:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body[:4096]},
        }
        try:
            r = self._http.post(self._url, json=payload, headers={"Authorization": f"Bearer {self._token}"})
        except httpx.HTTPError as e:
            log.error("send to %s failed: %s", _mask(to), type(e).__name__)
            return False
        if r.status_code >= 400:
            err = {}
            try:
                err = r.json().get("error", {})
            except ValueError:
                pass
            log.error("send to %s rejected: HTTP %s code=%s %s", _mask(to), r.status_code, err.get("code"), err.get("message", "")[:200])
            return False
        log.info("sent to %s (%d chars)", _mask(to), len(body))
        return True


def _mask(phone: str) -> str:
    return phone[:5] + "…" + phone[-2:] if len(phone) > 7 else "…"
