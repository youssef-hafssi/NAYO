"""Conversation logic. The AI classifies and phrases; this module decides every status change and number.

Statuses (sheet): new → awaiting_details → confirmed | cancelled | needs_human
Stages (state DB): '' → 'details' (collecting city/address) → 'await_yes' (recap sent) ; 'verify_name'
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable

from .ai import AI, AIError, AIResult
from .phone import normalize_phone
from .pricing import MAX_QTY, SHIPPING, UNIT_PRICE, order_total
from .sheets import OPEN_STATUSES, OrdersRepo
from .store import Conversation, Store
from .texts import ESCALATE, detect_lang, first_name, normalize_name, t
from .whatsapp import IncomingMessage

log = logging.getLogger("nayo.flow")

ORDER_RE = re.compile(r"\bNAYO\s*-?\s*(W?\d{3,8})\b", re.IGNORECASE)
WINDOW_S = 24 * 3600
REPLY_LANGUAGE = {
    "fr": "French",
    "darija": "Moroccan Darija in Latin letters (Arabizi)",
    "ar": "Moroccan Darija in Arabic script",
    "en": "English",
}
MAX_FAILED = 2
ORDER_ACTIONS = {"confirm", "cancel", "provide_details", "change_quantity"}
ALERT_EVERY_S = 3600  # at most one owner alert per order per hour


class Bot:
    def __init__(
        self,
        orders: OrdersRepo,
        store: Store,
        wa: Any,  # WhatsAppClient-like: send_text(to, body) -> bool
        ai: AI,
        *,
        owner: str = "",
        max_replies_per_hour: int = 20,
        history_size: int = 20,
        clock: Callable[[], float] = time.time,
    ):
        self.orders, self.store, self.wa, self.ai = orders, store, wa, ai
        self.owner = normalize_phone(owner) or ""
        self.max_replies = max_replies_per_hour
        self.history_size = history_size
        self.clock = clock

    # ------------------------------------------------------------------ entry point
    def handle(self, msg: IncomingMessage) -> None:
        try:
            self._handle(msg)
        except Exception:
            log.exception("unhandled error while processing message %s", msg.id)

    def _handle(self, msg: IncomingMessage) -> None:
        now = self.clock()
        if not self.store.mark_processed(msg.id, now):
            log.info("duplicate message %s ignored", msg.id)
            return
        phone = normalize_phone(msg.sender) or msg.sender
        text = (msg.text or "").strip()[:1500]
        self.store.touch_client(phone, now)
        self.store.add_message(phone, "client", text or f"[{msg.type}]", keep=self.history_size, now=now)
        log.info("message %s from %s type=%s len=%d", msg.id, _mask(phone), msg.type, len(text))

        if self.owner and phone == self.owner:
            log.info("owner message received — owner alerts can be delivered for the next 24h")
            return

        conv = self.store.get_conv(phone)
        lang = detect_lang(text, conv.lang) if text else (conv.lang or "fr")
        if lang != conv.lang:
            self.store.update_conv(phone, lang=lang)

        if self.store.count(f"reply:{phone}", 3600, now) >= self.max_replies:
            log.warning("rate limit reached for %s — no reply", _mask(phone))
            return

        if not text:
            self._send(phone, t("non_text", lang))
            return

        self._route(phone, text, conv, lang)

    # ------------------------------------------------------------------ order matching
    def _route(self, phone: str, text: str, conv: Conversation, lang: str) -> None:
        order: dict | None = None
        m = ORDER_RE.search(text)
        if m:
            number = self.store.resolve_alias(f"NAYO-{m.group(1).upper()}")
            found = self.orders.get(number)
            if found:
                number = found["order_number"]
                if found["phone"] != phone and conv.verified_order != number:
                    # Order numbers are guessable: a third-party sender must prove they know the name.
                    self.orders.update(number, whatsapp_from=phone)
                    self.store.update_conv(phone, order_number=number, stage="verify_name", failed_attempts=0)
                    self._send(phone, t("ask_name", lang))
                    return
                order = found

        if order is None and conv.stage == "verify_name" and conv.order_number:
            self._verify_name(phone, text, conv, lang)
            return

        if order is None and conv.order_number:
            bound = self.orders.get(conv.order_number)
            if bound and (bound["phone"] == phone or conv.verified_order == bound["order_number"]):
                order = bound

        if order is None:
            order = self.orders.find_open_by_phone(phone)

        if order is None:
            # An order waiting for a human is still this client's order: the bot keeps handling the order itself.
            order = self.orders.find_open_by_phone(phone, ("needs_human",))
        if order is None:
            # e.g. "imta twsel?" days later about an order that is already confirmed.
            order = self.orders.find_open_by_phone(phone, ("confirmed",))
        if order is None:
            # A client who cancelled and comes back ("bghit ncommandi") can reactivate their order.
            order = self.orders.find_open_by_phone(phone, ("cancelled",))

        if order is None:
            self._send(phone, t("ask_order_number", lang))
            return

        number = order["order_number"]
        if order.get("whatsapp_from") != phone:
            self.orders.update(number, whatsapp_from=phone)
            order["whatsapp_from"] = phone
        if conv.order_number != number:
            self.store.update_conv(phone, order_number=number, stage="", failed_attempts=0)
            conv.order_number, conv.stage, conv.failed_attempts = number, "", 0

        self._converse(phone, text, order, conv, lang)

    def _verify_name(self, phone: str, text: str, conv: Conversation, lang: str) -> None:
        order = self.orders.get(conv.order_number or "")
        if not order:
            self.store.update_conv(phone, stage="", order_number=None)
            self._send(phone, t("ask_order_number", lang))
            return
        if normalize_name(text) and normalize_name(text) == normalize_name(order["name"]):
            number = order["order_number"]
            self.store.update_conv(phone, verified_order=number, stage="", failed_attempts=0)
            conv.verified_order, conv.stage, conv.failed_attempts = number, "", 0
            log.info("name verified for %s on %s", _mask(phone), number)
            if order["status"] in OPEN_STATUSES:
                self._advance(phone, order, conv, lang, prefix=[], greet=order["status"] == "new")
            else:
                self._converse(phone, text, order, conv, lang)
            return
        self.store.update_conv(phone, stage="")
        self._escalate(phone, order, text, "numéro de commande envoyé par un autre téléphone, nom incorrect")

    # ------------------------------------------------------------------ main conversation
    def _converse(self, phone: str, text: str, order: dict, conv: Conversation, lang: str) -> None:
        status = order["status"]
        qty = _int(order.get("quantity"), 1)
        context = {
            "order_number": order["order_number"],
            "customer_first_name": first_name(order["name"]),
            "quantity": qty,
            "unit_price_mad": UNIT_PRICE,
            "shipping_mad": SHIPPING,
            "total_mad": order_total(qty) if 1 <= qty <= MAX_QTY else "ask team",
            "status": status,
            "city_known": bool(order.get("city")),
            "address_known": bool(order.get("address")),
            "waiting_for_yes_to_recap": conv.stage == "await_yes",
            "reply_language": REPLY_LANGUAGE[lang],
        }
        history = self.store.recent_messages(phone, self.history_size)[:-1]  # last one is passed separately
        try:
            r = self.ai.run(context, history, text)
        except AIError as e:
            log.error("AI unavailable for %s: %s", order["order_number"], str(e)[:200])
            self._escalate(phone, order, text, "IA indisponible")
            return
        log.info("AI %s intent=%s needs_human=%s", order["order_number"], r.intent, r.needs_human)

        action = r.intent in ORDER_ACTIONS
        if r.intent == "complaint" or (r.needs_human and not action):
            self._escalate(phone, order, text, f"intent={r.intent}")
            return
        if r.needs_human and action:
            # e.g. "je confirme, et ça arrive quand ?": the bot handles the order, a human answers the rest.
            self._notify_human(phone, order, text, f"question en plus ({r.intent})")

        if status == "needs_human":
            if not action:
                # Waiting for the team on something else: the bot still answers what it can.
                self._send(phone, r.reply)
                return
            # The client is acting on the order itself (confirm / details / quantity / cancel): the bot takes it back.
            notes = (order.get("notes") or "").strip()
            note = "[bot] reprise de la commande par le bot"
            self.orders.update(order["order_number"], status="awaiting_details", notes=f"{notes} | {note}" if notes else note)
            order["status"] = status = "awaiting_details"
            log.info("%s taken back by the bot (intent=%s)", order["order_number"], r.intent)

        if status == "confirmed" and action and r.intent != "confirm":
            # Change after confirmation (quantity / address / cancel): allowed, the order needs a new "yes",
            # and the owner is told — it may already be in preparation.
            self._notify_human(phone, order, text, f"modification après confirmation ({r.intent})", always=True)
            self.orders.update(order["order_number"], status="awaiting_details")
            order["status"] = status = "awaiting_details"
            self.store.update_conv(phone, stage="await_yes")
            conv.stage = "await_yes"
        elif status == "cancelled" and action and r.intent != "cancel":
            # The client changed their mind after cancelling: reactivate, show the recap, ask for a new "yes".
            self._notify_human(phone, order, text, f"réactivation après annulation ({r.intent})", always=True)
            self.orders.update(order["order_number"], status="awaiting_details")
            order["status"] = status = "awaiting_details"
            self.store.update_conv(phone, stage="")  # a plain "wakha" must lead to the recap, not straight to confirmed
            conv.stage = ""
            if r.intent == "confirm":
                self._advance(phone, order, conv, lang, prefix=[], greet=False)
                return

        if status not in OPEN_STATUSES:  # confirmed (question / thanks) / cancelled
            if r.intent in ("question", "other") or (status == "confirmed" and r.intent == "confirm"):
                self._send(phone, r.reply)
            else:
                self._escalate(phone, order, text, f"{r.intent} sur une commande {status}")
            return

        if r.intent == "other" and status == "new" and not (r.city or r.address):
            # First contact that isn't the pre-filled message ("salam", "allo", "bonjour"…):
            # welcome + ask for the details. Not a misunderstanding, so it doesn't count as a failed attempt.
            self._advance(phone, order, conv, lang, prefix=[], greet=True)
            return
        if r.intent == "other":
            failed = conv.failed_attempts + 1
            self.store.update_conv(phone, failed_attempts=failed)
            if failed >= MAX_FAILED:
                self._escalate(phone, order, text, "le bot ne comprend pas (2 tentatives)")
            else:
                self._send(phone, r.reply)
            return
        if conv.failed_attempts:
            self.store.update_conv(phone, failed_attempts=0)
            conv.failed_attempts = 0

        if r.intent == "cancel":
            self.orders.update(order["order_number"], status="cancelled")
            self.store.update_conv(phone, stage="")
            self._send(phone, t("cancelled", lang, number=order["order_number"]))
            return

        prefix: list[str] = []
        changed = False
        if r.intent == "change_quantity":
            if r.quantity is None:
                self._send(phone, r.reply)
                return
            if not 1 <= r.quantity <= MAX_QTY:
                self._escalate(phone, order, text, f"quantité demandée: {r.quantity}")
                return
            if r.quantity != qty:
                total = order_total(r.quantity)
                self.orders.update(order["order_number"], quantity=r.quantity, total=total)
                order["quantity"], order["total"] = r.quantity, total
                changed = True
            prefix.append(t("quantity_updated", lang, qty=r.quantity, total=order_total(r.quantity)))

        updates = {}
        if r.city and normalize_name(r.city) != normalize_name(order.get("city", "")):
            updates["city"] = r.city
        if r.address and normalize_name(r.address) != normalize_name(order.get("address", "")):
            updates["address"] = r.address
        if updates:
            self.orders.update(order["order_number"], **updates)
            order.update(updates)
            changed = True

        if r.intent == "question" and not updates:
            self._send(phone, r.reply)
            return

        if r.intent == "confirm" and conv.stage == "await_yes" and not changed and order.get("city") and order.get("address"):
            self.orders.update(order["order_number"], status="confirmed")
            self.store.update_conv(phone, stage="")
            q = _int(order.get("quantity"), 1)
            self._send(phone, t("confirmed", lang, first=first_name(order["name"]), total=order_total(q)))
            return

        self._advance(phone, order, conv, lang, prefix=prefix, greet=status == "new" and not updates and not prefix)

    def _advance(self, phone: str, order: dict, conv: Conversation, lang: str, *, prefix: list[str], greet: bool) -> None:
        """Move the order forward: ask what's missing, or send the recap once city + address are known."""
        number = order["order_number"]
        city, address = order.get("city", ""), order.get("address", "")
        q = _int(order.get("quantity"), 1)
        if order["status"] in ("new", "needs_human"):
            self.orders.update(number, status="awaiting_details")
            order["status"] = "awaiting_details"

        if city and address:
            recap = t(
                "recap",
                lang,
                name=order["name"],
                city=city,
                address=address,
                qty_part=t("qty_part", lang, qty=q) if q > 1 else "",
                total=order_total(q),
            )
            self.store.update_conv(phone, stage="await_yes")
            self._send(phone, "\n".join(prefix + [recap]))
            return

        self.store.update_conv(phone, stage="details")
        if greet:
            ask = t("greet_ask_details", lang, first=first_name(order["name"]))
        elif city:
            ask = t("ask_address", lang, city=city)
        elif address:
            ask = t("ask_city", lang)
        else:
            ask = t("ask_details", lang)
        self._send(phone, "\n".join(prefix + [ask]))

    # ------------------------------------------------------------------ helpers
    def _escalate(self, phone: str, order: dict | None, text: str, reason: str) -> None:
        """Order status → needs_human, holding reply to the client, alert to the owner (throttled)."""
        number = order["order_number"] if order else "?"
        if order:
            notes = (order.get("notes") or "").strip()
            note = f"[bot] {reason} : « {text[:120]} »"
            new_notes = f"{notes} | {note}" if notes else note
            if order["status"] in ("confirmed", "cancelled"):
                # A question never undoes a confirmation (or a cancellation): keep the status, note it, alert.
                self.orders.update(number, notes=new_notes)
            else:
                self.orders.update(number, status="needs_human", notes=new_notes)
                order["status"] = "needs_human"
            order["notes"] = new_notes
        log.warning("needs_human %s from %s: %s", number, _mask(phone), reason)
        self._send(phone, ESCALATE)
        self._throttled_alert(phone, number, text, reason)

    def _notify_human(self, phone: str, order: dict, text: str, reason: str, always: bool = False) -> None:
        """A question the bot can't answer, while the bot keeps handling the order: note + alert, no status change."""
        number = order["order_number"]
        notes = (order.get("notes") or "").strip()
        note = f"[bot] {reason} : « {text[:120]} »"
        self.orders.update(number, notes=f"{notes} | {note}" if notes else note)
        order["notes"] = f"{notes} | {note}" if notes else note
        self._throttled_alert(phone, number, text, reason, always=always)

    def _throttled_alert(self, phone: str, number: str, text: str, reason: str, always: bool = False) -> None:
        """At most one alert per order per hour — except changes to a confirmed order, which always alert."""
        key = f"alert:{number}"
        if not always and self.store.count(key, ALERT_EVERY_S, self.clock()) > 0:
            log.info("owner already alerted for %s in the last hour — not alerting again", number)
            return
        self.store.hit(key, self.clock())
        self._alert_owner(f"⚠️ {number} — client +{phone}\nRaison : {reason}\nDernier message : « {text[:300]} »")

    def _alert_owner(self, body: str) -> None:
        if not self.owner:
            log.warning("OWNER_WHATSAPP not set — alert not sent")
            return
        owner_conv = self.store.get_conv(self.owner)
        if not owner_conv.last_client_at or self.clock() - owner_conv.last_client_at > WINDOW_S:
            log.warning("owner hasn't messaged the bot in the last 24h — the alert will probably not be delivered")
        if not self.wa.send_text(self.owner, body):
            log.warning("owner alert NOT delivered (send a message to the bot number from OWNER_WHATSAPP to open the 24h window)")

    def _send(self, phone: str, body: str) -> bool:
        conv = self.store.get_conv(phone)
        now = self.clock()
        if not conv.last_client_at or now - conv.last_client_at > WINDOW_S:
            log.warning("outside the 24h window for %s — not sending (templates are never used)", _mask(phone))
            return False
        self.store.hit(f"reply:{phone}", now)
        self.store.add_message(phone, "bot", body, keep=self.history_size, now=now + 0.000001)
        return self.wa.send_text(phone, body)


def _int(v: Any, default: int) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _mask(phone: str) -> str:
    return phone[:5] + "…" + phone[-2:] if len(phone) > 7 else "…"
