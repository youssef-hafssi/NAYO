"""Stock with weighted average cost: ledger, order sync, bot checks, admin API."""

import itertools
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.flow import Bot
from app.main import Services, create_app
from app.sheets import DbOrders
from app.stock import InsufficientStock, Stock, StockOrders
from app.whatsapp import IncomingMessage

from .conftest import CLIENT, OWNER


@pytest.fixture
def stock(store):
    return Stock(store)


@pytest.fixture
def sorders(store, stock):
    return StockOrders(DbOrders(store), stock)


def add(sorders, number, qty=1, status="new", phone=CLIENT, **extra):
    sorders.append({"order_number": number, "created_at": "2026-11-12 10:00:00", "name": "Salma", "phone": phone,
                    "quantity": qty, "total": qty * 189 + 20, "status": status, **extra})


def moves(stock):
    return list(reversed(stock.movements(limit=200)["items"]))


def units(store, number):
    row = store._exec("SELECT units, unit_cost_cents FROM stock_order_units WHERE order_number = ?", (number,), fetch="one")
    return tuple(row) if row else None


# ---------------------------------------------------------------- ledger
def test_tracking_off_changes_nothing(sorders, stock):
    add(sorders, "NAYO-1", qty=3)
    sorders.update("NAYO-1", status="confirmed", stock_check=True)
    assert sorders.get("NAYO-1")["status"] == "confirmed" and moves(stock) == []
    assert stock.available() is None


def test_opening_backfills_confirmed_orders_without_movements(sorders, stock, store):
    add(sorders, "NAYO-1", qty=2, status="confirmed")
    add(sorders, "NAYO-2", qty=1, status="new")
    stock.open(50, 4000, "Karim", sorders.units_in(("confirmed", "shipped", "delivered")))
    assert [m["reason"] for m in moves(stock)] == ["opening"]
    assert units(store, "NAYO-1") == (2, 4000) and units(store, "NAYO-2") is None
    assert stock.summary()["stock_value_cents"] == 50 * 4000 and stock.summary()["ledger_start"]
    with pytest.raises(ValueError):
        stock.open(10, 100, "Karim", [])
    sorders.update("NAYO-1", status="cancelled")  # a backfilled order cancelled → its units come back
    assert stock.current() == (52, 4000)


def test_confirm_deducts_at_average_cost_and_purchase_updates_average(sorders, stock, store):
    stock.open(10, 5000, "K", [])
    stock.receive(10, 7000, reason="purchase", admin="K")
    assert stock.current() == (20, 6000)
    add(sorders, "NAYO-1", qty=2)
    sorders.update("NAYO-1", status="confirmed")
    m = moves(stock)[-1]
    assert (m["delta"], m["reason"], m["unit_cost_cents"], m["balance_after"]) == (-2, "order_confirmed", 6000, 18)
    assert units(store, "NAYO-1") == (2, 6000) and stock.current() == (18, 6000)


def test_cancel_and_return_restore_at_the_original_cost(sorders, stock, store):
    stock.open(10, 5000, "K", [])
    add(sorders, "NAYO-1", qty=2)
    sorders.update("NAYO-1", status="confirmed")  # exit at 50.00
    stock.receive(10, 8000, admin="K")  # avg (8*5000 + 10*8000) / 18 = 6667
    assert stock.current() == (18, 6667)
    sorders.update("NAYO-1", status="cancelled")
    m = moves(stock)[-1]
    assert (m["delta"], m["reason"], m["unit_cost_cents"]) == (2, "order_cancelled", 5000)
    assert stock.current() == (20, round((18 * 6667 + 2 * 5000) / 20))

    add(sorders, "NAYO-2", qty=1)
    sorders.update("NAYO-2", status="confirmed")
    sorders.update("NAYO-2", status="shipped")  # still out: nothing moves
    sorders.update("NAYO-2", status="delivered")
    n = len(moves(stock))
    sorders.update("NAYO-2", status="returned")
    assert len(moves(stock)) == n + 1 and moves(stock)[-1]["reason"] == "order_returned" and moves(stock)[-1]["delta"] == 1


def test_returned_not_recoverable_is_a_write_off(sorders, stock, store):
    stock.open(10, 5000, "K", [])
    add(sorders, "NAYO-1", qty=3, status="confirmed")
    before = stock.current()[0]
    sorders.update("NAYO-1", status="returned", recoverable=False)
    m = moves(stock)[-1]
    assert (m["delta"], m["written_off"], m["reason"], m["unit_cost_cents"]) == (0, 3, "order_returned", 5000)
    assert stock.current()[0] == before and units(store, "NAYO-1") == (0, 5000)


def test_quantity_change_reactivation_and_idempotence(sorders, stock):
    stock.open(20, 5000, "K", [])
    add(sorders, "NAYO-1", qty=2)
    sorders.update("NAYO-1", status="confirmed")
    sorders.update("NAYO-1", quantity=5, total=965)
    assert moves(stock)[-1]["delta"] == -3 and moves(stock)[-1]["reason"] == "order_changed"
    sorders.update("NAYO-1", quantity=1, total=209)
    assert moves(stock)[-1]["delta"] == 4 and stock.current()[0] == 19
    sorders.update("NAYO-1", status="awaiting_details")  # reopened by a change → units back
    sorders.update("NAYO-1", status="confirmed")  # reactivated → deducted again
    assert stock.current()[0] == 19
    n = len(moves(stock))
    sorders.update("NAYO-1", status="confirmed")
    sorders.reconcile("NAYO-1")
    sorders.reconcile("NAYO-1")
    assert len(moves(stock)) == n  # same state twice = no movement


def test_check_refuses_beyond_stock_and_leaves_the_order_unchanged(sorders, stock):
    stock.open(2, 5000, "K", [])
    add(sorders, "NAYO-1", qty=3, status="awaiting_details")
    with pytest.raises(InsufficientStock) as e:
        sorders.update("NAYO-1", status="confirmed", stock_check=True)
    assert e.value.available == 2 and sorders.get("NAYO-1")["status"] == "awaiting_details" and stock.current()[0] == 2
    sorders.update("NAYO-1", status="confirmed")  # forced (no check): goes negative, visible to the owner
    assert stock.current()[0] == -1 and stock.summary()["out"]


def test_two_simultaneous_confirmations_cannot_oversell_the_last_unit(sorders, stock):
    stock.open(1, 5000, "K", [])
    for n in ("NAYO-1", "NAYO-2", "NAYO-3", "NAYO-4"):
        add(sorders, n, qty=1, status="awaiting_details")
    results, barrier = [], threading.Barrier(4)

    def confirm(n):
        barrier.wait()
        try:
            sorders.update(n, status="confirmed", stock_check=True)
            results.append(n)
        except InsufficientStock:
            pass

    threads = [threading.Thread(target=confirm, args=(n,)) for n in ("NAYO-1", "NAYO-2", "NAYO-3", "NAYO-4")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(results) == 1 and stock.current()[0] == 0
    assert sum(1 for n in ("NAYO-1", "NAYO-2", "NAYO-3", "NAYO-4") if sorders.get(n)["status"] == "confirmed") == 1


# ---------------------------------------------------------------- bot
_ids = itertools.count(1)


@pytest.fixture
def sbot(sorders, store, wa, ai, clock):
    return Bot(sorders, store, wa, ai, owner=OWNER, clock=clock)


def say(bot, text, sender=CLIENT):
    bot.handle(IncomingMessage(f"wamid.s{next(_ids)}", sender, "text", text))


def ready(sorders, store, qty):
    add(sorders, "NAYO-9", qty=qty, status="awaiting_details", city="Agadir", address="hay salam")
    store.update_conv(CLIENT, order_number="NAYO-9", stage="await_yes")


def test_bot_offers_what_is_left_then_confirms_it(sbot, sorders, stock, store, wa, ai):
    say(sbot, "salam", sender=OWNER)
    stock.open(2, 5000, "K", [])
    ready(sorders, store, 3)
    ai.push("confirm", "x")
    say(sbot, "wakha")
    assert sorders.get("NAYO-9")["status"] == "awaiting_details" and stock.current()[0] == 2
    assert "ma b9a lina ghir 2" in wa.to(CLIENT)[-1] and store.get_conv(CLIENT).stage == "stock_limit:2"
    assert "stock insuffisant" in wa.to(OWNER)[-1]
    ai.push("confirm", "x")
    say(sbot, "oui")  # yes, 2 then
    o = sorders.get("NAYO-9")
    assert (o["quantity"], o["total"]) == ("2", "398") and "398" in wa.to(CLIENT)[-1]
    ai.push("confirm", "x")
    say(sbot, "oui c'est bon")
    assert sorders.get("NAYO-9")["status"] == "confirmed" and stock.current()[0] == 0
    assert "Stock bas" in wa.to(OWNER)[-1]


def test_bot_out_of_stock_keeps_the_order_waiting(sbot, sorders, stock, store, wa, ai):
    stock.open(0, 5000, "K", [])
    ready(sorders, store, 1)
    ai.push("confirm", "x")
    say(sbot, "wakha")
    assert sorders.get("NAYO-9")["status"] == "awaiting_details" and "salat f stock" in wa.to(CLIENT)[-1]


def test_bot_confirms_normally_when_tracking_is_off(sbot, sorders, store, ai):
    ready(sorders, store, 3)
    ai.push("confirm", "x")
    say(sbot, "wakha")
    assert sorders.get("NAYO-9")["status"] == "confirmed"


# ---------------------------------------------------------------- admin API
@pytest.fixture
def api(settings, sorders, store, sbot):
    settings.admin_secret = "test-admin-secret"
    store.upsert_admin(uuid.uuid4().hex, "owner@nayo.ma", hash_password("motdepasse123"), "Karim")
    store.upsert_admin(uuid.uuid4().hex, "agent@nayo.ma", hash_password("motdepasse123"), "Sara")
    store._exec("UPDATE admin_users SET role = 'agent' WHERE email = 'agent@nayo.ma'")
    with TestClient(create_app(Services(settings, store, sorders, sbot))) as c:
        yield c


def login(c, who="owner"):
    assert c.post("/admin/login", json={"email": f"{who}@nayo.ma", "password": "motdepasse123"}).status_code == 200


def test_admin_stock_flow(api, sorders, stock):
    login(api)
    assert api.get("/admin/stock").json()["tracking"] is False
    assert api.post("/admin/stock/restock", json={"quantity": 5, "unit_cost": 40}).status_code == 409  # not opened
    r = api.post("/admin/stock/opening", json={"quantity": 3, "unit_cost": 42.5}).json()
    assert (r["on_hand"], r["avg_cost_cents"], r["stock_value_cents"]) == (3, 4250, 12750)
    assert api.post("/admin/stock/opening", json={"quantity": 3, "unit_cost": 1}).status_code == 409
    assert api.post("/admin/stock/adjust", json={"new_quantity": 2, "note": ""}).status_code == 422  # note required
    assert api.post("/admin/stock/adjust", json={"new_quantity": 2, "note": "casse"}).json()["on_hand"] == 2
    assert api.post("/admin/stock/threshold", json={"value": 5}).json()["low"] is True

    add(sorders, "NAYO-1", qty=3, status="awaiting_details")
    r = api.post("/admin/order/NAYO-1/status", json={"status": "confirmed"})
    assert r.status_code == 409 and r.json()["detail"] == "Stock insuffisant : il reste 2"
    assert sorders.get("NAYO-1")["status"] == "awaiting_details"
    assert api.post("/admin/order/NAYO-1/status", json={"status": "confirmed", "force": True}).status_code == 200
    assert stock.current()[0] == -1

    r = api.patch("/admin/orders/NAYO-1", json={"quantity": 5})
    assert r.status_code == 409 and sorders.get("NAYO-1")["quantity"] == "3"

    api.post("/admin/stock/restock", json={"quantity": 10, "unit_cost": 40, "note": "fournisseur"})
    detail = api.get("/admin/orders/NAYO-1").json()
    assert [m["reason"] for m in detail["stock_movements"]] == ["order_confirmed"]
    page = api.get("/admin/stock/movements?limit=2").json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    rest = api.get(f"/admin/stock/movements?limit=50&cursor={page['next_cursor']}").json()
    assert len(page["items"]) + len(rest["items"]) == 4 and rest["next_cursor"] is None


def test_agent_sees_units_but_no_costs_and_cannot_write(api, stock):
    stock.open(10, 5000, "K", [])
    login(api, "agent")
    s = api.get("/admin/stock").json()
    assert s["on_hand"] == 10 and "avg_cost_cents" not in s and "stock_value_cents" not in s
    assert all("unit_cost_cents" not in m for m in api.get("/admin/stock/movements").json()["items"])
    for path, body in (("/admin/stock/restock", {"quantity": 1, "unit_cost": 1}),
                       ("/admin/stock/adjust", {"new_quantity": 1, "note": "test"}),
                       ("/admin/stock/threshold", {"value": 3})):
        assert api.post(path, json=body).status_code == 403
