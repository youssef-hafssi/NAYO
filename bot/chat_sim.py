"""Chat with the bot in your terminal — no Meta, no Google Sheets needed (only GEMINI_API_KEY in .env).

You play the client; the REAL conversation logic + REAL Gemini answer, exactly as on WhatsApp.
The Google Sheet is replaced by an in-memory table (/sheet shows it) and the state by a local
sim-state.db file, so your Supabase database and real order numbers are never touched.

    .venv\\Scripts\\python chat_sim.py

Commands:
    /sheet            show the orders table (what you'd see in Google Sheets)
    /new              place another order on the "website"
    /as 0699999999    write from another phone (to test the stranger-with-an-order-number check)
    /me               back to the client's own phone
    /audio            send a voice note (non-text message)
    /reset            start over (new orders, empty memory)
    /quit
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any

from app.ai import GeminiAI
from app.config import get_settings
from app.flow import Bot
from app.phone import normalize_phone
from app.pricing import order_total
from app.sheets import HEADERS, now_local
from app.store import Store
from app.whatsapp import IncomingMessage

DB = "sim-state.db"
GREY, BOLD, GREEN, RED, CYAN, RESET = "\033[90m", "\033[1m", "\033[32m", "\033[31m", "\033[36m", "\033[0m"


class MemorySheet:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def append(self, order: dict[str, Any]) -> None:
        row = {h: "" for h in HEADERS}
        row.update({k: str(v) for k, v in order.items()})
        self.rows.append(row)

    def get(self, number: str) -> dict[str, Any] | None:
        r = next((r for r in self.rows if r["order_number"].upper() == number.upper()), None)
        return dict(r) if r else None

    def find_open_by_phone(self, phone: str, statuses=("new", "awaiting_details")) -> dict[str, Any] | None:
        for r in reversed(self.rows):
            if r["phone"] == phone and r["status"] in statuses:
                return dict(r)
        return None

    def update(self, number: str, **fields: Any) -> None:
        r = next(r for r in self.rows if r["order_number"].upper() == number.upper())
        changes = {k: str(v) for k, v in fields.items() if str(v) != r.get(k)}
        r.update({k: str(v) for k, v in fields.items()})
        r["updated_at"] = now_local()
        shown = {k: v for k, v in changes.items() if k not in ("updated_at",)}
        if shown:
            print(f"{GREY}   📄 sheet {number}: " + ", ".join(f"{k} → {v}" for k, v in shown.items()) + RESET)

    def show(self) -> None:
        if not self.rows:
            print(f"{GREY}   (no orders){RESET}")
            return
        cols = ["order_number", "name", "phone", "quantity", "total", "status", "city", "address", "whatsapp_from", "notes"]
        for r in self.rows:
            print(f"{CYAN}   " + " | ".join(f"{c}={r.get(c, '')}" for c in cols if r.get(c, "") != "") + RESET)


class TerminalWhatsApp:
    def __init__(self, owner: str) -> None:
        self.owner = owner

    def send_text(self, to: str, body: str) -> bool:
        if to == self.owner:
            print(f"{RED}   🔔 alert to you (OWNER_WHATSAPP):{RESET}\n{RED}" + _indent(body) + RESET)
        else:
            print(f"{GREEN}{BOLD}NAYO ▸ {RESET}{GREEN}{_indent(body).lstrip()}{RESET}")
        return True


class TracingAI:
    def __init__(self, inner: GeminiAI) -> None:
        self.inner = inner

    def run(self, context, history, last_message):
        t0 = time.perf_counter()
        try:
            r = self.inner.run(context, history, last_message)
        except Exception as e:
            print(f"{GREY}   🤖 AI failed after {time.perf_counter() - t0:.1f}s: {type(e).__name__}{RESET}")
            raise
        extra = ", ".join(f"{k}={v!r}" for k, v in (("city", r.city), ("address", r.address), ("quantity", r.quantity)) if v is not None)
        print(f"{GREY}   🤖 {time.perf_counter() - t0:.1f}s intent={r.intent} needs_human={r.needs_human} {extra}{RESET}")
        return r


def _indent(text: str) -> str:
    return "\n".join("        " + line for line in text.splitlines())


def main() -> int:
    for stream in (sys.stdout, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    os.system("")  # enables colours in the Windows console
    logging.basicConfig(level=logging.ERROR)

    s = get_settings()
    if not s.gemini_api_key:
        print("GEMINI_API_KEY missing in bot/.env")
        return 1
    owner = normalize_phone(s.owner_whatsapp) or "212600000000"
    ai = TracingAI(GeminiAI(s.gemini_api_key, s.gemini_model, fallback_model=s.gemini_fallback_model,
                            timeout_s=s.gemini_timeout_s, thinking_budget=s.gemini_thinking_budget))

    def fresh() -> tuple[MemorySheet, Store, Bot]:
        if os.path.exists(DB):
            os.remove(DB)
        logging.getLogger("nayo.store").setLevel(logging.ERROR)
        store = Store("sqlite", sqlite_path=DB)
        store.touch_client(owner)  # pretend you messaged the bot today, so alerts are shown
        sheet = MemorySheet()
        return sheet, store, Bot(sheet, store, TerminalWhatsApp(owner), ai, owner=owner,
                                 max_replies_per_hour=s.max_replies_per_hour)

    sheet, store, bot = fresh()
    client_phone = "212612345678"
    sender = client_phone
    counter = [0]

    def place_order() -> str:
        nonlocal client_phone, sender
        print(f"\n{BOLD}— New order on the website —{RESET} (press Enter for the default)")
        name = input("  Nom complet [Salma Kettani]: ").strip() or "Salma Kettani"
        phone = normalize_phone(input("  Téléphone [06 12 34 56 78]: ").strip() or "0612345678") or "212612345678"
        q = input("  Quantité [1]: ").strip()
        qty = int(q) if q.isdigit() and 1 <= int(q) <= 10 else 1
        number = f"NAYO-{store.next_order_number()}"
        sheet.append({"order_number": number, "created_at": now_local(), "name": name, "phone": phone,
                      "quantity": qty, "total": order_total(qty), "status": "new", "updated_at": now_local()})
        client_phone = sender = phone
        msg = f"Bonjour NAYO, je confirme ma commande {number} – {order_total(qty)} MAD – {name}"
        print(f"{CYAN}   ✔ {number} created ({qty} × 189 + 20 = {order_total(qty)} MAD). "
              f"The success page's WhatsApp button pre-fills:{RESET}\n   {msg}")
        print(f"{GREY}   (press Enter to send it, or type something else){RESET}")
        return msg

    def say(text: str, type_: str = "text") -> None:
        counter[0] += 1
        bot.handle(IncomingMessage(f"sim.{counter[0]}.{time.time()}", sender, type_, text))

    print(f"{BOLD}NAYO WhatsApp simulator{RESET} — model {s.gemini_model} (fallback {s.gemini_fallback_model})")
    print(f"{GREY}Commands: /sheet /new /as <phone> /me /audio /reset /quit{RESET}")
    pending = place_order()

    while True:
        try:
            who = "you" if sender == client_phone else f"+{sender}"
            line = input(f"\n{BOLD}{who} ▸ {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line and pending:
            line = pending
            print(f"{GREY}   (sent: {line}){RESET}")
        pending = ""
        if not line:
            continue
        cmd = line.split()[0].lower()
        if cmd == "/quit":
            return 0
        if cmd == "/sheet":
            sheet.show()
            continue
        if cmd == "/new":
            pending = place_order()
            continue
        if cmd == "/as":
            p = normalize_phone(line[3:].strip())
            if p:
                sender = p
                print(f"{GREY}   now writing from +{p} (stranger). /me to go back{RESET}")
            continue
        if cmd == "/me":
            sender = client_phone
            continue
        if cmd == "/audio":
            say("", "audio")
            continue
        if cmd == "/reset":
            sheet, store, bot = fresh()
            pending = place_order()
            continue
        say(line)


if __name__ == "__main__":
    sys.exit(main())
