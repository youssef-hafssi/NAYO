import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useLayoutEffect, useState, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { adminApi, isSuperadmin, type Me } from '../../lib/adminApi'
import { clearCache } from '../../lib/query'
import Layout from './Layout'
import Login from './Login'
import Inbox from './Inbox'
import { PAGES, preloadAllChunks, setPreloadRole } from './preload'
import { PageSkeleton } from './ui'

const Dashboard = lazy(PAGES.dashboard)
const Orders = lazy(PAGES.orders)
const OrderDetail = lazy(PAGES.orderDetail)
const Customers = lazy(PAGES.customers)
const CustomerDetail = lazy(PAGES.customerDetail)
const FollowUps = lazy(PAGES.followUps)
const Delivery = lazy(PAGES.delivery)
const Stock = lazy(PAGES.stock)
const Purchasing = lazy(PAGES.purchasing)
const PurchaseOrderDetail = lazy(PAGES.purchaseOrder)
const Finance = lazy(PAGES.finance)
const Reports = lazy(PAGES.reports)
const Account = lazy(PAGES.account)
const Team = lazy(PAGES.team)
const Settings = lazy(PAGES.settings)
const Visitors = lazy(PAGES.visitors)
const ClosingPrint = lazy(() => import('./ClosingPrint'))
const DeliveryPrint = lazy(() => import('./DeliveryPrint'))

/*
 * /admin — team back-office. Login first, then nested pages inside the shared layout (sidebar on desktop,
 * bottom tab bar on phones). The role ('superadmin' | 'owner' | 'agent') only hides UI: the server enforces every rule.
 * /me is loaded once per session (and again only after a 401 → login). Page data is cached in memory for the
 * session (src/lib/query.ts) and cleared on logout.
 */

type Auth = { me: Me; refresh: () => void; logout: () => void }
const AuthContext = createContext<Auth | null>(null)

export function useAuth(): Auth {
  const auth = useContext(AuthContext)
  if (!auth) throw new Error('useAuth outside AdminApp')
  return auth
}

/** A lazily loaded page: the layout stays, a skeleton shows until its code is there (never a blank page). */
const page = (el: ReactNode, tiles = true) => <Suspense fallback={<PageSkeleton tiles={tiles} />}>{el}</Suspense>

/** Clients / Visiteurs for a non-superadmin (menu hidden; the server answers 403 anyway). */
const Restricted = () => <div className="p-24 fs-14 text-[#8a8a8a]">Réservé au super-administrateur.</div>

export default function AdminApp() {
  const [state, setState] = useState<'checking' | 'login' | 'in'>('checking')
  const [me, setMe] = useState<Me | null>(null)

  // Fixed px layout: undo the landing page's viewport-scaled root font-size while the admin is open.
  useLayoutEffect(() => {
    const html = document.documentElement
    const prev = html.style.fontSize
    html.style.fontSize = '16px'
    document.title = 'Admin — NAYO'
    return () => {
      html.style.fontSize = prev
    }
  }, [])

  const refresh = useCallback(() => {
    adminApi
      .me()
      .then((m) => {
        setPreloadRole(m.role)
        setMe(m)
        setState('in')
        preloadAllChunks() // every page's code, once the browser is idle
      })
      .catch(() => setState('login'))
  }, [])

  useEffect(refresh, [refresh])

  const logout = useCallback(() => {
    clearCache() // the cache belongs to this session only
    setMe(null)
    setState('login')
  }, [])

  if (state === 'checking') return <div className="min-h-screen bg-[#f8f4f1]" />
  if (state === 'login' || !me) return <Login onDone={() => (clearCache(), refresh())} />

  return (
    <AuthContext.Provider value={{ me, refresh, logout }}>
      <Routes>
        <Route path="reports/closing/print" element={<Suspense fallback={null}>{<ClosingPrint />}</Suspense>} />
        <Route path="delivery/print" element={<Suspense fallback={null}>{<DeliveryPrint />}</Suspense>} />
        <Route element={<Layout />}>
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={page(<Dashboard />)} />
          <Route path="inbox" element={<Inbox onLogout={logout} />} />
          <Route path="orders" element={page(<Orders />, false)} />
          <Route path="orders/:number" element={page(<OrderDetail />, false)} />
          <Route path="customers" element={isSuperadmin(me) ? page(<Customers />, false) : <Restricted />} />
          <Route path="customers/:phone" element={isSuperadmin(me) ? page(<CustomerDetail />) : <Restricted />} />
          <Route path="visitors" element={isSuperadmin(me) ? page(<Visitors />) : <Restricted />} />
          <Route path="follow-ups" element={page(<FollowUps />, false)} />
          <Route path="delivery" element={page(<Delivery />, false)} />
          <Route path="stock" element={page(<Stock />)} />
          <Route path="purchasing" element={page(<Purchasing />)} />
          <Route path="purchasing/:id" element={page(<PurchaseOrderDetail />, false)} />
          <Route path="finance" element={page(<Finance />)} />
          <Route path="reports" element={page(<Reports />)} />
          <Route path="plus" element={page(<Account />, false)} />
          <Route path="team" element={page(<Team />, false)} />
          <Route path="settings" element={page(<Settings />, false)} />
          <Route path="*" element={<Navigate to="inbox" replace />} />
        </Route>
      </Routes>
    </AuthContext.Provider>
  )
}
