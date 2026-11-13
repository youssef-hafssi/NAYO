"""Finance: P&L arithmetic on a fixed fixture, period boundaries, returns, CPA/ROAS, recurring expenses, CSV, access."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.delivery import Delivery
from app.finance import Finance, FinanceError, csv_cell
from app.main import Services, create_app
from app.purchasing import Purchasing
from app.sheets import DbOrders
from app.stock import Stock, StockOrders

PERIOD = ("2026-11-01", "2026-11-15")


@pytest.fixture
def world(store):
    stock = Stock(store)
    orders = StockOrders(DbOrders(store), stock)
    Purchasing(store, stock)
    Delivery(store)
    fin = Finance(store)

    def add(n, qty, created="2026-11-05 10:00:00"):
        orders.append({"order_number": n, "created_at": created, "name": "C", "phone": "212612345678",
                       "quantity": qty, "total": qty * 189 + 20, "status": "awaiting_details"})

    # F: confirmed BEFORE stock tracking started → counted by the opening backfill at the opening cost
    add("F", 1)
    orders.update("F", status="confirmed")
    stock.open(100, 5000, "Karim", orders.units_in(("confirmed", "shipped", "delivered")))  # 100 units at 50.00
    for n, q in (("A", 1), ("B", 2), ("C", 1), ("D", 1)):
        add(n, q)
    add("E", 1, created="2026-10-30 10:00:00")
    for n in ("A", "B", "C", "D", "E"):
        orders.update(n, status="confirmed")
    deliver = {"A": "2026-11-10 09:00:00", "B": "2026-11-15 23:59:59",  # last second of the period: included
               "C": "2026-11-16 00:00:00",  # first second after: excluded
               "E": "2026-10-31 23:59:59", "F": "2026-11-08 12:00:00"}
    for n, at in deliver.items():
        orders.update(n, status="delivered", delivered_at=at, carrier_fee_cents="0" if n == "F" else "2500",
                      cod_status="with_carrier")
    orders.update("D", status="returned", returned_at="2026-11-11 10:00:00", carrier_fee_cents="1500", recoverable=False)
    store._exec("UPDATE stock_movements SET at = '2026-11-11 10:00:00' WHERE written_off > 0")

    fin.add_expense(date_="2026-11-05", category="Publicité", amount_cents=20000, admin="K", campaign="FB novembre")
    fin.add_expense(date_="2026-11-15", category="Emballage", amount_cents=5000, admin="K")  # boundary: included
    fin.add_expense(date_="2026-11-16", category="Emballage", amount_cents=99999, admin="K")  # excluded
    fin.add_expense(date_="2026-10-31", category="Publicité", amount_cents=88888, admin="K")  # excluded
    return fin, orders, stock


def test_pnl_arithmetic(world):
    fin, _, _ = world
    r = fin.report(*PERIOD)
    p = r["pnl"]
    # revenue: A 209 + B 398 + F 209 (C after the period, E before, D returned)
    assert p["revenue_cents"] == (209 + 398 + 209) * 100
    assert p["cogs_cents"] == 4 * 5000  # A 1 + B 2 + F 1 (backfilled at the opening cost) units at 50.00
    assert r["counts"]["orders_without_cost"] == 0 and r["counts"]["delivered"] == 3 and r["counts"]["units_delivered"] == 4
    assert p["carrier_fees_cents"] == 2500 + 2500 + 0 + 1500  # A, B, F delivered + D returned
    assert p["gross_margin_cents"] == 81600 - 20000 - 6500
    assert p["expenses_cents"] == 20000 + 5000
    assert p["write_offs_cents"] == 5000  # D's unit lost at 50.00
    assert p["net_profit_cents"] == 55100 - 25000 - 5000
    assert p["return_cost_cents"] == 1500 + 5000
    assert {c["category"]: c["amount_cents"] for c in r["expenses_by_category"]} == {"Publicité": 20000, "Emballage": 5000}


def test_marketing_and_unit_economics(world):
    fin, _, _ = world
    r = fin.report(*PERIOD)
    m, u = r["marketing"], r["unit_economics"]
    assert r["counts"]["confirmed_created"] == 5  # A B C D F created in the period (E before)
    assert (m["ad_spend_cents"], m["cpa_cents"], m["roas"]) == (20000, 4000, round(81600 / 20000, 2))
    assert m["campaigns"] == [{"campaign": "FB novembre", "spend_cents": 20000}]
    assert u["avg_revenue_cents"] == 81600 // 3 and u["avg_cogs_cents"] == round(20000 / 3)
    assert u["avg_carrier_fee_cents"] == round(6500 / 4)
    assert u["profit_per_order_cents"] == 27200 - 6667 - 1625 - 4000
    assert u["break_even_orders_per_month"] is None  # no fixed monthly expense yet
    fin.add_expense(date_="2026-11-01", category="Salaires", amount_cents=300000, admin="K", recurring_monthly=True)
    u = fin.report(*PERIOD)["unit_economics"]
    assert u["fixed_monthly_cents"] == 300000 and u["break_even_orders_per_month"] == -(-300000 // 14908)


def test_zero_ad_spend_and_empty_period(world):
    fin, _, _ = world
    r = fin.report("2026-11-06", "2026-11-09")
    assert r["marketing"]["cpa_cents"] is None and r["marketing"]["roas"] is None
    assert r["pnl"]["revenue_cents"] == 20900  # F only
    empty = fin.report("2025-01-01", "2025-01-31")
    assert empty["pnl"]["net_profit_cents"] == 0 and empty["unit_economics"]["profit_per_order_cents"] is None
    with pytest.raises(FinanceError):
        fin.report("2026-11-15", "2026-11-01")


def test_cash_view(world):
    fin, _, _ = world
    c = fin.report(*PERIOD)["cash"]
    assert c["out_expenses_cents"] == 25000 and c["in_cents"] == 0 and c["net_cents"] == -25000
    assert [d["balance_cents"] for d in c["days"]] == [-20000, -25000]
    # COD still with carriers: A, B, C, E, F (delivered, not remitted) minus their fees
    assert c["to_collect_cents"] == (209 + 398 + 209 + 209 + 209) * 100 - 4 * 2500


def test_recurring_expense_created_once(store):
    fin = Finance(store)
    fin.add_expense(date_="2026-09-15", category="Outils et abonnements", amount_cents=4500, admin="K",
                    recurring_monthly=True, note="Vercel + Supabase")
    assert fin.ensure_recurring("2026-11-03") == 2  # October and November copies, dated the 1st
    assert fin.ensure_recurring("2026-11-20") == 0  # same month: nothing new
    dates = [e["date"] for e in fin.list_expenses("2026-01-01", "2026-12-31")["items"]]
    assert sorted(dates) == ["2026-09-15", "2026-10-01", "2026-11-01"]
    nov = next(e for e in fin.list_expenses("2026-11-01", "2026-11-30")["items"])
    fin.delete_expense(nov["id"])  # the owner deletes one month
    assert fin.ensure_recurring("2026-11-25") == 0  # not recreated
    assert fin.ensure_recurring("2026-12-01") == 1  # next month: created again


def test_csv_escapes_formulas_and_has_bom(world):
    fin, _, _ = world
    fin.add_expense(date_="2026-11-02", category="Autres", amount_cents=100, admin="K", note='=HYPERLINK("x")')
    out = fin.export_csv(*PERIOD)
    assert out.startswith("﻿") and "'=HYPERLINK" in out and "Bénéfice net" in out
    assert csv_cell("-5") == "'-5" and csv_cell("@x") == "'@x" and csv_cell("ok") == "ok"


def test_api_owner_only_and_flow(settings, store, bot):
    settings.admin_secret = "test-admin-secret"
    orders = StockOrders(DbOrders(store), Stock(store))
    store.upsert_admin(uuid.uuid4().hex, "owner@nayo.ma", hash_password("motdepasse123"), "Karim")
    store.upsert_admin(uuid.uuid4().hex, "agent@nayo.ma", hash_password("motdepasse123"), "Sara", role="agent")
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        c.post("/admin/login", json={"email": "agent@nayo.ma", "password": "motdepasse123"})
        assert c.get("/admin/finance/report?preset=month").status_code == 403
        assert c.post("/admin/expenses", json={"date": "2026-11-02", "category": "Autres", "amount": 1}).status_code == 403
        c.post("/admin/login", json={"email": "owner@nayo.ma", "password": "motdepasse123"})
        assert c.post("/admin/expenses", json={"date": "2026-11-02", "category": "Inconnue", "amount": 1}).status_code == 409
        assert c.post("/admin/expenses", json={"date": "02/11/2026", "category": "Autres", "amount": 1}).status_code == 422
        e = c.post("/admin/expenses", json={"date": "2026-11-02", "category": "Publicité", "amount": 150.5, "campaign": "IG"}).json()
        assert e["amount_cents"] == 15050
        r = c.get("/admin/finance/report?frm=2026-11-01&to=2026-11-30").json()
        assert r["pnl"]["expenses_cents"] == 15050 and r["marketing"]["ad_spend_cents"] == 15050
        assert c.get("/admin/finance/report").status_code == 422
        x = c.get("/admin/finance/export?frm=2026-11-01&to=2026-11-30")
        assert x.status_code == 200 and x.headers["content-type"].startswith("text/csv") and "attachment" in x.headers["content-disposition"]
        assert c.patch(f"/admin/expenses/{e['id']}", json={"amount": 100}).json()["amount_cents"] == 10000
        assert c.delete(f"/admin/expenses/{e['id']}").json() == {"ok": True}
        cat = c.post("/admin/expense-categories", json={"name": "Shooting photo"}).json()
        assert c.patch(f"/admin/expense-categories/{cat['id']}", json={"active": False}).json()["active"] is False
        pub = next(x for x in c.get("/admin/expense-categories").json()["items"] if x["name"] == "Publicité")
        assert c.patch(f"/admin/expense-categories/{pub['id']}", json={"name": "Pub"}).status_code == 409


def test_orders_delivered_without_stock_tracking_have_no_cost(store):
    orders = StockOrders(DbOrders(store), Stock(store))
    Purchasing(store, orders.stock)
    Delivery(store)
    fin = Finance(store)
    orders.append({"order_number": "X", "created_at": "2026-11-05 10:00:00", "name": "C", "phone": "212612345678",
                   "quantity": 1, "total": 209, "status": "confirmed"})
    orders.update("X", status="delivered", delivered_at="2026-11-06 10:00:00")
    r = fin.report(*PERIOD)
    assert r["pnl"]["revenue_cents"] == 20900 and r["pnl"]["cogs_cents"] == 0
    assert r["counts"]["orders_without_cost"] == 1 and r["ledger_start"] is None


def test_back_dated_recurring_added_mid_month_is_generated_at_once(store):
    fin = Finance(store)
    assert fin.ensure_recurring("2026-11-10") == 0  # this month's run is done
    fin.add_expense(date_="2026-10-05", category="Salaires", amount_cents=100, admin="K", recurring_monthly=True)
    assert fin.ensure_recurring("2026-11-12", force=True) == 1  # November created without waiting for December
