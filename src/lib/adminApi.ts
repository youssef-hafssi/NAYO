/*
 * Admin inbox API client. Calls go to /bot-api/admin/* on the website's own origin (forwarded to the bot by
 * vercel.json / the Vite dev proxy), so the HttpOnly session cookie is first-party in every browser.
 */

const BASE = '/bot-api/admin'

export class Unauthorized extends Error {}
/** Any non-2xx answer: `status` lets the UI react to 409 (stock) or 403 (owner only). */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

export type Status =
  | 'new'
  | 'awaiting_details'
  | 'confirmed'
  | 'shipped'
  | 'delivered'
  | 'returned'
  | 'cancelled'
  | 'needs_human'
  | ''
export type SettableStatus = 'confirmed' | 'shipped' | 'delivered' | 'returned' | 'cancelled' | 'needs_human'
export type Role = 'owner' | 'agent'
export type Me = { name: string; email: string; role: Role; online: number }
export type Filter = 'all' | 'needs_human' | 'confirmed' | 'cancelled'

export type ConversationItem = {
  phone: string
  name: string
  order_number: string | null
  status: Status
  last_message: string
  last_role: 'client' | 'bot' | 'agent'
  last_at: number
  unread: number
  taken_over_by: string | null
}

export type Message = { role: 'client' | 'bot' | 'agent'; text: string; at: number; agent_name: string | null }

export type Order = {
  order_number: string
  status: Status
  name: string
  phone: string
  quantity: number
  unit_price: number
  shipping: number
  total: number
  city: string
  address: string
  created_at: string
}

export type FullOrder = Order & {
  carrier: string
  tracking: string
  delivered_at: string
  return_reason: string
  source: string
  internal_note: string
  notes: string
  updated_at: string
  whatsapp_from: string
  shipped_at: string
}

export type StockMovement = {
  id: number
  at: string
  delta: number
  reason: string
  order_number: string | null
  admin_name: string | null
  note: string
  balance_after: number
  written_off: number
  unit_cost_cents?: number // owner only
  avg_cost_cents_after?: number // owner only
}

export type StockSummary = {
  tracking: boolean
  ledger_start: string | null
  on_hand: number
  low_threshold: number
  low: boolean
  out: boolean
  sold_14d: number
  days_of_stock: number | null
  avg_cost_cents?: number // owner only
  stock_value_cents?: number // owner only
}
export type AuditEntry = { at: number; admin_name: string; action: string; details: string }
export type OrderEdit = Partial<{
  name: string
  phone: string
  city: string
  address: string
  quantity: number
  carrier: string
  tracking: string
  internal_note: string
}>

export type Thread = {
  conversation: {
    phone: string
    taken_over_by: string | null
    internal_notes: string
    window_open: boolean
    window_expires_at: number | null
  }
  order: Order | null
  messages: Message[]
}

async function call<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(BASE + path, {
    method: init?.method ?? 'GET',
    credentials: 'same-origin',
    headers: init?.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  })
  if (res.status === 401 && path !== '/login') throw new Unauthorized()
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiError((data as { detail?: string }).detail || `Erreur ${res.status}`, res.status)
  return data as T
}

export const adminApi = {
  login: (email: string, password: string) =>
    call<{ name: string; email: string }>('/login', { method: 'POST', body: { email, password } }),
  logout: () => call('/logout', { method: 'POST' }),
  me: () => call<Me>('/me'),
  changePassword: (current: string, next: string) =>
    call('/me/password', { method: 'POST', body: { current, new: next } }),
  getOrder: (n: string) =>
    call<{ order: FullOrder; history: AuditEntry[]; last_modified: AuditEntry | null; stock_movements: StockMovement[] }>(
      `/orders/${encodeURIComponent(n)}`,
    ),
  editOrder: (n: string, edit: OrderEdit & { force?: boolean }) =>
    call<{ order: FullOrder; changed: string[] }>(`/orders/${encodeURIComponent(n)}`, { method: 'PATCH', body: edit }),
  conversations: (filter: Filter) =>
    call<{ items: ConversationItem[]; online: number }>(`/conversations?filter=${filter}`),
  thread: (phone: string) => call<Thread>(`/conversations/${phone}/messages`),
  send: (phone: string, text: string) => call(`/conversations/${phone}/send`, { method: 'POST', body: { text } }),
  takeover: (phone: string) => call(`/conversations/${phone}/takeover`, { method: 'POST' }),
  release: (phone: string) => call(`/conversations/${phone}/release`, { method: 'POST' }),
  notes: (phone: string, notes: string) => call(`/conversations/${phone}/notes`, { method: 'POST', body: { notes } }),
  setStatus: (
    orderNumber: string,
    status: SettableStatus,
    extra?: { return_reason?: string; force?: boolean; recoverable?: boolean },
  ) => call(`/order/${encodeURIComponent(orderNumber)}/status`, { method: 'POST', body: { status, ...extra } }),
  stock: () => call<StockSummary>('/stock'),
  stockMovements: (cursor?: number | null) =>
    call<{ items: StockMovement[]; next_cursor: number | null }>(`/stock/movements?limit=50${cursor ? `&cursor=${cursor}` : ''}`),
  stockOpening: (quantity: number, unit_cost: number) =>
    call<StockSummary>('/stock/opening', { method: 'POST', body: { quantity, unit_cost } }),
  stockRestock: (quantity: number, unit_cost: number, note: string) =>
    call<StockSummary>('/stock/restock', { method: 'POST', body: { quantity, unit_cost, note } }),
  stockAdjust: (new_quantity: number, note: string) =>
    call<StockSummary>('/stock/adjust', { method: 'POST', body: { new_quantity, note } }),
  stockThreshold: (value: number) => call<StockSummary>('/stock/threshold', { method: 'POST', body: { value } }),
}
