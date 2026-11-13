"""Delivery & cash on delivery: fees by status, reconciliation, locks, stock consistency, access."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.main import Services, create_app
from app.sheets import DbOrders
from app.stock import Stock, StockOrders


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


def add(orders, n, qty=1, status="confirmed", **extra):
    orders.append({"order_number": n, "created_at": "2026-11-13 10:00:00", "name": "Salma", "phone": "212612345678",
                   "quantity": qty, "total": qty * 189 + 20, "status": status, "city": "Agadir", "address": "hay salam",
                   **extra})


def carrier(c, **kw):
    body = {"name": "Amana", "fee_delivered": 25, "fee_returned": 15, "remit_delay_days": 7}
    body.update(kw)
    r = c.post("/admin/carriers", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_fees_by_status_and_cod(env):
    c, orders, stock, store = env
    login(c)
    amana = carrier(c)
    add(orders, "NAYO-1")
    add(orders, "NAYO-2", qty=2)
    r = c.post("/admin/delivery/bulk", json={"order_numbers": ["NAYO-1", "NAYO-2"], "carrier_id": amana["id"], "status": "shipped"})
    assert r.json() == {"done": ["NAYO-1", "NAYO-2"], "errors": {}}
    o = orders.get("NAYO-1")
    assert (o["status"], o["carrier"], o["carrier_id"], o["shipped_at"] != "") == ("shipped", "Amana", str(amana["id"]), True)

    assert c.post("/admin/order/NAYO-1/status", json={"status": "delivered"}).status_code == 200
    o = orders.get("NAYO-1")
    assert (o["cod_status"], o["cod_amount_cents"], o["carrier_fee_cents"]) == ("with_carrier", "20900", "2500")
    assert o["delivered_at"]

    assert c.post("/admin/order/NAYO-2/status", json={"status": "returned", "return_reason": "refus"}).status_code == 200
    o = orders.get("NAYO-2")
    assert (o["cod_status"], o["cod_amount_cents"], o["carrier_fee_cents"]) == ("none", "0", "1500")  # no COD

    c.patch("/admin/orders/NAYO-1", json={"carrier_fee": 30})  # fee is editable
    assert orders.get("NAYO-1")["carrier_fee_cents"] == "3000"


def test_reconciliation_expected_received_and_locks(env):
    c, orders, stock, store = env
    login(c)
    amana = carrier(c)
    for n, q in (("NAYO-1", 1), ("NAYO-2", 2), ("NAYO-3", 1)):
        add(orders, n, qty=q, carrier_id=str(amana["id"]), carrier="Amana")
        c.post(f"/admin/order/{n}/status", json={"status": "delivered"})
    store._exec("UPDATE orders SET delivered_at = '2020-01-01 10:00:00' WHERE order_number = 'NAYO-1'")

    s = c.get("/admin/cod/summary").json()
    assert s["total_cents"] == (209 + 398 + 209) * 100 - 3 * 2500 and s["late_carriers"] == 1
    assert s["carriers"][0]["orders"] == 3 and s["carriers"][0]["late"] is True
    pending = c.get(f"/admin/cod/pending?carrier_id={amana['id']}").json()["items"]
    assert [p["order_number"] for p in pending][0] == "NAYO-1" and pending[0]["late"] is True

    expected = (209 + 398) * 100 - 2 * 2500
    r = c.post("/admin/remittances", json={"carrier_id": amana["id"], "order_numbers": ["NAYO-1", "NAYO-2"],
                                           "amount_received": expected / 100 - 10, "note": "virement"}).json()
    assert (r["expected_cents"], r["difference_cents"], r["orders"]) == (expected, -1000, 2)
    assert [p["order_number"] for p in c.get(f"/admin/cod/pending?carrier_id={amana['id']}").json()["items"]] == ["NAYO-3"]
    assert orders.get("NAYO-1")["cod_status"] == "remitted"
    again = c.post("/admin/remittances", json={"carrier_id": amana["id"], "order_numbers": ["NAYO-1"], "amount_received": 1})
    assert again.status_code == 409  # already remitted: can't be counted twice
    assert c.get("/admin/remittances").json()["items"][0]["difference_cents"] == -1000

    # a remitted order is locked
    assert c.post("/admin/order/NAYO-1/status", json={"status": "returned"}).status_code == 409
    assert c.patch("/admin/orders/NAYO-1", json={"quantity": 3}).status_code == 409
    assert orders.get("NAYO-1")["status"] == "delivered"


def test_status_changes_keep_stock_and_cod_consistent(env):
    c, orders, stock, store = env
    login(c)
    stock.open(10, 4000, "Karim", [])
    amana = carrier(c)
    add(orders, "NAYO-1", status="awaiting_details", carrier_id=str(amana["id"]))
    c.post("/admin/order/NAYO-1/status", json={"status": "confirmed"})
    assert stock.current()[0] == 9
    c.post("/admin/delivery/bulk", json={"order_numbers": ["NAYO-1"], "status": "shipped"})
    c.post("/admin/delivery/bulk", json={"order_numbers": ["NAYO-1"], "status": "delivered"})
    assert stock.current()[0] == 9 and orders.get("NAYO-1")["cod_status"] == "with_carrier"
    c.post("/admin/order/NAYO-1/status", json={"status": "returned", "recoverable": False})  # lost in transit
    o = orders.get("NAYO-1")
    assert (o["cod_status"], o["carrier_fee_cents"]) == ("none", "1500") and stock.current()[0] == 9  # written off
    ret = c.get("/admin/returns").json()["items"][0]
    assert ret["order_number"] == "NAYO-1" and ret["loss_cents"] == 1500 + 4000  # fee + unit written off
    c.post("/admin/order/NAYO-1/status", json={"status": "confirmed"})  # back on: COD cleared
    o = orders.get("NAYO-1")
    assert (o["cod_status"], o["carrier_fee_cents"]) == ("", "")


def test_bulk_reports_per_order_errors(env):
    c, orders, stock, store = env
    login(c)
    amana = carrier(c)
    add(orders, "NAYO-1")
    add(orders, "NAYO-2", status="new")
    r = c.post("/admin/delivery/bulk", json={"order_numbers": ["NAYO-1", "NAYO-2", "NAYO-9"], "status": "delivered",
                                             "carrier_id": amana["id"]}).json()
    assert r["done"] == ["NAYO-1"] and set(r["errors"]) == {"NAYO-2", "NAYO-9"}
    assert c.post("/admin/delivery/bulk", json={"order_numbers": ["NAYO-1"]}).status_code == 422


def test_board_counts_and_slips(env):
    c, orders, stock, store = env
    login(c)
    add(orders, "NAYO-1")
    add(orders, "NAYO-2")
    add(orders, "NAYO-3", status="shipped")
    b = c.get("/admin/delivery?status=confirmed").json()
    assert [o["order_number"] for o in b["items"]] == ["NAYO-1", "NAYO-2"] and b["counts"] == {"confirmed": 2, "shipped": 1}
    s = c.get("/admin/delivery/slips?numbers=NAYO-1,NAYO-3").json()
    assert [x["order_number"] for x in s["items"]] == ["NAYO-1", "NAYO-3"] and s["company"]["name"] == "NAYO"
    assert s["items"][0]["total"] == "209" and s["items"][0]["address"] == "hay salam"


def test_agent_sees_board_but_no_money(env):
    c, orders, stock, store = env
    login(c)
    amana = carrier(c)
    add(orders, "NAYO-1", carrier_id=str(amana["id"]))
    c.post("/admin/order/NAYO-1/status", json={"status": "delivered"})
    login(c, "agent")
    assert set(c.get("/admin/carriers").json()["items"][0]) == {"id", "name", "phone", "active"}
    b = c.get("/admin/delivery?status=delivered").json()
    assert "carrier_fee_cents" not in b["items"][0]
    detail = c.get("/admin/orders/NAYO-1").json()["order"]
    assert "carrier_fee_cents" not in detail and "cod_amount_cents" not in detail
    for path in ("/admin/cod/summary", f"/admin/cod/pending?carrier_id={amana['id']}", "/admin/remittances", "/admin/returns"):
        assert c.get(path).status_code == 403
    assert c.post("/admin/carriers", json={"name": "X"}).status_code == 403
    assert c.patch("/admin/orders/NAYO-1", json={"carrier_fee": 1}).status_code == 403
    # agents can still move orders along the delivery board
    add(orders, "NAYO-2")
    assert c.post("/admin/delivery/bulk", json={"order_numbers": ["NAYO-2"], "status": "shipped"}).json()["done"] == ["NAYO-2"]
