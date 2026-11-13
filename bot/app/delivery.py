"""Delivery companies & cash on delivery (COD).

The carrier delivers, collects the cash from the client, keeps its fee and pays NAYO back later
("remittance"). Per order (database-only columns, the Google Sheet keeps its 12 columns):
    carrier_id, carrier_fee_cents, cod_status ('' | 'none' | 'with_carrier' | 'remitted'), cod_amount_cents,
    remittance_id
- delivered  → cod_amount = order total, cod_status 'with_carrier', fee = carrier's fee_delivered (editable)
- returned   → cod 0, cod_status 'none', fee = carrier's fee_returned (a return still costs the carrier fee)
- back to confirmed/shipped → COD fields cleared
- a remitted order is locked: its status/quantity can't change any more (the cash is already counted)
Reconciliation: pick delivered orders still 'with_carrier' for one carrier → expected = Σ totals − Σ fees;
the amount actually received is saved with the difference; the orders become 'remitted'. One transaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .sheets import TZ, now_local

COD_COLUMNS = ["carrier_id", "carrier_fee_cents", "cod_status", "cod_amount_cents", "remittance_id"]
LOCK = "nayo-cod"
CARRIER_COLS = "id, name, phone, fee_delivered_cents, fee_returned_cents, remit_delay_days, active"


class DeliveryError(ValueError):
    pass


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def cod_fields(order: dict[str, Any], new_status: str, carrier: dict[str, Any] | None) -> dict[str, Any]:
    """Fields to write with a status change (raises if the order's cash was already remitted)."""
    if order.get("cod_status") == "remitted" and new_status != "delivered":
        raise DeliveryError("Cette commande est déjà encaissée auprès du livreur : son statut ne peut plus changer.")
    if new_status == "delivered":
        if order.get("cod_status") in ("with_carrier", "remitted"):
            return {}
        total = _int(order.get("total"))
        return {"cod_status": "with_carrier", "cod_amount_cents": str(total * 100),
                "carrier_fee_cents": str(carrier["fee_delivered_cents"] if carrier else 0)}
    if new_status == "returned":
        return {"cod_status": "none", "cod_amount_cents": "0",
                "carrier_fee_cents": str(carrier["fee_returned_cents"] if carrier else 0)}
    if order.get("cod_status") or order.get("carrier_fee_cents"):
        return {"cod_status": "", "cod_amount_cents": "", "carrier_fee_cents": ""}
    return {}


class Delivery:
    SCHEMA_VERSION = 1

    def __init__(self, store: Any):
        self.store = store
        if store.needs_schema("delivery", self.SCHEMA_VERSION):
            pk = store.serial_pk
            for ddl in (
                f"""CREATE TABLE IF NOT EXISTS carriers (id {pk}, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
                    fee_delivered_cents BIGINT NOT NULL DEFAULT 0, fee_returned_cents BIGINT NOT NULL DEFAULT 0,
                    remit_delay_days INTEGER NOT NULL DEFAULT 7, active INTEGER NOT NULL DEFAULT 1)""",
                f"""CREATE TABLE IF NOT EXISTS remittances (id {pk}, carrier_id INTEGER NOT NULL, at TEXT NOT NULL,
                    amount_received_cents BIGINT NOT NULL, expected_cents BIGINT NOT NULL,
                    difference_cents BIGINT NOT NULL, orders_count INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '',
                    admin_name TEXT NOT NULL DEFAULT '')""",
                """CREATE TABLE IF NOT EXISTS remittance_orders (remittance_id INTEGER NOT NULL, order_number TEXT NOT NULL,
                    PRIMARY KEY (remittance_id, order_number))""",
                "CREATE INDEX IF NOT EXISTS remittances_carrier_at ON remittances (carrier_id, at)",
                "CREATE INDEX IF NOT EXISTS remittances_at ON remittances (at)",
            ):
                store._exec(ddl)
            if store.backend == "postgres":
                for t in ("carriers", "remittances", "remittance_orders"):
                    store._exec(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
            store.schema_done("delivery", self.SCHEMA_VERSION)

    # ------------------------------------------------------------------ carriers
    @staticmethod
    def _carrier(r: Any) -> dict[str, Any]:
        d = dict(zip([c.strip() for c in CARRIER_COLS.split(",")], r))
        d["active"] = bool(d["active"])
        return d

    def carriers(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        where = "" if include_inactive else "WHERE active = 1"
        rows = self.store._exec(f"SELECT {CARRIER_COLS} FROM carriers {where} ORDER BY active DESC, name", fetch="all")
        return [self._carrier(r) for r in rows]

    def carrier(self, cid: int | str | None) -> dict[str, Any] | None:
        cid = _int(cid)
        if not cid:
            return None
        r = self.store._exec(f"SELECT {CARRIER_COLS} FROM carriers WHERE id = ?", (cid,), fetch="one")
        return self._carrier(r) if r else None

    def create_carrier(self, *, name: str, phone: str = "", fee_delivered_cents: int = 0, fee_returned_cents: int = 0,
                       remit_delay_days: int = 7) -> dict[str, Any]:
        if not name.strip():
            raise DeliveryError("nom requis")
        r = self.store._exec(
            "INSERT INTO carriers (name, phone, fee_delivered_cents, fee_returned_cents, remit_delay_days, active) "
            "VALUES (?, ?, ?, ?, ?, 1) RETURNING id",
            (name.strip(), phone.strip(), fee_delivered_cents, fee_returned_cents, remit_delay_days), fetch="one",
        )
        return self.carrier(int(r[0]))  # type: ignore[return-value]

    def update_carrier(self, cid: int, **fields: Any) -> dict[str, Any]:
        allowed = {"name", "phone", "fee_delivered_cents", "fee_returned_cents", "remit_delay_days", "active"}
        fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not self.carrier(cid):
            raise DeliveryError("livreur introuvable")
        if "name" in fields and not str(fields["name"]).strip():
            raise DeliveryError("nom requis")
        if "active" in fields:
            fields["active"] = 1 if fields["active"] else 0
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            self.store._exec(f"UPDATE carriers SET {sets} WHERE id = ?",
                             (*[v.strip() if isinstance(v, str) else v for v in fields.values()], cid))
        return self.carrier(cid)  # type: ignore[return-value]

    # ------------------------------------------------------------------ COD held by carriers
    def held_by_carrier(self) -> list[dict[str, Any]]:
        """Cash still with each carrier (delivered, not remitted): one aggregated query."""
        rows = self.store._exec(
            "SELECT c.id, c.name, c.remit_delay_days, COUNT(o.order_number), "
            "COALESCE(SUM(CAST(o.total AS INTEGER) * 100 - CAST(COALESCE(NULLIF(o.carrier_fee_cents, ''), '0') AS INTEGER)), 0), "
            "MIN(NULLIF(o.delivered_at, '')) "
            "FROM carriers c JOIN orders o ON o.carrier_id = CAST(c.id AS TEXT) AND o.cod_status = 'with_carrier' "
            "GROUP BY c.id, c.name, c.remit_delay_days ORDER BY c.name",
            fetch="all",
        )
        now = datetime.now(TZ).replace(tzinfo=None)
        out = []
        for cid, name, delay, count, net, oldest in rows:
            age = (now - datetime.strptime(oldest[:19], "%Y-%m-%d %H:%M:%S")).days if oldest else None
            out.append({"carrier_id": cid, "name": name, "orders": int(count), "expected_cents": int(net),
                        "oldest_delivered_at": oldest, "oldest_age_days": age,
                        "late": age is not None and age > int(delay)})
        return out

    def pending(self, carrier_id: int) -> list[dict[str, Any]]:
        """Delivered orders whose cash is still with this carrier, oldest first."""
        c = self.carrier(carrier_id)
        if not c:
            raise DeliveryError("livreur introuvable")
        rows = self.store._exec(
            "SELECT order_number, name, city, delivered_at, total, carrier_fee_cents FROM orders "
            "WHERE carrier_id = ? AND cod_status = 'with_carrier' ORDER BY delivered_at, order_number",
            (str(carrier_id),), fetch="all",
        )
        limit_at = (datetime.now(TZ) - timedelta(days=int(c["remit_delay_days"]))).strftime("%Y-%m-%d %H:%M:%S")
        return [{"order_number": r[0], "name": r[1], "city": r[2], "delivered_at": r[3],
                 "total_cents": _int(r[4]) * 100, "fee_cents": _int(r[5]),
                 "net_cents": _int(r[4]) * 100 - _int(r[5]), "late": bool(r[3]) and r[3] < limit_at} for r in rows]

    def remit(self, carrier_id: int, order_numbers: list[str], amount_received_cents: int, admin: str,
              note: str = "") -> dict[str, Any]:
        numbers = sorted({n.strip().upper() for n in order_numbers if n.strip()})
        if not numbers:
            raise DeliveryError("sélectionnez au moins une commande")
        if amount_received_cents < 0:
            raise DeliveryError("montant invalide")
        if not self.carrier(carrier_id):
            raise DeliveryError("livreur introuvable")
        marks = ", ".join("?" for _ in numbers)
        with self.store.tx(LOCK) as tx:
            rows = tx.exec(
                f"SELECT order_number, total, carrier_fee_cents, cod_status, carrier_id FROM orders "
                f"WHERE UPPER(order_number) IN ({marks})", tuple(numbers), fetch="all",
            )
            found = {r[0].upper(): r for r in rows}
            missing = [n for n in numbers if n not in found]
            if missing:
                raise DeliveryError(f"commande(s) introuvable(s) : {', '.join(missing)}")
            bad = [n for n, r in found.items() if r[3] != "with_carrier" or str(r[4]) != str(carrier_id)]
            if bad:
                raise DeliveryError(f"déjà encaissée(s) ou pas chez ce livreur : {', '.join(sorted(bad))}")
            expected = sum(_int(r[1]) * 100 - _int(r[2]) for r in rows)
            rid = int(tx.exec(
                "INSERT INTO remittances (carrier_id, at, amount_received_cents, expected_cents, difference_cents, "
                "orders_count, note, admin_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (carrier_id, now_local(), amount_received_cents, expected, amount_received_cents - expected,
                 len(rows), note.strip(), admin), fetch="one")[0])
            for r in rows:
                tx.exec("INSERT INTO remittance_orders (remittance_id, order_number) VALUES (?, ?)", (rid, r[0]))
            real = [r[0] for r in rows]
            tx.exec(f"UPDATE orders SET cod_status = 'remitted', remittance_id = ? WHERE order_number IN "
                    f"({', '.join('?' for _ in real)})", (str(rid), *real))
        return {"id": rid, "expected_cents": expected, "amount_received_cents": amount_received_cents,
                "difference_cents": amount_received_cents - expected, "orders": len(rows)}

    def remittances(self, carrier_id: int | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        where, params = ("WHERE r.carrier_id = ?", [carrier_id]) if carrier_id else ("", [])
        rows = self.store._exec(
            "SELECT r.id, r.carrier_id, c.name, r.at, r.amount_received_cents, r.expected_cents, r.difference_cents, "
            f"r.orders_count, r.note, r.admin_name FROM remittances r LEFT JOIN carriers c ON c.id = r.carrier_id {where} "
            "ORDER BY r.id DESC LIMIT ? OFFSET ?", (*params, limit + 1, offset), fetch="all",
        )
        keys = ("id", "carrier_id", "carrier_name", "at", "amount_received_cents", "expected_cents", "difference_cents",
                "orders", "note", "admin_name")
        items = [dict(zip(keys, r)) for r in rows[:limit]]
        return {"items": items, "has_more": len(rows) > limit}

    # ------------------------------------------------------------------ board, slips, returns
    def board(self, status: str, carrier_id: int | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        where, params = ["status = ?"], [status]
        if carrier_id is not None:
            where.append("carrier_id = ?" if carrier_id else "(carrier_id = '' OR carrier_id IS NULL)")
            if carrier_id:
                params.append(str(carrier_id))
        order = "created_at" if status == "confirmed" else "updated_at DESC"
        rows = self.store._exec(
            "SELECT order_number, created_at, name, phone, city, address, quantity, total, status, carrier_id, carrier, "
            "tracking, shipped_at, delivered_at, return_reason, cod_status, carrier_fee_cents FROM orders "
            f"WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?",
            (*params, limit + 1, offset), fetch="all",
        )
        keys = ("order_number", "created_at", "name", "phone", "city", "address", "quantity", "total", "status",
                "carrier_id", "carrier", "tracking", "shipped_at", "delivered_at", "return_reason", "cod_status",
                "carrier_fee_cents")
        items = [dict(zip(keys, r)) for r in rows[:limit]]
        counts = dict(self.store._exec(
            "SELECT status, COUNT(*) FROM orders WHERE status IN ('confirmed', 'shipped', 'delivered', 'returned') "
            "GROUP BY status", fetch="all"))
        return {"items": items, "has_more": len(rows) > limit, "counts": {k: int(v) for k, v in counts.items()}}

    def slips(self, numbers: list[str]) -> list[dict[str, Any]]:
        numbers = [n.strip().upper() for n in numbers if n.strip()][:200]
        if not numbers:
            return []
        rows = self.store._exec(
            "SELECT order_number, name, phone, city, address, quantity, total, carrier, tracking FROM orders "
            f"WHERE UPPER(order_number) IN ({', '.join('?' for _ in numbers)}) ORDER BY order_number",
            tuple(numbers), fetch="all",
        )
        keys = ("order_number", "name", "phone", "city", "address", "quantity", "total", "carrier", "tracking")
        return [dict(zip(keys, r)) for r in rows]

    def returns(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Returned orders with reason and loss = carrier fee + units written off at their cost (one query)."""
        rows = self.store._exec(
            "SELECT o.order_number, o.name, o.city, o.quantity, o.total, o.return_reason, o.updated_at, o.carrier, "
            "CAST(COALESCE(NULLIF(o.carrier_fee_cents, ''), '0') AS INTEGER), "
            "COALESCE((SELECT SUM(m.written_off * m.unit_cost_cents) FROM stock_movements m "
            "          WHERE m.order_number = o.order_number AND m.written_off > 0), 0) "
            "FROM orders o WHERE o.status = 'returned' ORDER BY o.updated_at DESC LIMIT ? OFFSET ?",
            (limit + 1, offset), fetch="all",
        )
        items = [{"order_number": r[0], "name": r[1], "city": r[2], "quantity": _int(r[3]), "total": _int(r[4]),
                  "return_reason": r[5], "at": r[6], "carrier": r[7], "fee_cents": int(r[8] or 0),
                  "written_off_cents": int(r[9] or 0), "loss_cents": int(r[8] or 0) + int(r[9] or 0)}
                 for r in rows[:limit]]
        return {"items": items, "has_more": len(rows) > limit}
