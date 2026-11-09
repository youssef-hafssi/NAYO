/*
 * Website → bot (POST /orders).
 * - wakeBot(): free hosts sleep; a GET /health when the checkout opens wakes the bot up early.
 * - submitOrder(): waits up to 10 s for the bot's order number; otherwise returns a fallback NAYO-W… number
 *   and keeps the order in localStorage so it is never lost.
 * - flushPendingOrders(): re-sends saved fallback orders (on the success screen and on every page load)
 *   until the bot accepts them. The bot is idempotent per clientId, so retries never create duplicates.
 */

const ENDPOINT = (import.meta.env.VITE_ORDER_ENDPOINT as string | undefined)?.trim() || ''
const API_KEY = (import.meta.env.VITE_ORDER_API_KEY as string | undefined)?.trim() || ''
const PENDING_KEY = 'nayo:pending-orders'
const SUBMIT_TIMEOUT_MS = 10_000

export type OrderPayload = {
  clientId: string
  orderNumber?: string
  name: string
  phone: string
  quantity: number
  product: string
  unitPrice: number
  subtotal: number
  shipping: number
  total: number
  currency: string
  payment: 'cash_on_delivery'
  status: 'new'
  createdAt: string
}

export type SubmitResult = { orderNumber: string; total: number; fallback: boolean }

const healthUrl = () => ENDPOINT.replace(/\/orders\/?$/, '') + '/health'

export function wakeBot() {
  if (!ENDPOINT) return
  fetch(healthUrl(), { method: 'GET', cache: 'no-store' }).catch(() => {})
}

export function newClientId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

function fallbackNumber(): string {
  const n = new Uint32Array(1)
  crypto.getRandomValues(n)
  return `NAYO-W${String(n[0] % 1_000_000).padStart(6, '0')}`
}

async function post(order: OrderPayload, timeoutMs: number): Promise<{ ok: true; orderNumber: string; total: number } | { ok: false; permanent: boolean }> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(API_KEY ? { 'X-API-Key': API_KEY } : {}) },
      body: JSON.stringify(order),
      signal: ctrl.signal,
      keepalive: false,
    })
    if (res.ok) {
      const data = (await res.json()) as { orderNumber: string; total: number }
      return { ok: true, orderNumber: data.orderNumber, total: data.total }
    }
    // Only an invalid order (422/413) is permanent. A bad API key (401), a CORS/config problem or a
    // sleeping server can be fixed later, so the order stays saved and is retried.
    if (res.status === 401) console.error('[NAYO] the bot rejected VITE_ORDER_API_KEY — check it matches ORDER_API_KEY')
    return { ok: false, permanent: res.status === 422 || res.status === 413 }
  } catch {
    return { ok: false, permanent: false }
  } finally {
    clearTimeout(timer)
  }
}

// ---- pending queue (localStorage; every access guarded — private mode can throw) ----
function readPending(): OrderPayload[] {
  try {
    const v = JSON.parse(localStorage.getItem(PENDING_KEY) || '[]')
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}
function writePending(list: OrderPayload[]) {
  try {
    if (list.length) localStorage.setItem(PENDING_KEY, JSON.stringify(list))
    else localStorage.removeItem(PENDING_KEY)
  } catch {
    /* storage unavailable: nothing more we can do client-side */
  }
}
function savePending(order: OrderPayload) {
  writePending([...readPending().filter((o) => o.clientId !== order.clientId), order])
}

export async function submitOrder(order: OrderPayload): Promise<SubmitResult> {
  if (!ENDPOINT) {
    console.warn('[NAYO] VITE_ORDER_ENDPOINT is not set — order not saved:', order)
    return { orderNumber: fallbackNumber(), total: order.total, fallback: true }
  }
  const r = await post(order, SUBMIT_TIMEOUT_MS)
  if (r.ok) return { orderNumber: r.orderNumber, total: r.total, fallback: false }
  const orderNumber = fallbackNumber()
  if (!r.permanent) savePending({ ...order, orderNumber })
  else console.error('[NAYO] order rejected by the bot:', order)
  return { orderNumber, total: order.total, fallback: true }
}

let flushing = false
export async function flushPendingOrders(): Promise<number> {
  if (!ENDPOINT || flushing) return readPending().length
  flushing = true
  try {
    for (const order of readPending()) {
      const r = await post(order, 30_000) // a sleeping free host can take ~30 s to wake up
      if (r.ok || r.permanent) writePending(readPending().filter((o) => o.clientId !== order.clientId))
    }
  } finally {
    flushing = false
  }
  return readPending().length
}

/** Retry saved orders every `everyMs` while any are left. Returns a stop function. */
export function keepFlushing(everyMs = 20_000): () => void {
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const tick = async () => {
    const left = await flushPendingOrders()
    if (!stopped && left > 0) timer = setTimeout(tick, everyMs)
  }
  if (readPending().length) tick()
  return () => {
    stopped = true
    clearTimeout(timer)
  }
}

export const hasPendingOrders = () => readPending().length > 0
