"""Phase A — first-party visitor analytics: POST /t validation, bot filtering, rate limit, session aggregation,
order ↔ session link, 90-day retention, "Visiteurs" API (superadmin only)."""

import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.analytics import MAX_EVENTS, Analytics, is_bot, parse_batch, source_of
from app.main import Services, create_app
from app.sheets import DbOrders
from app.stock import Stock, StockOrders

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
FB_UA = UA + " [FBAN/FBIOS;FBAV/450.0.0.38.108;FBBV/123]"
H = {"User-Agent": UA, "x-vercel-ip-country": "MA", "x-vercel-ip-city": "F%C3%A8s", "x-forwarded-for": "41.250.1.2"}
VID, SID = "v-" + "1" * 12, "s-" + "2" * 12


def ev(name, **data):
    return {"n": name, "t": int(time.time() * 1000), "d": data}


def batch(events, vid=VID, sid=SID, **ctx):
    c = {"utm_source": "facebook", "utm_medium": "paid", "utm_campaign": "lancement", "fbclid": "IwAR0abc",
         "referrer": "https://l.facebook.com/l.php?u=secret", "landing": "/?utm_source=facebook", "device": "mobile",
         "in_app": "facebook", "lang": "fr-MA", "sw": 390}
    c.update(ctx)
    return {"v": vid, "s": sid, "c": c, "e": events}


@pytest.fixture
def env(settings, store, bot):
    settings.admin_secret = "test-admin-secret"
    orders = StockOrders(DbOrders(store), Stock(store))
    store.set_superadmin("boss@nayo.ma", "Youssef", hash_password("motdepasse123"))
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        c.app.state.analytics()  # tables are created on first use; create them now so empty counts can be read
        yield c, store, orders


def send(c, body, headers=H):
    return c.post("/t", content=json.dumps(body), headers={**headers, "Content-Type": "text/plain;charset=UTF-8"})


def session(store, sid=SID):
    return Analytics(store).session(sid)


# ---------------------------------------------------------------- validation
def test_validation(env):
    c, store, _ = env
    assert send(c, batch([ev("page_view")], vid="bad id")).status_code == 400
    assert send(c, batch([ev("page_view")] * (MAX_EVENTS + 1))).status_code == 400
    assert c.post("/t", content="{not json", headers=H).status_code == 400
    assert c.post("/t", content="x" * 40_000, headers=H).status_code == 413
    # unknown names are dropped, the rest is kept; data keeps only known keys (never what was typed)
    r = send(c, batch([ev("page_view", path="/"), ev("hack_me", x=1), ev("field_error", field="phone", error="format",
                                                                          value="0612345678", email="a@b.c")]))
    assert r.status_code == 204
    s = session(store)
    assert [e["name"] for e in s["events"]] == ["page_view", "field_error"]
    assert s["events"][1]["data"] == {"field": "phone", "error": "format"}
    assert "0612345678" not in json.dumps(store._exec("SELECT * FROM events", fetch="all"))


def test_context_is_cleaned():
    now = time.time()
    b = parse_batch(json.dumps(batch([ev("page_view")], referrer="https://www.google.com/search?q=nom+prenom",
                                     landing="/commande?phone=0612", device="fridge", in_app="evil", lang="<b>",
                                     sw=99999, utm_source="x" * 500)).encode(), now)
    ctx = b["ctx"]
    assert ctx["referrer"] == "https://www.google.com/search" and ctx["landing"] == "/commande"  # no query strings
    assert (ctx["device"], ctx["in_app"], ctx["lang"], ctx["screen_w"]) == ("", "", "", 0)
    assert len(ctx["utm_source"]) == 100
    old = parse_batch(json.dumps(batch([{"n": "page_view", "t": 1_000_000_000_000}])).encode(), now)
    assert old["events"][0][0] == round(now, 3)  # a wrong device clock → arrival time


# ---------------------------------------------------------------- bots / rate limit
def test_bots_are_dropped(env):
    c, store, _ = env
    for ua in ("", "Googlebot/2.1 (+http://www.google.com/bot.html)", "Mozilla/5.0 HeadlessChrome/120.0 Safari/537",
               "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)", "python-requests/2.31",
               "curl/8.4.0", "WhatsApp/2.23.20.0 A"):
        assert send(c, batch([ev("page_view")]), {**H, "User-Agent": ua}).status_code == 204
    assert send(c, {**batch([ev("page_view")]), "wd": True}).status_code == 204  # navigator.webdriver
    assert store._exec("SELECT COUNT(*) FROM sessions", fetch="one")[0] == 0
    # people in the Facebook / Instagram in-app browsers are not bots
    assert not is_bot(FB_UA) and not is_bot(UA + " Instagram 300.0.0.0")
    assert send(c, batch([ev("page_view")]), {**H, "User-Agent": FB_UA}).status_code == 204
    assert store._exec("SELECT COUNT(*) FROM sessions", fetch="one")[0] == 1


def test_rate_limit_per_visitor(env):
    c, store, _ = env
    for _ in range(35):
        send(c, batch([ev("click", id="cta")]))
    assert store._exec("SELECT COUNT(*) FROM events", fetch="one")[0] == 30
    send(c, batch([ev("click", id="cta")], vid="v-" + "9" * 12, sid="s-" + "9" * 12))  # another visitor: fine
    assert store._exec("SELECT COUNT(*) FROM events", fetch="one")[0] == 31


# ---------------------------------------------------------------- aggregation
def test_session_aggregation(env):
    c, store, _ = env
    send(c, batch([ev("page_view", path="/"), ev("scroll_depth", pct=25), ev("scroll_depth", pct=50)]))
    send(c, batch([ev("scroll_depth", pct=75), ev("checkout_view"), ev("form_start", form="express")],
                  utm_source="google", referrer="https://google.com/", device="desktop"))  # later batch: first values kept
    s = session(store)["session"]
    assert (s["events_count"], s["max_scroll"], s["reached_checkout"], s["form_started"], s["submitted"]) == \
        (6, 75, True, True, False)
    assert (s["utm_source"], s["utm_campaign"], s["device"], s["in_app"], s["screen_w"]) == \
        ("facebook", "lancement", "mobile", "facebook", 390)
    assert (s["country"], s["city"], s["source"]) == ("MA", "Fès", "facebook")
    assert "fbclid" not in s and "41.250.1.2" not in json.dumps(store._exec("SELECT * FROM sessions", fetch="all"))
    assert s["last_at"] >= s["started_at"]


def test_source_labels():
    assert source_of({"utm_source": "TikTok"}) == "tiktok"
    assert source_of({"fbclid": "x"}) == "facebook (pub)"
    assert source_of({"referrer": "https://l.instagram.com/x"}) == "instagram"
    assert source_of({"referrer": "https://www.blog.ma/a"}) == "blog.ma"
    assert source_of({"in_app": "facebook"}) == "facebook"
    assert source_of({}) == "direct"


def test_event_cap_per_session(env, monkeypatch):
    import app.analytics as an

    c, store, _ = env
    monkeypatch.setattr(an, "SESSION_EVENT_CAP", 4)
    for _ in range(4):
        send(c, batch([ev("click", id="x"), ev("click", id="y")]))
    assert store._exec("SELECT COUNT(*) FROM events", fetch="one")[0] == 4  # 2 batches accepted, then capped


# ---------------------------------------------------------------- order ↔ session
def order(**kw):
    o = {"clientId": str(uuid.uuid4()), "name": "Salma Kettani", "phone": "0612345678", "quantity": 2,
         "address": "Hay Salam, rue 12, Agadir", "visitorId": VID, "sessionId": SID, "utmSource": "facebook",
         "utmMedium": "paid", "utmCampaign": "lancement", "utmContent": "video-1", "utmTerm": "deo"}
    o.update(kw)
    return o


def test_order_links_to_its_session(env):
    c, store, orders = env
    api = {"X-API-Key": "k3y"}
    # the order arrives before the first events batch (the browser sends every 5 s)
    r = c.post("/orders", json=order(), headers=api)
    assert r.status_code == 200, r.text
    n = r.json()["orderNumber"]
    o = orders.get(n)
    assert (o["visitor_id"], o["session_id"], o["utm_source"], o["utm_campaign"], o["utm_content"], o["source"]) == \
        (VID, SID, "facebook", "lancement", "video-1", "website")
    s = session(store)["session"]
    assert s["order_number"] == n and s["submitted"] and s["ordered"]
    assert (s["utm_source"], s["utm_campaign"], s["source"]) == ("facebook", "lancement", "facebook")  # from the order
    # the batch arriving afterwards fills in the source without losing the order
    send(c, batch([ev("page_view"), ev("order_submit", form="express"), ev("order_success", order=n)]))
    s = session(store)["session"]
    assert (s["order_number"], s["utm_source"], s["events_count"]) == (n, "facebook", 3)
    # a retry of the same order: no second link, no change
    body = order()
    first = c.post("/orders", json=body, headers=api).json()["orderNumber"]
    assert c.post("/orders", json=body, headers=api).json()["orderNumber"] == first
    assert session(store)["session"]["order_number"] == first  # the latest order of the visit


def test_tracking_fields_never_reject_an_order(env):
    c, store, orders = env
    r = c.post("/orders", json=order(visitorId="<script>", sessionId="x" * 500, utmSource="=HYPERLINK()", utmTerm=7,
                                     fbp="fb.1.1700000000000.123", fbc="whatever", pageUrl="https://nayo.ma/"),
               headers={"X-API-Key": "k3y"})
    assert r.status_code == 200, r.text
    o = orders.get(r.json()["orderNumber"])
    assert (o["visitor_id"], o["session_id"], o["utm_source"], o["utm_term"]) == ("", "", "", "")
    assert store._exec("SELECT COUNT(*) FROM sessions", fetch="one")[0] == 0  # no session id: nothing to link
    # the Google Sheet keeps its 12 columns: the analytics fields are database-only
    from app.sheets import EXTRA_COLUMNS, HEADERS

    assert {"visitor_id", "session_id", "utm_source"} <= set(EXTRA_COLUMNS) and "utm_source" not in HEADERS


def test_whatsapp_orders_are_source_whatsapp(store):
    from app.orders import create_bot_order

    orders = DbOrders(store)
    row = create_bot_order(orders, store, name="Salma", phone="212612345678")
    assert orders.get(row["order_number"])["source"] == "whatsapp"
    assert orders.get(row["order_number"])["visitor_id"] == ""


# ---------------------------------------------------------------- retention
def test_events_older_than_90_days_are_deleted_sessions_kept(env):
    c, store, _ = env
    a = Analytics(store)
    now = time.time()
    old = parse_batch(json.dumps(batch([ev("page_view")], sid="s-old-12345678")).encode(), now)
    old["events"] = [(now - 91 * 86400, "page_view", "{}")]
    a.record(old, now=now)
    send(c, batch([ev("page_view")]))
    c.app.state.analytics().purge()
    assert store._exec("SELECT COUNT(*) FROM events", fetch="one")[0] == 1
    assert store._exec("SELECT COUNT(*) FROM sessions", fetch="one")[0] == 2  # sessions kept
    # the daily cron
    assert c.get("/cron/analytics-retention").status_code == 503  # CRON_SECRET not set


def test_retention_cron_auth(settings, store, bot, orders):
    settings.cron_secret = "cron-s3cret"
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        assert c.get("/cron/analytics-retention", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.get("/cron/analytics-retention", headers={"Authorization": "Bearer cron-s3cret"}).json() == {"ok": True}
        assert store.get_setting("analytics:purged_at")


# ---------------------------------------------------------------- "Visiteurs" (superadmin)
def test_visiteurs_api(env):
    c, store, _ = env
    send(c, batch([ev("page_view"), ev("scroll_depth", pct=50), ev("form_start", form="express")]))
    send(c, batch([ev("page_view")], vid="v-" + "3" * 12, sid="s-" + "3" * 12, utm_source="", fbclid="",
                  referrer="", in_app="", device="desktop"))
    c.post("/orders", json=order(), headers={"X-API-Key": "k3y"})
    c.post("/admin/login", json={"email": "boss@nayo.ma", "password": "motdepasse123"})
    o = c.get("/admin/analytics/overview?days=7").json()
    assert o["funnel"] == {"visits": 2, "scroll_50": 1, "form_started": 1, "ordered": 1}
    assert o["totals"] == {"visits": 2, "visitors": 2, "orders": 1}
    assert len(o["days"]) == 7 and o["days"][-1]["visits"] == 2
    assert {s["source"]: s["visits"] for s in o["sources"]} == {"facebook": 1, "direct": 1}
    assert {d["device"]: d["visits"] for d in o["devices"]} == {"mobile": 1, "desktop": 1}
    assert c.get("/admin/analytics/overview?days=12").status_code == 400
    lst = c.get("/admin/analytics/sessions?orders=true").json()
    assert [x["session_id"] for x in lst["items"]] == [SID]
    t = c.get(f"/admin/analytics/sessions/{SID}").json()
    assert [e["name"] for e in t["events"]] == ["page_view", "scroll_depth", "form_start"]
    assert c.get("/admin/analytics/sessions/s-nope-1234").status_code == 404
    assert c.get("/admin/analytics/sessions/bad%20id").status_code == 400


def test_batch_is_fast(env):
    """< 100 ms per 50-event batch once warm (SQLite here; one statement on Postgres — see test_postgres)."""
    c, store, _ = env
    send(c, batch([ev("page_view")]))
    events = [ev("scroll_depth", pct=25)] * MAX_EVENTS
    t0 = time.perf_counter()
    for i in range(10):
        assert send(c, batch(events, vid=f"v-{i:012d}", sid=f"s-{i:012d}")).status_code == 204
    assert (time.perf_counter() - t0) / 10 < 0.1
