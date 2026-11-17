"""Reviews: asked once 3 days after delivery inside the 24 h window, STOP respected, reply stored on the customer."""

import time
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.crm import Crm, fmt, now_dt
from app.flow import Bot
from app.main import Services, create_app
from app.sheets import DbOrders

from .conftest import CLIENT

B, C, D, E = "212622222222", "212633333333", "212644444444", "212655555555"


@pytest.fixture
def env(store, wa, ai):
    orders = DbOrders(store)
    bot = Bot(orders, store, wa, ai, clock=time.time)
    return bot, orders, store, Crm(store)


def deliver(orders, n, phone, days_ago, name="Salma Kettani"):
    orders.append({"order_number": n, "created_at": fmt(now_dt() - timedelta(days=days_ago + 2)), "name": name,
                   "phone": phone, "quantity": 1, "total": 209, "status": "delivered",
                   "delivered_at": fmt(now_dt() - timedelta(days=days_ago))})


def test_asked_once_only_when_due_and_window_open(env, wa):
    bot, orders, store, crm = env
    now = time.time()
    deliver(orders, "N1", CLIENT, 4)                      # due, window open → asked
    deliver(orders, "N2", B, 1)                           # delivered yesterday → too early
    deliver(orders, "N3", C, 5)                           # window closed (last message 30 h ago)
    deliver(orders, "N4", D, 5)                           # wrote STOP
    deliver(orders, "N5", E, 5)                           # has an order in progress → not now
    orders.append({"order_number": "N6", "created_at": fmt(now_dt()), "name": "X", "phone": E, "quantity": 1,
                   "total": 209, "status": "awaiting_details"})
    for p in (CLIENT, B, D, E):
        store.touch_client(p, now - 3600)
    store.touch_client(C, now - 30 * 3600)
    crm.update_customer(D, opted_out=True)
    assert bot.ask_reviews() == 1
    assert [p for p, _ in wa.sent] == [CLIENT] and "satisfaite" in wa.sent[0][1] and "Salma" in wa.sent[0][1]
    assert store.get_conv(CLIENT).stage.startswith("review:N1:")
    assert bot.ask_reviews() == 0  # once per order


def test_review_reply_is_stored_with_tag_and_thanked(env, wa, say_db):
    bot, orders, store, crm = env
    deliver(orders, "N1", CLIENT, 4)
    store.touch_client(CLIENT, time.time() - 600)
    bot.ask_reviews()
    say_db(bot, "Très contente, mes aisselles sont plus claires 😍")
    c = crm.get_customer(CLIENT)
    assert c["review_text"] == "Très contente, mes aisselles sont plus claires 😍" and c["review_order"] == "N1"
    assert "Avis" in c["tags"] and "Merci beaucoup pour votre avis" in wa.to(CLIENT)[-1]
    assert store.get_conv(CLIENT).stage == ""


def test_decline_question_and_stop(env, wa, ai, say_db):
    bot, orders, store, crm = env
    for n, p in (("N1", CLIENT), ("N2", B), ("N3", C)):
        deliver(orders, n, p, 4)
        store.touch_client(p, time.time() - 600)
    assert bot.ask_reviews() == 3
    say_db(bot, "Non merci", sender=CLIENT)                 # declined: no tag, polite answer
    c = crm.get_customer(CLIENT)
    assert c["review_text"] == "" and "Avis" not in c["tags"] and "Pas de souci" in wa.to(CLIENT)[-1]
    ai.push("other", "Votre commande N2 est livrée.")
    say_db(bot, "elle arrive quand ma prochaine commande ?", sender=B)  # a question: not a review
    assert crm.get_customer(B)["review_text"] == "" and store.get_conv(B).stage == ""
    say_db(bot, "STOP", sender=C)                           # STOP wins: opted out, nothing stored, no reply
    assert crm.opted_out(C) and crm.get_customer(C)["review_text"] == ""
    assert wa.to(C)[-1].startswith("Bonjour") or "satisfaite" in wa.to(C)[-1]  # last message is still the question


def test_late_reply_is_not_a_review(env, wa, ai, say_db):
    bot, orders, store, crm = env
    deliver(orders, "N1", CLIENT, 4)
    store.touch_client(CLIENT, time.time() - 600)
    bot.ask_reviews()
    store.update_conv(CLIENT, stage=f"review:N1:{int(time.time()) - 4 * 86400}")  # asked 4 days ago
    ai.push("other", "ok")
    say_db(bot, "Bonjour je veux commander encore")
    assert crm.get_customer(CLIENT)["review_text"] == ""


def test_cron_endpoint_and_admin_view(settings, store, wa, ai):
    settings.admin_secret = "test-admin-secret"
    orders = DbOrders(store)
    bot = Bot(orders, store, wa, ai, clock=time.time)
    # Clients and the CSV exports are superadmin-only: "owner" here is the superadmin (owners: test_access.py)
    store.set_superadmin("owner@nayo.ma", "Karim", hash_password("motdepasse123"))
    deliver(orders, "N1", CLIENT, 4)
    store.touch_client(CLIENT, time.time() - 600)
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        assert c.get("/cron/review-requests").status_code == 503  # CRON_SECRET not set: disabled
        settings.cron_secret = "cron-s3cret"
        assert c.get("/cron/review-requests", headers={"Authorization": "Bearer nope"}).status_code == 401
        r = c.get("/cron/review-requests", headers={"Authorization": "Bearer cron-s3cret"})
        assert r.json() == {"asked": 1}
        Crm(store).save_review("N1", CLIENT, "Super produit", False)
        c.post("/admin/login", json={"email": "owner@nayo.ma", "password": "motdepasse123"})
        cust = c.get(f"/admin/customers/{CLIENT}").json()["customer"]
        assert cust["review_text"] == "Super produit" and "Avis" in cust["tags"]
        assert [x["phone"] for x in c.get("/admin/customers?tag=avis").json()["items"]] == [CLIENT]
