import { adminApi } from '../../lib/adminApi'

/*
 * Instant navigation: each admin page's code chunk and first data requests, by route.
 * - every chunk is downloaded once the browser is idle after login (clicking never waits for code);
 * - a route's requests start on hover / touch / focus of a link and on every navigation, in parallel with the
 *   code (the page's own identical requests share them — see query.ts).
 * The requests here must be exactly the ones each page makes first (same arguments → same cache key).
 */

export const PAGES = {
  dashboard: () => import('./Dashboard'),
  orders: () => import('./Orders'),
  orderDetail: () => import('./OrderDetail'),
  customers: () => import('./Customers'),
  customerDetail: () => import('./CustomerDetail'),
  followUps: () => import('./FollowUps'),
  delivery: () => import('./Delivery'),
  stock: () => import('./Stock'),
  purchasing: () => import('./Purchasing'),
  purchaseOrder: () => import('./PurchaseOrderDetail'),
  finance: () => import('./Finance'),
  reports: () => import('./Reports'),
  account: () => import('./Account'),
}

type Prefetchable = { prefetch: () => void }

/** Chunk + first requests for a route (pathname under /admin, optional ?search). */
function plan(pathname: string, search = ''): { chunk?: () => Promise<unknown>; queries: Prefetchable[] } {
  const parts = pathname.replace(/^\/admin\/?/, '').split('/').filter(Boolean)
  const q = new URLSearchParams(search)
  const owner = isOwner
  switch (parts[0] ?? 'dashboard') {
    case 'dashboard':
      return { chunk: PAGES.dashboard, queries: [adminApi.dashboard()] }
    case 'inbox':
      return { queries: [adminApi.conversations('all'), ...(q.get('phone') ? [adminApi.thread(q.get('phone')!)] : [])] }
    case 'orders':
      return parts[1]
        ? { chunk: PAGES.orderDetail, queries: [adminApi.getOrder(decodeURIComponent(parts[1])), adminApi.carriers()] }
        : { chunk: PAGES.orders, queries: [adminApi.orders({ sort: 'created_at', dir: 'desc' }), adminApi.carriers()] }
    case 'customers':
      return parts[1]
        ? { chunk: PAGES.customerDetail, queries: [adminApi.customer(parts[1]), adminApi.team()] }
        : { chunk: PAGES.customers, queries: [adminApi.customers({ sort: 'last_order', dir: 'desc' })] }
    case 'follow-ups':
      return { chunk: PAGES.followUps, queries: [adminApi.tasks('today'), adminApi.taskCounts(), adminApi.team()] }
    case 'delivery':
      return { chunk: PAGES.delivery, queries: q.get('tab') ? [] : [adminApi.board('confirmed'), adminApi.carriers()] }
    case 'stock':
      return { chunk: PAGES.stock, queries: [adminApi.stock(), adminApi.stockMovements()] }
    case 'purchasing':
      return parts[1]
        ? { chunk: PAGES.purchaseOrder, queries: owner ? [adminApi.getPO(Number(parts[1]))] : [] }
        : {
            chunk: PAGES.purchasing,
            queries: owner ? [adminApi.purchaseOrders({ status: undefined, offset: 0 }), adminApi.purchasingSummary(), adminApi.suppliers()] : [],
          }
    case 'finance':
      return {
        chunk: PAGES.finance,
        queries: !owner
          ? []
          : q.get('tab') === 'expenses'
            ? [adminApi.expenses({ preset: 'month' }, 0, undefined), adminApi.expenseCategories(true)]
            : [adminApi.financeReport({ preset: 'month' })],
      }
    case 'reports': {
      const tab = q.get('tab') ?? 'sales'
      const month = new Date().toLocaleDateString('en-CA', { timeZone: 'Africa/Casablanca' }).slice(0, 7)
      return {
        chunk: PAGES.reports,
        queries: !owner
          ? []
          : tab === 'closing'
            ? [adminApi.closing(month)]
            : ['sales', 'stock', 'delivery', 'margin'].includes(tab)
              ? [adminApi.report(tab as 'sales', { preset: 'month' })]
              : [],
      }
    }
    case 'plus':
      return { chunk: PAGES.account, queries: [] }
    default:
      return { queries: [] }
  }
}

let isOwner = false
/** Owner-only requests are never prefetched for agents (they would only get 403s). */
export function setPreloadRole(owner: boolean) {
  isOwner = owner
}

/** Start a route's code and data (hover, touch, focus, navigation). Safe to call often: deduplicated. */
export function preloadRoute(to: string) {
  const [pathname, search = ''] = to.split('?')
  const p = plan(pathname, search)
  p.chunk?.().catch(() => undefined)
  p.queries.forEach((x) => x.prefetch())
}

let chunksStarted = false
/** Download every page's code once the browser is idle (after login). */
export function preloadAllChunks() {
  if (chunksStarted) return
  chunksStarted = true
  const run = () => Object.values(PAGES).forEach((load) => load().catch(() => undefined))
  const idle = (window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }).requestIdleCallback
  if (idle) idle(run, { timeout: 2000 })
  else window.setTimeout(run, 300)
}
