"""Phase 7: dashboard and reports. Money totals must equal the Finance page for the same period."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.crm import fmt, now_dt
from app.main import Services, create_app
from app.reports import ReportError, Reports
from app.sheets import DbOrders
from app.stock import Stock, StockOrders

from .test_finance import PERIOD, world  # noqa: F401  (the P&L fixture of phase 5)


def test_margin_totals_equal_finance(world):  # noqa: F811
    fin, orders, stock = world
    rep = Reports(fin.store, fin, None, stock)
    m = rep.margin(*PERIOD)
    p = fin.report(*PERIOD)["pnl"]
    t = m["totals"]
    keys = ("revenue_cents", "cogs_cents", "carrier_fees_cents", "gross_margin_cents", "expenses_cents",
            "write_offs_cents", "net_profit_cents")
    assert {k: t[k] for k in keys} == {k: p[k] for k in keys}
    days = {d["date"]: d for d in m["days"]}
    assert len(m["days"]) == 15 and days["2026-11-15"]["revenue_cents"] == 39800  # B at the last second
    assert days["2026-11-11"]["carrier_fees_cents"] == 1500 and days["2026-11-11"]["write_offs_cents"] == 5000


def test_sales_and_delivery_reports(world):  # noqa: F811
    fin, orders, stock = world
    rep = Reports(fin.store, fin, None, stock)
    s = rep.sales(*PERIOD)
    assert s["totals"]["delivered"] == 3 and s["totals"]["revenue_cents"] == 81600 and s["totals"]["units"] == 4
    assert s["totals"]["orders"] == 5 and s["totals"]["confirmed"] == 5  # A B C D F created on the 5th
    assert s["totals"]["avg_basket_cents"] == round(81600 / 3)
    assert s["totals"]["confirmation_rate"] == 1.0  # confirmed ÷ decided (pending orders excluded), like the dashboard
    d = rep.delivery(*PERIOD)
    assert (d["delivered"], d["returned"]) == (3, 1) and d["return_rate"] == 0.25
    assert d["avg_delay_days"] is not None and d["avg_delay_days"] >= 0
    for bad in (("2026-11-15", "2026-11-01"), ("2025-01-01", "2026-12-31"), ("2026-02-30", "2026-03-01")):
        with pytest.raises(ReportError):
            rep.sales(*bad)


def test_stock_valuation_follows_the_ledger(world):  # noqa: F811
    fin, orders, stock = world
    rep = Reports(fin.store, fin, None, stock)
    v = rep.stock_valuation("2025-01-01", "2025-01-02")  # before the ledger: nothing
    assert v["opening"]["value_cents"] == 0 and v["closing"]["on_hand"] == 0
    now = stock.summary()
    today = now_dt().strftime("%Y-%m-%d")
    v = rep.stock_valuation(today, today)
    assert v["closing"]["on_hand"] == now["on_hand"] and v["closing"]["value_cents"] == now["stock_value_cents"]


def test_closing_month(world):  # noqa: F811
    fin, orders, stock = world
    rep = Reports(fin.store, fin, None, stock)
    c = rep.closing("2026-11")
    assert c["pnl"] == fin.report("2026-11-01", c["to"])["pnl"]
    assert c["orders"]["created"] >= 5 and "delivered" in c["orders"]["by_status"]
    with pytest.raises(ReportError):
        rep.closing("2026-13")
    with pytest.raises(ReportError):
        rep.closing((now_dt() + timedelta(days=40)).strftime("%Y-%m"))


@pytest.fixture
def env(settings, store, bot):
    settings.admin_secret = "test-admin-secret"
    stock = Stock(store)
    orders = StockOrders(DbOrders(store), stock)
    store.upsert_admin(uuid.uuid4().hex, "owner@nayo.ma", hash_password("motdepasse123"), "Karim")
    store.upsert_admin(uuid.uuid4().hex, "agent@nayo.ma", hash_password("motdepasse123"), "Sara", role="agent")
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        yield c, orders, stock, store


def login(c, who="owner"):
    assert c.post("/admin/login", json={"email": f"{who}@nayo.ma", "password": "motdepasse123"}).status_code == 200


def add(orders, n, status, city="Agadir", qty=1, created=None):
    orders.append({"order_number": n, "created_at": created or fmt(now_dt() - timedelta(minutes=5)), "name": "C",
                   "phone": "212611111111", "quantity": qty, "total": qty * 189 + 20, "status": "new", "city": city})
    if status != "new":
        orders.update(n, status=status)


def test_dashboard_counts_rates_and_roles(env):
    c, orders, stock, store = env
    stock.open(10, 1500, "Karim", [])
    add(orders, "N1", "new")
    add(orders, "N2", "confirmed", city="Rabat")
    add(orders, "N3", "cancelled")
    add(orders, "N4", "confirmed")
    orders.update("N4", status="delivered", delivered_at=fmt(now_dt()), carrier_fee_cents="2500")
    add(orders, "N5", "needs_human", city=" AGADIR ")  # typed freely: same city
    add(orders, "OLD", "confirmed", created=fmt(now_dt() - timedelta(days=45)))
    login(c, "agent")
    d = c.get("/admin/dashboard").json()
    assert d["orders"]["today"] == 5
    # confirmed-like (N2, N4) ÷ decided this month (N2, N3, N4, N5): N1 is still pending
    assert d["confirmation_rate"] == {"rate": 0.5, "confirmed": 2, "decided": 4}
    assert d["delivery_rate"] == {"rate": 1.0, "delivered": 1, "returned": 0}
    assert d["needs_human"] == 1 and d["in_progress"]["orders"] == 2  # N2 + OLD
    assert d["stock"]["on_hand"] == 10 - 3 and "value_cents" not in d["stock"]
    assert "money" not in d and all("revenue_cents" not in r for r in d["chart"])  # agents: counts only
    assert len(d["chart"]) == 30 and d["chart"][-1]["orders"] == 5 and d["chart"][-1]["delivered"] == 1
    assert d["top_cities"] == [{"city": "Agadir", "orders": 4}, {"city": "Rabat", "orders": 1}]
    assert "follow_ups" in d
    login(c)
    d = c.get("/admin/dashboard").json()
    assert d["money"]["revenue_month_cents"] == 20900 and d["money"]["in_progress_cents"] == 2 * 20900
    assert d["money"]["to_collect_cents"] == 0 and d["stock"]["value_cents"] == 7 * 1500
    assert d["chart"][-1]["revenue_cents"] == 20900


def test_dashboard_is_cached_30s(env):
    c, orders, _, _ = env
    login(c, "agent")
    assert c.get("/admin/dashboard").json()["orders"]["today"] == 0
    add(orders, "X1", "new")
    assert c.get("/admin/dashboard").json()["orders"]["today"] == 0  # cached for 30 s


def test_reports_api_owner_only_and_csv(env):
    c, orders, stock, store = env
    add(orders, "R1", "confirmed", city="=cmd")
    orders.update("R1", status="delivered", delivered_at=fmt(now_dt()))
    login(c, "agent")
    assert c.get("/admin/reports/sales?preset=month").status_code == 403
    assert c.get("/admin/reports/sales.csv?preset=month").status_code == 403
    login(c)
    for name in ("sales", "stock", "delivery", "margin"):
        assert c.get(f"/admin/reports/{name}?preset=month").status_code == 200, name
        x = c.get(f"/admin/reports/{name}.csv?preset=month")
        assert x.status_code == 200 and x.text.startswith("﻿"), name
        assert "attachment" in x.headers["content-disposition"], name
    assert "'=Cmd" in c.get("/admin/reports/delivery.csv?preset=month").text
    month = now_dt().strftime("%Y-%m")
    cl = c.get(f"/admin/reports/closing?month={month}").json()
    assert cl["pnl"]["revenue_cents"] == 20900 and cl["orders"]["created"] == 1
    assert "Bénéfice net" in c.get(f"/admin/reports/closing.csv?month={month}").text
    assert c.get("/admin/reports/closing").status_code == 422
    assert c.get("/admin/reports/closing?month=2026-13").status_code == 409
    assert c.get("/admin/reports/nope?preset=month").status_code == 404
    assert c.get("/admin/reports/sales").status_code == 422
    assert c.get("/admin/reports/sales?frm=2026-11-10&to=2026-11-01").status_code == 409
    assert store.audit_for("report", "sales")[0]["action"] == "report.export"
