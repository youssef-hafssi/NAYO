"""Suppliers & purchase orders: landed cost, partial receipts, average cost, payments, debts, access."""

import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.main import Services, create_app
from app.purchasing import Purchasing, PurchasingError
from app.sheets import DbOrders
from app.stock import Stock, StockOrders


@pytest.fixture
def stock(store):
    return Stock(store)


@pytest.fixture
def pur(store, stock):
    return Purchasing(store, stock)


@pytest.fixture
def sup(pur):
    return pur.create_supplier("Atlas Cosmétiques", "0522000000", "Casablanca")


def po(pur, sup, **kw):
    args = dict(supplier_id=sup["id"], quantity=100, unit_cost_cents=4000, shipping_cost_cents=50000,
                other_costs_cents=10000, status="ordered", admin="Karim")
    args.update(kw)
    return pur.create_po(**args)


def test_numbering_and_totals(pur, sup):
    a, b = po(pur, sup), po(pur, sup, status="draft")
    assert (a["number"], b["number"]) == ("PO-0001", "PO-0002")
    assert a["total_cents"] == 100 * 4000 + 50000 + 10000
    assert a["landed_unit_cost_cents"] == 4000 + 600  # (500 + 100 MAD) spread over 100 units
    assert a["ordered_at"] and b["ordered_at"] is None


def test_partial_receipts_landed_cost_and_average(pur, sup, stock):
    stock.open(10, 3000, "Karim", [])  # 10 units at 30.00
    p = po(pur, sup)
    r = pur.receive(p["id"], 40, "Karim")
    assert r["landed_unit_cost_cents"] == 4600 and r["po"]["status"] == "partially_received"
    assert stock.current() == (50, round((10 * 3000 + 40 * 4600) / 50))
    with pytest.raises(PurchasingError, match="il reste 60"):
        pur.receive(p["id"], 61, "Karim")
    r = pur.receive(p["id"], 60, "Karim")
    assert r["po"]["status"] == "received" and r["po"]["remaining_qty"] == 0
    assert stock.current()[0] == 110
    m = stock.movements(limit=1)["items"][0]
    assert (m["reason"], m["unit_cost_cents"], m["delta"]) == ("purchase", 4600, 60)
    assert [x["quantity"] for x in pur.receipts(p["id"])] == [40, 60]
    with pytest.raises(PurchasingError):
        pur.receive(p["id"], 1, "Karim")  # fully received: closed


def test_receive_needs_stock_tracking(pur, sup):
    with pytest.raises(PurchasingError, match="suivi du stock"):
        pur.receive(po(pur, sup)["id"], 1, "Karim")


def test_concurrent_receipts_never_exceed_the_ordered_quantity(pur, sup, stock):
    stock.open(0, 0, "Karim", [])
    p = po(pur, sup, quantity=10)
    ok, barrier = [], threading.Barrier(4)

    def take():
        barrier.wait()
        try:
            pur.receive(p["id"], 4, "Karim")
            ok.append(1)
        except PurchasingError:
            pass

    threads = [threading.Thread(target=take) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 2 and pur.get_po(p["id"])["received_qty"] == 8 and stock.current()[0] == 8


def test_payments_status_and_debts(pur, sup):
    p = po(pur, sup)  # total 4 600.00 MAD
    assert pur.get_po(p["id"])["payment_status"] == "unpaid"
    pur.add_payment(p["id"], 100000, "virement", "Karim")
    q = pur.get_po(p["id"])
    assert (q["payment_status"], q["paid_cents"], q["due_cents"]) == ("partial", 100000, 360000)
    with pytest.raises(PurchasingError, match="reste à payer"):
        pur.add_payment(p["id"], 360001, "cash", "Karim")
    pur.add_payment(p["id"], 360000, "cash", "Karim")
    assert pur.get_po(p["id"])["payment_status"] == "paid"

    other = po(pur, sup, quantity=10, unit_cost_cents=5000, shipping_cost_cents=0, other_costs_cents=0)  # 500 MAD
    draft = po(pur, sup, status="draft")
    cancelled = po(pur, sup, quantity=1)
    pur.set_status(cancelled["id"], "cancelled")
    assert pur.summary() == {"debts_cents": 50000, "open": 2, "late": 0}  # paid PO 0, other 500, draft/cancelled excluded
    with pytest.raises(PurchasingError):
        pur.add_payment(draft["id"], 100, "cash", "Karim")  # not ordered yet
    assert other["due_cents"] == 50000


def test_cancel_only_without_receipts_and_edit_rules(pur, sup, stock):
    stock.open(0, 0, "Karim", [])
    d = po(pur, sup, status="draft")
    d = pur.update_po(d["id"], quantity=50, unit_cost_cents=4500)
    assert (d["quantity"], d["unit_cost_cents"]) == (50, 4500)
    d = pur.set_status(d["id"], "ordered")
    with pytest.raises(PurchasingError, match="non modifiable"):
        pur.update_po(d["id"], quantity=60)
    assert pur.update_po(d["id"], expected_at="2026-12-01")["expected_at"] == "2026-12-01"
    pur.receive(d["id"], 5, "Karim")
    with pytest.raises(PurchasingError, match="annulation impossible"):
        pur.set_status(d["id"], "cancelled")


def test_late_purchase_orders(pur, sup):
    po(pur, sup, expected_at="2020-01-01")
    po(pur, sup, expected_at="2999-01-01")
    assert pur.summary()["late"] == 1
    assert [p["late"] for p in pur.list_pos(late=True)["items"]] == [True]


# ---------------------------------------------------------------- API
@pytest.fixture
def api(settings, store, bot, stock):
    settings.admin_secret = "test-admin-secret"
    orders = StockOrders(DbOrders(store), stock)
    store.upsert_admin(uuid.uuid4().hex, "owner@nayo.ma", hash_password("motdepasse123"), "Karim")
    store.upsert_admin(uuid.uuid4().hex, "agent@nayo.ma", hash_password("motdepasse123"), "Sara", role="agent")
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        yield c


def login(c, who):
    assert c.post("/admin/login", json={"email": f"{who}@nayo.ma", "password": "motdepasse123"}).status_code == 200


def test_api_flow_and_owner_only(api, stock):
    login(api, "agent")
    assert api.get("/admin/purchase-orders").status_code == 403
    assert api.get("/admin/suppliers").status_code == 403
    login(api, "owner")
    s = api.post("/admin/suppliers", json={"name": "Atlas", "city": "Casa"}).json()
    assert api.post("/admin/suppliers", json={"name": "X", "evil": 1}).status_code == 422
    p = api.post("/admin/purchase-orders", json={"supplier_id": s["id"], "quantity": 20, "unit_cost": 40.5,
                                                 "shipping_cost": 100, "status": "ordered", "expected_at": "2026-12-01"}).json()
    assert (p["number"], p["total_cents"], p["landed_unit_cost_cents"]) == ("PO-0001", 20 * 4050 + 10000, 4050 + 500)
    assert api.post(f"/admin/purchase-orders/{p['id']}/receive", json={"quantity": 5}).status_code == 409  # stock not started
    stock.open(0, 0, "Karim", [])
    r = api.post(f"/admin/purchase-orders/{p['id']}/receive", json={"quantity": 5}).json()
    assert r["on_hand"] == 5 and r["po"]["status"] == "partially_received"
    assert api.post(f"/admin/purchase-orders/{p['id']}/payments", json={"amount": 100, "method": "bitcoin"}).status_code == 422
    q = api.post(f"/admin/purchase-orders/{p['id']}/payments", json={"amount": 100, "method": "chèque"}).json()
    assert q["payment_status"] == "partial"
    d = api.get(f"/admin/purchase-orders/{p['id']}").json()
    assert len(d["receipts"]) == 1 and len(d["payments"]) == 1 and d["supplier"]["name"] == "Atlas"
    assert api.get("/admin/purchasing/summary").json()["debts_cents"] == 20 * 4050 + 10000 - 10000
    assert api.get("/admin/purchase-orders?status=nope").status_code == 400
    assert api.post(f"/admin/purchase-orders/{p['id']}/status", json={"status": "cancelled"}).status_code == 409
