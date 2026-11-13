"""Finance (management accounting, not legal accounting: no VAT, no invoice numbering). Money = integer centimes.

P&L for a period [from, to] (dates 'YYYY-MM-DD', Casablanca time, both inclusive):
    revenue        = Σ totals of orders DELIVERED in the period (incl. the delivery charge paid by the client)
    COGS           = Σ units × unit cost of those orders (stock ledger; orders delivered before stock tracking
                     started have no cost — reported as `orders_without_cost`)
    carrier fees   = fees of orders delivered + orders returned in the period
    gross margin   = revenue − COGS − carrier fees
    expenses       = Σ expenses dated in the period (carrier fees and supplier payments are NOT expenses:
                     they reach the P&L through the orders and through COGS)
    write-offs     = units lost on returns (not recoverable) in the period, at their cost
    net profit     = gross margin − expenses − write-offs
    return cost    = carrier fees of the returns + write-offs
Marketing: CPA = ad spend (category "Publicité") ÷ confirmed orders created in the period; ROAS = revenue ÷ ad spend.
Cash: in = carrier remittances; out = expenses + supplier payments; running balance per day.
Recurring monthly expenses: the expense marked recurring is the template; a copy dated the 1st is created for every
later month (once per month, by the first finance request of that month).
"""

from __future__ import annotations

import csv
import io
import math
import re
from datetime import date, datetime, timedelta
from typing import Any

from .sheets import TZ, now_local

DEFAULT_CATEGORIES = ("Publicité", "Emballage", "Salaires", "Outils et abonnements", "Livraison (autre)", "Autres")
AD_CATEGORY = "Publicité"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXPENSE_COLS = "id, date, category, amount_cents, supplier_id, campaign, note, recurring_monthly, recurring_parent_id, created_at, created_by"


class FinanceError(ValueError):
    pass


def check_date(value: str) -> str:
    if not value or not DATE_RE.match(value):
        raise FinanceError("date invalide (AAAA-MM-JJ)")
    datetime.strptime(value, "%Y-%m-%d")
    return value


def today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def _months_between(start: str, end: str) -> list[str]:
    """'YYYY-MM' of every month strictly after start's month, up to end's month (inclusive)."""
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    while True:
        m += 1
        if m == 13:
            y, m = y + 1, 1
        if (y, m) > (ey, em):
            return out
        out.append(f"{y:04d}-{m:02d}")


def csv_cell(v: Any) -> str:
    """Excel-safe: a cell starting with = + - @ would run as a formula."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


class Finance:
    SCHEMA_VERSION = 1

    def __init__(self, store: Any):
        self.store = store
        if store.needs_schema("finance", self.SCHEMA_VERSION):
            pk = store.serial_pk
            for ddl in (
                f"CREATE TABLE IF NOT EXISTS expense_categories (id {pk}, name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1)",
                f"""CREATE TABLE IF NOT EXISTS expenses (id {pk}, date TEXT NOT NULL, category TEXT NOT NULL,
                    amount_cents BIGINT NOT NULL, supplier_id INTEGER, campaign TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '', recurring_monthly INTEGER NOT NULL DEFAULT 0,
                    recurring_parent_id INTEGER, created_at TEXT NOT NULL, created_by TEXT NOT NULL DEFAULT '')""",
                "CREATE INDEX IF NOT EXISTS expenses_date ON expenses (date)",
                "CREATE UNIQUE INDEX IF NOT EXISTS expenses_recurring_once ON expenses (recurring_parent_id, date)",
            ):
                store._exec(ddl)
            for name in DEFAULT_CATEGORIES:
                store._exec("INSERT INTO expense_categories (name, active) VALUES (?, 1) ON CONFLICT (name) DO NOTHING", (name,))
            if store.backend == "postgres":
                for t in ("expense_categories", "expenses"):
                    store._exec(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
            store.schema_done("finance", self.SCHEMA_VERSION)

    # ------------------------------------------------------------------ categories
    def categories(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        where = "" if include_inactive else "WHERE active = 1"
        rows = self.store._exec(f"SELECT id, name, active FROM expense_categories {where} ORDER BY id", fetch="all")
        return [{"id": r[0], "name": r[1], "active": bool(r[2])} for r in rows]

    def add_category(self, name: str) -> dict[str, Any]:
        name = " ".join(name.split())
        if not name:
            raise FinanceError("nom requis")
        self.store._exec("INSERT INTO expense_categories (name, active) VALUES (?, 1) ON CONFLICT (name) DO UPDATE SET active = 1",
                         (name,))
        return next(c for c in self.categories(True) if c["name"] == name)

    def update_category(self, cid: int, name: str | None = None, active: bool | None = None) -> dict[str, Any]:
        cat = next((c for c in self.categories(True) if c["id"] == cid), None)
        if not cat:
            raise FinanceError("catégorie introuvable")
        if name is not None:
            new = " ".join(name.split())
            if not new:
                raise FinanceError("nom requis")
            if new != cat["name"]:
                if any(c["name"] == new for c in self.categories(True)):
                    raise FinanceError("cette catégorie existe déjà")
                if cat["name"] == AD_CATEGORY:
                    raise FinanceError("« Publicité » sert au calcul du coût d'acquisition : elle ne peut pas être renommée")
                self.store._exec("UPDATE expense_categories SET name = ? WHERE id = ?", (new, cid))
                self.store._exec("UPDATE expenses SET category = ? WHERE category = ?", (new, cat["name"]))
        if active is not None:
            self.store._exec("UPDATE expense_categories SET active = ? WHERE id = ?", (1 if active else 0, cid))
        return next(c for c in self.categories(True) if c["id"] == cid)

    # ------------------------------------------------------------------ expenses
    @staticmethod
    def _expense(r: Any) -> dict[str, Any]:
        d = dict(zip([c.strip() for c in EXPENSE_COLS.split(",")], r))
        d["recurring_monthly"] = bool(d["recurring_monthly"])
        return d

    def _check_category(self, category: str) -> str:
        if not any(c["name"] == category for c in self.categories()):
            raise FinanceError("catégorie inconnue ou désactivée")
        return category

    def add_expense(self, *, date_: str, category: str, amount_cents: int, admin: str, supplier_id: int | None = None,
                    campaign: str = "", note: str = "", recurring_monthly: bool = False) -> dict[str, Any]:
        if amount_cents <= 0:
            raise FinanceError("montant invalide")
        r = self.store._exec(
            "INSERT INTO expenses (date, category, amount_cents, supplier_id, campaign, note, recurring_monthly, created_at, "
            "created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (check_date(date_), self._check_category(category), amount_cents, supplier_id, campaign.strip(), note.strip(),
             1 if recurring_monthly else 0, now_local(), admin), fetch="one",
        )
        return self.get_expense(int(r[0]))  # type: ignore[return-value]

    def get_expense(self, eid: int) -> dict[str, Any] | None:
        r = self.store._exec(f"SELECT {EXPENSE_COLS} FROM expenses WHERE id = ?", (eid,), fetch="one")
        return self._expense(r) if r else None

    def update_expense(self, eid: int, **fields: Any) -> dict[str, Any]:
        if not self.get_expense(eid):
            raise FinanceError("dépense introuvable")
        allowed = {"date", "category", "amount_cents", "supplier_id", "campaign", "note", "recurring_monthly"}
        changes = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "date" in changes:
            check_date(changes["date"])
        if "category" in changes:
            self._check_category(changes["category"])
        if "amount_cents" in changes and changes["amount_cents"] <= 0:
            raise FinanceError("montant invalide")
        if "recurring_monthly" in changes:
            changes["recurring_monthly"] = 1 if changes["recurring_monthly"] else 0
        for k in ("campaign", "note"):
            if k in changes:
                changes[k] = changes[k].strip()
        if changes:
            sets = ", ".join(f"{k} = ?" for k in changes)
            self.store._exec(f"UPDATE expenses SET {sets} WHERE id = ?", (*changes.values(), eid))
        return self.get_expense(eid)  # type: ignore[return-value]

    def delete_expense(self, eid: int) -> dict[str, Any]:
        e = self.get_expense(eid)
        if not e:
            raise FinanceError("dépense introuvable")
        self.store._exec("DELETE FROM expenses WHERE id = ?", (eid,))
        return e

    def list_expenses(self, frm: str, to: str, category: str | None = None, limit: int = 50,
                      offset: int = 0) -> dict[str, Any]:
        where, params = ["date >= ?", "date <= ?"], [check_date(frm), check_date(to)]
        if category:
            where.append("category = ?")
            params.append(category)
        w = " AND ".join(where)
        rows = self.store._exec(f"SELECT {EXPENSE_COLS} FROM expenses WHERE {w} ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
                                (*params, limit + 1, offset), fetch="all")
        total = self.store._exec(f"SELECT COALESCE(SUM(amount_cents), 0) FROM expenses WHERE {w}", tuple(params), fetch="one")
        return {"items": [self._expense(r) for r in rows[:limit]], "has_more": len(rows) > limit,
                "total_cents": int(total[0] or 0)}

    def ensure_recurring(self, on: str | None = None, force: bool = False) -> int:
        """Creates this month's copies of the recurring expenses (and of any missed month). Cheap when done:
        one settings read per request."""
        on = on or today()
        month = on[:7]
        key = f"finance:recurring:{month}"
        if not force and self.store.get_setting(key) == "done":
            return 0
        created = 0
        templates = self.store._exec(
            "SELECT id, date, category, amount_cents, supplier_id, campaign, note FROM expenses "
            "WHERE recurring_monthly = 1 AND recurring_parent_id IS NULL AND date <= ?", (on,), fetch="all")
        for tid, tdate, category, amount, supplier_id, campaign, note in templates:
            # Months after the last one generated for this template (a month the owner deleted never comes back).
            last_key = f"finance:recurring:last:{tid}"
            last = self.store.get_setting(last_key) or tdate[:7]
            for m in _months_between(f"{last}-01", on):
                r = self.store._exec(
                    "INSERT INTO expenses (date, category, amount_cents, supplier_id, campaign, note, recurring_monthly, "
                    "recurring_parent_id, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, 'auto') "
                    "ON CONFLICT (recurring_parent_id, date) DO NOTHING RETURNING id",
                    (f"{m}-01", category, amount, supplier_id, campaign, note, tid, now_local()), fetch="one")
                created += 1 if r else 0
            if month > last:
                self.store.set_setting(last_key, month)
        self.store.set_setting(key, "done")
        return created

    # ------------------------------------------------------------------ report
    def report(self, frm: str, to: str) -> dict[str, Any]:
        frm, to = check_date(frm), check_date(to)
        if frm > to:
            raise FinanceError("la date de début est après la date de fin")
        t0, t1 = f"{frm} 00:00:00", f"{to} 23:59:59"
        ex = self.store._exec
        # Delivered orders of the period, with their cost from the stock ledger — one query.
        d = ex(
            "SELECT COUNT(*), COALESCE(SUM(CAST(o.total AS INTEGER)), 0) * 100, "
            "COALESCE(SUM(u.units * u.unit_cost_cents), 0), "
            "COALESCE(SUM(CAST(COALESCE(NULLIF(o.carrier_fee_cents, ''), '0') AS INTEGER)), 0), "
            "COALESCE(SUM(CASE WHEN u.order_number IS NULL THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(CAST(o.quantity AS INTEGER)), 0) "
            "FROM orders o LEFT JOIN stock_order_units u ON u.order_number = o.order_number "
            "WHERE o.status = 'delivered' AND o.delivered_at >= ? AND o.delivered_at <= ?", (t0, t1), fetch="one")
        delivered, revenue, cogs, fees_delivered, without_cost, units = (int(x or 0) for x in d)
        r = ex(
            "SELECT COUNT(*), COALESCE(SUM(CAST(COALESCE(NULLIF(carrier_fee_cents, ''), '0') AS INTEGER)), 0) FROM orders "
            "WHERE status = 'returned' AND COALESCE(NULLIF(returned_at, ''), updated_at) >= ? "
            "AND COALESCE(NULLIF(returned_at, ''), updated_at) <= ?", (t0, t1), fetch="one")
        returned, fees_returned = int(r[0] or 0), int(r[1] or 0)
        w = ex("SELECT COALESCE(SUM(written_off * unit_cost_cents), 0), COALESCE(SUM(written_off), 0) FROM stock_movements "
               "WHERE written_off > 0 AND at >= ? AND at <= ?", (t0, t1), fetch="one")
        write_offs, units_lost = int(w[0] or 0), int(w[1] or 0)
        cats = ex("SELECT category, COALESCE(SUM(amount_cents), 0) FROM expenses WHERE date >= ? AND date <= ? "
                  "GROUP BY category ORDER BY 2 DESC", (frm, to), fetch="all")
        by_category = [{"category": c, "amount_cents": int(a)} for c, a in cats]
        expenses = sum(c["amount_cents"] for c in by_category)
        ad_spend = sum(c["amount_cents"] for c in by_category if c["category"] == AD_CATEGORY)
        camp = ex("SELECT campaign, COALESCE(SUM(amount_cents), 0) FROM expenses WHERE date >= ? AND date <= ? AND category = ? "
                  "AND campaign <> '' GROUP BY campaign ORDER BY 2 DESC", (frm, to, AD_CATEGORY), fetch="all")
        conf = ex("SELECT COUNT(*) FROM orders WHERE created_at >= ? AND created_at <= ? "
                  "AND status IN ('confirmed', 'shipped', 'delivered', 'returned')", (t0, t1), fetch="one")
        confirmed = int(conf[0] or 0)

        fees = fees_delivered + fees_returned
        gross = revenue - cogs - fees
        net = gross - expenses - write_offs
        cpa = round(ad_spend / confirmed) if confirmed and ad_spend else None
        roas = round(revenue / ad_spend, 2) if ad_spend else None

        # Unit economics (per delivered order) and break-even on the fixed monthly expenses.
        fixed = ex("SELECT COALESCE(SUM(amount_cents), 0) FROM expenses WHERE recurring_monthly = 1 AND recurring_parent_id IS NULL",
                   fetch="one")
        fixed_monthly = int(fixed[0] or 0)
        avg_revenue = round(revenue / delivered) if delivered else None
        avg_cogs = round(cogs / (delivered - without_cost)) if delivered - without_cost > 0 else None
        avg_fee = round(fees / (delivered + returned)) if delivered + returned else None
        contribution = None
        if avg_revenue is not None and avg_cogs is not None and avg_fee is not None:
            contribution = avg_revenue - avg_cogs - avg_fee - (cpa or 0)
        break_even = math.ceil(fixed_monthly / contribution) if contribution and contribution > 0 and fixed_monthly else None

        return {
            "from": frm, "to": to,
            "ledger_start": self.store.get_setting("stock_ledger_start") or None,
            "pnl": {"revenue_cents": revenue, "cogs_cents": cogs, "carrier_fees_cents": fees,
                    "gross_margin_cents": gross, "expenses_cents": expenses, "write_offs_cents": write_offs,
                    "net_profit_cents": net, "return_cost_cents": fees_returned + write_offs},
            "counts": {"delivered": delivered, "returned": returned, "units_delivered": units, "units_lost": units_lost,
                       "orders_without_cost": without_cost, "confirmed_created": confirmed},
            "expenses_by_category": by_category,
            "marketing": {"ad_spend_cents": ad_spend, "cpa_cents": cpa, "roas": roas,
                          "campaigns": [{"campaign": c, "spend_cents": int(a)} for c, a in camp]},
            "unit_economics": {"avg_revenue_cents": avg_revenue, "avg_cogs_cents": avg_cogs, "avg_carrier_fee_cents": avg_fee,
                               "cpa_cents": cpa, "profit_per_order_cents": contribution,
                               "fixed_monthly_cents": fixed_monthly, "break_even_orders_per_month": break_even},
            "cash": self.cash(frm, to),
        }

    def cash(self, frm: str, to: str) -> dict[str, Any]:
        ex = self.store._exec
        t0, t1 = f"{frm} 00:00:00", f"{to} 23:59:59"
        days: dict[str, dict[str, int]] = {}

        def add(rows: list, key: str) -> int:
            total = 0
            for day, amount in rows:
                days.setdefault(day[:10], {"in": 0, "out": 0})[key] += int(amount or 0)
                total += int(amount or 0)
            return total

        cash_in = add(ex("SELECT SUBSTR(at, 1, 10), SUM(amount_received_cents) FROM remittances WHERE at >= ? AND at <= ? "
                         "GROUP BY SUBSTR(at, 1, 10)", (t0, t1), fetch="all"), "in")
        out_expenses = add(ex("SELECT date, SUM(amount_cents) FROM expenses WHERE date >= ? AND date <= ? GROUP BY date",
                              (frm, to), fetch="all"), "out")
        out_suppliers = add(ex("SELECT at, SUM(amount_cents) FROM supplier_payments WHERE at >= ? AND at <= ? GROUP BY at",
                               (frm, to), fetch="all"), "out")
        running, series = 0, []
        for day in sorted(days):
            running += days[day]["in"] - days[day]["out"]
            series.append({"date": day, "in_cents": days[day]["in"], "out_cents": days[day]["out"], "balance_cents": running})
        held = ex("SELECT COALESCE(SUM(CAST(total AS INTEGER) * 100 - CAST(COALESCE(NULLIF(carrier_fee_cents, ''), '0') AS INTEGER)), 0) "
                  "FROM orders WHERE cod_status = 'with_carrier'", fetch="one")
        debts = ex("SELECT COALESCE(SUM(quantity * unit_cost_cents + shipping_cost_cents + other_costs_cents "
                   "- COALESCE((SELECT SUM(y.amount_cents) FROM supplier_payments y WHERE y.po_id = purchase_orders.id), 0)), 0) "
                   "FROM purchase_orders WHERE status IN ('ordered', 'partially_received', 'received')", fetch="one")
        return {"in_cents": cash_in, "out_expenses_cents": out_expenses, "out_suppliers_cents": out_suppliers,
                "net_cents": cash_in - out_expenses - out_suppliers, "days": series,
                "to_collect_cents": int(held[0] or 0), "to_pay_cents": max(int(debts[0] or 0), 0)}

    def export_csv(self, frm: str, to: str) -> str:
        rep = self.report(frm, to)
        p = rep["pnl"]
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        mad = lambda c: "" if c is None else f"{c / 100:.2f}".replace(".", ",")  # noqa: E731
        w.writerow([csv_cell("NAYO — compte de résultat"), csv_cell(f"du {frm} au {to}")])
        for label, key in (("Chiffre d'affaires (livrées)", "revenue_cents"), ("Coût des produits vendus", "cogs_cents"),
                           ("Frais des livreurs", "carrier_fees_cents"), ("Marge brute", "gross_margin_cents"),
                           ("Dépenses", "expenses_cents"), ("Produits perdus (retours)", "write_offs_cents"),
                           ("Bénéfice net", "net_profit_cents"), ("Coût des retours", "return_cost_cents")):
            w.writerow([csv_cell(label), mad(p[key])])
        w.writerow([])
        w.writerow(["Date", "Catégorie", "Montant (MAD)", "Campagne", "Note"])
        page = self.list_expenses(frm, to, limit=10_000)
        for e in page["items"]:
            w.writerow([e["date"], csv_cell(e["category"]), mad(e["amount_cents"]), csv_cell(e["campaign"]), csv_cell(e["note"])])
        return "﻿" + buf.getvalue()  # BOM: Excel opens the accents correctly


def period(preset: str, on: str | None = None) -> tuple[str, str]:
    d = date.fromisoformat(on or today())
    if preset == "today":
        return d.isoformat(), d.isoformat()
    if preset == "week":
        start = d - timedelta(days=d.weekday())
        return start.isoformat(), d.isoformat()
    if preset == "month":
        return d.replace(day=1).isoformat(), d.isoformat()
    raise FinanceError("période inconnue")
