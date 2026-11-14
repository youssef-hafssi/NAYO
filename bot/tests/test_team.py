"""Phase 8: team (add, disable, reset password, sessions), audit log viewer, settings."""

import time
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.admin import COOKIE, hash_password, make_session, read_session_v
from app.crm import fmt, now_dt
from app.main import Services, create_app
from app.sheets import DbOrders
from app.stock import Stock, StockOrders

PW = "motdepasse123"


@pytest.fixture
def app_env(settings, store, bot):
    settings.admin_secret = "test-admin-secret"
    orders = StockOrders(DbOrders(store), Stock(store))
    owner_id = uuid.uuid4().hex
    store.upsert_admin(owner_id, "owner@nayo.ma", hash_password(PW), "Karim")
    app = create_app(Services(settings, store, orders, bot))
    return app, store, orders, owner_id


def client(app, email="owner@nayo.ma", password=PW):
    c = TestClient(app)
    r = c.post("/admin/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


def test_add_member_temporary_password_and_roles(app_env):
    app, store, _, _ = app_env
    o = client(app)
    r = o.post("/admin/team/members", json={"email": " Sara@Nayo.ma ", "name": "Sara  B", "role": "agent"})
    assert r.status_code == 200, r.text
    tmp, m = r.json()["temporary_password"], r.json()["member"]
    assert len(tmp) == 14 and (m["email"], m["name"], m["role"], m["active"]) == ("sara@nayo.ma", "Sara B", "agent", True)
    a = client(app, "sara@nayo.ma", tmp)  # the temporary password works
    assert a.get("/admin/me").json()["role"] == "agent"
    assert a.get("/admin/team/members").status_code == 403 and a.get("/admin/audit").status_code == 403
    assert a.get("/admin/settings").status_code == 403
    assert o.post("/admin/team/members", json={"email": "sara@nayo.ma", "name": "X Y"}).status_code == 409
    assert o.post("/admin/team/members", json={"email": "pas-un-email", "name": "X Y"}).status_code == 422
    assert o.post("/admin/team/members", json={"email": "z@nayo.ma", "name": "Z Z", "role": "admin"}).status_code == 422
    assert all(tmp not in (e["details"] or "") for e in store._audit_all())  # never written anywhere
    items = o.get("/admin/team/members").json()["items"]
    assert {i["email"] for i in items} == {"owner@nayo.ma", "sara@nayo.ma"} and "password_hash" not in items[0]


def test_disable_ends_sessions_and_blocks_login(app_env):
    app, store, _, _ = app_env
    o = client(app)
    r = o.post("/admin/team/members", json={"email": "sara@nayo.ma", "name": "Sara"}).json()
    mid, tmp = r["member"]["id"], r["temporary_password"]
    a = client(app, "sara@nayo.ma", tmp)
    assert a.get("/admin/me").status_code == 200
    assert o.patch(f"/admin/team/members/{mid}", json={"active": False}).json()["member"]["active"] is False
    assert a.get("/admin/me").status_code == 401  # the open session ends at once
    bad = TestClient(app).post("/admin/login", json={"email": "sara@nayo.ma", "password": tmp})
    assert bad.status_code == 401 and bad.json()["detail"] == "Email ou mot de passe incorrect."  # same answer as a wrong password
    assert "Sara" not in o.get("/admin/team").json()["names"]  # not assignable while disabled
    o.patch(f"/admin/team/members/{mid}", json={"active": True})
    assert client(app, "sara@nayo.ma", tmp).get("/admin/me").status_code == 200
    assert [e["action"] for e in store.audit_for("admin_user", mid)][:2] == ["team.enable", "team.disable"]


def test_reset_password_ends_sessions(app_env):
    app, store, _, _ = app_env
    o = client(app)
    r = o.post("/admin/team/members", json={"email": "sara@nayo.ma", "name": "Sara"}).json()
    mid, tmp = r["member"]["id"], r["temporary_password"]
    a = client(app, "sara@nayo.ma", tmp)
    new = o.post(f"/admin/team/members/{mid}/reset-password").json()["temporary_password"]
    assert new != tmp and a.get("/admin/me").status_code == 401
    assert TestClient(app).post("/admin/login", json={"email": "sara@nayo.ma", "password": tmp}).status_code == 401
    assert client(app, "sara@nayo.ma", new).get("/admin/me").status_code == 200
    assert o.post(f"/admin/team/members/{o.get('/admin/team/members').json()['me']}/reset-password").status_code == 409


def test_own_password_change_keeps_this_session_only(app_env):
    app, _, _, _ = app_env
    phone, laptop = client(app), client(app)
    r = laptop.post("/admin/me/password", json={"current": PW, "new": "nouveau-mot-de-passe"})
    assert r.status_code == 200 and COOKIE in r.cookies
    assert laptop.get("/admin/me").status_code == 200  # fresh cookie
    assert phone.get("/admin/me").status_code == 401  # the other device is logged out


def test_last_active_owner_is_protected(app_env):
    app, store, _, owner_id = app_env
    o = client(app)
    assert o.patch(f"/admin/team/members/{owner_id}", json={"active": False}).status_code == 409
    assert o.patch(f"/admin/team/members/{owner_id}", json={"role": "agent"}).status_code == 409
    r = o.post("/admin/team/members", json={"email": "amal@nayo.ma", "name": "Amal", "role": "owner"}).json()
    assert store.active_owners() == 2
    assert o.patch(f"/admin/team/members/{r['member']['id']}", json={"role": "agent"}).status_code == 200
    assert o.patch("/admin/team/members/nope", json={"name": "Xx"}).status_code == 404


def test_old_session_tokens_without_version_still_work(app_env, settings):
    app, _, _, owner_id = app_env
    tok = make_session(settings.admin_secret, owner_id, 3600)
    assert read_session_v(settings.admin_secret, tok)[1] == 0
    import base64
    import hashlib
    import hmac
    import json
    payload = base64.urlsafe_b64encode(json.dumps({"id": owner_id, "exp": int(time.time()) + 3600}).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(settings.admin_secret.encode(), payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    c = TestClient(app)
    c.cookies.set(COOKIE, f"{payload}.{sig}")  # issued before phase 8 (no "v")
    assert c.get("/admin/me").status_code == 200


def test_audit_viewer_filters_and_pagination(app_env):
    app, store, _, _ = app_env
    day = 86400
    base = time.time() - 10 * day
    for i in range(60):
        store.audit("Sara" if i % 2 else "Karim", "order.edit" if i % 3 else "stock.adjust", "order" if i % 3 else "stock",
                    f"N{i}", f"détail {i}", now=base + i * 3600)
    o = client(app)
    r = o.get("/admin/audit?limit=50").json()
    assert len(r["items"]) == 50 and r["has_more"] is True
    assert r["items"][0]["at"] >= r["items"][-1]["at"]  # newest first
    assert all(i["admin_name"] == "Sara" for i in o.get("/admin/audit?admin_name=Sara&limit=200").json()["items"])
    assert {i["entity"] for i in o.get("/admin/audit?entity=stock&limit=200").json()["items"]} == {"stock"}
    from datetime import datetime

    from app.sheets import TZ
    d0 = datetime.fromtimestamp(base, TZ).strftime("%Y-%m-%d")
    first_day = o.get(f"/admin/audit?frm={d0}&to={d0}&limit=200").json()["items"]
    assert first_day and all(datetime.fromtimestamp(i["at"], TZ).strftime("%Y-%m-%d") == d0 for i in first_day)
    f = o.get("/admin/audit/facets").json()
    assert {"Sara", "Karim"} <= set(f["admins"]) and {"order", "stock"} <= set(f["entities"])
    assert o.get("/admin/audit?frm=2026-02-30").status_code == 422
    assert o.get("/admin/audit?frm=2026-11-10&to=2026-11-01").status_code == 409


def test_settings_validate_apply_and_audit(app_env):
    app, store, orders, _ = app_env
    o = client(app)
    s = o.get("/admin/settings").json()
    assert s == {"company_name": "NAYO", "company_address": "", "company_phone": "", "stock_low_threshold": 10,
                 "followup_stale_hours": 6}
    # an order waiting for 3 h is not a follow-up at 6 h, but is at 2 h
    orders.append({"order_number": "NAYO-1", "created_at": fmt(now_dt() - timedelta(hours=3)), "name": "Salma",
                   "phone": "212611111111", "quantity": 1, "total": 209, "status": "new"})
    assert all(x["key"] != "stale:NAYO-1" for x in o.get("/admin/tasks").json()["suggestions"])
    r = o.patch("/admin/settings", json={"followup_stale_hours": 2, "company_name": " NAYO  Maroc ",
                                         "company_address": "Rue 1, Agadir", "company_phone": "0600000000",
                                         "stock_low_threshold": 25})
    assert r.status_code == 200 and r.json()["company_name"] == "NAYO Maroc" and r.json()["stock_low_threshold"] == 25
    sug = [x for x in o.get("/admin/tasks").json()["suggestions"] if x["key"] == "stale:NAYO-1"]
    assert sug and "plus de 2 h" in sug[0]["title"]
    assert o.get("/admin/stock").json()["low_threshold"] == 25
    slips = o.get("/admin/delivery/slips?numbers=NAYO-1").json()["company"]
    assert slips == {"name": "NAYO Maroc", "address": "Rue 1, Agadir", "phone": "0600000000"}
    for bad in ({"followup_stale_hours": 0}, {"followup_stale_hours": 500}, {"stock_low_threshold": -1},
                {"company_name": "   "}, {"unknown": 1}):
        assert o.patch("/admin/settings", json=bad).status_code == 422, bad
    assert {e["entity_id"] for e in store._audit_all() if e["action"] == "settings.edit"} == \
        {"followup_stale_hours", "company_name", "company_address", "company_phone", "stock_low_threshold"}
