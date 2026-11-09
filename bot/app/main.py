"""FastAPI app: /orders (website), /webhook (WhatsApp Cloud API), /health.

Run locally:  py -3.11 -m uvicorn app.main:app --reload --port 8000   (from the bot/ folder)
"""

from __future__ import annotations

import hmac
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from .config import Settings, get_settings
from .flow import Bot
from .orders import OrderIn, OrderOut, create_order
from .sheets import OrdersRepo
from .store import Store
from .whatsapp import extract_messages, verify_signature

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nayo")
# httpx logs full request URLs at INFO; keep it quiet so nothing sensitive ends up in logs.
logging.getLogger("httpx").setLevel(logging.WARNING)


@dataclass
class Services:
    settings: Settings
    store: Store
    orders: OrdersRepo
    bot: Bot


def build_services(settings: Settings) -> Services:
    from .ai import GeminiAI
    from .sheets import CsvOrders, DbOrders, SheetOrders
    from .whatsapp import WhatsAppClient

    store = Store(settings.state_backend, database_url=settings.database_url, sqlite_path=settings.sqlite_path)
    if settings.orders_backend == "csv":
        orders = CsvOrders(settings.csv_path)
    elif settings.orders_backend == "db":
        orders = DbOrders(store)
    else:
        orders = SheetOrders(settings.google_sheet_id, settings.google_service_account_json, settings.orders_tab)
    wa = WhatsAppClient(settings.whatsapp_token, settings.whatsapp_phone_number_id, settings.graph_api_version)
    ai = GeminiAI(
        settings.gemini_api_key,
        settings.gemini_model,
        fallback_model=settings.gemini_fallback_model,
        timeout_s=settings.gemini_timeout_s,
        thinking_budget=settings.gemini_thinking_budget,
    )
    bot = Bot(
        orders,
        store,
        wa,
        ai,
        owner=settings.owner_whatsapp,
        max_replies_per_hour=settings.max_replies_per_hour,
        history_size=settings.history_size,
    )
    return Services(settings, store, orders, bot)


def create_app(services: Services | None = None, settings: Settings | None = None) -> FastAPI:
    settings = services.settings if services else (settings or get_settings())
    state: dict[str, Services] = {}
    if services:
        state["s"] = services

    def svc() -> Services:
        if "s" not in state:
            state["s"] = build_services(settings)
        return state["s"]

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        svc()  # fail fast on bad configuration
        log.info("NAYO bot ready (state=%s, model=%s, graph=%s)", settings.state_backend, settings.gemini_model, settings.graph_api_version)
        yield

    app = FastAPI(title="NAYO WhatsApp bot", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
        max_age=3600,
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        # Also touches the database, so uptime pings keep a free Supabase project from pausing.
        return {"ok": True, "db": svc().store.ping()}

    @app.post("/orders", response_model=OrderOut)
    async def post_order(request: Request) -> Any:
        s = svc()
        if s.settings.order_api_key and not hmac.compare_digest(request.headers.get("x-api-key", ""), s.settings.order_api_key):
            raise HTTPException(401, "bad api key")
        ip = _client_ip(request)
        if s.store.count(f"ip:{ip}", 3600) >= s.settings.max_orders_per_ip_per_hour:
            log.warning("order rate limit hit for an IP")
            raise HTTPException(429, "too many orders")
        raw = await request.body()
        if len(raw) > 4000:
            raise HTTPException(413, "payload too large")
        try:
            body = OrderIn.model_validate_json(raw)
        except ValueError as e:
            errors = getattr(e, "errors", lambda: [])()
            fields = sorted({".".join(str(p) for p in err.get("loc", ())) for err in errors})
            return JSONResponse({"detail": "invalid order", "fields": fields}, status_code=422)
        s.store.hit(f"ip:{ip}")
        try:
            return create_order(body, s.orders, s.store)
        except Exception:
            log.exception("could not save order")
            raise HTTPException(503, "order storage unavailable")

    @app.get("/webhook")
    def verify_webhook(request: Request) -> Any:
        p = request.query_params
        token = p.get("hub.verify_token", "")
        if (
            p.get("hub.mode") == "subscribe"
            and settings.whatsapp_verify_token
            and hmac.compare_digest(token, settings.whatsapp_verify_token)
        ):
            return PlainTextResponse(p.get("hub.challenge", ""))
        raise HTTPException(403, "verification failed")

    @app.post("/webhook")
    async def webhook(request: Request, background: BackgroundTasks) -> Any:
        raw = await request.body()
        if not verify_signature(raw, request.headers.get("x-hub-signature-256"), settings.whatsapp_app_secret):
            log.warning("webhook with invalid signature rejected")
            raise HTTPException(401, "bad signature")
        try:
            payload = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "bad json")
        s = svc()
        for msg in extract_messages(payload):
            if settings.process_inline:
                # Serverless (Vercel): the function may be frozen right after it answers, so do the work first.
                # Meta retries slow deliveries; duplicates are ignored by the processed-message store.
                await run_in_threadpool(s.bot.handle, msg)
            else:
                background.add_task(s.bot.handle, msg)  # reply happens after the 200 below
        return {"ok": True}

    return app


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def __getattr__(name: str) -> Any:  # `app.main:app` is built lazily so tests can import this module freely
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
