"""Meta for cash on delivery: Lead at placement (browser + server, event_id = order number), Purchase when
confirmed, OrderDelivered / OrderReturned — each once per order, never older than 7 days, never blocking an order."""

import hashlib
import time
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.crm import fmt, now_dt
from app.main import Services, create_app
from app.meta import MetaCapi, MetaTracker, TrackedOrders, order_event, user_data
from app.sheets import DbOrders
from app.stock import Stock, StockOrders

from .conftest import CLIENT
from .test_orders_api import H, order


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class FakePost:
    def __init__(self, status=200, fail=False):
        self.calls, self.status, self.fail = [], status, fail

    def __call__(self, url, json):
        self.calls.append((url, json))
        if self.fail:
            raise ConnectionError("down")
        return type("R", (), {"status_code": self.status, "text": '{"events_received":1}'})()

    def events(self):
        return [c[1]["data"][0] for c in self.calls]

    def names(self):
        return [e["event_name"] for e in self.events()]


def capi(post, test_code=""):
    return MetaCapi("1490585709624189", "TOKEN-xyz", "v26.0", test_code, post=post)


def use_meta(client, post, test_code=""):
    client.app.state.meta_box["m"] = capi(post, test_code)


# ---------------------------------------------------------------- hashing / event shape
def test_user_data_is_normalized_and_hashed():
    ud = user_data(phone="212612345678", name="  Salma  Kettani ", city="Agadir", ip="1.2.3.4", user_agent="UA",
                   fbp="fb.1.1700000000000.123", fbc="fb.1.1700000000000.AbC", external_id="212612345678")
    assert ud["ph"] == [sha("212612345678")] and ud["fn"] == [sha("salma")] and ud["ln"] == [sha("kettani")]
    assert ud["ct"] == [sha("agadir")] and ud["country"] == [sha("ma")]
    assert (ud["client_ip_address"], ud["client_user_agent"], ud["fbp"], ud["fbc"]) == ("1.2.3.4", "UA", "fb.1.1700000000000.123", "fb.1.1700000000000.AbC")
    assert "212612345678" not in str({k: v for k, v in ud.items() if k != "client_ip_address"})  # never in clear
    assert user_data(city="Fès")["ct"] == [sha("fes")]


def test_order_event_shape():
    e = order_event("Purchase", order_number="NAYO-1001", value=209, quantity=1, ud={}, at=1800000000)
    assert (e["event_id"], e["event_time"], e["action_source"]) == ("NAYO-1001", 1800000000, "system_generated")
    assert e["custom_data"] == {"currency": "MAD", "value": 209, "content_type": "product", "content_ids": ["nayo-deodorant"],
                                "contents": [{"id": "nayo-deodorant", "quantity": 1}], "num_items": 1, "order_id": "NAYO-1001"}


# ---------------------------------------------------------------- Lead at placement
def test_new_order_sends_one_lead_with_the_order_number(client, orders):
    post = FakePost()
    use_meta(client, post, test_code="TEST123")
    cid = str(uuid.uuid4())
    body = order(clientId=cid, quantity=2, address="Hay Salam, rue 12, Agadir", fbp="fb.1.1700000000000.123456789",
                 fbc="fb.1.1700000000000.IwAR0abc", pageUrl="https://nayo.ma/?utm_source=fb")
    r = client.post("/orders", json=body, headers={**H, "User-Agent": "Mozilla/5.0 test", "X-Forwarded-For": "41.250.1.2"})
    assert r.status_code == 200, r.text
    n = r.json()["orderNumber"]
    assert post.names() == ["Lead"]
    url, sent = post.calls[0]
    assert url == "https://graph.facebook.com/v26.0/1490585709624189/events" and "TOKEN" not in url  # token in the body
    assert sent["access_token"] == "TOKEN-xyz" and sent["test_event_code"] == "TEST123"
    e = sent["data"][0]
    assert (e["event_id"], e["action_source"], e["event_source_url"]) == (n, "website", "https://nayo.ma/?utm_source=fb")
    assert e["custom_data"]["value"] == 398 and e["custom_data"]["num_items"] == 2
    ud = e["user_data"]
    assert ud["ph"] == [sha("212612345678")] and ud["ct"] == [sha("agadir")]
    assert (ud["client_ip_address"], ud["client_user_agent"]) == ("41.250.1.2", "Mozilla/5.0 test")
    assert ud["fbp"] == "fb.1.1700000000000.123456789" and ud["fbc"] == "fb.1.1700000000000.IwAR0abc"
    # the browser retries the same order: stored once, Lead sent once
    assert client.post("/orders", json=body, headers=H).json()["orderNumber"] == n
    assert post.names() == ["Lead"]


def test_tracking_never_blocks_an_order(client, orders):
    post = FakePost()
    use_meta(client, post)
    r = client.post("/orders", json=order(fbp="<script>", fbc="fb.1.1700000000000." + "x" * 900, pageUrl="javascript:alert(1)"), headers=H)
    assert r.status_code == 200, r.text
    e = post.events()[0]
    assert "fbp" not in e["user_data"] and "fbc" not in e["user_data"] and "event_source_url" not in e
    assert "test_event_code" not in post.calls[0][1]
    for bad in (FakePost(fail=True), FakePost(status=400)):
        use_meta(client, bad)
        r = client.post("/orders", json=order(), headers=H)
        assert r.status_code == 200 and orders.get(r.json()["orderNumber"]) is not None


def test_disabled_without_token_or_pixel_and_invalid_orders(client):
    post = FakePost()
    client.app.state.meta_box["m"] = MetaCapi("1490585709624189", "", "v26.0", post=post)
    assert client.post("/orders", json=order(), headers=H).status_code == 200
    client.app.state.meta_box["m"] = MetaCapi("", "TOKEN", "v26.0", post=post)
    assert client.post("/orders", json=order(), headers=H).status_code == 200
    use_meta(client, post)
    assert client.post("/orders", json=order(phone="123"), headers=H).status_code == 422
    assert post.calls == []


# ---------------------------------------------------------------- Purchase / OrderDelivered / OrderReturned
@pytest.fixture
def tracked(store):
    post = FakePost()
    tracker = MetaTracker(store, capi(post))
    orders = TrackedOrders(StockOrders(DbOrders(store), Stock(store)), tracker)
    return orders, tracker, post


def place(orders, tracker, n="NAYO-1001", qty=1, created=None):
    orders.append({"order_number": n, "created_at": created or fmt(now_dt()), "name": "Salma Kettani", "phone": CLIENT,
                   "quantity": qty, "total": qty * 189 + 20, "status": "new", "city": "Agadir", "address": "Hay Salam"})
    tracker.lead(order_number=n, total=qty * 189 + 20, quantity=qty, phone=CLIENT, name="Salma Kettani", city="Agadir",
                 ip="41.250.1.2", user_agent="UA", fbp="fb.1.1700000000000.42", fbc="", source_url="https://nayo.ma/")


def test_status_events_fire_once_each(tracked):
    orders, tracker, post = tracked
    place(orders, tracker, qty=2)
    orders.update("NAYO-1001", status="awaiting_details")  # not an event
    orders.update("NAYO-1001", status="confirmed")
    orders.update("NAYO-1001", status="needs_human")
    orders.update("NAYO-1001", status="confirmed")  # confirmed again: Purchase already sent
    orders.update("NAYO-1001", status="shipped")
    orders.update("NAYO-1001", status="delivered", delivered_at=fmt(now_dt()))
    orders.update("NAYO-1001", status="delivered")  # same status: nothing
    assert post.names() == ["Lead", "Purchase", "OrderDelivered"]
    purchase = post.events()[1]
    assert purchase["event_id"] == "NAYO-1001" and purchase["action_source"] == "system_generated"
    assert purchase["custom_data"]["value"] == 398 and purchase["custom_data"]["currency"] == "MAD"
    assert purchase["user_data"]["fbp"] == "fb.1.1700000000000.42"  # kept from the Lead
    assert purchase["user_data"]["ph"] == [sha(CLIENT)] and "client_ip_address" not in purchase["user_data"]
    orders.update("NAYO-1001", status="returned", returned_at=fmt(now_dt()), recoverable=True)
    orders.update("NAYO-1001", status="returned")
    assert post.names() == ["Lead", "Purchase", "OrderDelivered", "OrderReturned"]
    assert tracker.store._exec("SELECT COUNT(*) FROM meta_events WHERE ok = 1", fetch="one")[0] == 4


def test_nothing_older_than_7_days(tracked):
    orders, tracker, post = tracked
    place(orders, tracker, n="OLD")
    orders.update("OLD", status="confirmed")
    orders.update("OLD", status="delivered", delivered_at=fmt(now_dt() - timedelta(days=8)))  # back-dated by the team
    assert post.names() == ["Lead", "Purchase"]
    orders.update("OLD", status="returned", returned_at=fmt(now_dt() - timedelta(days=6, hours=23)))
    assert post.names() == ["Lead", "Purchase", "OrderReturned"]


def test_meta_down_never_blocks_a_status_change(store):
    tracker = MetaTracker(store, capi(FakePost(fail=True)))
    orders = TrackedOrders(DbOrders(store), tracker)
    place(orders, tracker)
    orders.update("NAYO-1001", status="confirmed")
    assert orders.get("NAYO-1001")["status"] == "confirmed"
    # disabled: no extra query, no event
    off = TrackedOrders(DbOrders(store), MetaTracker(store, MetaCapi("", "", "v26.0", post=FakePost())))
    off.update("NAYO-1001", status="delivered", delivered_at=fmt(now_dt()))
    assert off.get("NAYO-1001")["status"] == "delivered"


def test_whatsapp_and_admin_paths_send_purchase(settings, store, wa, ai, say_db):
    """The bot's "oui" and the admin's status changes both go through the tracked orders."""
    from app.flow import Bot

    post = FakePost()
    tracker = MetaTracker(store, capi(post))
    orders = TrackedOrders(StockOrders(DbOrders(store), Stock(store)), tracker)
    bot = Bot(orders, store, wa, ai, clock=time.time)
    place(orders, tracker)
    # WhatsApp: recap, then "oui"
    ai.push("confirm", "Merci !")
    say_db(bot, "Bonjour NAYO, je confirme ma commande NAYO-1001 – 209 MAD – Salma Kettani")
    ai.push("confirm", "Super")
    say_db(bot, "oui")
    assert orders.get("NAYO-1001")["status"] == "confirmed" and post.names() == ["Lead", "Purchase"]
    # admin: delivered then returned through the API (single and bulk paths)
    settings.admin_secret = "test-admin-secret"
    store.upsert_admin(uuid.uuid4().hex, "owner@nayo.ma", hash_password("motdepasse123"), "Karim")
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        c.post("/admin/login", json={"email": "owner@nayo.ma", "password": "motdepasse123"})
        assert c.post("/admin/order/NAYO-1001/status", json={"status": "shipped"}).status_code == 200
        assert c.post("/admin/order/NAYO-1001/status", json={"status": "delivered"}).status_code == 200
        assert c.post("/admin/orders/bulk", json={"order_numbers": ["NAYO-1001"], "status": "returned"}).json()["done"] == ["NAYO-1001"]
    assert post.names() == ["Lead", "Purchase", "OrderDelivered", "OrderReturned"]
