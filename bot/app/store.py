"""Bot state — order counter, processed message IDs, history, 24h window, conversation stage, rate limits.

Production: Postgres (e.g. free Supabase) because free hosts lose their disk on every restart.
Local dev: SQLite file. Same SQL for both (`?` placeholders are rewritten for Postgres).
Every write that must be atomic is a single statement (UPSERT … RETURNING), so concurrent
requests can never get the same order number or process the same WhatsApp message twice.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

log = logging.getLogger("nayo.store")

FIRST_ORDER_NUMBER = 1001

# Bump when SCHEMA / MIGRATIONS / RLS_TABLES change: the DDL then runs once on the next start-up.
# (Each component keeps its own version under the settings key "schema:<name>".)
STORE_SCHEMA_VERSION = 3

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS processed_messages (id TEXT PRIMARY KEY, at DOUBLE PRECISION NOT NULL)",
    "CREATE TABLE IF NOT EXISTS messages (phone TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, at DOUBLE PRECISION NOT NULL)",
    "CREATE INDEX IF NOT EXISTS messages_phone_at ON messages (phone, at)",
    """CREATE TABLE IF NOT EXISTS conversations (
        phone TEXT PRIMARY KEY,
        last_client_at DOUBLE PRECISION,
        order_number TEXT,
        stage TEXT NOT NULL DEFAULT '',
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        verified_order TEXT,
        lang TEXT
    )""",
    "CREATE TABLE IF NOT EXISTS rate_events (key TEXT NOT NULL, at DOUBLE PRECISION NOT NULL)",
    "CREATE INDEX IF NOT EXISTS rate_events_key_at ON rate_events (key, at)",
    """CREATE TABLE IF NOT EXISTS order_requests (
        client_id TEXT PRIMARY KEY,
        order_number TEXT NOT NULL,
        written INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE TABLE IF NOT EXISTS order_aliases (alias TEXT PRIMARY KEY, order_number TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id TEXT PRIMARY KEY,
        at DOUBLE PRECISION NOT NULL,
        admin_name TEXT NOT NULL,
        action TEXT NOT NULL,
        entity TEXT NOT NULL,
        entity_id TEXT NOT NULL DEFAULT '',
        details TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS audit_entity ON audit_log (entity, entity_id, at)",
    "CREATE INDEX IF NOT EXISTS audit_at ON audit_log (at)",
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS admin_users (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        name TEXT NOT NULL
    )""",
]

# Columns added after the first release (tables created before them get them on start-up).
MIGRATIONS = [
    ("messages", "agent_name", "TEXT"),  # set only when role = agent
    ("conversations", "taken_over_by", "TEXT"),  # agent name while a human handles the thread; NULL = bot
    ("conversations", "admin_read_at", "DOUBLE PRECISION"),  # unread counter in the admin inbox
    ("conversations", "internal_notes", "TEXT"),  # team-only notes shown in the admin inbox
    ("admin_users", "last_seen_at", "DOUBLE PRECISION"),  # members online in the admin inbox
    ("admin_users", "role", "TEXT"),  # 'owner' | 'agent' (existing users become owners)
]

RLS_TABLES = ("counters", "processed_messages", "messages", "conversations", "rate_events", "order_requests",
              "order_aliases", "admin_users", "audit_log", "settings")

CONV_FIELDS = {"last_client_at", "order_number", "stage", "failed_attempts", "verified_order", "lang",
               "taken_over_by", "admin_read_at", "internal_notes"}
CONV_COLUMNS = ("phone, last_client_at, order_number, stage, failed_attempts, verified_order, lang, taken_over_by, "
                "admin_read_at, internal_notes")


class Tx:
    """Statements inside Store.tx() — same `?` placeholders as Store._exec."""

    def __init__(self, store: "Store", cur: Any):
        self.store, self.cur = store, cur

    def exec(self, sql: str, params: tuple = (), fetch: str | None = None) -> Any:
        self.cur.execute(self.store._sql(sql), params)
        if fetch == "one":
            return self.cur.fetchone()
        if fetch == "all":
            return self.cur.fetchall()
        return None


@dataclass
class Conversation:
    phone: str
    last_client_at: float | None = None
    order_number: str | None = None
    stage: str = ""  # '' | 'details' | 'await_yes' | 'verify_name'
    failed_attempts: int = 0
    verified_order: str | None = None
    lang: str | None = None
    taken_over_by: str | None = None  # agent name while a human handles this thread (bot silent)
    admin_read_at: float | None = None
    internal_notes: str | None = None


class Store:
    def __init__(self, backend: str, *, database_url: str = "", sqlite_path: str = "bot-state.db"):
        self.backend = backend
        self.database_url = database_url
        self.sqlite_path = sqlite_path
        if backend == "postgres" and not database_url:
            raise RuntimeError("STATE_BACKEND=postgres needs DATABASE_URL")
        if backend == "sqlite":
            log.warning("STATE_BACKEND=sqlite (%s): fine for local dev, state is lost on free hosts — use postgres in production", sqlite_path)
        # One Postgres connection per warm instance, shared by every statement (serialized by this lock).
        self._lock = threading.RLock()
        self._pg: Any = None
        # One query at start-up: which schema versions are already applied.
        self._schema = self._read_schema_versions()
        if self.needs_schema("store", STORE_SCHEMA_VERSION):
            for stmt in SCHEMA:
                self._exec(stmt)
            for table, column, decl in MIGRATIONS:
                self._ensure_column(table, column, decl)
            if backend == "postgres":
                # Supabase exposes the `public` schema through its REST API: RLS with no policies blocks that
                # entirely, while the bot's own connection (table owner) is unaffected.
                for table in RLS_TABLES:
                    self._exec(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            self._exec("UPDATE admin_users SET role = 'owner' WHERE role IS NULL OR role = ''")
            self.schema_done("store", STORE_SCHEMA_VERSION)

    # -- schema versions -----------------------------------------------------------------------
    def _read_schema_versions(self) -> dict[str, int]:
        try:
            rows = self._exec("SELECT key, value FROM settings WHERE key LIKE 'schema:%'", fetch="all")
        except Exception:  # first start: the settings table doesn't exist yet
            if self.backend == "postgres":
                self._drop_pg()
            return {}
        out: dict[str, int] = {}
        for k, v in rows:
            try:
                out[k.split(":", 1)[1]] = int(v)
            except ValueError:
                pass
        return out

    def needs_schema(self, name: str, version: int) -> bool:
        """True when the component's CREATE/ALTER statements must run (all of them are idempotent)."""
        return self._schema.get(name, 0) < version

    def schema_done(self, name: str, version: int) -> None:
        self.set_setting(f"schema:{name}", str(version))
        self._schema[name] = version

    def _ensure_column(self, table: str, column: str, decl: str) -> None:
        if self.backend == "postgres":
            self._exec(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {decl}")
        else:
            existing = {r[1] for r in self._exec(f"PRAGMA table_info({table})", fetch="all")}
            if column not in existing:
                self._exec(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # -- low level ---------------------------------------------------------------------------
    def _pg_conn(self) -> Any:
        """The instance's shared connection (opened on first use, reopened if it was closed or broken)."""
        if self._pg is None or self._pg.closed or getattr(self._pg, "broken", False):
            import psycopg  # imported lazily so local dev doesn't need it

            # prepare_threshold=None → works behind Supabase's transaction pooler (port 6543)
            self._pg = psycopg.connect(self.database_url, autocommit=True, prepare_threshold=None, connect_timeout=10)
        return self._pg

    def _drop_pg(self) -> None:
        try:
            if self._pg is not None:
                self._pg.close()
        except Exception:
            pass
        self._pg = None

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        if self.backend == "postgres":
            with self._lock:
                yield self._pg_conn()
        else:
            conn = sqlite3.connect(self.sqlite_path, timeout=10, isolation_level=None)  # autocommit
            try:
                yield conn
            finally:
                conn.close()

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.backend == "postgres" else sql

    @property
    def serial_pk(self) -> str:
        """Auto-increment primary key DDL for the current backend (ids are returned with RETURNING id)."""
        return "BIGSERIAL PRIMARY KEY" if self.backend == "postgres" else "INTEGER PRIMARY KEY AUTOINCREMENT"

    @contextmanager
    def tx(self, lock: str = "") -> Iterator["Tx"]:
        """One transaction on one connection. `lock` serializes writers sharing that name (Postgres advisory
        lock held until commit; SQLite: BEGIN IMMEDIATE takes the database write lock). Rolls back on error."""
        if self.backend == "postgres":
            import psycopg

            with self._lock:
                conn = self._pg_conn()
                try:
                    with conn.transaction():
                        cur = conn.cursor()
                        if lock:
                            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock,))
                        yield Tx(self, cur)
                except (psycopg.OperationalError, psycopg.InterfaceError):
                    self._drop_pg()  # the next statement reconnects (a transaction is never replayed)
                    raise
            return
        with self._conn() as conn:  # SQLite (tests / local dev)
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield Tx(self, conn.cursor())
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    # -- settings (key/value) ----------------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        row = self._exec("SELECT value FROM settings WHERE key = ?", (key,), fetch="one")
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._exec(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    def _exec(self, sql: str, params: tuple = (), fetch: str | None = None) -> Any:
        if self.backend != "postgres":
            with self._conn() as conn:
                return self._run(conn.cursor(), sql, params, fetch)
        import psycopg

        with self._lock:
            try:
                with self._pg_conn().cursor() as cur:
                    return self._run(cur, sql, params, fetch)
            except (psycopg.OperationalError, psycopg.InterfaceError) as e:
                # Connection dropped (pooler restart, idle timeout…): reconnect once and retry the statement.
                log.warning("database connection lost (%s) - reconnecting", type(e).__name__)
                self._drop_pg()
                with self._pg_conn().cursor() as cur:
                    return self._run(cur, sql, params, fetch)

    def _run(self, cur: Any, sql: str, params: tuple, fetch: str | None) -> Any:
        cur.execute(self._sql(sql), params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        return None

    def ping(self) -> bool:
        try:
            self._exec("SELECT 1", fetch="one")
            return True
        except Exception:
            log.warning("state database unreachable")
            return False

    # -- order numbers -----------------------------------------------------------------------
    def next_order_number(self) -> int:
        """Atomic: one UPSERT…RETURNING statement (row lock in Postgres, write lock in SQLite)."""
        row = self._exec(
            "INSERT INTO counters (name, value) VALUES ('order', ?) "
            "ON CONFLICT (name) DO UPDATE SET value = counters.value + 1 RETURNING value",
            (FIRST_ORDER_NUMBER,),
            fetch="one",
        )
        return int(row[0])

    def get_request(self, client_id: str) -> tuple[str, bool] | None:
        row = self._exec("SELECT order_number, written FROM order_requests WHERE client_id = ?", (client_id,), fetch="one")
        return (row[0], bool(row[1])) if row else None

    def claim_request(self, client_id: str, order_number: str) -> bool:
        """True if this request is new (we own it), False if another request already claimed this client_id."""
        row = self._exec(
            "INSERT INTO order_requests (client_id, order_number) VALUES (?, ?) ON CONFLICT (client_id) DO NOTHING RETURNING client_id",
            (client_id, order_number),
            fetch="one",
        )
        return row is not None

    def mark_written(self, client_id: str) -> None:
        self._exec("UPDATE order_requests SET written = 1 WHERE client_id = ?", (client_id,))

    def add_alias(self, alias: str, order_number: str) -> None:
        self._exec("INSERT INTO order_aliases (alias, order_number) VALUES (?, ?) ON CONFLICT (alias) DO NOTHING", (alias, order_number))

    def resolve_alias(self, number: str) -> str:
        row = self._exec("SELECT order_number FROM order_aliases WHERE alias = ?", (number,), fetch="one")
        return row[0] if row else number

    # -- webhook de-duplication ----------------------------------------------------------------
    def mark_processed(self, message_id: str, now: float | None = None) -> bool:
        """True the first time a WhatsApp message ID is seen, False for duplicates (Meta retries)."""
        now = now or time.time()
        row = self._exec(
            "INSERT INTO processed_messages (id, at) VALUES (?, ?) ON CONFLICT (id) DO NOTHING RETURNING id",
            (message_id, now),
            fetch="one",
        )
        if random.random() < 0.02:  # occasional cleanup
            self._exec("DELETE FROM processed_messages WHERE at < ?", (now - 7 * 86400,))
            self._exec("DELETE FROM rate_events WHERE at < ?", (now - 86400,))
        return row is not None

    # -- conversation history ----------------------------------------------------------------
    def add_message(
        self, phone: str, role: str, text: str, keep: int = 0, now: float | None = None, agent_name: str | None = None
    ) -> None:
        """Store one message. The full history is kept (the admin inbox shows it); `recent_messages(limit)`
        is what caps the context given to the AI. `keep` is ignored (kept for backwards compatibility)."""
        self._exec(
            "INSERT INTO messages (phone, role, text, at, agent_name) VALUES (?, ?, ?, ?, ?)",
            (phone, role, text[:2000], now or time.time(), agent_name if role == "agent" else None),
        )

    def recent_messages(self, phone: str, limit: int = 20) -> list[tuple[str, str]]:
        rows = self._exec(
            "SELECT role, text FROM messages WHERE phone = ? ORDER BY at DESC LIMIT ?", (phone, limit), fetch="all"
        )
        return [(r[0], r[1]) for r in reversed(rows)]

    # -- conversation state --------------------------------------------------------------------
    def get_conv(self, phone: str) -> Conversation:
        row = self._exec(
            f"SELECT {CONV_COLUMNS} FROM conversations WHERE phone = ?",
            (phone,),
            fetch="one",
        )
        if not row:
            return Conversation(phone=phone)
        return Conversation(*row)

    def update_conv(self, phone: str, **fields: Any) -> None:
        unknown = set(fields) - CONV_FIELDS
        if unknown:
            raise ValueError(f"unknown conversation fields: {unknown}")
        if not fields:
            self._exec("INSERT INTO conversations (phone) VALUES (?) ON CONFLICT (phone) DO NOTHING", (phone,))
            return
        # One statement: create the row if needed and set the fields (keys are whitelisted above).
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        sets = ", ".join(f"{k} = excluded.{k}" for k in fields)
        self._exec(f"INSERT INTO conversations (phone, {cols}) VALUES (?, {marks}) "
                   f"ON CONFLICT (phone) DO UPDATE SET {sets}", (phone, *fields.values()))

    def touch_client(self, phone: str, now: float | None = None) -> None:
        self.update_conv(phone, last_client_at=now or time.time())

    # -- rate limiting -------------------------------------------------------------------------
    def hit(self, key: str, now: float | None = None) -> None:
        self._exec("INSERT INTO rate_events (key, at) VALUES (?, ?)", (key, now or time.time()))

    def count(self, key: str, window_s: float, now: float | None = None) -> int:
        now = now or time.time()
        row = self._exec("SELECT COUNT(*) FROM rate_events WHERE key = ? AND at > ?", (key, now - window_s), fetch="one")
        return int(row[0])

    # -- admin inbox ---------------------------------------------------------------------------
    def thread(self, phone: str) -> list[dict[str, Any]]:
        rows = self._exec(
            "SELECT role, text, at, agent_name FROM messages WHERE phone = ? ORDER BY at ASC", (phone,), fetch="all"
        )
        return [{"role": r[0], "text": r[1], "at": r[2], "agent_name": r[3]} for r in rows]

    def conversation_rows(self, limit: int = 300) -> list[dict[str, Any]]:
        """One row per phone with its last message and unread count (client messages not yet seen by the team)."""
        rows = self._exec(
            f"""SELECT {", ".join("c." + c.strip() for c in CONV_COLUMNS.split(","))},
                   (SELECT m.text FROM messages m WHERE m.phone = c.phone ORDER BY m.at DESC LIMIT 1),
                   (SELECT m.role FROM messages m WHERE m.phone = c.phone ORDER BY m.at DESC LIMIT 1),
                   (SELECT MAX(m.at) FROM messages m WHERE m.phone = c.phone),
                   (SELECT COUNT(*) FROM messages m WHERE m.phone = c.phone AND m.role = 'client'
                        AND m.at > COALESCE(c.admin_read_at, 0))
                FROM conversations c""",
            fetch="all",
        )
        out = []
        for r in rows:
            conv = Conversation(*r[:10])
            if r[12] is None:  # no message at all
                continue
            out.append({"conv": conv, "last_text": r[10], "last_role": r[11], "last_at": r[12], "unread": int(r[13])})
        out.sort(key=lambda x: x["last_at"], reverse=True)
        return out[:limit]

    def get_admin_by_email(self, email: str) -> dict[str, Any] | None:
        row = self._exec(
            "SELECT id, email, password_hash, name, role FROM admin_users WHERE LOWER(email) = LOWER(?)", (email.strip(),),
            fetch="one",
        )
        return {"id": row[0], "email": row[1], "password_hash": row[2], "name": row[3], "role": row[4] or "owner"} if row else None

    def get_admin(self, admin_id: str) -> dict[str, Any] | None:
        row = self._exec(
            "SELECT id, email, name, role, password_hash FROM admin_users WHERE id = ?", (admin_id,), fetch="one"
        )
        return {"id": row[0], "email": row[1], "name": row[2], "role": row[3] or "owner", "password_hash": row[4]} if row else None

    def set_admin_password(self, admin_id: str, password_hash: str) -> None:
        self._exec("UPDATE admin_users SET password_hash = ? WHERE id = ?", (password_hash, admin_id))

    # -- audit log -----------------------------------------------------------------------------
    def audit(self, admin_name: str, action: str, entity: str, entity_id: str = "", details: str = "",
              now: float | None = None) -> None:
        import uuid

        self._exec(
            "INSERT INTO audit_log (id, at, admin_name, action, entity, entity_id, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, now or time.time(), admin_name, action, entity, str(entity_id), details[:1000]),
        )

    def _audit_all(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._exec("SELECT at, admin_name, action, entity, entity_id, details FROM audit_log ORDER BY at DESC LIMIT ?",
                          (limit,), fetch="all")
        return [{"at": r[0], "admin_name": r[1], "action": r[2], "entity": r[3], "entity_id": r[4], "details": r[5]} for r in rows]

    def audit_for(self, entity: str, entity_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._exec(
            "SELECT at, admin_name, action, details FROM audit_log WHERE entity = ? AND entity_id = ? ORDER BY at DESC LIMIT ?",
            (entity, str(entity_id), limit), fetch="all",
        )
        return [{"at": r[0], "admin_name": r[1], "action": r[2], "details": r[3]} for r in rows]

    def auth_admin(self, admin_id: str, now: float | None = None, touch_every_s: float = 30) -> dict[str, Any] | None:
        """Loads the logged-in admin and refreshes last_seen_at (at most every 30 s) in ONE statement."""
        now = now or time.time()
        row = self._exec(
            "UPDATE admin_users SET last_seen_at = CASE WHEN last_seen_at IS NULL OR last_seen_at < ? THEN ? "
            "ELSE last_seen_at END WHERE id = ? RETURNING id, email, name, role, password_hash",
            (now - touch_every_s, now, admin_id), fetch="one",
        )
        if not row:
            return None
        return {"id": row[0], "email": row[1], "name": row[2], "role": row[3] or "owner", "password_hash": row[4]}

    def get_settings(self, keys: tuple[str, ...]) -> dict[str, str]:
        marks = ", ".join("?" for _ in keys)
        return dict(self._exec(f"SELECT key, value FROM settings WHERE key IN ({marks})", tuple(keys), fetch="all"))

    def touch_admin(self, admin_id: str, now: float | None = None) -> None:
        self._exec("UPDATE admin_users SET last_seen_at = ? WHERE id = ?", (now or time.time(), admin_id))

    def admins_online(self, within_s: float = 60, now: float | None = None) -> int:
        row = self._exec(
            "SELECT COUNT(*) FROM admin_users WHERE last_seen_at > ?", ((now or time.time()) - within_s,), fetch="one"
        )
        return int(row[0])

    def upsert_admin(self, admin_id: str, email: str, password_hash: str, name: str, role: str = "owner") -> None:
        if role not in ("owner", "agent"):
            raise ValueError("role must be owner or agent")
        self._exec(
            "INSERT INTO admin_users (id, email, password_hash, name, role) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (email) DO UPDATE SET password_hash = excluded.password_hash, name = excluded.name, "
            "role = excluded.role",
            (admin_id, email.strip().lower(), password_hash, name.strip(), role),
        )
