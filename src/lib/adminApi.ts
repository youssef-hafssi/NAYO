/*
 * Admin inbox API client. Calls go to /bot-api/admin/* on the website's own origin (forwarded to the bot by
 * vercel.json / the Vite dev proxy), so the HttpOnly session cookie is first-party in every browser.
 */

const BASE = '/bot-api/admin'

export class Unauthorized extends Error {}

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
  if (!res.ok) throw new Error((data as { detail?: string }).detail || `Erreur ${res.status}`)
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
    call<{ order: FullOrder; history: AuditEntry[]; last_modified: AuditEntry | null }>(`/orders/${encodeURIComponent(n)}`),
  editOrder: (n: string, edit: OrderEdit) =>
    call<{ order: FullOrder; changed: string[] }>(`/orders/${encodeURIComponent(n)}`, { method: 'PATCH', body: edit }),
  conversations: (filter: Filter) =>
    call<{ items: ConversationItem[]; online: number }>(`/conversations?filter=${filter}`),
  thread: (phone: string) => call<Thread>(`/conversations/${phone}/messages`),
  send: (phone: string, text: string) => call(`/conversations/${phone}/send`, { method: 'POST', body: { text } }),
  takeover: (phone: string) => call(`/conversations/${phone}/takeover`, { method: 'POST' }),
  release: (phone: string) => call(`/conversations/${phone}/release`, { method: 'POST' }),
  notes: (phone: string, notes: string) => call(`/conversations/${phone}/notes`, { method: 'POST', body: { notes } }),
  setStatus: (orderNumber: string, status: SettableStatus, extra?: { return_reason?: string }) =>
    call(`/order/${encodeURIComponent(orderNumber)}/status`, { method: 'POST', body: { status, ...extra } }),
}
