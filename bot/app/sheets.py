"""Google Sheet "orders" — the owner's view of every order. One row per order."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

log = logging.getLogger("nayo.sheets")

TZ = ZoneInfo("Africa/Casablanca")

HEADERS = [
    "order_number",
    "created_at",
    "name",
    "phone",
    "quantity",
    "total",
    "status",
    "city",
    "address",
    "whatsapp_from",
    "notes",
    "updated_at",
]

OPEN_STATUSES = ("new", "awaiting_details")
# After "confirmed": shipped → delivered, or returned (client refused / not delivered).
STATUSES = ("new", "awaiting_details", "confirmed", "shipped", "delivered", "returned", "cancelled", "needs_human")
CONFIRMED_LIKE = ("confirmed", "shipped", "delivered")  # the order is "on": units are committed
CLOSED_LIKE = ("cancelled", "returned")

# Extra order fields kept in the database only (the Google Sheet keeps exactly the 12 HEADERS).
EXTRA_COLUMNS = ["carrier", "tracking", "delivered_at", "return_reason", "source", "internal_note", "shipped_at"]
ALL_COLUMNS = HEADERS + EXTRA_COLUMNS


def now_local() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


class OrdersRepo(Protocol):
    def append(self, order: dict[str, Any]) -> None: ...
    def get(self, order_number: str) -> dict[str, Any] | None: ...
    def find_open_by_phone(self, phone: str, statuses: tuple[str, ...] = OPEN_STATUSES) -> dict[str, Any] | None: ...
    def update(self, order_number: str, **fields: Any) -> None: ...


class SheetOrders:
    def __init__(self, sheet_id: str, service_account: str, tab: str = "orders"):
        import gspread

        if service_account.strip().startswith("{"):
            gc = gspread.service_account_from_dict(json.loads(service_account))
        else:
            gc = gspread.service_account(filename=service_account)
        sh = gc.open_by_key(sheet_id)
        try:
            self.ws = sh.worksheet(tab)
        except gspread.WorksheetNotFound:
            self.ws = sh.add_worksheet(title=tab, rows=1000, cols=len(HEADERS))
        if self.ws.row_values(1) != HEADERS:
            self.ws.update(range_name="A1", values=[HEADERS], value_input_option="RAW")
        self._lock = threading.Lock()

    def _rows(self) -> list[dict[str, Any]]:
        values = self.ws.get_all_values()
        out = []
        for i, row in enumerate(values[1:], start=2):
            row = row + [""] * (len(HEADERS) - len(row))
            rec = dict(zip(HEADERS, row))
            rec["_row"] = i
            out.append(rec)
        return out

    def append(self, order: dict[str, Any]) -> None:
        row = [str(order.get(h, "")) for h in HEADERS]
        with self._lock:
            # RAW keeps phone numbers / order numbers as text (no scientific notation, no formulas).
            self.ws.append_row(row, value_input_option="RAW", insert_data_option="INSERT_ROWS")

    def get(self, order_number: str) -> dict[str, Any] | None:
        with self._lock:
            for rec in self._rows():
                if rec["order_number"].strip().upper() == order_number.upper():
                    return rec
        return None

    def find_open_by_phone(self, phone: str, statuses: tuple[str, ...] = OPEN_STATUSES) -> dict[str, Any] | None:
        with self._lock:
            rows = self._rows()
        for rec in reversed(rows):  # most recent first
            if rec["phone"] == phone and rec["status"] in statuses:
                return rec
        return None

    def update(self, order_number: str, **fields: Any) -> None:
        fields = {k: v for k, v in fields.items() if k not in EXTRA_COLUMNS}  # database-only fields
        unknown = set(fields) - set(HEADERS)
        if unknown:
            raise ValueError(f"unknown columns: {unknown}")
        fields["updated_at"] = now_local()
        with self._lock:
            rec = next((r for r in self._rows() if r["order_number"].upper() == order_number.upper()), None)
            if not rec:
                log.warning("update: order %s not found", order_number)
                return
            cells = []
            for k, v in fields.items():
                col = HEADERS.index(k) + 1
                cells.append({"range": _a1(rec["_row"], col), "values": [[str(v)]]})
            self.ws.batch_update(cells, value_input_option="RAW")


def _a1(row: int, col: int) -> str:
    letters = ""
    while col:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row}"


class CsvOrders:
    """Local stand-in for the Google Sheet (ORDERS_BACKEND=csv): same columns, a file you can open in Excel.

    For local tests only — on a free host the file disappears at every restart.
    """

    def __init__(self, path: str = "orders.csv"):
        import csv

        self._csv = csv
        self.path = path
        self._lock = threading.Lock()
        try:
            open(path, "x", newline="", encoding="utf-8-sig").close()
            self._write([])
        except FileExistsError:
            pass
        log.warning("ORDERS_BACKEND=csv (%s): local test mode, orders are not in Google Sheets", path)

    def _read(self) -> list[dict[str, Any]]:
        with open(self.path, newline="", encoding="utf-8-sig") as f:
            rows = list(self._csv.DictReader(f))
        return [{h: (r.get(h) or "") for h in HEADERS} for r in rows]

    def _write(self, rows: list[dict[str, Any]]) -> None:
        with open(self.path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel shows accents/Arabic
            w = self._csv.DictWriter(f, fieldnames=HEADERS)
            w.writeheader()
            w.writerows([{h: r.get(h, "") for h in HEADERS} for r in rows])

    def append(self, order: dict[str, Any]) -> None:
        with self._lock:
            rows = self._read()
            rows.append({h: str(order.get(h, "")) for h in HEADERS})
            self._write(rows)

    def get(self, order_number: str) -> dict[str, Any] | None:
        with self._lock:
            return next((r for r in self._read() if r["order_number"].upper() == order_number.upper()), None)

    def find_open_by_phone(self, phone: str, statuses: tuple[str, ...] = OPEN_STATUSES) -> dict[str, Any] | None:
        with self._lock:
            rows = self._read()
        return next((r for r in reversed(rows) if r["phone"] == phone and r["status"] in statuses), None)

    def update(self, order_number: str, **fields: Any) -> None:
        fields = {k: v for k, v in fields.items() if k not in EXTRA_COLUMNS}  # database-only fields
        unknown = set(fields) - set(HEADERS)
        if unknown:
            raise ValueError(f"unknown columns: {unknown}")
        with self._lock:
            rows = self._read()
            for r in rows:
                if r["order_number"].upper() == order_number.upper():
                    r.update({k: str(v) for k, v in fields.items()}, updated_at=now_local())
                    break
            else:
                log.warning("update: order %s not found", order_number)
                return
            self._write(rows)


class DbOrders:
    """Orders in the bot's own database (ORDERS_BACKEND=db): Supabase Postgres in production.

    Same columns as the Google Sheet. View/edit them in Supabase → Table Editor → orders.
    """

    SCHEMA_VERSION = 2  # bump when columns / indexes below change

    def __init__(self, store: Any):
        self.store = store
        if not store.needs_schema("orders", self.SCHEMA_VERSION):
            return
        cols = ", ".join(f"{h} TEXT NOT NULL DEFAULT ''" for h in HEADERS if h != "order_number")
        store._exec(f"CREATE TABLE IF NOT EXISTS orders (order_number TEXT PRIMARY KEY, {cols})")
        for col in EXTRA_COLUMNS:
            store._ensure_column("orders", col, "TEXT NOT NULL DEFAULT ''")
        store._exec("CREATE INDEX IF NOT EXISTS orders_phone ON orders (phone)")
        store._exec("CREATE INDEX IF NOT EXISTS orders_status_created ON orders (status, created_at)")
        store._exec("CREATE INDEX IF NOT EXISTS orders_created ON orders (created_at)")
        if store.backend == "postgres":
            store._exec("ALTER TABLE orders ENABLE ROW LEVEL SECURITY")
        store.schema_done("orders", self.SCHEMA_VERSION)

    SELECT = ", ".join(ALL_COLUMNS)

    def _row(self, values: Any) -> dict[str, Any]:
        return {k: ("" if v is None else v) for k, v in zip(ALL_COLUMNS, values)}

    def append(self, order: dict[str, Any]) -> None:
        cols = ", ".join(ALL_COLUMNS)
        marks = ", ".join("?" for _ in ALL_COLUMNS)
        self.store._exec(
            f"INSERT INTO orders ({cols}) VALUES ({marks}) ON CONFLICT (order_number) DO NOTHING",
            tuple(str(order.get(h, "")) for h in ALL_COLUMNS),
        )

    def get(self, order_number: str) -> dict[str, Any] | None:
        row = self.store._exec(
            f"SELECT {self.SELECT} FROM orders WHERE UPPER(order_number) = UPPER(?)", (order_number,), fetch="one"
        )
        return self._row(row) if row else None

    def find_open_by_phone(self, phone: str, statuses: tuple[str, ...] = OPEN_STATUSES) -> dict[str, Any] | None:
        marks = ", ".join("?" for _ in statuses)
        row = self.store._exec(
            f"SELECT {self.SELECT} FROM orders WHERE phone = ? AND status IN ({marks}) "
            "ORDER BY created_at DESC, order_number DESC LIMIT 1",
            (phone, *statuses),
            fetch="one",
        )
        return self._row(row) if row else None

    def update(self, order_number: str, **fields: Any) -> None:
        unknown = set(fields) - set(ALL_COLUMNS)
        if unknown:
            raise ValueError(f"unknown columns: {unknown}")
        fields["updated_at"] = now_local()
        sets = ", ".join(f"{k} = ?" for k in fields)  # keys whitelisted above
        self.store._exec(
            f"UPDATE orders SET {sets} WHERE UPPER(order_number) = UPPER(?)", (*[str(v) for v in fields.values()], order_number)
        )

    def for_conversations(self, phones: list[str], numbers: list[str]) -> list[dict[str, Any]]:
        """Every order of these phones or with these numbers, newest first — ONE query for a whole inbox page."""
        if not phones and not numbers:
            return []
        p_marks = ", ".join("?" for _ in phones) or "''"
        n_marks = ", ".join("?" for _ in numbers) or "''"
        rows = self.store._exec(
            f"SELECT {self.SELECT} FROM orders WHERE phone IN ({p_marks}) OR UPPER(order_number) IN ({n_marks}) "
            "ORDER BY created_at DESC, order_number DESC",
            (*phones, *[n.upper() for n in numbers]), fetch="all",
        )
        return [self._row(r) for r in rows]

    def units_in(self, statuses: tuple[str, ...]) -> list[tuple[str, int]]:
        """(order_number, quantity) of every order in these statuses — used to backfill the stock ledger."""
        marks = ", ".join("?" for _ in statuses)
        rows = self.store._exec(
            f"SELECT order_number, CAST(quantity AS INTEGER) FROM orders WHERE status IN ({marks}) AND quantity <> ''",
            tuple(statuses), fetch="all",
        )
        return [(r[0], int(r[1] or 0)) for r in rows]


class MirroredOrders:
    """Wraps the real order store and copies every new/changed order to a Google Sheet through an
    Apps Script web app (SHEET_WEBHOOK_URL). The sheet is a mirror for the owner: if it is down,
    the bot keeps working and only logs a warning.
    """

    def __init__(self, inner: Any, url: str, secret: str, post: Any = None):
        self.inner, self.url, self.secret = inner, url, secret
        if post is None:
            import httpx

            client = httpx.Client(timeout=10, follow_redirects=True)  # Apps Script answers with a 302
            post = client.post
        self._post = post

    def _mirror(self, order_number: str) -> None:
        row = self.inner.get(order_number)
        if not row:
            return
        order = {h: row.get(h, "") for h in HEADERS}
        try:
            r = self._post(self.url, json={"secret": self.secret, "order": order})
            ok = getattr(r, "status_code", 200) < 400 and '"ok":true' in getattr(r, "text", '"ok":true').replace(" ", "")
            if not ok:
                log.warning("sheet mirror refused %s: HTTP %s %s", order_number, getattr(r, "status_code", "?"), getattr(r, "text", "")[:120])
        except Exception as e:  # never break the order flow because of the sheet
            log.warning("sheet mirror failed for %s: %s", order_number, type(e).__name__)

    def append(self, order: dict[str, Any]) -> None:
        self.inner.append(order)
        self._mirror(str(order.get("order_number", "")))

    def get(self, order_number: str) -> dict[str, Any] | None:
        return self.inner.get(order_number)

    def find_open_by_phone(self, phone: str, statuses: tuple[str, ...] = OPEN_STATUSES) -> dict[str, Any] | None:
        return self.inner.find_open_by_phone(phone, statuses)

    def update(self, order_number: str, **fields: Any) -> None:
        self.inner.update(order_number, **fields)
        if set(fields) & set(HEADERS):  # database-only fields (carrier, tracking…) are not in the sheet
            self._mirror(order_number)

    def __getattr__(self, name: str) -> Any:  # extra queries of the inner store (lists, counts…)
        return getattr(self.inner, name)
