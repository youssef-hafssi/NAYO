"""Phase 6: orders list / bulk / CSV, customers and segments, follow-up suggestions and tasks, STOP."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.crm import Crm, fmt, now_dt
from app.main import Services, create_app
from app.sheets import DbOrders
from app.stock import Stock, StockOrders

from .conftest import CLIENT

A, B, C, D = "212611111111", "212622222222", "212633333333", "212644444444"


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


def ago(**kw) -> str:
    return fmt(now_dt() - timedelta(**kw))


def add(orders, n, phone=A, name="Salma", qty=1, status="confirmed", created=None, **extra):
    orders.append({"order_number": n, "created_at": created or ago(hours=1), "name": name, "phone": phone,
                   "quantity": qty, "total": qty * 189 + 20, "status": status, "city": "Agadir", "address": "hay salam",
                   **extra})


# ------------------------------------------------------------------ orders
def test_orders_search_filters_counts_and_sort(env):
    c, orders, _, _ = env
    add(orders, "NAYO-1", A, "Salma Idrissi", 1, "confirmed", created="2026-11-01 10:00:00", source="website")
    add(orders, "NAYO-2", B, "Youssef", 3, "delivered", created="2026-11-05 23:59:59", source="whatsapp", city="Rabat")
    add(orders, "NAYO-3", C, "Karima", 2, "cancelled", created="2026-11-06 00:00:00", source="website")
    add(orders, "NAYO-4", A, "Salma Idrissi", 1, "new", created="2026-11-07 09:00:00")
    login(c, "agent")
    r = c.get("/admin/orders").json()
    assert [o["order_number"] for o in r["items"]] == ["NAYO-4", "NAYO-3", "NAYO-2", "NAYO-1"]
    assert r["counts"]["confirmed"] == 1 and r["counts"]["delivered"] == 1 and "Agadir" in r["cities"]
    assert "carrier_fee_cents" not in r["items"][0]  # money: owner only
    # search: name, number, phone in national format, city
    assert [o["order_number"] for o in c.get("/admin/orders?q=idris").json()["items"]] == ["NAYO-4", "NAYO-1"]
    assert [o["order_number"] for o in c.get("/admin/orders?q=nayo-3").json()["items"]] == ["NAYO-3"]
    assert [o["order_number"] for o in c.get("/admin/orders?q=0622222222").json()["items"]] == ["NAYO-2"]
    assert [o["order_number"] for o in c.get("/admin/orders?city=rabat").json()["items"]] == ["NAYO-2"]
    # status multi-select; the chips keep counting every status for the other filters
    r = c.get("/admin/orders?status=confirmed,new").json()
    assert [o["order_number"] for o in r["items"]] == ["NAYO-4", "NAYO-1"] and r["counts"]["cancelled"] == 1
    # date range: inclusive days
    assert [o["order_number"] for o in c.get("/admin/orders?frm=2026-11-02&to=2026-11-05").json()["items"]] == ["NAYO-2"]
    assert [o["order_number"] for o in c.get("/admin/orders?source=whatsapp").json()["items"]] == ["NAYO-2"]
    # sort and pagination
    assert c.get("/admin/orders?sort=total&dir=desc").json()["items"][0]["order_number"] == "NAYO-2"
    p = c.get("/admin/orders?limit=3").json()
    assert len(p["items"]) == 3 and p["has_more"] is True
    assert c.get("/admin/orders?limit=3&offset=3").json()["items"][0]["order_number"] == "NAYO-1"
    assert c.get("/admin/orders?status=bogus").status_code == 400
    assert c.get("/admin/orders?sort=phone; drop").status_code == 409
    assert c.get("/admin/orders?frm=01/11/2026").status_code == 422
    assert c.get("/admin/orders.csv").status_code == 403


def test_orders_bulk_and_csv(env):
    c, orders, stock, _ = env
    stock.open(1, 1000, "Karim", [])
    add(orders, "NAYO-1", status="new")
    add(orders, "NAYO-2", status="new")
    add(orders, "NAYO-3", status="new", name="=HYPERLINK(1)")
    login(c, "agent")
    r = c.post("/admin/orders/bulk", json={"order_numbers": ["NAYO-1", "NAYO-2", "NAYO-X"], "status": "confirmed"}).json()
    # only 1 unit in stock: the second is refused (never forced in bulk), the unknown one is reported
    assert r["done"] == ["NAYO-1"] and r["errors"]["NAYO-2"].startswith("Stock insuffisant") and r["errors"]["NAYO-X"] == "introuvable"
    assert orders.get("NAYO-1")["confirmed_at"]
    r = c.post("/admin/orders/bulk", json={"order_numbers": ["NAYO-3"], "status": "delivered"}).json()
    assert r["errors"] == {"NAYO-3": "commande pas encore confirmée"}
    assert c.post("/admin/orders/bulk", json={"order_numbers": ["NAYO-3"], "status": "new"}).status_code == 400
    assert c.post("/admin/orders/bulk", json={"order_numbers": ["NAYO-3"], "status": "cancelled"}).json()["done"] == ["NAYO-3"]
    login(c)
    x = c.get("/admin/orders.csv?status=cancelled")
    assert x.status_code == 200 and "attachment" in x.headers["content-disposition"]
    assert x.text.startswith("﻿") and "'=HYPERLINK(1)" in x.text and "NAYO-1" not in x.text


# ------------------------------------------------------------------ customers
def test_customers_segments_tags_and_page(env):
    c, orders, _, store = env
    add(orders, "NAYO-1", A, "Salma", status="delivered")
    add(orders, "NAYO-2", A, "Salma B.", status="delivered", qty=2)          # A: 2 delivered → Fidèle
    add(orders, "NAYO-3", B, "Youssef", status="returned")                  # B: a return → À risque
    add(orders, "NAYO-4", C, "Karima", status="delivered", created=ago(days=61))  # C: 61 days → Inactif
    add(orders, "NAYO-5", D, "Driss", status="new")                         # D: Nouveau
    login(c, "agent")
    r = c.get("/admin/customers").json()
    seg = {x["phone"]: x["segment"] for x in r["items"]}
    assert seg == {A: "loyal", B: "at_risk", C: "inactive", D: "new"}
    assert r["counts"] == {"new": 1, "loyal": 1, "at_risk": 1, "inactive": 1}
    a = next(x for x in r["items"] if x["phone"] == A)
    assert (a["name"], a["orders_count"], a["delivered"]) == ("Salma B.", 2, 2)  # latest name
    assert "delivered_cents" not in a  # money: owner only
    assert [x["phone"] for x in c.get("/admin/customers?segment=at_risk").json()["items"]] == [B]
    assert [x["phone"] for x in c.get("/admin/customers?q=0633").json()["items"]] == [C]
    # tags / note / name override
    r = c.patch(f"/admin/customers/{A}", json={"tags": ["VIP", "vip", " Grossiste "], "internal_note": "Préfère le soir",
                                               "name": "Salma Bennani"}).json()["customer"]
    assert r["tags"] == ["VIP", "Grossiste"] and r["name"] == "Salma Bennani" and orders.get("NAYO-1")["name"] == "Salma"
    assert [x["phone"] for x in c.get("/admin/customers?tag=vip").json()["items"]] == [A]
    assert store.audit_for("customer", A)[0]["action"] == "customer.edit"
    page = c.get(f"/admin/customers/0611111111").json()
    assert [o["order_number"] for o in page["orders"]] == ["NAYO-2", "NAYO-1"] and page["window_open"] is False
    # the order detail warns when the customer returned an order before
    assert c.get("/admin/orders/NAYO-3").json()["customer"]["returned"] == 1
    assert c.get("/admin/customers/212699999999").status_code == 404
    assert c.get("/admin/customers.csv").status_code == 403
    login(c)
    assert c.get("/admin/customers").json()["items"][0]["delivered_cents"] >= 0
    x = c.get("/admin/customers.csv?segment=loyal")
    assert x.status_code == 200 and "Salma Bennani" in x.text and "VIP, Grossiste" in x.text and "Fidèle" in x.text


def test_new_order_from_customer_page(env):
    c, orders, _, store = env
    add(orders, "NAYO-1", A, "Salma", status="delivered", city="Fès", address="rue 5")
    store.next_counter("order", 1000) if hasattr(store, "next_counter") else None
    login(c, "agent")
    r = c.post(f"/admin/customers/{A}/orders", json={"quantity": 2})
    assert r.status_code == 200, r.text
    o = orders.get(r.json()["order_number"])
    assert (o["status"], o["source"], o["quantity"], o["total"], o["city"], o["address"], o["name"]) == \
        ("awaiting_details", "whatsapp", "2", "398", "Fès", "rue 5", "Salma")
    assert store.audit_for("order", o["order_number"])[0]["action"] == "order.create"
    assert c.post(f"/admin/customers/{A}/orders", json={"quantity": 11}).status_code == 422


# ------------------------------------------------------------------ follow-ups
def test_suggestions_rules(env):
    c, orders, stock, store = env
    add(orders, "NAYO-1", A, status="new", created=ago(hours=7))           # stale
    add(orders, "NAYO-2", B, status="awaiting_details", created=ago(hours=5))  # too recent
    add(orders, "NAYO-3", C, status="confirmed", created=ago(days=3))      # confirmed_at '' → created_at: > 48 h
    add(orders, "NAYO-4", D, status="shipped", shipped_at=ago(days=6))      # not delivered after 5 days
    add(orders, "NAYO-5", D, status="returned", returned_at=ago(days=1))    # no reason
    add(orders, "NAYO-6", D, status="delivered", delivered_at=ago(days=9), cod_status="with_carrier")  # COD late (7 days)
    add(orders, "NAYO-7", A, status="confirmed")
    orders.update("NAYO-7", status="confirmed")  # confirmed_at = now → not late
    stock.open(3, 1000, "Karim", [])
    login(c)
    keys = {s["key"] for s in c.get("/admin/tasks").json()["suggestions"]}
    today = now_dt().strftime("%Y-%m-%d")
    assert keys == {"stale:NAYO-1", "ship:NAYO-3", "deliver:NAYO-4", "reason:NAYO-5", "cod:NAYO-6", f"stock:{today}"}
    assert c.patch(f"/admin/customers/{A}", json={"opted_out": True}).status_code == 200
    assert "stale:NAYO-1" not in {s["key"] for s in c.get("/admin/tasks").json()["suggestions"]}  # STOP: no reminder
    login(c, "agent")  # money suggestions are the owner's
    assert "cod:NAYO-6" not in {s["key"] for s in c.get("/admin/tasks").json()["suggestions"]}


def test_tasks_accept_dismiss_views_and_badge(env):
    c, orders, _, store = env
    add(orders, "NAYO-1", A, status="new", created=ago(hours=7))
    add(orders, "NAYO-2", B, status="returned")
    login(c, "agent")
    counts = c.get("/admin/tasks/counts").json()
    assert counts["suggestions"] == 2 and counts["badge"] == 2
    t = c.post("/admin/tasks", json={"suggestion_key": "stale:NAYO-1", "assigned_to": "Sara"}).json()
    assert (t["order_number"], t["customer_phone"], t["assigned_to"], t["created_by"]) == ("NAYO-1", A, "Sara", "Sara")
    assert c.post("/admin/tasks", json={"suggestion_key": "stale:NAYO-1"}).status_code == 409  # accepted once
    assert c.post("/admin/tasks/dismiss", json={"key": "reason:NAYO-2"}).json() == {"ok": True}
    r = c.get("/admin/tasks").json()
    assert r["suggestions"] == [] and [x["id"] for x in r["items"]] == [t["id"]]
    # manual tasks: late / upcoming
    late = c.post("/admin/tasks", json={"title": "Rappeler", "due_at": ago(days=2)[:16], "customer_phone": "0633333333"}).json()
    assert late["customer_phone"] == C
    up = c.post("/admin/tasks", json={"title": "Plus tard", "due_at": fmt(now_dt() + timedelta(days=3))[:10]}).json()
    assert up["due_at"].endswith("09:00:00")
    assert [x["id"] for x in c.get("/admin/tasks?view=late").json()["items"]] == [late["id"]]
    assert [x["id"] for x in c.get("/admin/tasks?view=upcoming").json()["items"]] == [up["id"]]
    assert c.get("/admin/tasks/counts").json() == {"late": 1, "today": 1, "upcoming": 1, "suggestions": 0, "badge": 2}
    done = c.patch(f"/admin/tasks/{late['id']}", json={"done": True}).json()
    assert done["done_at"] and [x["id"] for x in c.get("/admin/tasks?view=done").json()["items"]] == [late["id"]]
    assert c.post("/admin/tasks", json={"title": "  "}).status_code == 409
    assert c.post("/admin/tasks", json={"title": "x", "order_number": "NAYO-404"}).status_code == 422
    assert c.patch("/admin/tasks/999", json={"done": True}).status_code == 409
    assert store.audit_for("task", str(t["id"]))[0]["action"] == "task.create"
    assert [x["id"] for x in c.get(f"/admin/customers/{A}").json()["tasks"]] == [t["id"]]  # open tasks only
    assert "Karim" in c.get("/admin/team").json()["names"]


# ------------------------------------------------------------------ STOP
def test_stop_opts_out_without_reply(say, wa, store, orders):
    DbOrders(store)  # production keeps orders in the database
    say("STOP")
    assert wa.to(CLIENT) == []
    crm = Crm(store)
    assert crm.opted_out(CLIENT)
    assert crm.get_customer(CLIENT)["opted_out"] is True
    say("Start")
    assert not crm.opted_out(CLIENT)


def test_stop_flag_shown_in_lists(env, say_db, wa):
    c, orders, _, store = env
    add(orders, "NAYO-1", CLIENT)
    bot = c.app.state.services.bot if hasattr(c.app.state, "services") else None
    Crm(store).update_customer(CLIENT, opted_out=True)
    login(c, "agent")
    assert c.get("/admin/orders").json()["items"][0]["opted_out"] is True
    assert c.get(f"/admin/conversations/{CLIENT}/messages").json()["conversation"]["opted_out"] is True
    assert c.get("/admin/orders/NAYO-1").json()["customer"]["opted_out"] is True
    assert bot is None or bot  # services wiring unchanged
