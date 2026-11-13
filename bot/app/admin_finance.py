"""Admin finance API (owner only): expense categories, expenses, P&L / marketing / unit economics / cash, CSV."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .finance import Finance, FinanceError, period


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class CategoryEditIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: str | None = Field(default=None, min_length=1, max_length=60)
    active: bool | None = None


class ExpenseIn(BaseModel):
    model_config = {"extra": "forbid"}
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    category: str = Field(min_length=1, max_length=60)
    amount: float = Field(gt=0, le=10_000_000)
    supplier_id: int | None = Field(default=None, ge=1)
    campaign: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=500)
    recurring_monthly: bool = False


class ExpenseEditIn(BaseModel):
    model_config = {"extra": "forbid"}
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    category: str | None = Field(default=None, min_length=1, max_length=60)
    amount: float | None = Field(default=None, gt=0, le=10_000_000)
    supplier_id: int | None = Field(default=None, ge=1)
    campaign: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)
    recurring_monthly: bool | None = None


def add_finance_routes(router: APIRouter, svc: Callable[[], Any], owner_only: Any, audit: Callable[..., None],
                       delivery: Callable[[], Any]) -> None:
    cache: dict[str, Finance] = {}

    def finance() -> Finance:
        s = svc()
        if "f" not in cache or cache["f"].store is not s.store:
            # The report reads the stock, delivery and purchasing tables: make sure they exist (no query when they do).
            from .purchasing import Purchasing
            from .stock import Stock

            stock = getattr(s.orders, "stock", None) or Stock(s.store)
            Purchasing(s.store, stock)
            delivery()
            cache["f"] = Finance(s.store)
        f = cache["f"]
        f.ensure_recurring()
        return f

    def run(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except FinanceError as e:
            raise HTTPException(409, str(e))

    def _range(frm: str | None, to: str | None, preset: str | None) -> tuple[str, str]:
        if preset:
            return run(lambda: period(preset))
        if not frm or not to:
            raise HTTPException(422, "période requise (from / to ou preset)")
        return frm, to

    # ---------------------------------------------------------------- categories
    @router.get("/expense-categories")
    def categories(include_inactive: bool = False, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        return {"items": finance().categories(include_inactive)}

    @router.post("/expense-categories")
    def add_category(body: CategoryIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        c = run(lambda: finance().add_category(body.name))
        audit(admin, "expense_category.create", "expense_category", str(c["id"]), c["name"])
        return c

    @router.patch("/expense-categories/{cid}")
    def edit_category(cid: int, body: CategoryEditIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        c = run(lambda: finance().update_category(cid, body.name, body.active))
        audit(admin, "expense_category.edit", "expense_category", str(cid), str(body.model_dump(exclude_none=True)))
        return c

    # ---------------------------------------------------------------- expenses
    @router.get("/expenses")
    def expenses(frm: str | None = None, to: str | None = None, preset: str | None = None, category: str | None = None,
                 limit: int = 50, offset: int = 0, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(400, "pagination invalide")
        a, b = _range(frm, to, preset)
        return run(lambda: finance().list_expenses(a, b, category, limit, offset))

    @router.post("/expenses")
    def add_expense(body: ExpenseIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        e = run(lambda: finance().add_expense(
            date_=body.date, category=body.category, amount_cents=round(body.amount * 100), admin=admin["name"],
            supplier_id=body.supplier_id, campaign=body.campaign, note=body.note, recurring_monthly=body.recurring_monthly))
        if body.recurring_monthly:
            finance().ensure_recurring(force=True)  # a back-dated recurring expense gets its missing months now
        audit(admin, "expense.create", "expense", str(e["id"]),
              f"{e['date']} {e['category']} {body.amount:.2f} MAD" + (" (mensuelle)" if body.recurring_monthly else ""))
        return e

    @router.patch("/expenses/{eid}")
    def edit_expense(eid: int, body: ExpenseEditIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        raw = body.model_dump(exclude_none=True)
        if "amount" in raw:
            raw["amount_cents"] = round(raw.pop("amount") * 100)
        e = run(lambda: finance().update_expense(eid, **raw))
        if raw:
            audit(admin, "expense.edit", "expense", str(eid), ", ".join(f"{k}: {v}" for k, v in raw.items())[:300])
        return e

    @router.delete("/expenses/{eid}")
    def delete_expense(eid: int, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        e = run(lambda: finance().delete_expense(eid))
        audit(admin, "expense.delete", "expense", str(eid), f"{e['date']} {e['category']} {e['amount_cents'] / 100:.2f} MAD")
        return {"ok": True}

    # ---------------------------------------------------------------- reports
    @router.get("/finance/report")
    def report(frm: str | None = None, to: str | None = None, preset: str | None = None,
               admin: dict = Depends(owner_only)) -> dict[str, Any]:
        a, b = _range(frm, to, preset)
        return run(lambda: finance().report(a, b))

    @router.get("/finance/export")
    def export(frm: str | None = None, to: str | None = None, preset: str | None = None,
               admin: dict = Depends(owner_only)) -> Response:
        a, b = _range(frm, to, preset)
        body = run(lambda: finance().export_csv(a, b))
        audit(admin, "finance.export", "finance", "", f"{a} → {b}")
        return Response(body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="nayo-finance-{a}_{b}.csv"'})
