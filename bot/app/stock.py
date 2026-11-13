"""Stock with weighted average cost (CMP — coût moyen pondéré). Single product.

- stock_movements: every change, with the balance and the average cost AFTER it (latest row = current state).
  Each write runs in one transaction under one lock, so two confirmations can never take the same last unit.
- stock_order_units: how many units each order currently holds, and at which unit cost (its COGS).
- Tracking starts only when the owner enters the opening stock and its unit cost. Before that nothing is
  deducted or blocked, and orders already confirmed at that moment are backfilled without any movement.
- StockOrders wraps the order store (bot, website and admin all write through it): after any change of
  status or quantity, desired units = quantity if confirmed/shipped/delivered else 0; the difference with
  stock_order_units becomes ONE movement. Running the same update twice changes nothing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from .sheets import CONFIRMED_LIKE, TZ, now_local

log = logging.getLogger("nayo.stock")

LOCK = "nayo-stock"
ENTRY_REASONS = ("opening", "purchase", "restock_manual")
REASONS = ENTRY_REASONS + ("adjustment", "order_confirmed", "order_changed", "order_cancelled", "order_returned")
MAX_UNITS = 100_000
DEFAULT_THRESHOLD = 10


class InsufficientStock(Exception):
    def __init__(self, available: int):
        super().__init__(f"Stock insuffisant : il reste {available}")
        self.available = available


def mad_to_cents(value: float | int | str) -> int:
    cents = round(float(value) * 100)
    if not 0 <= cents <= 100_000 * 100:
        raise ValueError("montant invalide")
    return cents


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


MOVE_COLUMNS = ("id, at, delta, reason, order_number, ref_type, ref_id, admin_name, note, unit_cost_cents, "
                "balance_after, avg_cost_cents_after, written_off")


class Stock:
    SCHEMA_VERSION = 1

    def __init__(self, store: Any):
        self.store = store
        if store.needs_schema("stock", self.SCHEMA_VERSION):
            self._create(store)
            store.schema_done("stock", self.SCHEMA_VERSION)

    @staticmethod
    def _create(store: Any) -> None:
        store._exec(
            f"""CREATE TABLE IF NOT EXISTS stock_movements (
                id {store.serial_pk},
                at TEXT NOT NULL,
                delta INTEGER NOT NULL,
                reason TEXT NOT NULL,
                order_number TEXT,
                ref_type TEXT,
                ref_id TEXT,
                admin_name TEXT,
                note TEXT NOT NULL DEFAULT '',
                unit_cost_cents BIGINT NOT NULL DEFAULT 0,
                balance_after INTEGER NOT NULL,
                avg_cost_cents_after BIGINT NOT NULL DEFAULT 0,
                written_off INTEGER NOT NULL DEFAULT 0
            )"""
        )
        store._exec("CREATE INDEX IF NOT EXISTS stock_movements_order ON stock_movements (order_number)")
        store._exec("CREATE INDEX IF NOT EXISTS stock_movements_at ON stock_movements (at)")
        store._exec(
            "CREATE TABLE IF NOT EXISTS stock_order_units (order_number TEXT PRIMARY KEY, units INTEGER NOT NULL, "
            "unit_cost_cents BIGINT NOT NULL DEFAULT 0)"
        )
        if store.backend == "postgres":
            for t in ("stock_movements", "stock_order_units"):
                store._exec(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")

    # ------------------------------------------------------------------ state
    def tracking(self) -> bool:
        return self.store.get_setting("stock_tracking_started") == "1"

    def threshold(self) -> int:
        return _int(self.store.get_setting("stock_low_threshold", str(DEFAULT_THRESHOLD)), DEFAULT_THRESHOLD)

    def set_threshold(self, value: int) -> None:
        self.store.set_setting("stock_low_threshold", str(int(value)))

    @staticmethod
    def _state(tx: Any) -> tuple[int, int]:
        row = tx.exec("SELECT balance_after, avg_cost_cents_after FROM stock_movements ORDER BY id DESC LIMIT 1",
                      fetch="one")
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def current(self) -> tuple[int, int]:
        row = self.store._exec(
            "SELECT balance_after, avg_cost_cents_after FROM stock_movements ORDER BY id DESC LIMIT 1", fetch="one"
        )
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def available(self) -> int | None:
        """Units that can still be sold, or None when tracking hasn't started (no limit)."""
        return max(self.current()[0], 0) if self.tracking() else None

    @staticmethod
    def _insert(tx: Any, *, delta: int, reason: str, unit_cost: int, balance: int, avg: int,
                order_number: str | None = None, ref_type: str | None = None, ref_id: str | None = None,
                admin: str | None = None, note: str = "", written_off: int = 0) -> int:
        row = tx.exec(
            "INSERT INTO stock_movements (at, delta, reason, order_number, ref_type, ref_id, admin_name, note, "
            "unit_cost_cents, balance_after, avg_cost_cents_after, written_off) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (now_local(), delta, reason, order_number, ref_type, ref_id, admin, note[:300], unit_cost, balance, avg,
             written_off),
            fetch="one",
        )
        return int(row[0])

    def summary(self) -> dict[str, Any]:
        cfg = self.store.get_settings(("stock_tracking_started", "stock_low_threshold", "stock_ledger_start"))
        tracking = cfg.get("stock_tracking_started") == "1"
        on_hand, avg = self.current()
        since = (datetime.now(TZ) - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
        row = self.store._exec(
            "SELECT COALESCE(SUM(-delta), 0) FROM stock_movements WHERE reason IN "
            "('order_confirmed', 'order_changed', 'order_cancelled', 'order_returned') AND at >= ?",
            (since,), fetch="one",
        )
        out_14d = max(int(row[0] or 0), 0)
        per_day = out_14d / 14
        threshold = _int(cfg.get("stock_low_threshold", DEFAULT_THRESHOLD), DEFAULT_THRESHOLD)
        return {
            "tracking": tracking,
            "ledger_start": cfg.get("stock_ledger_start") or None,
            "on_hand": on_hand,
            "avg_cost_cents": avg,
            "stock_value_cents": max(on_hand, 0) * avg,
            "low_threshold": threshold,
            "low": tracking and on_hand <= threshold,
            "out": tracking and on_hand <= 0,
            "sold_14d": out_14d,
            "days_of_stock": round(on_hand / per_day, 1) if per_day > 0 and on_hand > 0 else None,
        }

    # ------------------------------------------------------------------ owner actions
    def open(self, quantity: int, unit_cost_cents: int, admin: str, confirmed_orders: list[tuple[str, int]]) -> None:
        """Starts tracking: opening movement + backfill of orders already confirmed (no movements for them)."""
        if not 0 <= quantity <= MAX_UNITS:
            raise ValueError("quantité invalide")
        with self.store.tx(LOCK) as tx:
            row = tx.exec("SELECT value FROM settings WHERE key = 'stock_tracking_started'", fetch="one")
            if row and row[0] == "1":
                raise ValueError("Le suivi du stock a déjà commencé.")
            self._insert(tx, delta=quantity, reason="opening", unit_cost=unit_cost_cents, balance=quantity,
                         avg=unit_cost_cents, admin=admin, note="Stock d'ouverture (commandes déjà confirmées exclues)")
            for number, units in confirmed_orders:
                if units > 0:
                    tx.exec("INSERT INTO stock_order_units (order_number, units, unit_cost_cents) VALUES (?, ?, ?) "
                            "ON CONFLICT (order_number) DO NOTHING", (number, units, unit_cost_cents))
            for key, value in (("stock_tracking_started", "1"),
                               ("stock_ledger_start", datetime.now(TZ).strftime("%Y-%m-%d"))):
                tx.exec("INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))
        log.info("stock tracking started with %d units", quantity)

    def receive(self, quantity: int, unit_cost_cents: int, *, reason: str = "restock_manual", admin: str | None = None,
                note: str = "", ref_type: str | None = None, ref_id: str | None = None) -> dict[str, Any]:
        """Entry at a cost: updates the weighted average."""
        if reason not in ENTRY_REASONS or not 1 <= quantity <= MAX_UNITS:
            raise ValueError("entrée invalide")
        self._require_tracking()
        with self.store.tx(LOCK) as tx:
            return self.receive_in(tx, quantity, unit_cost_cents, reason=reason, admin=admin, note=note,
                                   ref_type=ref_type, ref_id=ref_id)

    def receive_in(self, tx: Any, quantity: int, unit_cost_cents: int, *, reason: str, admin: str | None = None,
                   note: str = "", ref_type: str | None = None, ref_id: str | None = None) -> dict[str, Any]:
        """Same as receive(), inside a transaction the caller already holds under LOCK (purchase receipts)."""
        if reason not in ENTRY_REASONS or not 1 <= quantity <= MAX_UNITS:
            raise ValueError("entrée invalide")
        bal, avg = self._state(tx)
        new_bal = bal + quantity
        new_avg = round((bal * avg + quantity * unit_cost_cents) / new_bal) if bal > 0 else unit_cost_cents
        mid = self._insert(tx, delta=quantity, reason=reason, unit_cost=unit_cost_cents, balance=new_bal,
                           avg=new_avg, admin=admin, note=note, ref_type=ref_type, ref_id=ref_id)
        return {"id": mid, "on_hand": new_bal, "avg_cost_cents": new_avg}

    def adjust(self, new_quantity: int, note: str, admin: str) -> dict[str, Any] | None:
        """Counted stock differs from the books: the difference is recorded at the current average cost."""
        if not 0 <= new_quantity <= MAX_UNITS or len(note.strip()) < 3:
            raise ValueError("correction invalide (une note est obligatoire)")
        self._require_tracking()
        with self.store.tx(LOCK) as tx:
            bal, avg = self._state(tx)
            delta = new_quantity - bal
            if delta == 0:
                return None
            mid = self._insert(tx, delta=delta, reason="adjustment", unit_cost=avg, balance=new_quantity, avg=avg,
                               admin=admin, note=note.strip())
        return {"id": mid, "on_hand": new_quantity, "delta": delta}

    def _require_tracking(self) -> None:
        if not self.tracking():
            raise ValueError("Entrez d'abord le stock d'ouverture.")

    # ------------------------------------------------------------------ orders
    def sync_order(self, order_number: str, quantity: int, status: str, *, check: bool = False,
                   recoverable: bool = True, admin: str | None = None) -> dict[str, Any] | None:
        """Brings stock_order_units in line with the order. Idempotent. With check=True an exit larger than
        the stock raises InsufficientStock (inside the lock: nothing is written)."""
        if not self.tracking():
            return None
        desired = quantity if status in CONFIRMED_LIKE else 0
        with self.store.tx(LOCK) as tx:
            row = tx.exec("SELECT units, unit_cost_cents FROM stock_order_units WHERE order_number = ?",
                          (order_number,), fetch="one")
            already, order_cost = (int(row[0]), int(row[1])) if row else (0, 0)
            if desired == already:
                return None
            bal, avg = self._state(tx)
            diff = desired - already
            if diff > 0:  # units leave the stock at the current average cost
                if check and diff > bal:
                    raise InsufficientStock(max(bal, 0) + already)
                new_bal = bal - diff
                self._insert(tx, delta=-diff, reason="order_confirmed" if already == 0 else "order_changed",
                             unit_cost=avg, balance=new_bal, avg=avg, order_number=order_number, admin=admin)
                new_cost = avg if already == 0 else round((already * order_cost + diff * avg) / desired)
                delta = -diff
            else:  # units come back at the order's own cost
                back = -diff
                reason = ("order_returned" if status == "returned" else
                          "order_cancelled" if status == "cancelled" else "order_changed")
                if status == "returned" and not recoverable:
                    new_bal = bal
                    self._insert(tx, delta=0, reason="order_returned", unit_cost=order_cost, balance=bal, avg=avg,
                                 order_number=order_number, admin=admin, written_off=back,
                                 note=f"Produit non récupérable : {back} unité(s) perdue(s)")
                    delta = 0
                else:
                    new_bal = bal + back
                    new_avg = round((bal * avg + back * order_cost) / new_bal) if bal > 0 and new_bal > 0 else order_cost
                    self._insert(tx, delta=back, reason=reason, unit_cost=order_cost, balance=new_bal, avg=new_avg,
                                 order_number=order_number, admin=admin)
                    delta = back
                new_cost = order_cost
            tx.exec("INSERT INTO stock_order_units (order_number, units, unit_cost_cents) VALUES (?, ?, ?) "
                    "ON CONFLICT (order_number) DO UPDATE SET units = excluded.units, "
                    "unit_cost_cents = excluded.unit_cost_cents", (order_number, desired, new_cost))
        return {"delta": delta, "on_hand": new_bal, "low": new_bal <= self.threshold()}

    # ------------------------------------------------------------------ reads
    @staticmethod
    def _move(r: Any) -> dict[str, Any]:
        return dict(zip([c.strip() for c in MOVE_COLUMNS.split(",")], r))

    def movements(self, cursor: int | None = None, limit: int = 50) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        if cursor:
            rows = self.store._exec(f"SELECT {MOVE_COLUMNS} FROM stock_movements WHERE id < ? ORDER BY id DESC LIMIT ?",
                                    (int(cursor), limit + 1), fetch="all")
        else:
            rows = self.store._exec(f"SELECT {MOVE_COLUMNS} FROM stock_movements ORDER BY id DESC LIMIT ?",
                                    (limit + 1,), fetch="all")
        items = [self._move(r) for r in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["id"] if len(rows) > limit else None}

    def order_movements(self, order_number: str) -> list[dict[str, Any]]:
        rows = self.store._exec(f"SELECT {MOVE_COLUMNS} FROM stock_movements WHERE order_number = ? ORDER BY id",
                                (order_number,), fetch="all")
        return [self._move(r) for r in rows]


class StockOrders:
    """Order store wrapper: every status/quantity change goes through Stock.sync_order (one place)."""

    def __init__(self, inner: Any, stock: Stock):
        self.inner, self.stock = inner, stock

    def append(self, order: dict[str, Any]) -> None:
        self.inner.append(order)
        if str(order.get("status", "")) in CONFIRMED_LIKE:
            self.reconcile(str(order.get("order_number", "")))

    def get(self, order_number: str) -> dict[str, Any] | None:
        return self.inner.get(order_number)

    def find_open_by_phone(self, phone: str, statuses: tuple[str, ...] | None = None) -> dict[str, Any] | None:
        return self.inner.find_open_by_phone(phone, statuses) if statuses else self.inner.find_open_by_phone(phone)

    def update(self, order_number: str, *, stock_check: bool = False, recoverable: bool = True,
               stock_admin: str | None = None, **fields: Any) -> None:
        cur = self.inner.get(order_number) if {"status", "quantity"} & set(fields) else None
        if not cur:
            self.inner.update(order_number, **fields)
            return
        new = {**cur, **fields}
        number = cur["order_number"]
        # Stock first (may refuse with InsufficientStock — then the order is not changed at all).
        self.stock.sync_order(number, _int(new.get("quantity"), 1), str(new.get("status", "")), check=stock_check,
                              recoverable=recoverable, admin=stock_admin)
        try:
            self.inner.update(order_number, **fields)
        except Exception:
            self.stock.sync_order(number, _int(cur.get("quantity"), 1), str(cur.get("status", "")), admin=stock_admin)
            raise

    def reconcile(self, order_number: str) -> dict[str, Any] | None:
        o = self.inner.get(order_number)
        if not o:
            return None
        return self.stock.sync_order(o["order_number"], _int(o.get("quantity"), 1), str(o.get("status", "")))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)
