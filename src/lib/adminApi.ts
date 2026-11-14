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
  carrier_id: string
  cod_status: string
  carrier_fee_cents?: string // owner only
  cod_amount_cents?: string // owner only
  remittance_id?: string // owner only
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

export type Carrier = {
  id: number
  name: string
  phone: string
  active: boolean
  fee_delivered_cents?: number // owner only
  fee_returned_cents?: number // owner only
  remit_delay_days?: number // owner only
}
export type BoardStatus = 'confirmed' | 'shipped' | 'delivered' | 'returned'
export type BoardOrder = {
  order_number: string
  created_at: string
  name: string
  phone: string
  city: string
  address: string
  quantity: string
  total: string
  status: Status
  carrier_id: string
  carrier: string
  tracking: string
  shipped_at: string
  delivered_at: string
  return_reason: string
  cod_status: string
  carrier_fee_cents?: string
}
export type Slip = { order_number: string; name: string; phone: string; city: string; address: string; quantity: string; total: string; carrier: string; tracking: string }
export type CodCarrier = {
  carrier_id: number
  name: string
  orders: number
  expected_cents: number
  oldest_delivered_at: string | null
  oldest_age_days: number | null
  late: boolean
}
export type CodPending = { order_number: string; name: string; city: string; delivered_at: string; total_cents: number; fee_cents: number; net_cents: number; late: boolean }
export type Remittance = {
  id: number
  carrier_id: number
  carrier_name: string
  at: string
  amount_received_cents: number
  expected_cents: number
  difference_cents: number
  orders: number
  note: string
  admin_name: string
}
export type ReturnRow = {
  order_number: string
  name: string
  city: string
  quantity: number
  total: number
  return_reason: string
  at: string
  carrier: string
  fee_cents: number
  written_off_cents: number
  loss_cents: number
}
export type CarrierInput = { name: string; phone?: string; fee_delivered?: number; fee_returned?: number; remit_delay_days?: number; active?: boolean }

export type ExpenseCategory = { id: number; name: string; active: boolean }
export type Expense = {
  id: number
  date: string
  category: string
  amount_cents: number
  supplier_id: number | null
  campaign: string
  note: string
  recurring_monthly: boolean
  recurring_parent_id: number | null
  created_at: string
  created_by: string
}
export type ExpenseInput = {
  date: string
  category: string
  amount: number
  supplier_id?: number | null
  campaign?: string
  note?: string
  recurring_monthly?: boolean
}
export type Period = { preset?: 'today' | 'week' | 'month'; frm?: string; to?: string }
export type FinanceReport = {
  from: string
  to: string
  ledger_start: string | null
  pnl: {
    revenue_cents: number
    cogs_cents: number
    carrier_fees_cents: number
    gross_margin_cents: number
    expenses_cents: number
    write_offs_cents: number
    net_profit_cents: number
    return_cost_cents: number
  }
  counts: { delivered: number; returned: number; units_delivered: number; units_lost: number; orders_without_cost: number; confirmed_created: number }
  expenses_by_category: { category: string; amount_cents: number }[]
  marketing: { ad_spend_cents: number; cpa_cents: number | null; roas: number | null; campaigns: { campaign: string; spend_cents: number }[] }
  unit_economics: {
    avg_revenue_cents: number | null
    avg_cogs_cents: number | null
    avg_carrier_fee_cents: number | null
    cpa_cents: number | null
    profit_per_order_cents: number | null
    fixed_monthly_cents: number
    break_even_orders_per_month: number | null
  }
  cash: {
    in_cents: number
    out_expenses_cents: number
    out_suppliers_cents: number
    net_cents: number
    days: { date: string; in_cents: number; out_cents: number; balance_cents: number }[]
    to_collect_cents: number
    to_pay_cents: number
  }
}

export const periodQuery = (p: Period) =>
  p.preset ? `preset=${p.preset}` : `frm=${encodeURIComponent(p.frm ?? '')}&to=${encodeURIComponent(p.to ?? '')}`

export type OrderCustomer = { orders_count: number; returned: number; cancelled: number; segment: Segment; opted_out: boolean; tags: string[] }
export type OrderRow = {
  order_number: string
  created_at: string
  name: string
  phone: string
  city: string
  quantity: string
  total: string
  status: Status
  carrier: string
  carrier_id: string
  source: string
  delivered_at: string
  cod_status: string
  tracking: string
  returns_count: number
  opted_out: boolean
}
export type OrderFilters = {
  q?: string
  status?: string[]
  frm?: string
  to?: string
  city?: string
  carrier_id?: string
  source?: string
  sort?: string
  dir?: 'asc' | 'desc'
}
export type Segment = 'new' | 'loyal' | 'at_risk' | 'inactive'
export type Customer = {
  phone: string
  name: string
  city: string
  address: string
  tags: string[]
  internal_note: string
  opted_out: boolean
  orders_count: number
  delivered: number
  delivered_cents?: number // owner only
  returned: number
  cancelled: number
  last_order: string
  segment: Segment
}
export type CustomerOrder = {
  order_number: string
  created_at: string
  quantity: string
  total: string
  status: Status
  city: string
  carrier: string
  delivered_at: string
  return_reason: string
  source: string
}
export type Task = {
  id: number
  created_at: string
  due_at: string
  done_at: string
  customer_phone: string
  order_number: string
  title: string
  assigned_to: string
  created_by: string
  suggestion_key: string | null
  dismissed: boolean
}
export type Suggestion = { key: string; kind: string; title: string; customer_phone: string; order_number: string; since: string }
export type TaskView = 'today' | 'late' | 'upcoming' | 'done'
export type TaskCounts = { late: number; today: number; upcoming: number; suggestions: number; badge: number }

const qs = (o: Record<string, string | number | undefined>) =>
  Object.entries(o)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&')
const orderQs = (f: OrderFilters) =>
  qs({ q: f.q, status: f.status?.join(','), frm: f.frm, to: f.to, city: f.city, carrier_id: f.carrier_id, source: f.source, sort: f.sort, dir: f.dir })

export type Rate = { rate: number | null }
export type Dashboard = {
  generated_at: string
  orders: { today: number; week: number; month: number }
  confirmation_rate: Rate & { confirmed: number; decided: number }
  delivery_rate: Rate & { delivered: number; returned: number }
  units_month: number
  needs_human: number
  in_progress: { orders: number }
  chart: { date: string; orders: number; delivered: number; revenue_cents?: number }[]
  top_cities: { city: string; orders: number }[]
  stock?: { tracking: boolean; on_hand: number; low: boolean; out: boolean; days_of_stock: number | null; low_threshold: number; value_cents?: number }
  follow_ups?: { late: number; today: number; suggestions: number }
  money?: {
    revenue_month_cents: number
    net_profit_month_cents: number
    avg_basket_cents: number | null
    in_progress_cents: number
    to_collect_cents: number
    to_pay_cents: number
  }
}
export type SalesReport = {
  from: string
  to: string
  days: { date: string; orders: number; confirmed: number; cancelled: number; delivered: number; units: number; revenue_cents: number }[]
  totals: { orders: number; confirmed: number; cancelled: number; decided: number; delivered: number; units: number; revenue_cents: number; avg_basket_cents: number | null; confirmation_rate: number | null }
  by_source: { source: string; orders: number; confirmed: number }[]
  by_city: { city: string; delivered: number; revenue_cents: number }[]
}
type StockDay = { date: string; on_hand: number; avg_cost_cents: number; value_cents: number }
export type StockReport = {
  from: string
  to: string
  opening: Omit<StockDay, 'date'>
  closing: StockDay
  days: StockDay[]
  units_in: number
  units_out: number
  units_lost: number
  by_reason: { reason: string; movements: number; units: number }[]
  ledger_start: string | null
}
type DeliveryGroup = { delivered: number; returned: number; return_rate: number | null; avg_delay_days: number | null }
export type DeliveryReport = {
  from: string
  to: string
  delivered: number
  returned: number
  return_rate: number | null
  avg_delay_days: number | null
  median_delay_days: number | null
  by_carrier: (DeliveryGroup & { carrier: string })[]
  by_city: (DeliveryGroup & { city: string })[]
}
type MarginRow = {
  delivered: number
  revenue_cents: number
  cogs_cents: number
  carrier_fees_cents: number
  gross_margin_cents: number
  expenses_cents: number
  write_offs_cents: number
  net_profit_cents: number
}
export type MarginReport = { from: string; to: string; days: (MarginRow & { date: string })[]; totals: MarginRow }
export type ClosingReport = {
  month: string
  from: string
  to: string
  complete: boolean
  generated_at: string
  orders: { created: number; by_status: Record<string, number> }
  pnl: FinanceReport['pnl']
  counts: FinanceReport['counts']
  expenses_by_category: FinanceReport['expenses_by_category']
  cash: { in_cents: number; out_expenses_cents: number; out_suppliers_cents: number; net_cents: number }
  stock: StockDay
  receivables_cents: number
  debts_cents: number
}
export type ReportName = 'sales' | 'stock' | 'delivery' | 'margin'
type ReportOf = { sales: SalesReport; stock: StockReport; delivery: DeliveryReport; margin: MarginReport }

export type Supplier = { id: number; name: string; phone: string; city: string; note: string; active: boolean; created_at: string }
export type POStatus = 'draft' | 'ordered' | 'partially_received' | 'received' | 'cancelled'
export type PurchaseOrder = {
  id: number
  number: string
  supplier_id: number
  supplier_name: string
  ordered_at: string | null
  expected_at: string | null
  status: POStatus
  quantity: number
  unit_cost_cents: number
  shipping_cost_cents: number
  other_costs_cents: number
  note: string
  created_at: string
  created_by: string
  received_qty: number
  remaining_qty: number
  paid_cents: number
  due_cents: number
  total_cents: number
  landed_unit_cost_cents: number
  payment_status: 'unpaid' | 'partial' | 'paid'
  late: boolean
}
export type Receipt = { id: number; at: string; quantity: number; landed_unit_cost_cents: number; admin_name: string }
export type SupplierPayment = { id: number; at: string; amount_cents: number; method: string; note: string; admin_name: string }
export type POInput = {
  supplier_id: number
  quantity: number
  unit_cost: number
  shipping_cost?: number
  other_costs?: number
  ordered_at?: string | null
  expected_at?: string | null
  note?: string
  status?: 'draft' | 'ordered'
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
    opted_out?: boolean
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
    call<{
      order: FullOrder
      history: AuditEntry[]
      last_modified: AuditEntry | null
      stock_movements: StockMovement[]
      thread: Message[]
      customer: OrderCustomer | null
    }>(
      `/orders/${encodeURIComponent(n)}`,
    ),
  editOrder: (n: string, edit: OrderEdit & { force?: boolean; carrier_id?: number; carrier_fee?: number }) =>
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
  expenseCategories: (includeInactive = false) =>
    call<{ items: ExpenseCategory[] }>(`/expense-categories${includeInactive ? '?include_inactive=true' : ''}`),
  addCategory: (name: string) => call<ExpenseCategory>('/expense-categories', { method: 'POST', body: { name } }),
  editCategory: (id: number, b: { name?: string; active?: boolean }) =>
    call<ExpenseCategory>(`/expense-categories/${id}`, { method: 'PATCH', body: b }),
  expenses: (p: Period, offset = 0, category?: string) =>
    call<{ items: Expense[]; has_more: boolean; total_cents: number }>(
      `/expenses?${periodQuery(p)}&limit=50&offset=${offset}${category ? `&category=${encodeURIComponent(category)}` : ''}`,
    ),
  addExpense: (b: ExpenseInput) => call<Expense>('/expenses', { method: 'POST', body: b }),
  editExpense: (id: number, b: Partial<ExpenseInput>) => call<Expense>(`/expenses/${id}`, { method: 'PATCH', body: b }),
  deleteExpense: (id: number) => call(`/expenses/${id}`, { method: 'DELETE' }),
  financeReport: (p: Period) => call<FinanceReport>(`/finance/report?${periodQuery(p)}`),
  financeExportUrl: (p: Period) => `/bot-api/admin/finance/export?${periodQuery(p)}`,
  orders: (f: OrderFilters, offset = 0) =>
    call<{ items: OrderRow[]; has_more: boolean; counts: Record<Status, number>; cities?: string[] }>(
      `/orders?${orderQs(f)}&limit=50&offset=${offset}`,
    ),
  ordersCsvUrl: (f: OrderFilters) => `/bot-api/admin/orders.csv?${orderQs(f)}`,
  ordersBulk: (b: { order_numbers: string[]; status?: SettableStatus; carrier_id?: number; return_reason?: string }) =>
    call<{ done: string[]; errors: Record<string, string> }>('/orders/bulk', { method: 'POST', body: b }),
  customers: (f: { q?: string; segment?: string; tag?: string; sort?: string; dir?: string }, offset = 0) =>
    call<{ items: Customer[]; has_more: boolean; counts: Record<Segment, number> }>(`/customers?${qs(f)}&limit=50&offset=${offset}`),
  customersCsvUrl: (f: { q?: string; segment?: string; tag?: string }) => `/bot-api/admin/customers.csv?${qs(f)}`,
  customer: (phone: string) =>
    call<{ customer: Customer; orders: CustomerOrder[]; tasks: Task[]; window_open: boolean }>(`/customers/${encodeURIComponent(phone)}`),
  editCustomer: (phone: string, b: { name?: string; city?: string; address?: string; tags?: string[]; internal_note?: string; opted_out?: boolean }) =>
    call<{ customer: Customer }>(`/customers/${encodeURIComponent(phone)}`, { method: 'PATCH', body: b }),
  newCustomerOrder: (phone: string, quantity: number) =>
    call<{ order_number: string }>(`/customers/${encodeURIComponent(phone)}/orders`, { method: 'POST', body: { quantity } }),
  tasks: (view: TaskView, offset = 0) =>
    call<{ items: Task[]; has_more: boolean; suggestions?: Suggestion[] }>(`/tasks?view=${view}&limit=50&offset=${offset}`),
  taskCounts: () => call<TaskCounts>('/tasks/counts'),
  addTask: (b: { title?: string; due_at?: string; customer_phone?: string; order_number?: string; assigned_to?: string; suggestion_key?: string }) =>
    call<Task>('/tasks', { method: 'POST', body: b }),
  dismissSuggestion: (key: string) => call('/tasks/dismiss', { method: 'POST', body: { key } }),
  editTask: (id: number, b: { done?: boolean; due_at?: string; title?: string; assigned_to?: string }) =>
    call<Task>(`/tasks/${id}`, { method: 'PATCH', body: b }),
  team: () => call<{ names: string[] }>('/team'),
  dashboard: () => call<Dashboard>('/dashboard'),
  report: <N extends ReportName>(name: N, p: Period) => call<ReportOf[N]>(`/reports/${name}?${periodQuery(p)}`),
  reportCsvUrl: (name: ReportName, p: Period) => `/bot-api/admin/reports/${name}.csv?${periodQuery(p)}`,
  closing: (month: string) => call<ClosingReport>(`/reports/closing?month=${encodeURIComponent(month)}`),
  closingCsvUrl: (month: string) => `/bot-api/admin/reports/closing.csv?month=${encodeURIComponent(month)}`,
  carriers: (includeInactive = false) => call<{ items: Carrier[] }>(`/carriers${includeInactive ? '?include_inactive=true' : ''}`),
  createCarrier: (b: CarrierInput) => call<Carrier>('/carriers', { method: 'POST', body: b }),
  editCarrier: (id: number, b: Partial<CarrierInput>) => call<Carrier>(`/carriers/${id}`, { method: 'PATCH', body: b }),
  board: (status: BoardStatus, offset = 0, carrierId?: number) =>
    call<{ items: BoardOrder[]; has_more: boolean; counts: Record<string, number> }>(
      `/delivery?status=${status}&limit=50&offset=${offset}${carrierId !== undefined ? `&carrier_id=${carrierId}` : ''}`,
    ),
  bulkDelivery: (b: { order_numbers: string[]; carrier_id?: number; status?: 'shipped' | 'delivered' | 'returned'; return_reason?: string; recoverable?: boolean }) =>
    call<{ done: string[]; errors: Record<string, string> }>('/delivery/bulk', { method: 'POST', body: b }),
  slips: (numbers: string[]) =>
    call<{ items: Slip[]; company: { name: string; address: string; phone: string } }>(`/delivery/slips?numbers=${encodeURIComponent(numbers.join(','))}`),
  codSummary: () => call<{ carriers: CodCarrier[]; total_cents: number; late_carriers: number }>('/cod/summary'),
  codPending: (carrierId: number) => call<{ items: CodPending[] }>(`/cod/pending?carrier_id=${carrierId}`),
  remit: (b: { carrier_id: number; order_numbers: string[]; amount_received: number; note?: string }) =>
    call<{ id: number; expected_cents: number; amount_received_cents: number; difference_cents: number; orders: number }>('/remittances', {
      method: 'POST',
      body: b,
    }),
  remittances: (offset = 0) => call<{ items: Remittance[]; has_more: boolean }>(`/remittances?limit=50&offset=${offset}`),
  returns: (offset = 0) => call<{ items: ReturnRow[]; has_more: boolean }>(`/returns?limit=50&offset=${offset}`),
  suppliers: (includeInactive = false) =>
    call<{ items: Supplier[] }>(`/suppliers${includeInactive ? '?include_inactive=true' : ''}`),
  createSupplier: (b: { name: string; phone?: string; city?: string; note?: string }) =>
    call<Supplier>('/suppliers', { method: 'POST', body: b }),
  editSupplier: (id: number, b: Partial<Omit<Supplier, 'id' | 'created_at'>>) =>
    call<Supplier>(`/suppliers/${id}`, { method: 'PATCH', body: b }),
  purchasingSummary: () => call<{ debts_cents: number; open: number; late: number }>('/purchasing/summary'),
  purchaseOrders: (q: { status?: string; supplier_id?: number; late?: boolean; offset?: number }) => {
    const p = new URLSearchParams({ limit: '50', offset: String(q.offset ?? 0) })
    if (q.status) p.set('status', q.status)
    if (q.supplier_id) p.set('supplier_id', String(q.supplier_id))
    if (q.late) p.set('late', 'true')
    return call<{ items: PurchaseOrder[]; has_more: boolean }>(`/purchase-orders?${p}`)
  },
  createPO: (b: POInput) => call<PurchaseOrder>('/purchase-orders', { method: 'POST', body: b }),
  getPO: (id: number) =>
    call<{ po: PurchaseOrder; receipts: Receipt[]; payments: SupplierPayment[]; supplier: Supplier | null }>(`/purchase-orders/${id}`),
  editPO: (id: number, b: Partial<POInput>) => call<PurchaseOrder>(`/purchase-orders/${id}`, { method: 'PATCH', body: b }),
  setPOStatus: (id: number, status: 'ordered' | 'cancelled') =>
    call<PurchaseOrder>(`/purchase-orders/${id}/status`, { method: 'POST', body: { status } }),
  receivePO: (id: number, quantity: number, note = '') =>
    call<{ po: PurchaseOrder; landed_unit_cost_cents: number; on_hand: number }>(`/purchase-orders/${id}/receive`, {
      method: 'POST',
      body: { quantity, note },
    }),
  payPO: (id: number, amount: number, method: string, note = '', at?: string) =>
    call<PurchaseOrder>(`/purchase-orders/${id}/payments`, { method: 'POST', body: { amount, method, note, ...(at ? { at } : {}) } }),
  stockThreshold: (value: number) => call<StockSummary>('/stock/threshold', { method: 'POST', body: { value } }),
}
