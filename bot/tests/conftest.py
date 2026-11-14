from __future__ import annotations

import copy
import itertools
from typing import Any

import pytest

from app.ai import AIError, AIResult
from app.config import Settings
from app.flow import Bot
from app.main import Services, create_app
from app.store import Store
from app.whatsapp import IncomingMessage


class FakeOrders:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def append(self, order: dict[str, Any]) -> None:
        row = {k: "" for k in ("city", "address", "whatsapp_from", "notes")}
        row.update({k: str(v) for k, v in order.items()})
        self.rows.append(row)

    def get(self, number: str) -> dict[str, Any] | None:
        r = next((r for r in self.rows if r["order_number"].upper() == number.upper()), None)
        return copy.deepcopy(r) if r else None

    def find_open_by_phone(self, phone: str, statuses=("new", "awaiting_details")) -> dict[str, Any] | None:
        for r in reversed(self.rows):
            if r["phone"] == phone and r["status"] in statuses:
                return copy.deepcopy(r)
        return None

    def update(self, number: str, **fields: Any) -> None:
        r = next(r for r in self.rows if r["order_number"].upper() == number.upper())
        r.update({k: str(v) for k, v in fields.items()})

    def add(self, number: str, name: str, phone: str, quantity: int = 1, status: str = "new", **extra: str) -> None:
        self.append({"order_number": number, "name": name, "phone": phone, "quantity": quantity,
                     "total": quantity * 189 + 20, "status": status, **extra})


class FakeWA:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = False

    def send_text(self, to: str, body: str) -> bool:
        self.sent.append((to, body))
        return not self.fail

    def to(self, phone: str) -> list[str]:
        return [b for p, b in self.sent if p == phone]


class FakeAI:
    """Returns queued results; records what it was given."""

    def __init__(self) -> None:
        self.queue: list[AIResult | Exception] = []
        self.calls: list[tuple[dict, list, str]] = []

    def push(self, intent: str = "other", reply: str = "ok", **kw: Any) -> None:
        self.queue.append(AIResult(reply=reply, intent=intent, **kw))

    def fail(self) -> None:
        self.queue.append(AIError("down"))

    def run(self, context: dict, history: list, last_message: str) -> AIResult:
        self.calls.append((context, history, last_message))
        item = self.queue.pop(0) if self.queue else AIResult(reply="ok", intent="other")
        if isinstance(item, Exception):
            raise item
        return item


OWNER = "212600000001"
CLIENT = "212612345678"


@pytest.fixture
def store(tmp_path) -> Store:
    return Store("sqlite", sqlite_path=str(tmp_path / "state.db"))


@pytest.fixture
def orders() -> FakeOrders:
    return FakeOrders()


@pytest.fixture
def wa() -> FakeWA:
    return FakeWA()


@pytest.fixture
def ai() -> FakeAI:
    return FakeAI()


@pytest.fixture
def clock():
    class Clock:
        t = 1_800_000_000.0

        def __call__(self) -> float:
            self.t += 1
            return self.t

    return Clock()


@pytest.fixture
def bot(orders, store, wa, ai, clock) -> Bot:
    return Bot(orders, store, wa, ai, owner=OWNER, max_replies_per_hour=20, clock=clock)


_ids = itertools.count(1)


@pytest.fixture
def say(bot):
    def _say(text: str, sender: str = CLIENT, type_: str = "text", msg_id: str | None = None) -> None:
        bot.handle(IncomingMessage(msg_id or f"wamid.{next(_ids)}", sender, type_, text))

    return _say


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        whatsapp_verify_token="verify-me",
        whatsapp_app_secret="app-secret",
        order_api_key="k3y",
        allowed_origins="https://nayo.ma",
        sqlite_path=str(tmp_path / "api.db"),
        max_orders_per_ip_per_hour=5,
    )


@pytest.fixture
def client(settings, orders, store, bot):
    from fastapi.testclient import TestClient

    app = create_app(Services(settings, store, orders, bot))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def say_db():
    """Send a WhatsApp message to any Bot instance (used with the real DbOrders setups)."""
    def _say(bot, text: str, sender: str = CLIENT, type_: str = "text") -> None:
        bot.handle(IncomingMessage(f"wamid.{next(_ids)}", sender, type_, text))

    return _say


@pytest.fixture(autouse=True)
def _no_literal_percent_in_sql(monkeypatch):
    """Postgres (psycopg) reads '%' as a placeholder: a literal '%' in SQL text breaks there even though SQLite
    accepts it. LIKE patterns must be passed as parameters. Checked on every statement the tests send."""
    orig = Store._run

    def run(self, cur, sql, params, fetch):
        assert "%" not in sql, f"literal % in SQL (use a ? parameter): {sql[:120]}"
        return orig(self, cur, sql, params, fetch)

    monkeypatch.setattr(Store, "_run", run)
