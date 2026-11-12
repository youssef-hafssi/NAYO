import { NavLink, Outlet } from 'react-router-dom'
import { MessageSquare, MoreHorizontal, Package, type LucideIcon } from 'lucide-react'
import { useAuth } from './AdminApp'
import { WINE } from './ui'

/*
 * Admin shell: a narrow icon rail on the left from 768px, a bottom tab bar on phones.
 * Pages are added to NAV as each phase ships (Tableau de bord, Inbox, Commandes, Clients, Stock, Plus).
 */

type NavItem = { to: string; label: string; icon: LucideIcon; ownerOnly?: boolean; badge?: number }

export const NAV: NavItem[] = [
  { to: '/admin/inbox', label: 'Inbox', icon: MessageSquare },
  { to: '/admin/stock', label: 'Stock', icon: Package },
  { to: '/admin/plus', label: 'Plus', icon: MoreHorizontal },
]

export default function Layout() {
  const { me } = useAuth()
  const items = NAV.filter((i) => !i.ownerOnly || me.role === 'owner')

  return (
    <div className="flex h-[100dvh] flex-col bg-white text-[#1a1a1a] md:flex-row">
      {/* Desktop / tablet: icon rail */}
      <nav aria-label="Navigation" className="hidden w-76 shrink-0 flex-col items-center gap-4 border-r border-[#e8e8e8] bg-[#fbf8f6] py-12 md:flex">
        <span className="mb-10 font-serif fs-15 font-semibold tracking-[0.18em]" style={{ color: WINE }}>
          N
        </span>
        {items.map((i) => (
          <NavLink
            key={i.to}
            to={i.to}
            className={({ isActive }) =>
              `relative flex w-64 flex-col items-center gap-3 r-10 py-8 fs-10.5 font-semibold transition-colors ${
                isActive ? 'bg-[#f1e3e5] text-[#3a0a10]' : 'text-[#6b6b6b] hover:bg-[#f3eeeb]'
              }`
            }
          >
            <i.icon className="size-20" strokeWidth={1.8} aria-hidden />
            {i.label}
            {i.badge ? (
              <span className="absolute right-8 top-4 grid h-16 min-w-16 place-items-center rounded-pill bg-[#d93b54] px-4 fs-10 font-bold text-white">
                {i.badge}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>

      <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>

      {/* Phones: bottom tab bar */}
      <nav aria-label="Navigation" className="flex h-58 shrink-0 border-t border-[#e8e8e8] bg-white md:hidden">
        {items.map((i) => (
          <NavLink
            key={i.to}
            to={i.to}
            className={({ isActive }) =>
              `relative flex min-w-0 flex-1 flex-col items-center justify-center gap-2 fs-10.5 font-semibold ${
                isActive ? 'text-[#3a0a10]' : 'text-[#8a8a8a]'
              }`
            }
          >
            <i.icon className="size-22" strokeWidth={1.8} aria-hidden />
            <span className="truncate">{i.label}</span>
            {i.badge ? (
              <span className="absolute right-[22%] top-6 grid h-16 min-w-16 place-items-center rounded-pill bg-[#d93b54] px-4 fs-10 font-bold text-white">
                {i.badge}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
