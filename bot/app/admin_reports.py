"""Admin dashboard (everyone; money for the owner only) and reports (owner only), each with a CSV export."""

from __future__ import annotations

import re
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Response

from .crm import csv_rows
from .finance import Finance, FinanceError, period
from .reports import Reports, ReportError, csv_for

PERIOD_REPORTS = ("sales", "stock", "delivery", "margin")


def add_reports_routes(router: APIRouter, svc: Callable[[], Any], current_admin: Any, owner_only: Any,
                       audit: Callable[..., None], delivery: Callable[[], Any]) -> None:
    cache: dict[str, Reports] = {}

    def reports() -> Reports:
        s = svc()
        if "r" not in cache or cache["r"].store is not s.store:
            crm = router.crm()  # type: ignore[attr-defined]  (also makes sure every table exists)
            delivery()
            stock = getattr(s.orders, "stock", None)
            cache["r"] = Reports(s.store, Finance(s.store), crm, stock)
        r = cache["r"]
        r.finance.ensure_recurring()
        return r

    def run(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except (ReportError, FinanceError) as e:
            raise HTTPException(409, str(e))

    def _range(frm: str, to: str, preset: str) -> tuple[str, str]:
        if preset:
            return run(lambda: period(preset))
        if not frm or not to:
            raise HTTPException(422, "période requise (frm / to ou preset)")
        return frm, to

    def _data(name: str, frm: str, to: str, preset: str, month: str) -> dict[str, Any]:
        r = reports()
        if name == "closing":
            if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
                raise HTTPException(422, "mois requis (AAAA-MM)")
            return run(lambda: r.closing(month))
        if name not in PERIOD_REPORTS:
            raise HTTPException(404, "rapport inconnu")
        a, b = _range(frm, to, preset)
        fn = {"sales": r.sales, "stock": r.stock_valuation, "delivery": r.delivery, "margin": r.margin}[name]
        return run(lambda: fn(a, b))

    @router.get("/dashboard")
    def dashboard(admin: dict = Depends(current_admin)) -> dict[str, Any]:
        return reports().dashboard(admin.get("role") == "owner")

    # The CSV route is registered first: "/reports/{name}" would otherwise also match "sales.csv".
    @router.get("/reports/{name}.csv")
    def report_csv(name: str, frm: str = "", to: str = "", preset: str = "", month: str = "",
                   admin: dict = Depends(owner_only)) -> Response:
        data = _data(name, frm, to, preset, month)
        rows, cols = run(lambda: csv_for(name, data))
        label = data.get("month") or f"{data['from']}_{data['to']}"
        audit(admin, "report.export", "report", name, label)
        return Response(csv_rows(rows, cols), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="nayo-{name}-{label}.csv"'})

    @router.get("/reports/{name}")
    def report(name: str, frm: str = "", to: str = "", preset: str = "", month: str = "",
               admin: dict = Depends(owner_only)) -> dict[str, Any]:
        return _data(name, frm, to, preset, month)
