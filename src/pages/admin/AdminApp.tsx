import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useLayoutEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { adminApi, type Me } from '../../lib/adminApi'
import Layout from './Layout'
import Login from './Login'
import Inbox from './Inbox'

const OrderDetail = lazy(() => import('./OrderDetail'))
const Account = lazy(() => import('./Account'))

/*
 * /admin — team back-office. Login first, then nested pages inside the shared layout (sidebar on desktop,
 * bottom tab bar on phones). The role ('owner' | 'agent') only hides UI: the server enforces every rule.
 */

type Auth = { me: Me; refresh: () => void; logout: () => void }
const AuthContext = createContext<Auth | null>(null)

export function useAuth(): Auth {
  const auth = useContext(AuthContext)
  if (!auth) throw new Error('useAuth outside AdminApp')
  return auth
}

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
        setMe(m)
        setState('in')
      })
      .catch(() => setState('login'))
  }, [])

  useEffect(refresh, [refresh])

  const logout = useCallback(() => {
    setMe(null)
    setState('login')
  }, [])

  if (state === 'checking') return <div className="min-h-screen bg-[#f8f4f1]" />
  if (state === 'login' || !me) return <Login onDone={refresh} />

  return (
    <AuthContext.Provider value={{ me, refresh, logout }}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="inbox" replace />} />
          <Route path="inbox" element={<Inbox onLogout={logout} />} />
          <Route
            path="orders/:number"
            element={
              <Suspense fallback={null}>
                <OrderDetail />
              </Suspense>
            }
          />
          <Route
            path="plus"
            element={
              <Suspense fallback={null}>
                <Account />
              </Suspense>
            }
          />
          <Route path="*" element={<Navigate to="inbox" replace />} />
        </Route>
      </Routes>
    </AuthContext.Provider>
  )
}
