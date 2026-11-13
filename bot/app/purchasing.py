"""Suppliers & purchase orders (management accounting, single product).

- PO numbers PO-0001… from an atomic counter.
- Receiving (full or partial, never more than what is left) creates a receipt AND a 'purchase' stock movement
  at the landed unit cost, in ONE transaction under the stock lock:
      landed unit cost = unit cost + (shipping + other costs) / ordered quantity
  (extra costs spread over the ordered quantity, so each partial receipt carries its share).
  This updates the weighted average cost through the stock ledger. Receipts are never edited: a mistake is
  corrected with a stock adjustment (with a note).
- Payments per PO: unpaid / partial / paid. Supplier debt = Σ (total − paid) of committed POs
  (ordered / partially_received / received; drafts and cancelled POs are not debts).
Money is integer centimes everywhere.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .sheets import TZ, now_local
from .stock import LOCK, Stock

PO_STATUSES = ("draft", "ordered", "partially_received", "received", "cancelled")
COMMITTED = ("ordered", "partially_received", "received")
OPEN_FOR_RECEIPT = ("draft", "ordered", "partially_received")
PAYMENT_METHODS = ("cash", "virement", "chèque", "autre")
MAX_MONEY_CENTS = 10_000_000 * 100  # 10 M MAD
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PurchasingError(ValueError):
    pass


def money_cents(value: float | int | str, *, allow_zero: bool = True) -> int:
    cents = round(float(value) * 100)
    if cents < 0 or cents > MAX_MONEY_CENTS or (cents == 0 and not allow_zero):
        raise PurchasingError("montant invalide")
    return cents


def check_date(value: str | None, *, required: bool = False) -> str | None:
    if not value:
        if required:
            raise PurchasingError("date requise")
        return None
    if not DATE_RE.match(value):
        raise PurchasingError("date invalide (AAAA-MM-JJ)")
    datetime.strptime(value, "%Y-%m-%d")
    return value


def today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def landed_unit_cost(po: dict[str, Any]) -> int:
    extra = int(po["shipping_cost_cents"]) + int(po["other_costs_cents"])
    return int(po["unit_cost_cents"]) + round(extra / int(po["quantity"]))


def po_total(po: dict[str, Any]) -> int:
    return int(po["quantity"]) * int(po["unit_cost_cents"]) + int(po["shipping_cost_cents"]) + int(po["other_costs_cents"])


SUPPLIER_COLS = "id, name, phone, city, note, active, created_at"
PO_COLS = ("id, number, supplier_id, ordered_at, expected_at, status, quantity, unit_cost_cents, shipping_cost_cents, "
           "other_costs_cents, note, created_at, created_by")
# One query for a list page: aggregates of receipts and payments as sub-selects (no query per row).
PO_SELECT = (f"SELECT {', '.join('p.' + c.strip() for c in PO_COLS.split(','))}, s.name, "
             "COALESCE((SELECT SUM(r.quantity) FROM purchase_receipts r WHERE r.po_id = p.id), 0), "
             "COALESCE((SELECT SUM(y.amount_cents) FROM supplier_payments y WHERE y.po_id = p.id), 0) "
             "FROM purchase_orders p LEFT JOIN suppliers s ON s.id = p.supplier_id")


class Purchasing:
    SCHEMA_VERSION = 1

    def __init__(self, store: Any, stock: Stock):
        self.store, self.stock = store, stock
        if store.needs_schema("purchasing", self.SCHEMA_VERSION):
            pk = store.serial_pk
            for ddl in (
                f"""CREATE TABLE IF NOT EXISTS suppliers (id {pk}, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL)""",
                f"""CREATE TABLE IF NOT EXISTS purchase_orders (id {pk}, number TEXT NOT NULL UNIQUE,
                    supplier_id INTEGER NOT NULL, ordered_at TEXT, expected_at TEXT, status TEXT NOT NULL,
                    quantity INTEGER NOT NULL, unit_cost_cents BIGINT NOT NULL, shipping_cost_cents BIGINT NOT NULL DEFAULT 0,
                    other_costs_cents BIGINT NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL DEFAULT '')""",
                f"""CREATE TABLE IF NOT EXISTS purchase_receipts (id {pk}, po_id INTEGER NOT NULL, at TEXT NOT NULL,
                    quantity INTEGER NOT NULL, landed_unit_cost_cents BIGINT NOT NULL, admin_name TEXT NOT NULL DEFAULT '',
                    movement_id INTEGER)""",
                f"""CREATE TABLE IF NOT EXISTS supplier_payments (id {pk}, po_id INTEGER NOT NULL, at TEXT NOT NULL,
                    amount_cents BIGINT NOT NULL, method TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
                    admin_name TEXT NOT NULL DEFAULT '')""",
                "CREATE INDEX IF NOT EXISTS po_status ON purchase_orders (status, expected_at)",
                "CREATE INDEX IF NOT EXISTS po_supplier ON purchase_orders (supplier_id)",
                "CREATE INDEX IF NOT EXISTS receipts_po ON purchase_receipts (po_id)",
                "CREATE INDEX IF NOT EXISTS payments_po ON supplier_payments (po_id)",
                "CREATE INDEX IF NOT EXISTS payments_at ON supplier_payments (at)",
            ):
                store._exec(ddl)
            if store.backend == "postgres":
                for t in ("suppliers", "purchase_orders", "purchase_receipts", "supplier_payments"):
                    store._exec(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
            store.schema_done("purchasing", self.SCHEMA_VERSION)

    # ------------------------------------------------------------------ suppliers
    def suppliers(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        where = "" if include_inactive else "WHERE active = 1"
        rows = self.store._exec(f"SELECT {SUPPLIER_COLS} FROM suppliers {where} ORDER BY active DESC, name", fetch="all")
        return [self._supplier(r) for r in rows]

    @staticmethod
    def _supplier(r: Any) -> dict[str, Any]:
        d = dict(zip([c.strip() for c in SUPPLIER_COLS.split(",")], r))
        d["active"] = bool(d["active"])
        return d

    def supplier(self, sid: int) -> dict[str, Any] | None:
        r = self.store._exec(f"SELECT {SUPPLIER_COLS} FROM suppliers WHERE id = ?", (sid,), fetch="one")
        return self._supplier(r) if r else None

    def create_supplier(self, name: str, phone: str = "", city: str = "", note: str = "") -> dict[str, Any]:
        if not name.strip():
            raise PurchasingError("nom requis")
        r = self.store._exec(
            "INSERT INTO suppliers (name, phone, city, note, active, created_at) VALUES (?, ?, ?, ?, 1, ?) RETURNING id",
            (name.strip(), phone.strip(), city.strip(), note.strip(), now_local()), fetch="one",
        )
        return self.supplier(int(r[0]))  # type: ignore[return-value]

    def update_supplier(self, sid: int, **fields: Any) -> dict[str, Any]:
        allowed = {"name", "phone", "city", "note", "active"}
        fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not self.supplier(sid):
            raise PurchasingError("fournisseur introuvable")
        if "name" in fields and not str(fields["name"]).strip():
            raise PurchasingError("nom requis")
        if fields:
            if "active" in fields:
                fields["active"] = 1 if fields["active"] else 0
            sets = ", ".join(f"{k} = ?" for k in fields)
            self.store._exec(f"UPDATE suppliers SET {sets} WHERE id = ?",
                             (*[v.strip() if isinstance(v, str) else v for v in fields.values()], sid))
        return self.supplier(sid)  # type: ignore[return-value]

    # ------------------------------------------------------------------ purchase orders
    def _po(self, r: Any) -> dict[str, Any]:
        cols = [c.strip() for c in PO_COLS.split(",")]
        po = dict(zip(cols, r[: len(cols)]))
        po["supplier_name"], po["received_qty"], po["paid_cents"] = r[len(cols)], int(r[len(cols) + 1]), int(r[len(cols) + 2])
        po["total_cents"] = po_total(po)
        po["landed_unit_cost_cents"] = landed_unit_cost(po)
        po["remaining_qty"] = max(int(po["quantity"]) - po["received_qty"], 0)
        po["due_cents"] = max(po["total_cents"] - po["paid_cents"], 0) if po["status"] in COMMITTED else 0
        po["payment_status"] = ("paid" if po["paid_cents"] >= po["total_cents"] else
                                "partial" if po["paid_cents"] > 0 else "unpaid")
        po["late"] = bool(po["expected_at"]) and po["status"] in ("ordered", "partially_received") \
            and po["expected_at"] < today()
        return po

    def get_po(self, po_id: int) -> dict[str, Any] | None:
        r = self.store._exec(f"{PO_SELECT} WHERE p.id = ?", (po_id,), fetch="one")
        return self._po(r) if r else None

    def list_pos(self, *, status: str | None = None, supplier_id: int | None = None, late: bool = False,
                 limit: int = 50, offset: int = 0) -> dict[str, Any]:
        where, params = [], []
        if status:
            where.append("p.status = ?")
            params.append(status)
        if supplier_id:
            where.append("p.supplier_id = ?")
            params.append(supplier_id)
        if late:
            where.append("p.status IN ('ordered', 'partially_received') AND p.expected_at IS NOT NULL "
                         "AND p.expected_at <> '' AND p.expected_at < ?")
            params.append(today())
        sql = PO_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY p.id DESC LIMIT ? OFFSET ?"
        rows = self.store._exec(sql, (*params, limit + 1, offset), fetch="all")
        items = [self._po(r) for r in rows[:limit]]
        return {"items": items, "has_more": len(rows) > limit}

    def create_po(self, *, supplier_id: int, quantity: int, unit_cost_cents: int, shipping_cost_cents: int = 0,
                  other_costs_cents: int = 0, ordered_at: str | None = None, expected_at: str | None = None,
                  note: str = "", status: str = "draft", admin: str = "") -> dict[str, Any]:
        if status not in ("draft", "ordered"):
            raise PurchasingError("statut initial : draft ou ordered")
        if not 1 <= quantity <= 1_000_000:
            raise PurchasingError("quantité invalide")
        sup = self.supplier(supplier_id)
        if not sup or not sup["active"]:
            raise PurchasingError("fournisseur introuvable ou désactivé")
        if status == "ordered" and not ordered_at:
            ordered_at = today()
        number = f"PO-{self.store.next_counter('po'):04d}"
        r = self.store._exec(
            "INSERT INTO purchase_orders (number, supplier_id, ordered_at, expected_at, status, quantity, unit_cost_cents, "
            "shipping_cost_cents, other_costs_cents, note, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (number, supplier_id, check_date(ordered_at), check_date(expected_at), status, quantity, unit_cost_cents,
             shipping_cost_cents, other_costs_cents, note.strip(), now_local(), admin), fetch="one",
        )
        return self.get_po(int(r[0]))  # type: ignore[return-value]

    def update_po(self, po_id: int, **fields: Any) -> dict[str, Any]:
        po = self.get_po(po_id)
        if not po:
            raise PurchasingError("commande introuvable")
        if po["status"] == "draft":
            allowed = {"supplier_id", "quantity", "unit_cost_cents", "shipping_cost_cents", "other_costs_cents",
                       "ordered_at", "expected_at", "note"}
        elif po["status"] in ("ordered", "partially_received"):
            allowed = {"expected_at", "note"}  # amounts are fixed once ordered
        else:
            allowed = {"note"}
        changes = {k: v for k, v in fields.items() if v is not None}
        refused = set(changes) - allowed
        if refused:
            raise PurchasingError(f"non modifiable dans ce statut : {', '.join(sorted(refused))}")
        if "quantity" in changes and not 1 <= int(changes["quantity"]) <= 1_000_000:
            raise PurchasingError("quantité invalide")
        if "supplier_id" in changes:
            sup = self.supplier(int(changes["supplier_id"]))
            if not sup or not sup["active"]:
                raise PurchasingError("fournisseur introuvable ou désactivé")
        for k in ("ordered_at", "expected_at"):
            if k in changes:
                changes[k] = check_date(changes[k])
        if isinstance(changes.get("note"), str):
            changes["note"] = changes["note"].strip()
        if changes:
            sets = ", ".join(f"{k} = ?" for k in changes)
            self.store._exec(f"UPDATE purchase_orders SET {sets} WHERE id = ?", (*changes.values(), po_id))
        return self.get_po(po_id)  # type: ignore[return-value]

    def set_status(self, po_id: int, status: str) -> dict[str, Any]:
        po = self.get_po(po_id)
        if not po:
            raise PurchasingError("commande introuvable")
        if status == "ordered":
            if po["status"] != "draft":
                raise PurchasingError("seul un brouillon peut être passé en commande")
            self.store._exec("UPDATE purchase_orders SET status = 'ordered', ordered_at = COALESCE(NULLIF(ordered_at, ''), ?) "
                             "WHERE id = ?", (today(), po_id))
        elif status == "cancelled":
            if po["received_qty"] > 0:
                raise PurchasingError("déjà réceptionnée en partie : annulation impossible (corrigez le stock)")
            if po["status"] == "cancelled":
                return po
            self.store._exec("UPDATE purchase_orders SET status = 'cancelled' WHERE id = ?", (po_id,))
        else:
            raise PurchasingError("statut invalide")
        return self.get_po(po_id)  # type: ignore[return-value]

    # ------------------------------------------------------------------ receipts
    def receive(self, po_id: int, quantity: int, admin: str, note: str = "") -> dict[str, Any]:
        """Receipt + stock entry at the landed cost, atomically (no double receipt beyond the ordered quantity)."""
        if quantity < 1:
            raise PurchasingError("quantité invalide")
        if not self.stock.tracking():
            raise PurchasingError("Démarrez d'abord le suivi du stock (stock d'ouverture).")
        with self.store.tx(LOCK) as tx:
            row = tx.exec("SELECT status, quantity, unit_cost_cents, shipping_cost_cents, other_costs_cents, number "
                          "FROM purchase_orders WHERE id = ?", (po_id,), fetch="one")
            if not row:
                raise PurchasingError("commande introuvable")
            status, ordered, unit, ship, other, number = row
            if status not in OPEN_FOR_RECEIPT:
                raise PurchasingError("cette commande ne peut plus être réceptionnée")
            got = tx.exec("SELECT COALESCE(SUM(quantity), 0) FROM purchase_receipts WHERE po_id = ?", (po_id,),
                          fetch="one")[0]
            remaining = int(ordered) - int(got)
            if quantity > remaining:
                raise PurchasingError(f"il reste {remaining} unité(s) à réceptionner")
            landed = landed_unit_cost({"unit_cost_cents": unit, "shipping_cost_cents": ship,
                                       "other_costs_cents": other, "quantity": ordered})
            move = self.stock.receive_in(tx, quantity, landed, reason="purchase", admin=admin, ref_type="po",
                                         ref_id=number, note=(note.strip() or f"Réception {number}"))
            tx.exec("INSERT INTO purchase_receipts (po_id, at, quantity, landed_unit_cost_cents, admin_name, movement_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)", (po_id, now_local(), quantity, landed, admin, move["id"]))
            new_status = "received" if quantity == remaining else "partially_received"
            tx.exec("UPDATE purchase_orders SET status = ?, ordered_at = COALESCE(NULLIF(ordered_at, ''), ?) WHERE id = ?",
                    (new_status, today(), po_id))
        return {"po": self.get_po(po_id), "landed_unit_cost_cents": landed, "on_hand": move["on_hand"]}

    def receipts(self, po_id: int) -> list[dict[str, Any]]:
        rows = self.store._exec("SELECT id, at, quantity, landed_unit_cost_cents, admin_name, movement_id "
                                "FROM purchase_receipts WHERE po_id = ? ORDER BY id", (po_id,), fetch="all")
        return [dict(zip(("id", "at", "quantity", "landed_unit_cost_cents", "admin_name", "movement_id"), r)) for r in rows]

    # ------------------------------------------------------------------ payments
    def add_payment(self, po_id: int, amount_cents: int, method: str, admin: str, note: str = "",
                    at: str | None = None) -> dict[str, Any]:
        if method not in PAYMENT_METHODS:
            raise PurchasingError("mode de paiement invalide")
        if amount_cents <= 0:
            raise PurchasingError("montant invalide")
        po = self.get_po(po_id)
        if not po:
            raise PurchasingError("commande introuvable")
        if po["status"] not in COMMITTED:
            raise PurchasingError("paiement possible seulement sur une commande passée")
        due = po["total_cents"] - po["paid_cents"]
        if amount_cents > due:
            raise PurchasingError(f"montant supérieur au reste à payer ({due / 100:.2f} MAD)")
        when = check_date(at) or today()
        self.store._exec("INSERT INTO supplier_payments (po_id, at, amount_cents, method, note, admin_name) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (po_id, when, amount_cents, method, note.strip(), admin))
        return self.get_po(po_id)  # type: ignore[return-value]

    def payments(self, po_id: int) -> list[dict[str, Any]]:
        rows = self.store._exec("SELECT id, at, amount_cents, method, note, admin_name FROM supplier_payments "
                                "WHERE po_id = ? ORDER BY at, id", (po_id,), fetch="all")
        return [dict(zip(("id", "at", "amount_cents", "method", "note", "admin_name"), r)) for r in rows]

    # ------------------------------------------------------------------ totals
    def summary(self) -> dict[str, Any]:
        """Supplier debt and counts in one query."""
        row = self.store._exec(
            "SELECT "
            "COALESCE(SUM(CASE WHEN status IN ('ordered', 'partially_received', 'received') THEN "
            "  quantity * unit_cost_cents + shipping_cost_cents + other_costs_cents "
            "  - COALESCE((SELECT SUM(y.amount_cents) FROM supplier_payments y WHERE y.po_id = purchase_orders.id), 0) "
            "  ELSE 0 END), 0), "
            "COALESCE(SUM(CASE WHEN status IN ('ordered', 'partially_received') THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(CASE WHEN status IN ('ordered', 'partially_received') AND expected_at IS NOT NULL "
            "  AND expected_at <> '' AND expected_at < ? THEN 1 ELSE 0 END), 0) "
            "FROM purchase_orders", (today(),), fetch="one",
        )
        return {"debts_cents": max(int(row[0] or 0), 0), "open": int(row[1] or 0), "late": int(row[2] or 0)}
