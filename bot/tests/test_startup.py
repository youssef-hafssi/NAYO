"""Cold start: schema versions are read with a parameter, and a database failure at start-up never kills the app."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main as main_mod
from app.config import Settings
from app.store import Store


def test_schema_versions_read_once_then_no_migration(tmp_path, monkeypatch):
    path = str(tmp_path / "s.db")
    Store("sqlite", sqlite_path=path)  # first start: migrations run and are recorded
    seen: list[str] = []
    orig = Store._run

    def run(self, cur, sql, params, fetch):
        seen.append(sql)
        return orig(self, cur, sql, params, fetch)

    monkeypatch.setattr(Store, "_run", run)
    s = Store("sqlite", sqlite_path=path)
    assert s._schema.get("store") and len(seen) == 1  # warm restart: ONE query, no DDL


def test_startup_survives_database_failure(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, state_backend="sqlite", orders_backend="db", sqlite_path=str(tmp_path / "x.db"))
    calls = {"n": 0}

    def flaky(s):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("pooler timeout")
        return SimpleNamespace(store=Store("sqlite", sqlite_path=s.sqlite_path))  # the database is back

    monkeypatch.setattr(main_mod, "build_services", flaky)
    with TestClient(main_mod.create_app(settings=settings)) as c:  # lifespan must not raise
        r = c.get("/health")
        assert r.status_code == 200 and r.json()["db"] is True  # rebuilt on the next request
    assert calls["n"] == 2


def test_health_503_while_database_down(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, sqlite_path=str(tmp_path / "x.db"))

    def down(s):
        raise RuntimeError("pooler timeout")

    monkeypatch.setattr(main_mod, "build_services", down)
    with TestClient(main_mod.create_app(settings=settings)) as c:
        r = c.get("/health")
        assert r.status_code == 503 and r.json() == {"ok": False, "db": False}
