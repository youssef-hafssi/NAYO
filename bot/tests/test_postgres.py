"""Real Postgres checks (migrations + Postgres-only SQL). Skipped unless NAYO_TEST_PG_URL points to a throwaway
server, e.g. a local one:  NAYO_TEST_PG_URL=postgresql://nayo@127.0.0.1:54329/postgres
Each test creates its own database and drops it. NEVER point this at Supabase."""

import json
import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient

PG = os.environ.get("NAYO_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG or "supabase" in PG or "pooler" in PG, reason="set NAYO_TEST_PG_URL (local only)")

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
SID, VID = "s-" + "7" * 12, "v-" + "7" * 12


@pytest.fixture
def pg_url():
    import psycopg

    name = "nayo_t_" + uuid.uuid4().hex[:10]
    with psycopg.connect(PG, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {name}")
    url = PG.rsplit("/", 1)[0] + "/" + name
    yield url
    with psycopg.connect(PG, autocommit=True) as c:
        c.execute(f"DROP DATABASE {name} WITH (FORCE)")


def app_for(url, settings, bot_factory):
    from app.main import Services, create_app
    from app.sheets import DbOrders
    from app.stock import Stock, StockOrders
    from app.store import Store

    store = Store("postgres", database_url=url)
    orders = StockOrders(DbOrders(store), Stock(store))
    settings.admin_secret = "test-admin-secret"
    settings.state_backend = "postgres"
    return create_app(Services(settings, store, orders, bot_factory(orders, store))), store, orders


@pytest.fixture
def bot_factory(wa, ai):
    from app.flow import Bot

    return lambda orders, store: Bot(orders, store, wa, ai)


def visit(c, events):
    body = {"v": VID, "s": SID, "c": {"utm_source": "facebook", "device": "mobile", "landing": "/"},
            "e": [{"n": n, "t": int(time.time() * 1000), "d": d} for n, d in events]}
    return c.post("/t", content=json.dumps(body), headers={"User-Agent": UA, "Content-Type": "text/plain"})


def test_fresh_database_everything_works(pg_url, settings, bot_factory):
    from app.admin import hash_password

    app, store, orders = app_for(pg_url, settings, bot_factory)
    with TestClient(app) as c:
        assert c.get("/health").json() == {"ok": True, "db": True}
        assert visit(c, [("page_view", {}), ("scroll_depth", {"pct": 50}), ("form_start", {"form": "express"})]).status_code == 204
        r = c.post("/orders", json={"clientId": str(uuid.uuid4()), "name": "Salma Kettani", "phone": "0612345678",
                                    "quantity": 1, "address": "Hay Salam, rue 12, Agadir", "sessionId": SID,
                                    "visitorId": VID, "utmSource": "facebook"}, headers={"X-API-Key": "k3y"})
        assert r.status_code == 200 and r.json()["orderNumber"] == "NAYO-1001"  # empty database: first number
        assert visit(c, [("order_success", {"order": "NAYO-1001"})]).status_code == 204
        # superadmin (the script's store method) on Postgres
        assert store.set_superadmin("youssef@admin.com", "Youssef", hash_password("motdepasse123")) == "created"
        assert store.set_superadmin("youssef@admin.com", "Youssef", hash_password("motdepasse456")) == "updated"
        assert c.post("/admin/login", json={"email": "youssef@admin.com", "password": "motdepasse456"}).status_code == 200
        o = c.get("/admin/analytics/overview?days=7").json()
        assert o["funnel"] == {"visits": 1, "scroll_50": 1, "form_started": 1, "ordered": 1}
        s = c.get(f"/admin/analytics/sessions/{SID}").json()
        assert s["session"]["order_number"] == "NAYO-1001" and s["session"]["events_count"] == 4
        assert [e["name"] for e in s["events"]] == ["page_view", "scroll_depth", "form_start", "order_success"]
        for path in ("/admin/dashboard", "/admin/orders", "/admin/customers", "/admin/orders.csv", "/admin/customers.csv",
                     "/admin/stock", "/admin/finance/report?preset=month", "/admin/tasks", "/admin/team/members"):
            assert c.get(path).status_code == 200, path
        assert orders.get("NAYO-1001")["utm_source"] == "facebook"
        c.app.state.analytics().purge()
    versions = dict(store._exec("SELECT key, value FROM settings WHERE key LIKE ?", ("schema:%",), fetch="all"))
    assert versions["schema:orders"] == "6" and versions["schema:analytics"] == "1"
    rls = store._exec("SELECT relname FROM pg_class WHERE relname IN ('sessions', 'events') AND relrowsecurity", fetch="all")
    assert len(rls) == 2


def test_upgrade_from_the_live_schema(pg_url, settings, bot_factory):
    """Live today: orders at schema 5 (no analytics columns), no sessions / events tables. The new code migrates in
    place: old rows stay readable, new columns default to ''."""
    from app.sheets import ALL_COLUMNS, HEADERS
    from app.store import Store

    store = Store("postgres", database_url=pg_url)
    old_cols = [c for c in ALL_COLUMNS if c not in ("visitor_id", "session_id", "utm_source", "utm_medium",
                                                     "utm_campaign", "utm_content", "utm_term")]
    store._exec("CREATE TABLE orders (order_number TEXT PRIMARY KEY, "
                + ", ".join(f"{h} TEXT NOT NULL DEFAULT ''" for h in old_cols if h != "order_number") + ")")
    store._exec("INSERT INTO orders (order_number, name, phone, quantity, total, status, source) "
                "VALUES ('NAYO-1001', 'Salma', '212612345678', '1', '209', 'confirmed', 'website')")
    store.schema_done("orders", 5)
    assert len(HEADERS) == 12
    app, store2, orders = app_for(pg_url, settings, bot_factory)
    with TestClient(app) as c:
        assert c.get("/health").json()["ok"] is True
        o = orders.get("NAYO-1001")
        assert o["name"] == "Salma" and o["visitor_id"] == "" and o["utm_source"] == ""
        assert visit(c, [("page_view", {})]).status_code == 204
    assert store2._exec("SELECT value FROM settings WHERE key = 'schema:orders'", fetch="one")[0] == "6"
    # a second start: nothing to migrate (one query reads every schema version)
    from app.store import Store as S

    again = S("postgres", database_url=pg_url)
    assert not again.needs_schema("orders", 6) and not again.needs_schema("analytics", 1)


def test_one_statement_per_batch(pg_url, settings, bot_factory):
    from app.analytics import Analytics, parse_batch

    app, store, _ = app_for(pg_url, settings, bot_factory)
    a = Analytics(store)
    calls = []
    orig = store._exec
    store._exec = lambda *args, **kw: (calls.append(args[0]), orig(*args, **kw))[1]  # type: ignore[method-assign]
    now = time.time()
    b = parse_batch(json.dumps({"v": VID, "s": SID, "c": {}, "e": [{"n": "click", "d": {"id": "cta"}}] * 50}).encode(), now)
    assert a.record(b, now=now) == 50
    assert len(calls) == 1 and calls[0].startswith("WITH s AS (INSERT INTO sessions")
    t0 = time.perf_counter()
    for i in range(10):
        a.record({**b, "session_id": f"s-{i:012d}"}, now=now)
    assert (time.perf_counter() - t0) / 10 < 0.1  # warm, local
    assert orig("SELECT COUNT(*) FROM events", fetch="one")[0] == 550
