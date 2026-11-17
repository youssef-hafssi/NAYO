"""Admin "Visiteurs" API (superadmin only, server-enforced): visits per day, sources, devices, funnel, sessions and
one session's timeline. Data from analytics.py (first-party, anonymous)."""

from __future__ import annotations

import re
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException

_SID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
PERIODS = (7, 30, 90)


def add_analytics_routes(router: APIRouter, svc: Callable[[], Any], superadmin_only: Any) -> None:
    own: dict[str, Any] = {}

    def analytics() -> Any:
        shared = getattr(router, "analytics", None)  # set by create_app: same instance as POST /t
        if shared is not None:
            return shared()
        from .analytics import Analytics

        s = svc()
        if "a" not in own or own["a"].store is not s.store:
            own["a"] = Analytics(s.store)
        return own["a"]

    @router.get("/analytics/overview")
    def overview(days: int = 30, admin: dict = Depends(superadmin_only)) -> dict[str, Any]:
        if days not in PERIODS:
            raise HTTPException(400, "période invalide (7, 30 ou 90 jours)")
        return analytics().overview(days)

    @router.get("/analytics/sessions")
    def sessions(limit: int = 50, offset: int = 0, orders: bool = False,
                 admin: dict = Depends(superadmin_only)) -> dict[str, Any]:
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(400, "pagination invalide")
        return analytics().sessions(limit, offset, only_orders=orders)

    @router.get("/analytics/sessions/{session_id}")
    def session(session_id: str, admin: dict = Depends(superadmin_only)) -> dict[str, Any]:
        if not _SID.fullmatch(session_id):
            raise HTTPException(400, "session invalide")
        found = analytics().session(session_id)
        if not found:
            raise HTTPException(404, "session introuvable")
        return found
