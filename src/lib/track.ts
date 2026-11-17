/*
 * First-party visitor analytics (phase A) → POST /bot-api/t (bot/app/analytics.py). No library, no cookie.
 * - visitor_id: random, in localStorage. session: new after 30 min idle, or when the visitor comes back from another
 *   campaign link (utm_source / fbclid). Its first-touch context (utm_*, fbclid, referrer, landing, device…) goes
 *   with every batch (the server keeps the first values).
 * - Events are queued (flushed at 50, so a batch never exceeds the server's limit) and sent every 5 s and when the page is hidden (sendBeacon; fetch keepalive otherwise).
 * - Clicks: any element with data-track="id" (main buttons, quantity stepper, FAQ, WhatsApp). Never field values.
 * - Off on /admin, and when no order endpoint is configured.
 */

type Data = Record<string, string | number | boolean>
type Ctx = Record<string, string | number>
type Session = { id: string; last: number; ctx: Ctx }

const ORDERS = (import.meta.env.VITE_ORDER_ENDPOINT as string | undefined) || ''
const URL_T = ORDERS.replace(/\/orders\/?$/, '/t')
const UTM = ['Source', 'Medium', 'Campaign', 'Content', 'Term']

const on = () => URL_T !== ORDERS && !location.pathname.startsWith('/admin')
const rid = () => crypto.randomUUID?.() ?? Math.random().toString(36).slice(2) + Date.now().toString(36)

// localStorage can throw (private mode, blocked storage): the values are also kept in memory for this page.
function store(k: string, v?: string): string | null {
  try {
    if (v === undefined) return localStorage.getItem(k)
    localStorage.setItem(k, v)
  } catch {
    /* memory only */
  }
  return null
}

let vid = ''
const visitor = () => vid || (vid = store('nayo:v') || rid(), store('nayo:v', vid), vid)

function context(q: URLSearchParams): Ctx {
  const ua = navigator.userAgent
  const ref = document.referrer
  const c: Ctx = {
    fbclid: q.get('fbclid') ?? '',
    referrer: ref.includes(location.host) ? '' : ref,
    landing: location.pathname,
    device: /Mobi|Android|iP(hone|ad)/i.test(ua) ? 'mobile' : 'desktop', // tablets count as mobile
    in_app: /FBA[NV]/.test(ua) ? 'facebook' : /Instagram/.test(ua) ? 'instagram' : '',
    lang: navigator.language,
    sw: innerWidth,
  }
  UTM.forEach((n) => (c['utm_' + n.toLowerCase()] = q.get('utm_' + n.toLowerCase()) ?? ''))
  return c
}

/** The current session (renewed after 30 min idle or a new campaign link), touched on every event. */
let cur: Session | null = null
function session(): Session {
  const now = Date.now()
  const q = new URLSearchParams(location.search)
  let s = cur
  try {
    s = JSON.parse(store('nayo:s') || 'null') || s
  } catch {
    /* corrupted: new session */
  }
  const src = q.get('utm_source'), click = q.get('fbclid')
  if (!s || now - s.last > 18e5 || ((src || click) && (s.ctx.utm_source !== (src ?? '') || s.ctx.fbclid !== (click ?? ''))))
    s = { id: rid(), last: now, ctx: context(q) }
  s.last = now
  store('nayo:s', JSON.stringify(s))
  return (cur = s)
}

let queue: { n: string; t: number; d: Data }[] = []

export function flush() {
  if (!queue.length || !on()) return
  const s = session()
  const body = JSON.stringify({ v: visitor(), s: s.id, c: s.ctx, e: queue.splice(0, 50), wd: navigator.webdriver })
  // a string body is sent as text/plain: no CORS preflight
  if (!navigator.sendBeacon?.(URL_T, body)) fetch(URL_T, { method: 'POST', body, keepalive: true }).catch(() => undefined)
}

export function t(name: string, d: Data = {}) {
  if (!on()) return
  start()
  queue.push({ n: name, t: Date.now(), d })
  if (queue.length >= 50) flush()
}

const fired = new Set<string>()
/** Once per page view (scroll thresholds, sections, form start…). */
export function once(key: string, name: string, d: Data = {}) {
  if (!fired.has(key)) fired.add(key), t(name, d)
}

let shownAt = 0
let visibleMs = 0
function leave() {
  if (shownAt) visibleMs += Date.now() - shownAt
  shownAt = 0
  if (visibleMs > 500) t('time_on_page', { seconds: Math.round(visibleMs / 1000) })
  visibleMs = 0
}

/** page_view + scroll depth + (optionally) section views for the current page. */
export function pageView(sections = true) {
  if (!on()) return
  if (shownAt) leave() // SPA navigation: close the previous page
  fired.clear()
  shownAt = Date.now()
  t('page_view', { path: location.pathname })
  if (!sections) return
  const io = new IntersectionObserver(
    (entries) =>
      entries.forEach(({ isIntersecting, target: el }) => {
        if (!isIntersecting) return
        const name = el.id || el.getAttribute('aria-labelledby')
        if (name) once('s:' + name, 'section_view', { section: name })
        if (el.id === 'commander') once('checkout', 'checkout_view', { form: 'express' })
        io.unobserve(el)
      }),
    { threshold: 0.4 },
  )
  requestAnimationFrame(() => document.querySelectorAll('section').forEach((s) => io.observe(s)))
}

let started = false
function start() {
  if (started) return
  started = true
  let ticking = false
  addEventListener(
    'scroll',
    () => {
      if (ticking) return
      ticking = true
      requestAnimationFrame(() => {
        ticking = false
        const h = document.documentElement.scrollHeight - innerHeight
        const pct = h > 0 ? (scrollY / h) * 100 : 100
        for (const p of [25, 50, 75, 100]) if (pct >= p - 1) once('p' + p, 'scroll_depth', { pct: p })
      })
    },
    { passive: true },
  )
  addEventListener(
    'click',
    (e) => {
      const id = (e.target as Element | null)?.closest?.('[data-track]')?.getAttribute('data-track')
      if (!id) return
      t('click', { id })
      if (id.startsWith('whatsapp')) t('whatsapp_click', { id })
    },
    true,
  )
  setInterval(flush, 5000)
  const bye = () => (leave(), flush())
  addEventListener('visibilitychange', () => (document.visibilityState === 'hidden' ? bye() : (shownAt = Date.now())))
  addEventListener('pagehide', bye)
}

/** Sent with the order (database only): the visit that placed it. Empty when tracking is off. */
export function orderTrackingFields(): Record<string, string> {
  if (!on()) return {}
  const s = session()
  const f: Record<string, string> = { visitorId: visitor(), sessionId: s.id }
  UTM.forEach((n) => {
    const v = String(s.ctx['utm_' + n.toLowerCase()] ?? '').slice(0, 100)
    if (v) f['utm' + n] = v
  })
  return f
}
