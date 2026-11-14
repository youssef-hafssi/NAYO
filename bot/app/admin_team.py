"""Team, audit log viewer and settings (owner only).

Members are never deleted: they are disabled (they can't log in, every open session ends at once). A new member
and a password reset get a temporary password, shown ONCE in the answer (never stored in clear, never logged)."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .crm import STALE_HOURS_MAX
from .sheets import TZ

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# No 0/O, 1/l/I: the owner reads it out or types it on a phone.
_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def temporary_password(n: int = 14) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


class MemberIn(BaseModel):
    model_config = {"extra": "forbid"}
    email: str = Field(min_length=5, max_length=200)
    name: str = Field(min_length=2, max_length=80)
    role: Literal["owner", "agent"] = "agent"


class MemberEditIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: str | None = Field(default=None, min_length=2, max_length=80)
    role: Literal["owner", "agent"] | None = None
    active: bool | None = None


class SettingsIn(BaseModel):
    model_config = {"extra": "forbid"}
    company_name: str | None = Field(default=None, max_length=80)
    company_address: str | None = Field(default=None, max_length=300)
    company_phone: str | None = Field(default=None, max_length=30)
    stock_low_threshold: int | None = Field(default=None, ge=0, le=100_000)
    followup_stale_hours: int | None = Field(default=None, ge=1, le=STALE_HOURS_MAX)


SETTING_KEYS = ("company_name", "company_address", "company_phone", "stock_low_threshold", "followup_stale_hours")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day_start(d: str) -> float:
    """Start of a Casablanca day as a timestamp (the audit log stores epoch seconds)."""
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=TZ).timestamp()


def add_team_routes(router: APIRouter, svc: Callable[[], Any], owner_only: Any, audit: Callable[..., None]) -> None:
    def store() -> Any:
        return svc().store

    def member(mid: str) -> dict[str, Any]:
        m = store().admin_row(mid)
        if not m:
            raise HTTPException(404, "membre introuvable")
        return m

    # ================================================================== team
    @router.get("/team/members")
    def members(admin: dict = Depends(owner_only)) -> dict[str, Any]:
        return {"items": store().list_admins(), "me": admin["id"]}

    @router.post("/team/members")
    def add_member(body: MemberIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        email = body.email.strip().lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(422, "adresse email invalide")
        name = " ".join(body.name.split())
        password = temporary_password()
        from .admin import hash_password

        m = store().create_admin(email, name, body.role, hash_password(password))
        if not m:
            raise HTTPException(409, "Cette adresse email est déjà utilisée.")
        audit(admin, "team.create", "admin_user", m["id"], f"{name} <{email}> ({body.role})")
        # Shown once: the owner gives it to the member, who changes it in "Plus → Mon compte".
        return {"member": m, "temporary_password": password}

    @router.patch("/team/members/{mid}")
    def edit_member(mid: str, body: MemberEditIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        m = member(mid)
        if mid == admin["id"] and (body.active is False or body.role == "agent"):
            raise HTTPException(409, "Vous ne pouvez pas vous désactiver ni retirer votre propre rôle de propriétaire.")
        losing_owner = m["role"] == "owner" and m["active"] and (body.role == "agent" or body.active is False)
        if losing_owner and store().active_owners() <= 1:
            raise HTTPException(409, "Il faut au moins un propriétaire actif.")
        name = " ".join(body.name.split()) if body.name is not None else None
        store().update_admin(mid, name=name, role=body.role, active=body.active)
        words = []
        if name is not None and name != m["name"]:
            words.append(f"nom → {name}")
        if body.role is not None and body.role != m["role"]:
            words.append("rôle → " + ("propriétaire" if body.role == "owner" else "agent"))
        if body.active is not None and body.active != m["active"]:
            words.append("réactivé" if body.active else "désactivé (sessions fermées)")
        if words:
            action = "team.disable" if body.active is False else "team.enable" if body.active else "team.edit"
            audit(admin, action, "admin_user", mid, f"{m['name']} : " + ", ".join(words))
        return {"member": member(mid)}

    @router.post("/team/members/{mid}/reset-password")
    def reset_password(mid: str, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        m = member(mid)
        if mid == admin["id"]:
            raise HTTPException(409, "Pour votre propre compte, utilisez « Changer mon mot de passe ».")
        password = temporary_password()
        from .admin import hash_password

        store().set_admin_password(mid, hash_password(password))  # also ends the member's open sessions
        audit(admin, "team.reset_password", "admin_user", mid, m["name"])
        return {"temporary_password": password}

    # ================================================================== audit log
    @router.get("/audit")
    def audit_log(admin_name: str = "", entity: str = "", frm: str = "", to: str = "", limit: int = 50, offset: int = 0,
                  admin: dict = Depends(owner_only)) -> dict[str, Any]:
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(400, "pagination invalide")
        for d in (frm, to):
            if d and not DATE_RE.match(d):
                raise HTTPException(422, "date invalide (AAAA-MM-JJ)")
        try:
            t0 = _day_start(frm) if frm else None
            t1 = (_day_start(to) + timedelta(days=1).total_seconds()) if to else None  # whole last day
        except ValueError:
            raise HTTPException(422, "date invalide (AAAA-MM-JJ)")
        if t0 is not None and t1 is not None and t0 >= t1:
            raise HTTPException(409, "la date de début est après la date de fin")
        return store().audit_search(admin_name=admin_name[:80], entity=entity[:40], frm=t0, to=t1, limit=limit, offset=offset)

    @router.get("/audit/facets")
    def audit_facets(admin: dict = Depends(owner_only)) -> dict[str, Any]:
        return store().audit_facets()

    # ================================================================== settings
    def read_settings() -> dict[str, Any]:
        from .crm import stale_hours
        from .stock import DEFAULT_THRESHOLD

        cfg = store().get_settings(SETTING_KEYS)
        try:
            threshold = int(cfg.get("stock_low_threshold", DEFAULT_THRESHOLD))
        except ValueError:
            threshold = DEFAULT_THRESHOLD
        return {"company_name": cfg.get("company_name") or "NAYO", "company_address": cfg.get("company_address", ""),
                "company_phone": cfg.get("company_phone", ""), "stock_low_threshold": threshold,
                "followup_stale_hours": stale_hours(cfg.get("followup_stale_hours"))}

    @router.get("/settings")
    def get_settings(admin: dict = Depends(owner_only)) -> dict[str, Any]:
        return read_settings()

    @router.patch("/settings")
    def edit_settings(body: SettingsIn, admin: dict = Depends(owner_only)) -> dict[str, Any]:
        before = read_settings()
        raw = body.model_dump(exclude_none=True)
        for k in ("company_name", "company_address", "company_phone"):
            if k in raw:
                raw[k] = " ".join(raw[k].split())
        if "company_name" in raw and not raw["company_name"]:
            raise HTTPException(422, "nom de l'entreprise requis")
        changed = {k: v for k, v in raw.items() if v != before.get(k)}
        for k, v in changed.items():
            store().set_setting(k, str(v))
            audit(admin, "settings.edit", "settings", k, f"{before.get(k)} → {v}")
        if "followup_stale_hours" in changed or "stock_low_threshold" in changed:
            crm = getattr(router, "crm", None)
            if crm is not None:
                crm()._cache.clear()  # the suggestions use both
        return read_settings()
