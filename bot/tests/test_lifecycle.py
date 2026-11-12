"""Phase 1: order lifecycle (shipped / delivered / returned), admin edits + audit, password change, roles."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.flow import Bot
from app.main import Services, create_app
from app.sheets import DbOrders, MirroredOrders
from app.texts import ESCALATE

from .conftest import CLIENT, OWNER


class Resp:
    status_code, text = 200, '{"ok":true}'


@pytest.fixture
def db_setup(settings, store, wa, ai, clock):
    """Real DbOrders (extra columns) wrapped by the Sheet mirror, as in production."""
    posted = []
    orders = MirroredOrders(DbOrders(store), "https://script.example/exec", "s",
                            post=lambda url, json: posted.append(json["order"]) or Resp())
    bot = Bot(orders, store, wa, ai, owner=OWNER, clock=clock)
    settings.admin_secret = "test-admin-secret"
    store.upsert_admin(uuid.uuid4().hex, "owner@nayo.ma", hash_password("motdepasse-owner"), "Karim", "owner")
    store.upsert_admin(uuid.uuid4().hex, "agent@nayo.ma", hash_password("motdepasse-agent"), "Sara", "agent")
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        yield c, orders, posted, bot


def login(c, who="owner"):
    r = c.post("/admin/login", json={"email": f"{who}@nayo.ma", "password": f"motdepasse-{who}"})
    assert r.status_code == 200


def add(orders, number="NAYO-1001", status="confirmed", quantity=1, **extra):
    orders.append({"order_number": number, "created_at": "2026-11-12 10:00:00", "name": "Salma", "phone": CLIENT,
                   "quantity": quantity, "total": quantity * 189 + 20, "status": status, "city": "Agadir",
                   "address": "hay salam", **extra})


# ---------------------------------------------------------------- transitions
def test_status_transitions_shipped_delivered_returned(db_setup, store):
    c, orders, posted, _ = db_setup
    add(orders)
    login(c)
    assert c.post("/admin/order/NAYO-1001/status", json={"status": "shipped"}).status_code == 200
    assert orders.get("NAYO-1001")["status"] == "shipped"
    assert c.post("/admin/order/NAYO-1001/status", json={"status": "delivered"}).status_code == 200
    o = orders.get("NAYO-1001")
    assert o["status"] == "delivered" and o["delivered_at"].startswith("20")
    add(orders, "NAYO-1002")
    r = c.post("/admin/order/NAYO-1002/status", json={"status": "returned", "return_reason": "Client absent"})
    assert r.status_code == 200 and orders.get("NAYO-1002")["return_reason"] == "Client absent"
    assert c.post("/admin/order/NAYO-1002/status", json={"status": "lost"}).status_code == 400
    assert [p["status"] for p in posted if p["order_number"] == "NAYO-1001"][-2:] == ["shipped", "delivered"]
    assert "return_reason" not in posted[-1]  # the Sheet keeps its 12 columns
    history = store.audit_for("order", "NAYO-1002")
    assert history[0]["action"] == "order.status" and "returned" in history[0]["details"]


# ---------------------------------------------------------------- edits
def test_edit_quantity_recomputes_total_audits_and_mirrors(db_setup, store):
    c, orders, posted, _ = db_setup
    add(orders)
    login(c)
    r = c.patch("/admin/orders/NAYO-1001", json={"quantity": 3, "city": "  Rabat ", "carrier": "Amana", "tracking": "AM123"})
    assert r.status_code == 200 and set(r.json()["changed"]) == {"quantity", "city", "carrier", "tracking"}
    o = orders.get("NAYO-1001")
    assert (o["quantity"], o["total"], o["city"], o["carrier"], o["tracking"]) == ("3", "587", "Rabat", "Amana", "AM123")
    assert posted[-1]["total"] == "587" and posted[-1]["city"] == "Rabat"  # Sheet mirror got the change
    assert "carrier" not in posted[-1]
    edits = [h for h in store.audit_for("order", "NAYO-1001") if h["action"] == "order.edit"]
    assert len(edits) == 4 and all(h["admin_name"] == "Karim" for h in edits)
    detail = c.get("/admin/orders/NAYO-1001").json()
    assert detail["last_modified"]["admin_name"] == "Karim" and detail["order"]["carrier"] == "Amana"

    # unchanged values → nothing written, nothing audited
    n = len(store.audit_for("order", "NAYO-1001"))
    assert c.patch("/admin/orders/NAYO-1001", json={"city": "Rabat"}).json()["changed"] == []
    assert len(store.audit_for("order", "NAYO-1001")) == n


def test_edit_validation(db_setup):
    c, orders, _, _ = db_setup
    add(orders)
    login(c)
    for bad in ({"quantity": 0}, {"quantity": 11}, {"phone": "abc"}, {"name": "x"}, {"status": "delivered"},
                {"address": "a" * 301}):
        assert c.patch("/admin/orders/NAYO-1001", json=bad).status_code == 422, bad
    assert c.patch("/admin/orders/NAYO-9999", json={"city": "x"}).status_code == 404
    assert c.patch("/admin/orders/NAYO-1001", json={"phone": "06 99 88 77 66"}).json()["order"]["phone"] == "212699887766"


# ---------------------------------------------------------------- bot on the new statuses
@pytest.mark.parametrize("status", ["shipped", "delivered"])
def test_bot_answers_questions_on_shipped_delivered(db_setup, ai, wa, say_db, status):
    c, orders, _, bot = db_setup
    add(orders, status=status)
    ai.push("question", "Paiement à la livraison.")
    say_db(bot, "kifach nkhless?")
    assert wa.to(CLIENT)[-1] == "Paiement à la livraison." and orders.get("NAYO-1001")["status"] == status


@pytest.mark.parametrize("status", ["shipped", "delivered"])
def test_bot_never_applies_changes_on_shipped_delivered(db_setup, ai, wa, say_db, status):
    c, orders, _, bot = db_setup
    add(orders, status=status, quantity=1)
    say_db(bot, "salam", sender=OWNER)
    ai.push("change_quantity", "x", quantity=3)
    say_db(bot, "rdha 3")
    o = orders.get("NAYO-1001")
    assert (o["status"], o["quantity"]) == (status, "1")  # nothing applied silently
    assert wa.to(CLIENT)[-1] == ESCALATE and "NAYO-1001" in wa.to(OWNER)[-1]
    ai.push("provide_details", "x", city="Rabat", address="Agdal")
    say_db(bot, "bdel l'adresse: Rabat Agdal")
    assert orders.get("NAYO-1001")["city"] == "Agadir"


def test_bot_treats_returned_like_cancelled(db_setup, ai, wa, say_db):
    c, orders, _, bot = db_setup
    add(orders, status="returned")
    ai.push("new_order", "x")
    say_db(bot, "bghit commande akhra")
    others = [n for n in ("NAYO-1001",) if orders.get(n)["status"] == "returned"]
    assert others == ["NAYO-1001"]  # the returned order is untouched
    assert "Combien" in wa.to(CLIENT)[-1]  # a new order was started


# ---------------------------------------------------------------- password + roles
def test_change_password(db_setup, store):
    c, _, _, _ = db_setup
    login(c)
    assert c.post("/admin/me/password", json={"current": "wrong", "new": "un-nouveau-mdp"}).status_code == 400
    assert c.post("/admin/me/password", json={"current": "motdepasse-owner", "new": "court"}).status_code == 422
    assert c.post("/admin/me/password", json={"current": "motdepasse-owner", "new": "motdepasse-owner"}).status_code == 400
    assert c.post("/admin/me/password", json={"current": "motdepasse-owner", "new": "un-nouveau-mdp"}).status_code == 200
    c.post("/admin/logout")
    assert c.post("/admin/login", json={"email": "owner@nayo.ma", "password": "motdepasse-owner"}).status_code == 401
    assert c.post("/admin/login", json={"email": "owner@nayo.ma", "password": "un-nouveau-mdp"}).status_code == 200
    assert any(h["action"] == "password.change" for h in store._audit_all())


def test_roles_in_me_and_existing_users_become_owner(db_setup, store):
    c, _, _, _ = db_setup
    login(c, "agent")
    assert c.get("/admin/me").json()["role"] == "agent"
    store._exec("UPDATE admin_users SET role = NULL WHERE email = ?", ("agent@nayo.ma",))
    store.__init__(store.backend, sqlite_path=store.sqlite_path)  # restart: migration backfills the role
    assert store.get_admin_by_email("agent@nayo.ma")["role"] == "owner"
