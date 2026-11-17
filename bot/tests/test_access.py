"""Roles: superadmin > owner > agent. Clients, visitor tracking (Visiteurs) and the customer & order CSV exports are
superadmin only (403 for owners and agents); superadmins keep every owner right; superadmin accounts are managed by
superadmins only and there is always at least one."""

import getpass
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.main import Services, create_app
from app.sheets import DbOrders
from app.stock import Stock, StockOrders

PW = "motdepasse123"
PHONE = "212611111111"


@pytest.fixture
def env(settings, store, bot):
    settings.admin_secret = "test-admin-secret"
    orders = StockOrders(DbOrders(store), Stock(store))
    store.set_superadmin("boss@nayo.ma", "Youssef", hash_password(PW))
    store.upsert_admin(uuid.uuid4().hex, "owner@nayo.ma", hash_password(PW), "Karim")
    store.upsert_admin(uuid.uuid4().hex, "agent@nayo.ma", hash_password(PW), "Sara", role="agent")
    orders.append({"order_number": "NAYO-1", "created_at": "2026-11-10 10:00:00", "name": "Salma", "phone": PHONE,
                   "quantity": "1", "total": "209", "status": "delivered", "source": "website"})
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        c.app.state.analytics()  # tables exist even before the first visit
        c.post("/admin/customers", json={})  # no-op (405): keeps the client warm
        yield c, store


def login(c, who):
    c.cookies.clear()
    assert c.post("/admin/login", json={"email": f"{who}@nayo.ma", "password": PW}).status_code == 200


SUPERADMIN_ONLY = [
    ("GET", "/admin/customers", None),
    ("GET", f"/admin/customers/{PHONE}", None),
    ("PATCH", f"/admin/customers/{PHONE}", {"tags": ["VIP"], "internal_note": "note"}),
    ("POST", f"/admin/customers/{PHONE}/orders", {"quantity": 1}),
    ("GET", "/admin/customers.csv", None),
    ("GET", "/admin/orders.csv", None),
    ("GET", "/admin/analytics/overview?days=30", None),
    ("GET", "/admin/analytics/sessions", None),
    ("GET", "/admin/analytics/sessions/abcdefgh-1234", None),
]
# A sample of owner rights a superadmin must keep (and agents never get).
OWNER_ONLY = [
    ("GET", "/admin/team/members"), ("GET", "/admin/settings"), ("GET", "/admin/audit"),
    ("GET", "/admin/finance/report?preset=month"), ("GET", "/admin/suppliers"), ("GET", "/admin/reports/sales?preset=month"),
]


def call(c, method, path, body=None):
    return c.request(method, path, json=body) if body is not None else c.request(method, path)


@pytest.mark.parametrize("method,path,body", SUPERADMIN_ONLY)
def test_superadmin_only_endpoints(env, method, path, body):
    c, _ = env
    c.cookies.clear()
    assert call(c, method, path, body).status_code == 401  # not logged in
    for who in ("agent", "owner"):
        login(c, who)
        r = call(c, method, path, body)
        assert r.status_code == 403, (who, path, r.text)
        assert r.json()["detail"] == "Réservé au super-administrateur."
    login(c, "boss")
    r = call(c, method, path, body)
    assert r.status_code in (200, 404), (path, r.text)  # 404: the sample session doesn't exist
    assert r.status_code == 200 or path.endswith("abcdefgh-1234")


@pytest.mark.parametrize("method,path", OWNER_ONLY)
def test_superadmin_keeps_every_owner_right(env, method, path):
    c, _ = env
    login(c, "agent")
    assert call(c, method, path).status_code == 403
    for who in ("owner", "boss"):
        login(c, who)
        assert call(c, method, path).status_code == 200, (who, path)


def test_everyday_screens_stay_open_to_owners_and_agents(env):
    c, _ = env
    for who in ("agent", "owner", "boss"):
        login(c, who)
        for path in ("/admin/dashboard", "/admin/orders", "/admin/orders/NAYO-1", "/admin/conversations", "/admin/tasks",
                     "/admin/stock", "/admin/carriers", "/admin/team"):
            assert c.get(path).status_code == 200, (who, path)


def test_order_detail_hides_customer_tags_below_superadmin(env):
    c, store = env
    login(c, "boss")
    assert c.patch(f"/admin/customers/{PHONE}", json={"tags": ["VIP"]}).status_code == 200
    assert c.get("/admin/orders/NAYO-1").json()["customer"]["tags"] == ["VIP"]
    for who in ("owner", "agent"):
        login(c, who)
        cust = c.get("/admin/orders/NAYO-1").json()["customer"]
        assert cust["tags"] == [] and cust["orders_count"] == 1  # the order context stays


def test_me_reports_the_role(env):
    c, _ = env
    for who, role in (("boss", "superadmin"), ("owner", "owner"), ("agent", "agent")):
        login(c, who)
        assert c.get("/admin/me").json()["role"] == role


# ---------------------------------------------------------------- team rules
def members(c):
    return {m["email"]: m for m in c.get("/admin/team/members").json()["items"]}


def test_only_a_superadmin_creates_or_promotes_a_superadmin(env):
    c, store = env
    login(c, "owner")
    assert c.post("/admin/team/members", json={"email": "x@nayo.ma", "name": "Xavier", "role": "superadmin"}).status_code == 403
    agent = members(c)["agent@nayo.ma"]
    assert c.patch(f"/admin/team/members/{agent['id']}", json={"role": "superadmin"}).status_code == 403
    # owners still manage owners and agents
    assert c.patch(f"/admin/team/members/{agent['id']}", json={"role": "owner"}).status_code == 200
    assert c.patch(f"/admin/team/members/{agent['id']}", json={"role": "agent"}).status_code == 200
    login(c, "boss")
    r = c.post("/admin/team/members", json={"email": "deux@nayo.ma", "name": "Deuxième", "role": "superadmin"})
    assert r.status_code == 200 and r.json()["member"]["role"] == "superadmin"
    assert c.patch(f"/admin/team/members/{agent['id']}", json={"role": "superadmin"}).status_code == 200
    assert store.active_superadmins() == 3
    assert store.audit_for("admin_user", agent["id"])[0]["details"].endswith("rôle → super-administrateur")


def test_owners_cannot_touch_a_superadmin_account(env):
    c, _ = env
    login(c, "owner")
    boss = members(c)["boss@nayo.ma"]
    assert boss["role"] == "superadmin"  # listed, read-only for owners
    for body in ({"role": "owner"}, {"role": "agent"}, {"active": False}, {"name": "Autre"}):
        assert c.patch(f"/admin/team/members/{boss['id']}", json=body).status_code == 403
    assert c.post(f"/admin/team/members/{boss['id']}/reset-password").status_code == 403


def test_there_is_always_one_active_superadmin(env):
    c, store = env
    login(c, "boss")
    me = members(c)["boss@nayo.ma"]
    assert c.patch(f"/admin/team/members/{me['id']}", json={"role": "owner"}).status_code == 409  # the only one
    created = c.post("/admin/team/members", json={"email": "deux@nayo.ma", "name": "Deux", "role": "superadmin"}).json()
    second, temp = created["member"], created["temporary_password"]
    # with two, one can be demoted or disabled — but not the last one left
    assert c.patch(f"/admin/team/members/{second['id']}", json={"active": False}).status_code == 200
    assert c.patch(f"/admin/team/members/{me['id']}", json={"role": "owner"}).status_code == 409
    assert c.patch(f"/admin/team/members/{second['id']}", json={"active": True}).status_code == 200
    assert c.patch(f"/admin/team/members/{me['id']}", json={"role": "owner"}).status_code == 200  # self → owner: ok now
    assert store.active_superadmins() == 1
    c.cookies.clear()
    assert c.post("/admin/login", json={"email": "deux@nayo.ma", "password": temp}).status_code == 200
    assert c.patch(f"/admin/team/members/{second['id']}", json={"role": "owner"}).status_code == 409


# ---------------------------------------------------------------- create_superadmin.py
def run_script(monkeypatch, settings, answers, tty=True, args=("--email", "Youssef@Admin.com", "--name", "Youssef")):
    import create_superadmin
    from app import config

    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty, raising=False)
    it = iter(answers)
    prompts = []

    def fake_getpass(prompt=""):
        prompts.append(prompt)
        a = next(it)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(getpass, "getpass", fake_getpass)
    monkeypatch.setattr(sys, "argv", ["create_superadmin.py", *args])
    return create_superadmin.main(), prompts


def test_create_superadmin_script(monkeypatch, settings, capsys):
    from app.admin import verify_password
    from app.store import Store

    secret = "Un-tres-bon-mot-de-passe-42"
    code, prompts = run_script(monkeypatch, settings, [secret, secret])
    out = capsys.readouterr()
    assert code == 0 and "youssef@admin.com" in out.out and "super-administrateur" in out.out
    assert secret not in out.out + out.err and all(secret not in p for p in prompts)  # never echoed
    store = Store("sqlite", sqlite_path=settings.sqlite_path)
    a = store.get_admin_by_email("youssef@admin.com")
    assert a["role"] == "superadmin" and verify_password(secret, a["password_hash"]) and secret not in a["password_hash"]
    assert store.audit_for("admin_user", "youssef@admin.com")[0]["action"] == "team.superadmin"
    # again: new password, sessions ended, still one account
    code, _ = run_script(monkeypatch, settings, ["Encore-un-autre-mdp-77", "Encore-un-autre-mdp-77"])
    b = store.get_admin_by_email("youssef@admin.com")
    assert code == 0 and b["id"] == a["id"] and b["session_version"] == a["session_version"] + 1
    assert verify_password("Encore-un-autre-mdp-77", b["password_hash"])


def test_create_superadmin_script_refuses_unsafe_input(monkeypatch, settings, capsys):
    from app.store import Store

    assert run_script(monkeypatch, settings, ["court", "court"])[0] == 1  # too short
    assert run_script(monkeypatch, settings, ["Un-tres-bon-mot-de-passe-42", "different-different"])[0] == 1
    assert run_script(monkeypatch, settings, [], tty=False)[0] == 1  # piped input: refused
    # a terminal that can't hide the input: stop instead of showing the password
    assert run_script(monkeypatch, settings, [getpass.GetPassWarning("echo")])[0] == 1
    assert "--password" not in open("create_superadmin.py", encoding="utf-8").read().split("def main")[1]
    assert Store("sqlite", sqlite_path=settings.sqlite_path).get_admin_by_email("youssef@admin.com") is None
