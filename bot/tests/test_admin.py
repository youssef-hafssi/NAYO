"""Admin inbox: takeover silences the bot, login/session, inbox API."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password, make_session, read_session, verify_password
from app.main import Services, create_app

from .conftest import CLIENT


# ---------------------------------------------------------------- takeover (bot side)
def test_taken_over_conversation_only_stores_messages(say, orders, wa, ai, store):
    orders.add("NAYO-1043", "Salma", CLIENT, status="awaiting_details", city="Agadir", address="hay salam")
    store.update_conv(CLIENT, order_number="NAYO-1043", stage="await_yes", taken_over_by="Sara")
    ai.push("confirm", "x")
    ai.push("cancel", "x")
    say("wakha")
    say("lla, bghit nlghi")
    o = orders.get("NAYO-1043")
    assert ai.calls == [] and wa.sent == []  # no AI, no auto-reply
    assert (o["status"], o["quantity"]) == ("awaiting_details", "1")  # no order change
    assert [m["text"] for m in store.thread(CLIENT)] == ["wakha", "lla, bghit nlghi"]  # stored only

    store.update_conv(CLIENT, taken_over_by=None)  # released
    say("wakha")
    assert ai.calls and status_of(orders) == "confirmed"  # bot handles the next message


def status_of(orders):
    return orders.get("NAYO-1043")["status"]


def test_agent_send_respects_24h_window_and_takes_over(bot, store, wa):
    assert bot.send_as_agent(CLIENT, "Bonjour", "Sara") == "window_closed"  # client never wrote
    store.touch_client(CLIENT, bot.clock())
    assert bot.send_as_agent(CLIENT, "Bonjour", "Sara") == "sent"
    assert wa.to(CLIENT) == ["Bonjour"] and store.get_conv(CLIENT).taken_over_by == "Sara"
    assert store.thread(CLIENT)[-1] == {**store.thread(CLIENT)[-1], "role": "agent", "agent_name": "Sara"}
    store.update_conv(CLIENT, last_client_at=bot.clock() - 25 * 3600)
    assert bot.send_as_agent(CLIENT, "encore", "Sara") == "window_closed"


# ---------------------------------------------------------------- auth helpers
def test_password_hash_and_session():
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h) and not verify_password("wrong", h)
    assert "correct" not in h
    tok = make_session("s3cret", "abc", 60, now=1000)
    assert read_session("s3cret", tok, now=1030) == "abc"
    assert read_session("s3cret", tok, now=2000) is None  # expired
    assert read_session("other", tok, now=1030) is None  # wrong key
    payload, sig = tok.split(".")
    assert read_session("s3cret", payload + "x." + sig, now=1030) is None  # tampered


# ---------------------------------------------------------------- API
@pytest.fixture
def admin_client(settings, orders, store, bot):
    settings.admin_secret = "test-admin-secret"
    store.upsert_admin(uuid.uuid4().hex, "sara@nayo.ma", hash_password("motdepasse123"), "Sara")
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        yield c


def login(c):
    r = c.post("/admin/login", json={"email": "Sara@nayo.ma", "password": "motdepasse123"})
    assert r.status_code == 200 and r.json()["name"] == "Sara"


def test_admin_requires_login(admin_client):
    assert admin_client.get("/admin/conversations").status_code == 401
    assert admin_client.post("/admin/login", json={"email": "sara@nayo.ma", "password": "nope"}).status_code == 401
    assert admin_client.post("/admin/login", json={"email": "x@y.z", "password": "nope"}).status_code == 401
    admin_client.cookies.set("nayo_admin", "forged.cookie")
    assert admin_client.get("/admin/me").status_code == 401


def test_login_rate_limited(admin_client):
    codes = [admin_client.post("/admin/login", json={"email": "sara@nayo.ma", "password": "bad"}).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429


def test_inbox_flow(admin_client, orders, store, bot, wa, say, ai):
    orders.add("NAYO-1043", "Salma", CLIENT, status="needs_human", city="Agadir", address="hay salam")
    orders.add("NAYO-1050", "Imane", "212699999999", status="confirmed")
    ai.push("question", "189 MAD")
    say("chhal taman?")
    say("allo", sender="212699999999")
    login(admin_client)

    r = admin_client.get("/admin/conversations").json()
    assert {i["phone"] for i in r["items"]} == {CLIENT, "212699999999"} and r["online"] == 1
    item = next(i for i in r["items"] if i["phone"] == CLIENT)
    assert (item["name"], item["order_number"], item["status"], item["unread"]) == ("Salma", "NAYO-1043", "needs_human", 1)
    assert [i["phone"] for i in admin_client.get("/admin/conversations?filter=confirmed").json()["items"]] == ["212699999999"]
    assert admin_client.get("/admin/conversations?filter=nope").status_code == 400

    t = admin_client.get(f"/admin/conversations/{CLIENT}/messages").json()
    assert [m["role"] for m in t["messages"]] == ["client", "bot"]
    assert t["order"]["total"] == 209 and t["order"]["address"] == "hay salam" and t["conversation"]["window_open"]
    after = next(i for i in admin_client.get("/admin/conversations").json()["items"] if i["phone"] == CLIENT)
    assert after["unread"] == 0  # opening the thread marks it read

    r = admin_client.post(f"/admin/conversations/{CLIENT}/send", json={"text": "Bonjour Salma, c'est Sara 🙂"})
    assert r.status_code == 200 and wa.to(CLIENT)[-1] == "Bonjour Salma, c'est Sara 🙂"
    assert store.get_conv(CLIENT).taken_over_by == "Sara"
    assert admin_client.get(f"/admin/conversations/{CLIENT}/messages").json()["messages"][-1]["agent_name"] == "Sara"

    assert admin_client.post(f"/admin/conversations/{CLIENT}/release").json() == {"taken_over_by": None}
    assert admin_client.post(f"/admin/conversations/{CLIENT}/takeover").json() == {"taken_over_by": "Sara"}

    assert admin_client.post("/admin/order/NAYO-1043/status", json={"status": "confirmed"}).status_code == 200
    o = orders.get("NAYO-1043")
    assert o["status"] == "confirmed" and "[Sara] statut → confirmed" in o["notes"]
    assert admin_client.post("/admin/order/NAYO-1043/status", json={"status": "new"}).status_code == 400
    assert admin_client.post("/admin/order/NAYO-9999/status", json={"status": "confirmed"}).status_code == 404

    assert admin_client.post(f"/admin/conversations/{CLIENT}/notes", json={"notes": "Rappeler après 18h"}).status_code == 200
    assert admin_client.get(f"/admin/conversations/{CLIENT}/messages").json()["conversation"]["internal_notes"] == "Rappeler après 18h"


def test_agent_send_outside_window_is_refused(admin_client, store, wa):
    store.update_conv(CLIENT, last_client_at=1.0)
    store.add_message(CLIENT, "client", "old message", now=1.0)
    login(admin_client)
    r = admin_client.post(f"/admin/conversations/{CLIENT}/send", json={"text": "hello"})
    assert r.status_code == 409 and wa.sent == []
