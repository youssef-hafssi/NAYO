"""CRM: order search, customers (one per normalized phone) and follow-up tasks.

Everything is aggregated in SQL (one query per list page, no query per row). The orders table keeps its TEXT
columns: numbers are CAST in SQL. Dates are Casablanca local time strings ('YYYY-MM-DD HH:MM:SS').
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any

from .sheets import STATUSES, TZ

log = logging.getLogger("nayo.crm")

SEGMENTS = ("new", "loyal", "at_risk", "inactive")
SEGMENT_LABEL = {"new": "Nouveau", "loyal": "Fidèle", "at_risk": "À risque", "inactive": "Inactif"}
INACTIVE_DAYS = 60
ORDER_SORTS = {"created_at": "o.created_at", "total": "CAST(NULLIF(o.total, '') AS INTEGER)", "name": "LOWER(o.name)",
               "city": "LOWER(o.city)", "status": "o.status", "order_number": "o.order_number"}
CUSTOMER_SORTS = {"last_order": "COALESCE(x.last_order, '')", "name": "LOWER(x.display_name)", "orders": "x.orders_count",
                  "value": "x.delivered_cents"}
STOP_WORDS = {"stop", "arret", "arrêt", "arrete", "arrête", "unsubscribe", "توقف", "ستوب"}
START_WORDS = {"start", "reprendre"}
SUGGESTION_TTL_S = 30
TASK_COLS = ("id, created_at, due_at, done_at, customer_phone, order_number, title, assigned_to, created_by, "
             "suggestion_key, dismissed")


class CrmError(Exception):
    pass


def now_dt() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def fmt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def _like(s: str) -> str:
    return "%" + s.replace("\\", "").replace("%", "").replace("_", "").lower() + "%"


def clean_tags(tags: list[str]) -> str:
    out: list[str] = []
    for t in tags:
        t = " ".join(re.sub(r"[,;]", " ", t).split())[:30]
        if t and t.lower() not in (x.lower() for x in out):
            out.append(t)
    return ",".join(out[:12])


class Crm:
    SCHEMA_VERSION = 1

    def __init__(self, store: Any):
        self.store = store
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        if store.needs_schema("crm", self.SCHEMA_VERSION):
            pk = store.serial_pk
            for ddl in (
                """CREATE TABLE IF NOT EXISTS customers (phone TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '',
                    internal_note TEXT NOT NULL DEFAULT '', opted_out INTEGER NOT NULL DEFAULT 0,
                    opted_out_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '')""",
                f"""CREATE TABLE IF NOT EXISTS tasks (id {pk}, created_at TEXT NOT NULL, due_at TEXT NOT NULL,
                    done_at TEXT, customer_phone TEXT NOT NULL DEFAULT '', order_number TEXT,
                    title TEXT NOT NULL, assigned_to TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL DEFAULT '',
                    suggestion_key TEXT, dismissed INTEGER NOT NULL DEFAULT 0)""",
                "CREATE INDEX IF NOT EXISTS tasks_open ON tasks (done_at, due_at)",
                "CREATE UNIQUE INDEX IF NOT EXISTS tasks_suggestion ON tasks (suggestion_key)",
                "CREATE INDEX IF NOT EXISTS tasks_phone ON tasks (customer_phone)",
            ):
                store._exec(ddl)
            if store.backend == "postgres":
                for t in ("customers", "tasks"):
                    store._exec(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
            store.schema_done("crm", self.SCHEMA_VERSION)

    # ================================================================== orders
    def _order_where(self, f: dict[str, Any], with_status: bool = True) -> tuple[str, list[Any]]:
        where, args = ["1 = 1"], []
        q = (f.get("q") or "").strip()
        if q:
            digits = re.sub(r"\D", "", q)
            parts = ["UPPER(o.order_number) LIKE ?", "LOWER(o.name) LIKE ?", "LOWER(o.city) LIKE ?"]
            args += [_like(q).upper(), _like(q), _like(q)]
            if len(digits) >= 3:
                parts.append("o.phone LIKE ?")
                args.append("%" + (digits[1:] if digits.startswith("0") else digits) + "%")
            where.append("(" + " OR ".join(parts) + ")")
        statuses = [s for s in (f.get("statuses") or []) if s in STATUSES]
        if with_status and statuses:
            where.append(f"o.status IN ({', '.join('?' for _ in statuses)})")
            args += statuses
        if f.get("frm"):
            where.append("o.created_at >= ?")
            args.append(f["frm"])
        if f.get("to"):
            where.append("o.created_at <= ?")
            args.append(f["to"] + " 23:59:59")
        if f.get("city"):
            where.append("LOWER(o.city) = LOWER(?)")
            args.append(f["city"])
        if f.get("carrier_id") not in (None, ""):
            where.append("o.carrier_id = ?")
            args.append("" if str(f["carrier_id"]) == "0" else str(f["carrier_id"]))
        if f.get("source"):
            where.append("o.source = ?")
            args.append(f["source"])
        return " AND ".join(where), args

    ORDER_LIST_COLS = ("order_number, created_at, name, phone, city, quantity, total, status, carrier, carrier_id, "
                       "source, delivered_at, cod_status, tracking, carrier_fee_cents")

    def search_orders(self, f: dict[str, Any], sort: str = "created_at", desc: bool = True, limit: int = 50,
                      offset: int = 0) -> dict[str, Any]:
        """One page of orders + the per-status counts for the same filters (2 queries, +1 for cities on page 1)."""
        if sort not in ORDER_SORTS:
            raise CrmError("tri invalide")
        where, args = self._order_where(f)
        cols = ", ".join(f"o.{c}" for c in self.ORDER_LIST_COLS.split(", "))
        rows = self.store._exec(
            f"SELECT {cols}, COALESCE(r.n, 0), COALESCE(c.opted_out, 0) FROM orders o "
            "LEFT JOIN (SELECT phone, COUNT(*) AS n FROM orders WHERE status = 'returned' GROUP BY phone) r ON r.phone = o.phone "
            "LEFT JOIN customers c ON c.phone = o.phone "
            f"WHERE {where} ORDER BY {ORDER_SORTS[sort]} "
            f"{'DESC' if desc else 'ASC'}, o.order_number {'DESC' if desc else 'ASC'} LIMIT ? OFFSET ?",
            (*args, limit + 1, offset), fetch="all",
        )
        names = self.ORDER_LIST_COLS.split(", ")
        items = []
        for r in rows[:limit]:
            d = {k: ("" if v is None else v) for k, v in zip(names, r)}
            d["returns_count"] = int(r[len(names)] or 0)
            d["opted_out"] = bool(r[len(names) + 1])
            items.append(d)
        w2, a2 = self._order_where(f, with_status=False)
        counts = dict(self.store._exec(f"SELECT o.status, COUNT(*) FROM orders o WHERE {w2} GROUP BY o.status",
                                       tuple(a2), fetch="all"))
        out: dict[str, Any] = {"items": items, "has_more": len(rows) > limit,
                               "counts": {s: int(counts.get(s, 0)) for s in STATUSES}}
        if offset == 0:
            out["cities"] = [r[0] for r in self.store._exec(
                "SELECT city FROM orders WHERE city <> '' GROUP BY city ORDER BY COUNT(*) DESC LIMIT 100", fetch="all")]
        return out

    def export_orders(self, f: dict[str, Any], limit: int = 10000) -> list[dict[str, Any]]:
        where, args = self._order_where(f)
        cols = self.ORDER_LIST_COLS + ", address, internal_note"
        rows = self.store._exec(
            f"SELECT {', '.join('o.' + c for c in cols.split(', '))} FROM orders o WHERE {where} "
            "ORDER BY o.created_at DESC, o.order_number DESC LIMIT ?", (*args, limit), fetch="all")
        return [dict(zip(cols.split(", "), ["" if v is None else v for v in r])) for r in rows]

    # ================================================================== customers
    def _customers_sql(self) -> str:
        cutoff = fmt(now_dt() - timedelta(days=INACTIVE_DAYS))
        assert re.fullmatch(r"[\d\- :]+", cutoff)
        return f"""
            SELECT b.phone,
              COALESCE(NULLIF(c.name, ''), a.last_name, '') AS display_name,
              COALESCE(NULLIF(c.city, ''), a.last_city, '') AS display_city,
              COALESCE(NULLIF(c.address, ''), a.last_address, '') AS display_address,
              COALESCE(c.tags, '') AS tags, COALESCE(c.internal_note, '') AS internal_note,
              COALESCE(c.opted_out, 0) AS opted_out,
              COALESCE(a.orders_count, 0) AS orders_count, COALESCE(a.delivered, 0) AS delivered,
              COALESCE(a.delivered_cents, 0) AS delivered_cents, COALESCE(a.returned, 0) AS returned,
              COALESCE(a.cancelled, 0) AS cancelled, a.last_order AS last_order,
              CASE WHEN COALESCE(a.returned, 0) >= 1 OR COALESCE(a.cancelled, 0) >= 2 THEN 'at_risk'
                   WHEN a.last_order IS NULL OR a.last_order < '{cutoff}' THEN 'inactive'
                   WHEN COALESCE(a.delivered, 0) >= 2 THEN 'loyal'
                   ELSE 'new' END AS segment
            FROM (SELECT phone FROM orders WHERE phone <> '' UNION SELECT phone FROM customers) b
            LEFT JOIN (
              SELECT phone, COUNT(*) AS orders_count,
                SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered,
                SUM(CASE WHEN status = 'delivered' THEN COALESCE(CAST(NULLIF(total, '') AS INTEGER), 0) ELSE 0 END) * 100 AS delivered_cents,
                SUM(CASE WHEN status = 'returned' THEN 1 ELSE 0 END) AS returned,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
                MAX(created_at) AS last_order,
                SUBSTR(MAX(created_at || '|' || name), 21) AS last_name,
                SUBSTR(MAX(CASE WHEN city <> '' THEN created_at || '|' || city END), 21) AS last_city,
                SUBSTR(MAX(CASE WHEN address <> '' THEN created_at || '|' || address END), 21) AS last_address
              FROM orders WHERE phone <> '' GROUP BY phone) a ON a.phone = b.phone
            LEFT JOIN customers c ON c.phone = b.phone"""

    CUSTOMER_FIELDS = ("phone", "name", "city", "address", "tags", "internal_note", "opted_out", "orders_count",
                       "delivered", "delivered_cents", "returned", "cancelled", "last_order", "segment")

    def _customer(self, r: Any) -> dict[str, Any]:
        d = dict(zip(self.CUSTOMER_FIELDS, r))
        d["tags"] = [t for t in (d["tags"] or "").split(",") if t]
        d["opted_out"] = bool(d["opted_out"])
        for k in ("orders_count", "delivered", "delivered_cents", "returned", "cancelled"):
            d[k] = int(d[k] or 0)
        d["last_order"] = d["last_order"] or ""
        return d

    def _customer_where(self, q: str, tag: str) -> tuple[str, list[Any]]:
        where, args = ["1 = 1"], []
        q = (q or "").strip()
        if q:
            digits = re.sub(r"\D", "", q)
            parts = ["LOWER(x.display_name) LIKE ?", "LOWER(x.display_city) LIKE ?", "LOWER(x.tags) LIKE ?"]
            args += [_like(q)] * 3
            if len(digits) >= 3:
                parts.append("x.phone LIKE ?")
                args.append("%" + (digits[1:] if digits.startswith("0") else digits) + "%")
            where.append("(" + " OR ".join(parts) + ")")
        if tag:
            where.append("(',' || LOWER(x.tags) || ',') LIKE ?")
            args.append("%," + tag.lower().replace("%", "").replace("_", "") + ",%")
        return " AND ".join(where), args

    def list_customers(self, q: str = "", segment: str = "", tag: str = "", sort: str = "last_order", desc: bool = True,
                       limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if sort not in CUSTOMER_SORTS or (segment and segment not in SEGMENTS):
            raise CrmError("filtre invalide")
        where, args = self._customer_where(q, tag)
        cols = ("x.phone, x.display_name, x.display_city, x.display_address, x.tags, x.internal_note, x.opted_out, "
                "x.orders_count, x.delivered, x.delivered_cents, x.returned, x.cancelled, x.last_order, x.segment")
        seg = " AND x.segment = ?" if segment else ""
        nulls = CUSTOMER_SORTS[sort]
        rows = self.store._exec(
            f"SELECT {cols} FROM ({self._customers_sql()}) x WHERE {where}{seg} "
            f"ORDER BY {nulls} {'DESC' if desc else 'ASC'}, x.phone LIMIT ? OFFSET ?",
            (*args, *([segment] if segment else []), limit + 1, offset), fetch="all")
        counts = dict(self.store._exec(
            f"SELECT x.segment, COUNT(*) FROM ({self._customers_sql()}) x WHERE {where} GROUP BY x.segment",
            tuple(args), fetch="all"))
        return {"items": [self._customer(r) for r in rows[:limit]], "has_more": len(rows) > limit,
                "counts": {s: int(counts.get(s, 0)) for s in SEGMENTS}}

    def get_customer(self, phone: str) -> dict[str, Any] | None:
        row = self.store._exec(
            "SELECT x.phone, x.display_name, x.display_city, x.display_address, x.tags, x.internal_note, x.opted_out, "
            "x.orders_count, x.delivered, x.delivered_cents, x.returned, x.cancelled, x.last_order, x.segment "
            f"FROM ({self._customers_sql()}) x WHERE x.phone = ?", (phone,), fetch="one")
        return self._customer(row) if row else None

    def customer_orders(self, phone: str, limit: int = 200) -> list[dict[str, Any]]:
        cols = "order_number, created_at, quantity, total, status, city, carrier, delivered_at, return_reason, source"
        rows = self.store._exec(f"SELECT {cols} FROM orders WHERE phone = ? ORDER BY created_at DESC, order_number DESC LIMIT ?",
                                (phone, limit), fetch="all")
        return [dict(zip(cols.split(", "), ["" if v is None else v for v in r])) for r in rows]

    def update_customer(self, phone: str, **fields: Any) -> None:
        allowed = {"name", "city", "address", "tags", "internal_note", "opted_out"}
        fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "tags" in fields:
            fields["tags"] = clean_tags(fields["tags"])
        if "opted_out" in fields:
            fields["opted_out_at"] = fmt(now_dt()) if fields["opted_out"] else ""
            fields["opted_out"] = 1 if fields["opted_out"] else 0
        fields["updated_at"] = fmt(now_dt())
        self.store._exec("INSERT INTO customers (phone) VALUES (?) ON CONFLICT (phone) DO NOTHING", (phone,))
        sets = ", ".join(f"{k} = ?" for k in fields)  # keys whitelisted above
        self.store._exec(f"UPDATE customers SET {sets} WHERE phone = ?", (*fields.values(), phone))
        self._cache.clear()

    def opted_out(self, phone: str) -> bool:
        row = self.store._exec("SELECT opted_out FROM customers WHERE phone = ?", (phone,), fetch="one")
        return bool(row and row[0])

    def handle_keyword(self, phone: str, text: str) -> str | None:
        """'STOP' from a client → opted out; 'START' → back in. Returns 'stop' / 'start' / None."""
        word = re.sub(r"[^\w؀-ۿ]", "", (text or "").strip().lower())
        if word in STOP_WORDS:
            self.update_customer(phone, opted_out=True)
            return "stop"
        if word in START_WORDS and self.opted_out(phone):
            self.update_customer(phone, opted_out=False)
            return "start"
        return None

    # ================================================================== tasks
    def _task(self, r: Any) -> dict[str, Any]:
        d = dict(zip([c.strip() for c in TASK_COLS.split(",")], r))
        d["dismissed"] = bool(d["dismissed"])
        d["order_number"] = d["order_number"] or ""
        d["done_at"] = d["done_at"] or ""
        return d

    def add_task(self, *, title: str, due_at: str, admin: str, customer_phone: str = "", order_number: str = "",
                 assigned_to: str = "", suggestion_key: str | None = None, done: bool = False,
                 dismissed: bool = False) -> dict[str, Any]:
        title = " ".join(title.split())
        if not title:
            raise CrmError("titre requis")
        now = fmt(now_dt())
        row = self.store._exec(
            "INSERT INTO tasks (created_at, due_at, done_at, customer_phone, order_number, title, assigned_to, created_by, "
            "suggestion_key, dismissed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (suggestion_key) DO NOTHING RETURNING id",
            (now, due_at, now if done else None, customer_phone, order_number or None, title[:200], assigned_to, admin,
             suggestion_key, 1 if dismissed else 0), fetch="one")
        if not row:
            raise CrmError("Cette suggestion a déjà été traitée.")
        self._cache.clear()
        return self.get_task(int(row[0]))  # type: ignore[return-value]

    def get_task(self, tid: int) -> dict[str, Any] | None:
        row = self.store._exec(f"SELECT {TASK_COLS} FROM tasks WHERE id = ?", (tid,), fetch="one")
        return self._task(row) if row else None

    def update_task(self, tid: int, **fields: Any) -> dict[str, Any]:
        t = self.get_task(tid)
        if not t:
            raise CrmError("tâche introuvable")
        sets: dict[str, Any] = {}
        if fields.get("done") is not None:
            sets["done_at"] = fmt(now_dt()) if fields["done"] else None
        for k in ("due_at", "title", "assigned_to"):
            if fields.get(k) is not None:
                sets[k] = " ".join(str(fields[k]).split()) if k == "title" else fields[k]
        if "title" in sets and not sets["title"]:
            raise CrmError("titre requis")
        if sets:
            self.store._exec(f"UPDATE tasks SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), tid))
            self._cache.clear()
        return self.get_task(tid)  # type: ignore[return-value]

    def list_tasks(self, view: str, limit: int = 50, offset: int = 0, phone: str = "") -> dict[str, Any]:
        day = now_dt().strftime("%Y-%m-%d")
        start, end = day + " 00:00:00", day + " 23:59:59"
        cond = {"today": ("done_at IS NULL AND due_at >= ? AND due_at <= ?", (start, end), "due_at"),
                "late": ("done_at IS NULL AND due_at < ?", (start,), "due_at"),
                "upcoming": ("done_at IS NULL AND due_at > ?", (end,), "due_at"),
                "done": ("done_at IS NOT NULL AND dismissed = 0", (), "done_at DESC")}
        if view not in cond:
            raise CrmError("vue invalide")
        where, args, order = cond[view]
        if phone:
            where += " AND customer_phone = ?"
            args = (*args, phone)
        rows = self.store._exec(f"SELECT {TASK_COLS} FROM tasks WHERE {where} ORDER BY {order}, id LIMIT ? OFFSET ?",
                                (*args, limit + 1, offset), fetch="all")
        return {"items": [self._task(r) for r in rows[:limit]], "has_more": len(rows) > limit}

    def task_counts(self) -> dict[str, int]:
        day = now_dt().strftime("%Y-%m-%d")
        row = self.store._exec(
            "SELECT SUM(CASE WHEN due_at < ? THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN due_at >= ? AND due_at <= ? THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN due_at > ? THEN 1 ELSE 0 END) FROM tasks WHERE done_at IS NULL",
            (day + " 00:00:00", day + " 00:00:00", day + " 23:59:59", day + " 23:59:59"), fetch="one")
        return {"late": int(row[0] or 0), "today": int(row[1] or 0), "upcoming": int(row[2] or 0)}

    # ------------------------------------------------------------------ computed suggestions
    def suggestions(self, owner: bool, *, fresh: bool = False) -> list[dict[str, Any]]:
        """Follow-ups computed from the data (not stored until accepted). Cached 30 s; a handful of queries."""
        key = "owner" if owner else "agent"
        hit = self._cache.get(key)
        if hit and not fresh and time.time() - hit[0] < SUGGESTION_TTL_S:
            return hit[1]
        items = self._compute_suggestions(owner)
        self._cache[key] = (time.time(), items)
        return items

    def _compute_suggestions(self, owner: bool) -> list[dict[str, Any]]:
        now = now_dt()
        out: list[dict[str, Any]] = []
        x = self.store._exec

        def add(k: str, kind: str, title: str, phone: str = "", number: str = "", since: str = "") -> None:
            out.append({"key": k, "kind": kind, "title": title, "customer_phone": phone, "order_number": number,
                        "since": since})

        for n, name, phone, created, st in x(
                "SELECT order_number, name, phone, created_at, status FROM orders WHERE status IN ('new', 'awaiting_details') "
                "AND created_at < ? AND created_at > ? "
                "AND phone NOT IN (SELECT phone FROM customers WHERE opted_out = 1) "  # STOP: no reminder to write
                "ORDER BY created_at LIMIT 100",
                (fmt(now - timedelta(hours=6)), fmt(now - timedelta(days=30))), fetch="all"):
            add(f"stale:{n}", "stale", f"Relancer {name or 'le client'} : {n} sans réponse depuis plus de 6 h", phone, n, created)
        for n, name, phone, since in x(
                "SELECT order_number, name, phone, COALESCE(NULLIF(confirmed_at, ''), created_at) FROM orders "
                "WHERE status = 'confirmed' AND COALESCE(NULLIF(confirmed_at, ''), created_at) < ? "
                "ORDER BY 4 LIMIT 100", (fmt(now - timedelta(hours=48)),), fetch="all"):
            add(f"ship:{n}", "not_shipped", f"Expédier {n} ({name}) : confirmée depuis plus de 48 h", phone, n, since)
        for n, name, phone, since in x(
                "SELECT order_number, name, phone, COALESCE(NULLIF(shipped_at, ''), updated_at) FROM orders "
                "WHERE status = 'shipped' AND COALESCE(NULLIF(shipped_at, ''), updated_at) < ? ORDER BY 4 LIMIT 100",
                (fmt(now - timedelta(days=5)),), fetch="all"):
            add(f"deliver:{n}", "not_delivered", f"Vérifier la livraison de {n} ({name}) : expédiée depuis plus de 5 jours",
                phone, n, since)
        for n, name, phone in x(
                "SELECT order_number, name, phone FROM orders WHERE status = 'returned' AND return_reason = '' "
                "ORDER BY returned_at LIMIT 100", fetch="all"):
            add(f"reason:{n}", "return_reason", f"Noter la raison du retour de {n} ({name})", phone, n)
        if owner:
            for n, name, phone, delivered, carrier, delay in x(
                    "SELECT o.order_number, o.name, o.phone, o.delivered_at, COALESCE(c.name, ''), "
                    "COALESCE(c.remit_delay_days, 7) FROM orders o LEFT JOIN carriers c ON o.carrier_id = CAST(c.id AS TEXT) "
                    "WHERE o.cod_status = 'with_carrier' AND o.delivered_at <> '' ORDER BY o.delivered_at LIMIT 300",
                    fetch="all"):
                if delivered < fmt(now - timedelta(days=int(delay))):
                    add(f"cod:{n}", "cod_late",
                        f"Réclamer l'encaissement de {n} à {carrier or 'au livreur'} (livrée le {delivered[8:10]}/{delivered[5:7]})",
                        phone, n, delivered)
            for number, expected in x(
                    "SELECT number, expected_at FROM purchase_orders WHERE status IN ('ordered', 'partially_received') "
                    "AND expected_at IS NOT NULL AND expected_at <> '' AND expected_at < ? ORDER BY expected_at LIMIT 50",
                    (now.strftime("%Y-%m-%d"),), fetch="all"):
                add(f"po:{number}", "po_late", f"Relancer le fournisseur : {number} attendue le {expected[8:10]}/{expected[5:7]}",
                    since=expected)
        stock = self.store.get_settings(["stock_tracking_started", "stock_low_threshold"])
        if stock.get("stock_tracking_started") == "1":
            row = x("SELECT balance_after FROM stock_movements ORDER BY id DESC LIMIT 1", fetch="one")
            on_hand = int(row[0]) if row else 0
            threshold = int(stock.get("stock_low_threshold") or 10)
            if on_hand <= threshold:
                add(f"stock:{now.strftime('%Y-%m-%d')}", "stock_low",
                    f"Stock bas : {on_hand} unité{'s' if abs(on_hand) > 1 else ''} restante{'s' if abs(on_hand) > 1 else ''}"
                    " — passer une commande fournisseur")
        if out:
            keys = [s["key"] for s in out]
            taken: set[str] = set()
            for i in range(0, len(keys), 500):
                part = keys[i:i + 500]
                taken |= {r[0] for r in x(f"SELECT suggestion_key FROM tasks WHERE suggestion_key IN ({', '.join('?' for _ in part)})",
                                          tuple(part), fetch="all")}
            out = [s for s in out if s["key"] not in taken]
        return out


def csv_rows(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> str:
    import csv
    import io

    from .finance import csv_cell

    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow([label for _, label in cols])
    for r in rows:
        w.writerow([csv_cell(r.get(k, "")) for k, _ in cols])
    return buf.getvalue()
