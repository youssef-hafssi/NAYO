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
STATUSES = ("new", "awaiting_details", "confirmed", "cancelled", "needs_human")


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

    def __init__(self, store: Any):
        self.store = store
        cols = ", ".join(f"{h} TEXT NOT NULL DEFAULT ''" for h in HEADERS if h != "order_number")
        store._exec(f"CREATE TABLE IF NOT EXISTS orders (order_number TEXT PRIMARY KEY, {cols})")
        store._exec("CREATE INDEX IF NOT EXISTS orders_phone ON orders (phone)")
        if store.backend == "postgres":
            store._exec("ALTER TABLE orders ENABLE ROW LEVEL SECURITY")

    def _row(self, values: Any) -> dict[str, Any]:
        return dict(zip(HEADERS, values))

    def append(self, order: dict[str, Any]) -> None:
        cols = ", ".join(HEADERS)
        marks = ", ".join("?" for _ in HEADERS)
        self.store._exec(
            f"INSERT INTO orders ({cols}) VALUES ({marks}) ON CONFLICT (order_number) DO NOTHING",
            tuple(str(order.get(h, "")) for h in HEADERS),
        )

    def get(self, order_number: str) -> dict[str, Any] | None:
        row = self.store._exec(
            f"SELECT {', '.join(HEADERS)} FROM orders WHERE UPPER(order_number) = UPPER(?)", (order_number,), fetch="one"
        )
        return self._row(row) if row else None

    def find_open_by_phone(self, phone: str, statuses: tuple[str, ...] = OPEN_STATUSES) -> dict[str, Any] | None:
        marks = ", ".join("?" for _ in statuses)
        row = self.store._exec(
            f"SELECT {', '.join(HEADERS)} FROM orders WHERE phone = ? AND status IN ({marks}) "
            "ORDER BY created_at DESC, order_number DESC LIMIT 1",
            (phone, *statuses),
            fetch="one",
        )
        return self._row(row) if row else None

    def update(self, order_number: str, **fields: Any) -> None:
        unknown = set(fields) - set(HEADERS)
        if unknown:
            raise ValueError(f"unknown columns: {unknown}")
        fields["updated_at"] = now_local()
        sets = ", ".join(f"{k} = ?" for k in fields)  # keys whitelisted above
        self.store._exec(
            f"UPDATE orders SET {sets} WHERE UPPER(order_number) = UPPER(?)", (*[str(v) for v in fields.values()], order_number)
        )
