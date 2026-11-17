"""After merging Meta (pixel) into superadmin + analytics: placing an order still sends ONE Lead (event_id = order number)
and still links the visit; confirming it (admin, as the superadmin) still sends ONE Purchase. Same wrapper chain as
production: TrackedOrders(StockOrders(DbOrders))."""

import json
import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.main import Services, create_app
from app.meta import MetaCapi, MetaTracker, TrackedOrders
from app.sheets import DbOrders
from app.stock import Stock, StockOrders

from .test_meta import FakePost

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 [FBAN/FBIOS]"
VID, SID = "v-" + "4" * 12, "s-" + "4" * 12


def run_scenario(settings, store, bot_for):
    post = FakePost()
    tracker = MetaTracker(store, MetaCapi("1490585709624189", "TOKEN-xyz", "v26.0", post=post))
    orders = TrackedOrders(StockOrders(DbOrders(store), Stock(store)), tracker)
    settings.admin_secret = "test-admin-secret"
    store.set_superadmin("boss@nayo.ma", "Youssef", hash_password("motdepasse123"))
    with TestClient(create_app(Services(settings, store, orders, bot_for(orders, store)))) as c:
        # the visit, then the order placed on the website
        batch = {"v": VID, "s": SID, "c": {"utm_source": "facebook", "utm_campaign": "lancement", "device": "mobile"},
                 "e": [{"n": "page_view", "t": int(time.time() * 1000), "d": {}}]}
        assert c.post("/t", content=json.dumps(batch), headers={"User-Agent": UA}).status_code == 204
        body = {"clientId": str(uuid.uuid4()), "name": "Salma Kettani", "phone": "0612345678", "quantity": 2,
                "address": "Hay Salam, rue 12, Agadir", "visitorId": VID, "sessionId": SID, "utmSource": "facebook",
                "utmCampaign": "lancement", "fbp": "fb.1.1700000000000.123456789", "pageUrl": "https://nayo.ma/?utm_source=facebook"}
        r = c.post("/orders", json=body, headers={"X-API-Key": "k3y", "User-Agent": UA})
        assert r.status_code == 200, r.text
        n = r.json()["orderNumber"]
        assert post.names() == ["Lead"]
        lead = post.events()[0]
        assert (lead["event_id"], lead["action_source"], lead["custom_data"]["value"]) == (n, "website", 398)
        assert lead["user_data"]["fbp"] == "fb.1.1700000000000.123456789"
        # the browser retries: still one order, one Lead
        assert c.post("/orders", json=body, headers={"X-API-Key": "k3y"}).json()["orderNumber"] == n
        assert post.names() == ["Lead"]
        # analytics still linked
        o = orders.get(n)
        assert (o["session_id"], o["utm_source"], o["utm_campaign"]) == (SID, "facebook", "lancement")
        # confirmed by the superadmin in the admin → Purchase, once
        assert c.post("/admin/login", json={"email": "boss@nayo.ma", "password": "motdepasse123"}).status_code == 200
        assert c.get(f"/admin/analytics/sessions/{SID}").json()["session"]["order_number"] == n
        assert c.post(f"/admin/order/{n}/status", json={"status": "confirmed"}).status_code == 200
        assert c.post(f"/admin/orders/bulk", json={"order_numbers": [n], "status": "confirmed"}).status_code == 200
        assert post.names() == ["Lead", "Purchase"]
        purchase = post.events()[1]
        assert (purchase["event_id"], purchase["action_source"]) == (n, "system_generated")
        assert purchase["custom_data"]["value"] == 398 and purchase["custom_data"]["currency"] == "MAD"
        assert purchase["user_data"]["fbp"] == "fb.1.1700000000000.123456789"  # kept from the Lead
        # and the rest of the lifecycle still follows
        assert c.post(f"/admin/order/{n}/status", json={"status": "shipped"}).status_code == 200
        assert c.post(f"/admin/order/{n}/status", json={"status": "delivered"}).status_code == 200
        assert post.names() == ["Lead", "Purchase", "OrderDelivered"]


@pytest.fixture
def bot_for(wa, ai):
    from app.flow import Bot

    return lambda orders, store: Bot(orders, store, wa, ai)


def test_lead_and_purchase_still_sent_with_analytics(settings, store, bot_for):
    run_scenario(settings, store, bot_for)


def test_whatsapp_oui_still_sends_purchase(settings, store, wa, ai, say_db):
    from app.flow import Bot

    post = FakePost()
    tracker = MetaTracker(store, MetaCapi("1490585709624189", "TOKEN-xyz", "v26.0", post=post))
    orders = TrackedOrders(StockOrders(DbOrders(store), Stock(store)), tracker)
    bot = Bot(orders, store, wa, ai, clock=time.time)
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        r = c.post("/orders", json={"clientId": str(uuid.uuid4()), "name": "Salma Kettani", "phone": "0612345678",
                                    "quantity": 1, "address": "Hay Salam, rue 12, Agadir", "sessionId": SID,
                                    "visitorId": VID}, headers={"X-API-Key": "k3y"})
        n = r.json()["orderNumber"]
    ai.push("confirm", "Merci !")
    say_db(bot, f"Bonjour NAYO, je confirme ma commande {n} – 209 MAD – Salma Kettani")
    ai.push("confirm", "Super")
    say_db(bot, "oui")
    assert orders.get(n)["status"] == "confirmed", orders.get(n)
    assert post.names() == ["Lead", "Purchase"]


PG = os.environ.get("NAYO_TEST_PG_URL", "")


@pytest.mark.skipif(not PG or "supabase" in PG or "pooler" in PG, reason="set NAYO_TEST_PG_URL (local only)")
def test_lead_and_purchase_on_postgres(pg_url, settings, bot_for):
    from app.store import Store

    settings.state_backend = "postgres"
    run_scenario(settings, Store("postgres", database_url=pg_url), bot_for)


from .test_postgres import pg_url  # noqa: E402,F401  (fixture: a throwaway database per test)
