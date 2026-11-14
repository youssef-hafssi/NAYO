"""Database connection reuse, schema versions, and a constant number of queries per admin request."""

import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.admin import hash_password
from app.main import Services, create_app
from app.sheets import DbOrders
from app.stock import Stock, StockOrders
from app.store import Store


# ---------------------------------------------------------------- one shared Postgres connection
class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        # Like psycopg: with parameters (even an empty tuple), every '%' must be a placeholder.
        if params is not None and "%" in sql.replace("%s", ""):
            raise psycopg.ProgrammingError("only '%s', '%b', '%t' are allowed as placeholders")
        self.conn.statements.append(sql)
        if self.conn.fail_next:
            self.conn.fail_next = False
            self.conn.closed = True
            raise psycopg.OperationalError("server closed the connection unexpectedly")

    def fetchall(self):
        return [("schema:store", "999")]  # schema already applied: no DDL

    def fetchone(self):
        return (1,)


class FakeConn:
    def __init__(self, fail_next=False):
        self.closed, self.broken, self.fail_next, self.statements = False, False, fail_next, []

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_pg(monkeypatch):
    opened = []

    def connect(*a, **kw):
        conn = FakeConn(fail_next=len(opened) == 1)  # the 2nd connection drops on its first statement
        opened.append(conn)
        return conn

    monkeypatch.setattr(psycopg, "connect", connect)
    return opened


def test_one_connection_reused_and_one_reconnect_on_drop(fake_pg):
    st = Store("postgres", database_url="postgresql://fake")
    assert len(fake_pg) == 1
    assert fake_pg[0].statements == ["SELECT key, value FROM settings WHERE key LIKE %s"]  # 1 query, no DDL
    for _ in range(5):
        st._exec("SELECT 1", fetch="one")
    assert len(fake_pg) == 1  # the same connection for every statement

    fake_pg[0].closed = True  # e.g. idle timeout
    st._exec("SELECT 1", fetch="one")  # 2nd connection drops on this statement -> reconnect once -> retry
    assert len(fake_pg) == 3 and fake_pg[2].statements == ["SELECT 1"]


# ---------------------------------------------------------------- schema versions
def test_schema_runs_once_then_start_up_is_one_query(tmp_path, monkeypatch):
    path = str(tmp_path / "s.db")
    first = Store("sqlite", sqlite_path=path)
    DbOrders(first)
    Stock(first)
    calls = []
    real = Store._exec

    def spy(self, sql, params=(), fetch=None):
        calls.append(sql)
        return real(self, sql, params, fetch)

    monkeypatch.setattr(Store, "_exec", spy)
    second = Store("sqlite", sqlite_path=path)
    DbOrders(second)
    Stock(second)
    assert len(calls) == 1 and "FROM settings WHERE key LIKE" in calls[0]
    assert second.needs_schema("store", 3) is False and second.needs_schema("store", 4) is True


# ---------------------------------------------------------------- queries per admin request
@pytest.fixture
def counted(settings, store, bot, monkeypatch):
    settings.admin_secret = "test-admin-secret"
    orders = StockOrders(DbOrders(store), Stock(store))
    store.upsert_admin(uuid.uuid4().hex, "owner@nayo.ma", hash_password("motdepasse123"), "Karim")
    calls = []
    real = Store._exec

    def spy(self, sql, params=(), fetch=None):
        calls.append(sql)
        return real(self, sql, params, fetch)

    monkeypatch.setattr(Store, "_exec", spy)
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        assert c.post("/admin/login", json={"email": "owner@nayo.ma", "password": "motdepasse123"}).status_code == 200
        yield c, orders, calls


def _seed(store, orders, start, end):
    for i in range(start, end):
        phone = f"21266200{i:04d}"
        orders.append({"order_number": f"NAYO-{2000 + i}", "created_at": f"2026-11-13 10:{i % 60:02d}:00",
                       "name": f"C{i}", "phone": phone, "quantity": 1, "total": 209, "status": "awaiting_details"})
        store.add_message(phone, "client", "salam", now=1000 + i)
        store.touch_client(phone, 1000 + i)


def test_inbox_list_query_count_does_not_grow_with_rows(counted, store):
    c, orders, calls = counted
    _seed(store, orders, 0, 3)
    calls.clear()
    r = c.get("/admin/conversations").json()
    few = len(calls)
    assert len(r["items"]) == 3
    _seed(store, orders, 3, 30)
    calls.clear()
    r = c.get("/admin/conversations").json()
    assert len(r["items"]) == 30 and len(calls) == few <= 4  # auth + rows + orders + online
    assert all(i["order_number"] == f"NAYO-{2000 + int(i['phone'][-4:])}" for i in r["items"])


def test_auth_is_one_statement_and_read_marker_written_only_when_new(counted, store):
    c, orders, calls = counted
    _seed(store, orders, 0, 1)
    calls.clear()
    c.get("/admin/me")
    assert sum("admin_users" in q for q in calls) == 2  # auth (one UPDATE ... RETURNING) + online count
    phone = "212662000000"
    c.get(f"/admin/conversations/{phone}/messages")
    calls.clear()
    c.get(f"/admin/conversations/{phone}/messages")  # nothing new since the last opening
    assert not any(q.startswith("INSERT INTO conversations") for q in calls)


def test_stock_screen_query_count(counted):
    c, orders, calls = counted
    calls.clear()
    c.get("/admin/stock")
    assert len(calls) <= 4  # auth + settings + current state + 14-day sales
