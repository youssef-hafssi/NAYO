"""First-party visitor analytics (phase A): the store page sends small batches of events to POST /t
(src/lib/track.ts); the "Visiteurs" admin screen reads them (superadmin only).

- Anonymous: a random visitor_id (browser localStorage) and session_id (new after 30 min idle). Never the IP: only
  the country / city that Vercel derives from it (x-vercel-ip-country / x-vercel-ip-city).
- sessions: one row per visit, aggregated as events arrive (first source, device, deepest scroll, checkout reached,
  form started, order placed + its number). events: the raw timeline, deleted after 90 days (sessions are kept).
- One database statement per batch on Postgres (session upsert + events insert in a single CTE), on the instance's
  shared connection. Bots, malformed batches and over-eager visitors are dropped silently (the browser never retries).
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit

log = logging.getLogger("nayo.analytics")

MAX_BODY = 32_000
MAX_EVENTS = 50
SESSION_EVENT_CAP = 3000  # one visit can't fill the table
RETENTION_DAYS = 90
RATE_PER_MIN = 30  # batches per visitor per minute (the page sends one every 5 s at most)

EVENTS = frozenset({
    "page_view", "scroll_depth", "section_view", "click", "faq_open", "checkout_view", "form_start", "field_error",
    "quantity_change", "order_submit", "order_success", "whatsapp_click", "time_on_page",
})
# Only these keys survive in an event's data — e.g. field_error keeps {field, error}, never what was typed.
DATA_KEYS = frozenset({"pct", "section", "id", "label", "form", "field", "error", "qty", "from", "to", "q", "seconds",
                       "path", "order", "fallback", "visible"})
IN_APP = frozenset({"facebook", "instagram", "tiktok", "snapchat", "other"})
DEVICES = frozenset({"mobile", "tablet", "desktop"})
CTX_TEXT = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "fbclid", "referrer", "landing",
            "device", "in_app", "lang")
SESSION_TEXT = (*CTX_TEXT, "country", "city")

_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_KEY = re.compile(r"^[a-z_]{1,24}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_FBCLID = re.compile(r"^[A-Za-z0-9_\-.]{1,300}$")
_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
# Crawlers, link previews, headless browsers and HTTP libraries. In-app browsers (FBAN/FBAV, Instagram) are people.
BOT_UA = re.compile(
    r"bot\b|bot/|crawl|spider|slurp|headless|lighthouse|pagespeed|gtmetrix|pingdom|uptime|monitor|preview|"
    r"facebookexternalhit|facebookcatalog|meta-externalagent|whatsapp/|telegram|discord|curl|wget|python|httpx|"
    r"aiohttp|okhttp|java/|go-http|axios|node-fetch|undici|phantom|selenium|puppeteer|playwright|scrapy", re.I)


class BatchError(ValueError):
    """Malformed batch (400)."""


# ---------------------------------------------------------------- parsing / validation
def _text(v: Any, limit: int) -> str:
    return _CONTROL.sub("", v).strip()[:limit] if isinstance(v, str) else ""


def _url_part(v: Any, *, path_only: bool) -> str:
    """Referrer → scheme://host/path (no query: it can carry personal data). Landing → /path only."""
    s = _text(v, 1000)
    if not s:
        return ""
    if path_only:
        p = urlsplit(s).path if "://" in s else s.split("?")[0].split("#")[0]
        return p[:200] if p.startswith("/") else ""
    u = urlsplit(s)
    if u.scheme not in ("http", "https") or not u.netloc:
        return ""
    return f"{u.scheme}://{u.netloc.lower()}{u.path}"[:200]


def _data(d: Any) -> dict[str, Any]:
    if not isinstance(d, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in list(d.items())[:12]:
        if not isinstance(k, str) or not _KEY.fullmatch(k) or k not in DATA_KEYS:
            continue
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)) and math.isfinite(v):
            out[k] = max(-1e9, min(1e9, v))
        elif isinstance(v, str):
            out[k] = _text(v, 120)
    return out


def parse_batch(raw: bytes, now: float) -> dict[str, Any]:
    """Validated batch: {visitor_id, session_id, ctx, events: [(at, name, data_json)], webdriver}."""
    if len(raw) > MAX_BODY:
        raise BatchError("too large")
    try:
        body = json.loads(raw)
    except ValueError:
        raise BatchError("bad json")
    if not isinstance(body, dict):
        raise BatchError("bad body")
    vid, sid = body.get("v"), body.get("s")
    if not (isinstance(vid, str) and _ID.fullmatch(vid) and isinstance(sid, str) and _ID.fullmatch(sid)):
        raise BatchError("bad ids")
    raw_events = body.get("e")
    if not isinstance(raw_events, list) or len(raw_events) > MAX_EVENTS:
        raise BatchError("bad events")
    events = []
    for e in raw_events:
        if not isinstance(e, dict) or e.get("n") not in EVENTS:
            continue  # unknown names are dropped, the rest of the batch is kept
        t = e.get("t")
        at = t / 1000 if isinstance(t, (int, float)) and math.isfinite(t) else now
        if not now - 86400 <= at <= now + 300:  # a wrong device clock: use the arrival time
            at = now
        events.append((round(at, 3), e["n"], json.dumps(_data(e.get("d")), separators=(",", ":"), ensure_ascii=False)))
    c = body.get("c") if isinstance(body.get("c"), dict) else {}
    ctx = {k: _text(c.get(k), 100) for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")}
    fbclid = _text(c.get("fbclid"), 300)
    ctx["fbclid"] = fbclid if _FBCLID.fullmatch(fbclid or "-") and fbclid else ""
    ctx["referrer"] = _url_part(c.get("referrer"), path_only=False)
    ctx["landing"] = _url_part(c.get("landing"), path_only=True)
    ctx["device"] = c.get("device") if c.get("device") in DEVICES else ""
    ctx["in_app"] = c.get("in_app") if c.get("in_app") in IN_APP else ""
    lang = _text(c.get("lang"), 20)
    ctx["lang"] = lang if _LANG.fullmatch(lang or "-") else ""
    sw = c.get("sw")
    ctx["screen_w"] = int(sw) if isinstance(sw, (int, float)) and math.isfinite(sw) and 0 < sw <= 10000 else 0
    return {"visitor_id": vid, "session_id": sid, "ctx": ctx, "events": events, "webdriver": body.get("wd") is True}


def is_bot(user_agent: str) -> bool:
    ua = (user_agent or "").strip()
    return not ua or len(ua) < 20 or bool(BOT_UA.search(ua))


def geo(headers: Any) -> tuple[str, str]:
    """Country / city from Vercel's edge headers (derived from the IP, which is never stored)."""
    country = (headers.get("x-vercel-ip-country") or "").strip().upper()
    city = _text(unquote(headers.get("x-vercel-ip-city") or ""), 80)
    return (country if re.fullmatch(r"[A-Z]{2}", country) else ""), city


class RateLimiter:
    """Per-visitor fixed window, in memory (one per server instance: enough to stop a runaway tab or a script)."""

    def __init__(self, per_minute: int = RATE_PER_MIN):
        self.per_minute, self._hits, self._lock = per_minute, {}, threading.Lock()

    def allow(self, key: str, now: float) -> bool:
        with self._lock:
            if len(self._hits) > 20000:
                self._hits = {k: v for k, v in self._hits.items() if now - v[0] < 60}
            start, n = self._hits.get(key, (now, 0))
            if now - start >= 60:
                start, n = now, 0
            if n >= self.per_minute:
                return False
            self._hits[key] = (start, n + 1)
            return True


# ---------------------------------------------------------------- source label
SOCIAL = (("facebook", "facebook"), ("fb.", "facebook"), ("instagram", "instagram"), ("tiktok", "tiktok"),
          ("snapchat", "snapchat"), ("google.", "google"), ("bing.", "bing"), ("youtube", "youtube"),
          ("whatsapp", "whatsapp"), ("t.co", "twitter"), ("twitter", "twitter"), ("x.com", "twitter"))


def source_of(row: dict[str, Any]) -> str:
    """utm_source, else a Meta ad click (fbclid), else the referring site, else the in-app browser, else direct."""
    if row.get("utm_source"):
        return row["utm_source"].lower()[:40]
    if row.get("fbclid"):
        return "facebook (pub)"
    host = urlsplit(row.get("referrer") or "").netloc.lower()
    if host:
        for needle, label in SOCIAL:
            if needle in host:
                return label
        return host.removeprefix("www.")[:40]
    if row.get("in_app") in ("facebook", "instagram", "tiktok", "snapchat"):
        return row["in_app"]
    return "direct"


# ---------------------------------------------------------------- store
class Analytics:
    SCHEMA_VERSION = 1

    def __init__(self, store: Any):
        self.store = store
        if not store.needs_schema("analytics", self.SCHEMA_VERSION):
            return
        text = ", ".join(f"{c} TEXT NOT NULL DEFAULT ''" for c in SESSION_TEXT)
        for ddl in (
            f"CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL DEFAULT '', "
            f"started_at DOUBLE PRECISION NOT NULL, last_at DOUBLE PRECISION NOT NULL, {text}, "
            "screen_w INTEGER NOT NULL DEFAULT 0, events_count INTEGER NOT NULL DEFAULT 0, "
            "max_scroll INTEGER NOT NULL DEFAULT 0, reached_checkout INTEGER NOT NULL DEFAULT 0, "
            "form_started INTEGER NOT NULL DEFAULT 0, submitted INTEGER NOT NULL DEFAULT 0, "
            "order_number TEXT NOT NULL DEFAULT '')",
            "CREATE TABLE IF NOT EXISTS events (session_id TEXT NOT NULL, at DOUBLE PRECISION NOT NULL, "
            "name TEXT NOT NULL, data TEXT NOT NULL DEFAULT '')",
            "CREATE INDEX IF NOT EXISTS sessions_started ON sessions (started_at)",
            "CREATE INDEX IF NOT EXISTS sessions_visitor ON sessions (visitor_id, started_at)",
            "CREATE INDEX IF NOT EXISTS events_session ON events (session_id, at)",
            "CREATE INDEX IF NOT EXISTS events_at ON events (at)",
        ):
            store._exec(ddl)
        if store.backend == "postgres":
            for t in ("sessions", "events"):
                store._exec(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")  # not readable through Supabase's REST API
        store.schema_done("analytics", self.SCHEMA_VERSION)

    @property
    def _pg(self) -> bool:
        return self.store.backend == "postgres"

    def _upsert_sql(self, *, order: bool = False) -> str:
        """Session upsert. Text fields keep their first non-empty value (the visit's source). `order=True` (an order
        placed during the visit): the order number is overwritten (the latest order wins) and the event cap ignored."""
        mx, mn = ("GREATEST", "LEAST") if self._pg else ("MAX", "MIN")
        cols = ("session_id", "visitor_id", "started_at", "last_at", *SESSION_TEXT, "screen_w", "events_count",
                "max_scroll", "reached_checkout", "form_started", "submitted", "order_number")
        keep_first = ", ".join(f"{c} = CASE WHEN sessions.{c} = '' THEN excluded.{c} ELSE sessions.{c} END"
                               for c in ("visitor_id", *SESSION_TEXT, *(() if order else ("order_number",))))
        if order:
            keep_first += ", order_number = excluded.order_number"
        return (
            f"INSERT INTO sessions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
            "ON CONFLICT (session_id) DO UPDATE SET "
            f"started_at = {mn}(sessions.started_at, excluded.started_at), "
            f"last_at = {mx}(sessions.last_at, excluded.last_at), "
            "events_count = sessions.events_count + excluded.events_count, "
            f"max_scroll = {mx}(sessions.max_scroll, excluded.max_scroll), "
            f"reached_checkout = {mx}(sessions.reached_checkout, excluded.reached_checkout), "
            f"form_started = {mx}(sessions.form_started, excluded.form_started), "
            f"submitted = {mx}(sessions.submitted, excluded.submitted), "
            "screen_w = CASE WHEN sessions.screen_w = 0 THEN excluded.screen_w ELSE sessions.screen_w END, "
            f"{keep_first} "
            + ("" if order else f"WHERE sessions.events_count < {SESSION_EVENT_CAP} ")
            + "RETURNING events_count"
        )

    def record(self, batch: dict[str, Any], *, country: str = "", city: str = "", now: float | None = None) -> int:
        """Store one batch: the session's aggregates + its events. Returns the number of events stored."""
        now = now or time.time()
        events = batch["events"]
        names = {e[1] for e in events}
        scroll = 0
        for _, name, data in events:
            if name == "scroll_depth":
                try:
                    scroll = max(scroll, int(json.loads(data).get("pct", 0)))
                except (ValueError, TypeError):
                    pass
        times = [e[0] for e in events] or [now]
        ctx = {**batch["ctx"], "country": country, "city": city}
        params = (batch["session_id"], batch["visitor_id"], min(times), max(times), *[ctx.get(c, "") for c in SESSION_TEXT],
                  ctx.get("screen_w", 0), len(events), max(0, min(100, scroll)), int("checkout_view" in names),
                  int("form_start" in names), int(bool(names & {"order_submit", "order_success"})), "")
        sid = batch["session_id"]
        if self._pg:
            # ONE statement (one round trip): the events are written only if the session accepted them (cap).
            if events:
                values = ", ".join("(?::text, ?::float8, ?::text, ?::text)" for _ in events)
                sql = (f"WITH s AS ({self._upsert_sql()}) INSERT INTO events (session_id, at, name, data) "
                       f"SELECT v.* FROM (VALUES {values}) AS v(session_id, at, name, data) WHERE EXISTS (SELECT 1 FROM s)")
                self.store._exec(sql, (*params, *[x for at, name, data in events for x in (sid, at, name, data)]))
            else:
                self.store._exec(self._upsert_sql(), params, fetch="one")
            return len(events)
        with self.store.tx() as tx:  # SQLite (tests / local dev)
            accepted = tx.exec(self._upsert_sql(), params, fetch="one")
            if accepted and events:
                tx.exec("INSERT INTO events (session_id, at, name, data) VALUES "
                        + ", ".join("(?, ?, ?, ?)" for _ in events),
                        tuple(x for at, name, data in events for x in (sid, at, name, data)))
            return len(events) if accepted else 0

    def link_order(self, session_id: str, visitor_id: str, order_number: str, now: float | None = None,
                   utm: dict[str, str] | None = None) -> None:
        """POST /orders created an order during this visit (the session row may not exist yet: the browser sends its
        events every 5 s — the next batch then fills in the rest). The order's utm values fill an empty source."""
        now = now or time.time()
        utm = {k: (v or "")[:100] for k, v in (utm or {}).items()}
        params = (session_id, visitor_id, now, now, *[utm.get(c, "") for c in SESSION_TEXT], 0, 0, 0, 0, 1, 1, order_number)
        self.store._exec(self._upsert_sql(order=True), params, fetch="one")

    def purge(self, now: float | None = None) -> None:
        """Events older than 90 days are deleted; sessions (the aggregates) are kept."""
        cutoff = (now or time.time()) - RETENTION_DAYS * 86400
        self.store._exec("DELETE FROM events WHERE at < ?", (cutoff,))
        self.store.set_setting("analytics:purged_at", str(int(now or time.time())))

    # ------------------------------------------------------------------ admin ("Visiteurs", superadmin only)
    SESSION_COLS = ("session_id", "visitor_id", "started_at", "last_at", *SESSION_TEXT, "screen_w", "events_count",
                    "max_scroll", "reached_checkout", "form_started", "submitted", "order_number")

    def _session(self, r: Any) -> dict[str, Any]:
        s = dict(zip(self.SESSION_COLS, r))
        for k in ("reached_checkout", "form_started", "submitted"):
            s[k] = bool(s[k])
        s["ordered"] = bool(s["order_number"]) or s["submitted"]
        s["source"] = source_of(s)
        s.pop("fbclid", None)  # an ad click id: useful for the source label only
        return s

    def overview(self, days: int, now: float | None = None) -> dict[str, Any]:
        from .sheets import TZ

        now = now or time.time()
        today = datetime.fromtimestamp(now, TZ).date()
        first = today - timedelta(days=days - 1)
        start = datetime(first.year, first.month, first.day, tzinfo=TZ).timestamp()
        rows = self.store._exec(
            f"SELECT {', '.join(self.SESSION_COLS)} FROM sessions WHERE started_at >= ? ORDER BY started_at", (start,),
            fetch="all")
        sessions = [self._session(r) for r in rows]
        per_day: dict[str, dict[str, Any]] = {}
        for i in range(days):
            d = (first + timedelta(days=i)).isoformat()
            per_day[d] = {"day": d, "visits": 0, "visitors": set(), "orders": 0}
        sources: dict[str, Counter] = defaultdict(Counter)
        devices: Counter = Counter()
        in_app: Counter = Counter()
        funnel = Counter()
        for s in sessions:
            d = datetime.fromtimestamp(s["started_at"], TZ).date().isoformat()
            day = per_day.get(d)
            if day is None:
                continue
            day["visits"] += 1
            day["visitors"].add(s["visitor_id"])
            day["orders"] += int(s["ordered"])
            sources[s["source"]]["visits"] += 1
            sources[s["source"]]["orders"] += int(s["ordered"])
            devices[s["device"] or "inconnu"] += 1
            if s["in_app"]:
                in_app[s["in_app"]] += 1
            funnel["visits"] += 1
            funnel["scroll_50"] += int(s["max_scroll"] >= 50)
            funnel["form_started"] += int(s["form_started"])
            funnel["ordered"] += int(s["ordered"])
        return {
            "days": [{**v, "visitors": len(v["visitors"])} for v in per_day.values()],
            "totals": {"visits": funnel["visits"], "visitors": len({s["visitor_id"] for s in sessions}),
                       "orders": funnel["ordered"]},
            "sources": sorted(({"source": k, **v} for k, v in sources.items()), key=lambda x: -x["visits"])[:15],
            "devices": [{"device": k, "visits": v} for k, v in devices.most_common()],
            "in_app": [{"app": k, "visits": v} for k, v in in_app.most_common()],
            "funnel": {k: funnel[k] for k in ("visits", "scroll_50", "form_started", "ordered")},
        }

    def sessions(self, limit: int, offset: int, only_orders: bool = False) -> dict[str, Any]:
        where = "WHERE order_number <> '' OR submitted = 1 " if only_orders else ""
        rows = self.store._exec(
            f"SELECT {', '.join(self.SESSION_COLS)} FROM sessions {where}ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (limit + 1, offset), fetch="all")
        items = [self._session(r) for r in rows]
        return {"items": items[:limit], "has_more": len(items) > limit}

    def session(self, session_id: str) -> dict[str, Any] | None:
        r = self.store._exec(f"SELECT {', '.join(self.SESSION_COLS)} FROM sessions WHERE session_id = ?", (session_id,),
                             fetch="one")
        if not r:
            return None
        s = self._session(r)
        events = self.store._exec("SELECT at, name, data FROM events WHERE session_id = ? ORDER BY at LIMIT 1000",
                                  (session_id,), fetch="all")
        others = self.store._exec(
            f"SELECT {', '.join(self.SESSION_COLS)} FROM sessions WHERE visitor_id = ? AND session_id <> ? "
            "ORDER BY started_at DESC LIMIT 10", (s["visitor_id"], session_id), fetch="all") if s["visitor_id"] else []

        def data(x: str) -> dict[str, Any]:
            try:
                return json.loads(x) if x else {}
            except ValueError:
                return {}

        return {"session": s, "events": [{"at": e[0], "name": e[1], "data": data(e[2])} for e in events],
                "other_visits": [self._session(o) for o in others]}
