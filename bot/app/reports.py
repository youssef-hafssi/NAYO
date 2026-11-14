"""Dashboard and reports. Same money definitions as finance.py (revenue = delivered orders by delivered_at, COGS from
the stock ledger, carrier fees of delivered + returned orders, expenses by date, write-offs of lost returns), so a
report's totals always equal the Finance page for the same period. Aggregated SQL only (no query per row)."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from .crm import fmt, now_dt
from .finance import Finance, FinanceError, check_date

CONFIRMED_LIKE = ("confirmed", "shipped", "delivered", "returned")  # the client said yes
PENDING = ("new", "awaiting_details")  # not decided yet
DASHBOARD_TTL_S = 30
MAX_DAYS = 366

TOTAL = "COALESCE(CAST(NULLIF(o.total, '') AS INTEGER), 0)"
QTY = "COALESCE(CAST(NULLIF(o.quantity, '') AS INTEGER), 0)"
FEE = "COALESCE(CAST(NULLIF(o.carrier_fee_cents, '') AS INTEGER), 0)"


class ReportError(Exception):
    pass


def _days(frm: str, to: str) -> list[str]:
    a, b = date.fromisoformat(frm), date.fromisoformat(to)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _range(frm: str, to: str) -> tuple[str, str]:
    try:
        frm, to = check_date(frm), check_date(to)
    except (FinanceError, ValueError):
        raise ReportError("date invalide (AAAA-MM-JJ)")
    if frm > to:
        raise ReportError("la date de début est après la date de fin")
    if (date.fromisoformat(to) - date.fromisoformat(frm)).days >= MAX_DAYS:
        raise ReportError("période trop longue (un an maximum)")
    return frm, to


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def city_name(c: str | None) -> str:
    """Cities are typed freely ("casablanca", "CASABLANCA "): grouped case-insensitively, shown capitalised."""
    c = " ".join((c or "").split())
    return c.title() if c else ""


def _parse(s: str) -> datetime | None:
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


class Reports:
    def __init__(self, store: Any, finance: Finance, crm: Any = None, stock: Any = None):
        self.store, self.finance, self.crm, self.stock = store, finance, crm, stock
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    # ================================================================== dashboard
    def dashboard(self, owner: bool, *, fresh: bool = False) -> dict[str, Any]:
        key = "owner" if owner else "agent"
        hit = self._cache.get(key)
        if hit and not fresh and time.time() - hit[0] < DASHBOARD_TTL_S:
            return hit[1]
        data = self._dashboard(owner)
        self._cache[key] = (time.time(), data)
        return data

    def _dashboard(self, owner: bool) -> dict[str, Any]:
        ex = self.store._exec
        now = now_dt()
        today = now.date()
        t_day = f"{today.isoformat()} 00:00:00"
        t_week = f"{(today - timedelta(days=today.weekday())).isoformat()} 00:00:00"
        t_month = f"{today.replace(day=1).isoformat()} 00:00:00"
        t_30 = f"{(today - timedelta(days=29)).isoformat()} 00:00:00"

        # 1. Order counts + this month's statuses + pipeline, in one pass over the orders table.
        r = ex(
            "SELECT SUM(CASE WHEN o.created_at >= ? THEN 1 ELSE 0 END), SUM(CASE WHEN o.created_at >= ? THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN o.created_at >= ? THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN o.created_at >= ? AND o.status IN {CONFIRMED_LIKE} THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN o.created_at >= ? AND o.status NOT IN {PENDING} THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN o.status = 'needs_human' THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN o.status IN ('confirmed', 'shipped') THEN {TOTAL} ELSE 0 END), "
            "SUM(CASE WHEN o.status IN ('confirmed', 'shipped') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN o.status = 'delivered' AND o.delivered_at >= ? THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN o.status = 'returned' AND COALESCE(NULLIF(o.returned_at, ''), o.updated_at) >= ? THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN o.status = 'delivered' AND o.delivered_at >= ? THEN {QTY} ELSE 0 END) "
            "FROM orders o", (t_day, t_week, t_month, t_month, t_month, t_30, t_30, t_month), fetch="one")
        (n_day, n_week, n_month, conf_month, decided_month, needs_human, pipeline, pipeline_n,
         deliv_30, ret_30, units_month) = (int(x or 0) for x in r)

        # 2. 30-day chart: orders created per day, delivered orders + revenue per day.
        created = dict(ex("SELECT SUBSTR(o.created_at, 1, 10), COUNT(*) FROM orders o WHERE o.created_at >= ? "
                          "GROUP BY SUBSTR(o.created_at, 1, 10)", (t_30,), fetch="all"))
        deliv = {d: (int(n), int(v)) for d, n, v in ex(
            f"SELECT SUBSTR(o.delivered_at, 1, 10), COUNT(*), SUM({TOTAL}) * 100 FROM orders o "
            "WHERE o.status = 'delivered' AND o.delivered_at >= ? GROUP BY SUBSTR(o.delivered_at, 1, 10)", (t_30,), fetch="all")}
        chart = []
        for d in _days((today - timedelta(days=29)).isoformat(), today.isoformat()):
            row = {"date": d, "orders": int(created.get(d, 0)), "delivered": deliv.get(d, (0, 0))[0]}
            if owner:
                row["revenue_cents"] = deliv.get(d, (0, 0))[1]
            chart.append(row)

        # 3. Top cities this month.
        cities = [{"city": city_name(c), "orders": int(n)} for c, n in ex(
            "SELECT LOWER(TRIM(o.city)), COUNT(*) FROM orders o WHERE o.created_at >= ? AND TRIM(o.city) <> '' "
            "GROUP BY LOWER(TRIM(o.city)) ORDER BY 2 DESC, 1 LIMIT 5", (t_month,), fetch="all")]

        out: dict[str, Any] = {
            "generated_at": fmt(now),
            "orders": {"today": n_day, "week": n_week, "month": n_month},
            "confirmation_rate": {"rate": _rate(conf_month, decided_month), "confirmed": conf_month, "decided": decided_month},
            "delivery_rate": {"rate": _rate(deliv_30, deliv_30 + ret_30), "delivered": deliv_30, "returned": ret_30},
            "units_month": units_month,
            "needs_human": needs_human,
            "in_progress": {"orders": pipeline_n},
            "chart": chart,
            "top_cities": cities,
        }
        if self.stock is not None:
            st = self.stock.summary()
            out["stock"] = {k: st[k] for k in ("tracking", "on_hand", "low", "out", "days_of_stock", "low_threshold")}
            if owner:
                out["stock"]["value_cents"] = st["stock_value_cents"]
        if self.crm is not None:
            tc = self.crm.task_counts()
            out["follow_ups"] = {"late": tc["late"], "today": tc["today"],
                                 "suggestions": len(self.crm.suggestions(owner))}
        if owner:
            month = self.finance.report(today.replace(day=1).isoformat(), today.isoformat())
            p, c = month["pnl"], month["cash"]
            out["money"] = {
                "revenue_month_cents": p["revenue_cents"], "net_profit_month_cents": p["net_profit_cents"],
                "avg_basket_cents": month["unit_economics"]["avg_revenue_cents"],
                "in_progress_cents": pipeline * 100,
                "to_collect_cents": c["to_collect_cents"], "to_pay_cents": c["to_pay_cents"],
            }
        return out

    # ================================================================== Ventes
    def sales(self, frm: str, to: str) -> dict[str, Any]:
        frm, to = _range(frm, to)
        t0, t1 = f"{frm} 00:00:00", f"{to} 23:59:59"
        ex = self.store._exec
        created = {d: (int(a), int(b), int(c), int(e)) for d, a, b, c, e in ex(
            f"SELECT SUBSTR(o.created_at, 1, 10), COUNT(*), SUM(CASE WHEN o.status IN {CONFIRMED_LIKE} THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN o.status = 'cancelled' THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN o.status NOT IN {PENDING} THEN 1 ELSE 0 END) "
            "FROM orders o WHERE o.created_at >= ? AND o.created_at <= ? "
            "GROUP BY SUBSTR(o.created_at, 1, 10)", (t0, t1), fetch="all")}
        deliv = {d: (int(a), int(b), int(c)) for d, a, b, c in ex(
            f"SELECT SUBSTR(o.delivered_at, 1, 10), COUNT(*), SUM({QTY}), SUM({TOTAL}) * 100 FROM orders o "
            "WHERE o.status = 'delivered' AND o.delivered_at >= ? AND o.delivered_at <= ? "
            "GROUP BY SUBSTR(o.delivered_at, 1, 10)", (t0, t1), fetch="all")}
        rows = []
        for d in _days(frm, to):
            c, dl = created.get(d, (0, 0, 0, 0)), deliv.get(d, (0, 0, 0))
            rows.append({"date": d, "orders": c[0], "confirmed": c[1], "cancelled": c[2], "decided": c[3],
                         "delivered": dl[0], "units": dl[1], "revenue_cents": dl[2]})
        tot = {k: sum(r[k] for r in rows) for k in ("orders", "confirmed", "cancelled", "decided", "delivered", "units",
                                                    "revenue_cents")}
        tot["avg_basket_cents"] = round(tot["revenue_cents"] / tot["delivered"]) if tot["delivered"] else None
        tot["confirmation_rate"] = _rate(tot["confirmed"], tot["decided"])  # same rule as the dashboard
        by_source = [{"source": s or "inconnue", "orders": int(n), "confirmed": int(c)} for s, n, c in ex(
            f"SELECT o.source, COUNT(*), SUM(CASE WHEN o.status IN {CONFIRMED_LIKE} THEN 1 ELSE 0 END) FROM orders o "
            "WHERE o.created_at >= ? AND o.created_at <= ? GROUP BY o.source ORDER BY 2 DESC", (t0, t1), fetch="all")]
        by_city = [{"city": city_name(c) or "—", "delivered": int(n), "revenue_cents": int(v)} for c, n, v in ex(
            f"SELECT LOWER(TRIM(o.city)), COUNT(*), SUM({TOTAL}) * 100 FROM orders o WHERE o.status = 'delivered' "
            "AND o.delivered_at >= ? AND o.delivered_at <= ? GROUP BY LOWER(TRIM(o.city)) ORDER BY 3 DESC LIMIT 20",
            (t0, t1), fetch="all")]
        return {"from": frm, "to": to, "days": rows, "totals": tot, "by_source": by_source, "by_city": by_city}

    # ================================================================== Valorisation du stock
    def stock_valuation(self, frm: str, to: str) -> dict[str, Any]:
        frm, to = _range(frm, to)
        ex = self.store._exec
        t0, t1 = f"{frm} 00:00:00", f"{to} 23:59:59"
        opening = ex("SELECT balance_after, avg_cost_cents_after FROM stock_movements WHERE at < ? ORDER BY at DESC, id DESC LIMIT 1",
                     (t0,), fetch="one")
        bal, avg = (int(opening[0]), int(opening[1])) if opening else (0, 0)
        moves = ex("SELECT SUBSTR(at, 1, 10), balance_after, avg_cost_cents_after, delta, reason, written_off FROM stock_movements "
                   "WHERE at >= ? AND at <= ? ORDER BY at, id", (t0, t1), fetch="all")
        closing: dict[str, tuple[int, int]] = {}
        in_units = out_units = lost = 0
        by_reason: dict[str, dict[str, int]] = {}
        for day, b, a, delta, reason, w in moves:
            closing[day] = (int(b), int(a))
            r = by_reason.setdefault(reason, {"movements": 0, "units": 0})
            r["movements"] += 1
            r["units"] += int(delta)
            in_units += max(int(delta), 0)
            out_units += max(-int(delta), 0)
            lost += int(w or 0)
        rows = []
        start = {"on_hand": bal, "avg_cost_cents": avg, "value_cents": max(bal, 0) * avg}
        for d in _days(frm, to):
            if d in closing:
                bal, avg = closing[d]
            rows.append({"date": d, "on_hand": bal, "avg_cost_cents": avg, "value_cents": max(bal, 0) * avg})
        return {"from": frm, "to": to, "opening": start, "closing": rows[-1], "days": rows,
                "units_in": in_units, "units_out": out_units, "units_lost": lost,
                "by_reason": [{"reason": k, **v} for k, v in sorted(by_reason.items())],
                "ledger_start": self.store.get_setting("stock_ledger_start") or None}

    # ================================================================== Livraisons
    def delivery(self, frm: str, to: str) -> dict[str, Any]:
        frm, to = _range(frm, to)
        t0, t1 = f"{frm} 00:00:00", f"{to} 23:59:59"
        rows = self.store._exec(
            "SELECT o.status, o.carrier, o.city, COALESCE(NULLIF(o.confirmed_at, ''), o.created_at), o.delivered_at "
            "FROM orders o WHERE (o.status = 'delivered' AND o.delivered_at >= ? AND o.delivered_at <= ?) "
            "OR (o.status = 'returned' AND COALESCE(NULLIF(o.returned_at, ''), o.updated_at) >= ? "
            "AND COALESCE(NULLIF(o.returned_at, ''), o.updated_at) <= ?) LIMIT 20000", (t0, t1, t0, t1), fetch="all")
        groups: dict[str, dict[str, dict[str, Any]]] = {"carrier": {}, "city": {}}
        all_delays: list[float] = []
        delivered = returned = 0
        for status, carrier, city, confirmed_at, delivered_at in rows:
            delay = None
            if status == "delivered":
                delivered += 1
                a, b = _parse(confirmed_at), _parse(delivered_at)
                if a and b and b >= a:
                    delay = (b - a).total_seconds() / 86400
                    all_delays.append(delay)
            else:
                returned += 1
            for kind, name in (("carrier", carrier or "Sans livreur"), ("city", city_name(city) or "—")):
                g = groups[kind].setdefault(name, {"delivered": 0, "returned": 0, "delays": []})
                g["delivered" if status == "delivered" else "returned"] += 1
                if delay is not None:
                    g["delays"].append(delay)

        def shape(kind: str) -> list[dict[str, Any]]:
            out = []
            for name, g in groups[kind].items():
                out.append({kind: name, "delivered": g["delivered"], "returned": g["returned"],
                            "return_rate": _rate(g["returned"], g["delivered"] + g["returned"]),
                            "avg_delay_days": round(sum(g["delays"]) / len(g["delays"]), 1) if g["delays"] else None})
            return sorted(out, key=lambda x: -(x["delivered"] + x["returned"]))

        return {"from": frm, "to": to, "delivered": delivered, "returned": returned,
                "return_rate": _rate(returned, delivered + returned),
                "avg_delay_days": round(sum(all_delays) / len(all_delays), 1) if all_delays else None,
                "median_delay_days": round(median(all_delays), 1) if all_delays else None,
                "by_carrier": shape("carrier"), "by_city": shape("city")}

    # ================================================================== Marge par jour
    def margin(self, frm: str, to: str) -> dict[str, Any]:
        frm, to = _range(frm, to)
        t0, t1 = f"{frm} 00:00:00", f"{to} 23:59:59"
        ex = self.store._exec
        days = {d: {"date": d, "delivered": 0, "revenue_cents": 0, "cogs_cents": 0, "carrier_fees_cents": 0,
                    "expenses_cents": 0, "write_offs_cents": 0} for d in _days(frm, to)}
        for d, n, rev, cogs, fees in ex(
                f"SELECT SUBSTR(o.delivered_at, 1, 10), COUNT(*), SUM({TOTAL}) * 100, COALESCE(SUM(u.units * u.unit_cost_cents), 0), "
                f"SUM({FEE}) FROM orders o LEFT JOIN stock_order_units u ON u.order_number = o.order_number "
                "WHERE o.status = 'delivered' AND o.delivered_at >= ? AND o.delivered_at <= ? "
                "GROUP BY SUBSTR(o.delivered_at, 1, 10)", (t0, t1), fetch="all"):
            days[d].update(delivered=int(n), revenue_cents=int(rev or 0), cogs_cents=int(cogs or 0))
            days[d]["carrier_fees_cents"] += int(fees or 0)
        for d, fees in ex(
                f"SELECT SUBSTR(COALESCE(NULLIF(o.returned_at, ''), o.updated_at), 1, 10), SUM({FEE}) FROM orders o "
                "WHERE o.status = 'returned' AND COALESCE(NULLIF(o.returned_at, ''), o.updated_at) >= ? "
                "AND COALESCE(NULLIF(o.returned_at, ''), o.updated_at) <= ? "
                "GROUP BY SUBSTR(COALESCE(NULLIF(o.returned_at, ''), o.updated_at), 1, 10)", (t0, t1), fetch="all"):
            days[d]["carrier_fees_cents"] += int(fees or 0)
        for d, amount in ex("SELECT date, SUM(amount_cents) FROM expenses WHERE date >= ? AND date <= ? GROUP BY date",
                            (frm, to), fetch="all"):
            days[d]["expenses_cents"] += int(amount or 0)
        for d, amount in ex("SELECT SUBSTR(at, 1, 10), SUM(written_off * unit_cost_cents) FROM stock_movements "
                            "WHERE written_off > 0 AND at >= ? AND at <= ? GROUP BY SUBSTR(at, 1, 10)", (t0, t1), fetch="all"):
            days[d]["write_offs_cents"] += int(amount or 0)
        rows = []
        for d in sorted(days):
            r = days[d]
            r["gross_margin_cents"] = r["revenue_cents"] - r["cogs_cents"] - r["carrier_fees_cents"]
            r["net_profit_cents"] = r["gross_margin_cents"] - r["expenses_cents"] - r["write_offs_cents"]
            rows.append(r)
        keys = ("delivered", "revenue_cents", "cogs_cents", "carrier_fees_cents", "gross_margin_cents", "expenses_cents",
                "write_offs_cents", "net_profit_cents")
        return {"from": frm, "to": to, "days": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}}

    # ================================================================== Clôture mensuelle
    def closing(self, month: str) -> dict[str, Any]:
        try:
            first = date.fromisoformat(f"{month}-01")
        except ValueError:
            raise ReportError("mois invalide (AAAA-MM)")
        today = now_dt().date()
        if first > today:
            raise ReportError("ce mois n'a pas encore commencé")
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        end = min(last, today)
        frm, to = first.isoformat(), end.isoformat()
        rep = self.finance.report(frm, to)
        statuses = dict(self.store._exec(
            "SELECT o.status, COUNT(*) FROM orders o WHERE o.created_at >= ? AND o.created_at <= ? GROUP BY o.status",
            (f"{frm} 00:00:00", f"{to} 23:59:59"), fetch="all"))
        stock = self.stock_valuation(to, to)["closing"]
        return {
            "month": month, "from": frm, "to": to, "complete": end == last, "generated_at": fmt(now_dt()),
            "orders": {"created": sum(int(v) for v in statuses.values()),
                       "by_status": {k: int(v) for k, v in sorted(statuses.items())}},
            "pnl": rep["pnl"], "counts": rep["counts"], "expenses_by_category": rep["expenses_by_category"],
            "cash": {k: rep["cash"][k] for k in ("in_cents", "out_expenses_cents", "out_suppliers_cents", "net_cents")},
            "stock": stock,
            # Debts and receivables can't be rebuilt for a past date: they are the amounts when the page is generated.
            "receivables_cents": rep["cash"]["to_collect_cents"], "debts_cents": rep["cash"]["to_pay_cents"],
        }


# ---------------------------------------------------------------------- CSV shapes
def mad(c: Any) -> str:
    return "" if c is None else f"{int(c) / 100:.2f}".replace(".", ",")


def pct(r: Any) -> str:
    return "" if r is None else f"{r * 100:.1f}".replace(".", ",") + " %"


def csv_for(name: str, data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    if name == "sales":
        rows = [{**r, "revenue": mad(r["revenue_cents"])} for r in data["days"]]
        return rows, [("date", "Date"), ("orders", "Commandes créées"), ("confirmed", "Confirmées"), ("cancelled", "Annulées"),
                      ("delivered", "Livrées"), ("units", "Unités livrées"), ("revenue", "Chiffre d'affaires (MAD)")]
    if name == "stock":
        rows = [{**r, "avg": mad(r["avg_cost_cents"]), "value": mad(r["value_cents"])} for r in data["days"]]
        return rows, [("date", "Date"), ("on_hand", "Stock (unités)"), ("avg", "Coût moyen (MAD)"), ("value", "Valeur (MAD)")]
    if name == "delivery":
        rows = [{"kind": "Livreur", "name": r["carrier"], **r} for r in data["by_carrier"]] + \
               [{"kind": "Ville", "name": r["city"], **r} for r in data["by_city"]]
        rows = [{**r, "rate": pct(r["return_rate"]), "delay": "" if r["avg_delay_days"] is None else str(r["avg_delay_days"]).replace(".", ",")}
                for r in rows]
        return rows, [("kind", "Type"), ("name", "Nom"), ("delivered", "Livrées"), ("returned", "Retours"),
                      ("rate", "Taux de retour"), ("delay", "Délai moyen confirmée → livrée (jours)")]
    if name == "margin":
        keys = ("revenue_cents", "cogs_cents", "carrier_fees_cents", "gross_margin_cents", "expenses_cents",
                "write_offs_cents", "net_profit_cents")
        rows = [{**r, **{k: mad(r[k]) for k in keys}} for r in data["days"]]
        return rows, [("date", "Date"), ("delivered", "Livrées"), ("revenue_cents", "CA (MAD)"), ("cogs_cents", "Coût produits (MAD)"),
                      ("carrier_fees_cents", "Frais livreurs (MAD)"), ("gross_margin_cents", "Marge brute (MAD)"),
                      ("expenses_cents", "Dépenses (MAD)"), ("write_offs_cents", "Produits perdus (MAD)"),
                      ("net_profit_cents", "Bénéfice net (MAD)")]
    if name == "closing":
        p, c = data["pnl"], data["cash"]
        lines = [("Commandes créées", str(data["orders"]["created"])), ("Commandes livrées", str(data["counts"]["delivered"])),
                 ("Retours", str(data["counts"]["returned"])), ("Chiffre d'affaires", mad(p["revenue_cents"])),
                 ("Coût des produits vendus", mad(p["cogs_cents"])), ("Frais des livreurs", mad(p["carrier_fees_cents"])),
                 ("Marge brute", mad(p["gross_margin_cents"])), ("Dépenses", mad(p["expenses_cents"])),
                 ("Produits perdus (retours)", mad(p["write_offs_cents"])), ("Bénéfice net", mad(p["net_profit_cents"])),
                 ("Encaissements (versements livreurs)", mad(c["in_cents"])), ("Décaissements (dépenses)", mad(c["out_expenses_cents"])),
                 ("Décaissements (fournisseurs)", mad(c["out_suppliers_cents"])), ("Solde de trésorerie", mad(c["net_cents"])),
                 ("Stock en fin de période (unités)", str(data["stock"]["on_hand"])),
                 ("Valeur du stock", mad(data["stock"]["value_cents"])),
                 ("À encaisser chez les livreurs (à la date d'édition)", mad(data["receivables_cents"])),
                 ("Dettes fournisseurs (à la date d'édition)", mad(data["debts_cents"]))]
        return [{"label": a, "value": b} for a, b in lines], [("label", f"Clôture {data['month']}"), ("value", "Montant (MAD) / nombre")]
    raise ReportError("rapport inconnu")
