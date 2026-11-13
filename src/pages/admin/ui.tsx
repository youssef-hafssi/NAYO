import { useEffect, useRef, type ReactNode } from 'react'
import type { Filter, Status } from '../../lib/adminApi'

/* Shared admin UI: palette, status labels, small components. Moved from the original Admin.tsx. */

export const POLL_MS = 4000
export const WINE = '#3a0a10'

export const STATUS_LABEL: Record<string, string> = {
  needs_human: "Besoin d'aide",
  confirmed: 'Confirmée',
  cancelled: 'Annulée',
  new: 'Nouvelle',
  awaiting_details: 'En cours',
  shipped: 'Expédiée',
  delivered: 'Livrée',
  returned: 'Retournée',
}
export const STATUS_PILL: Record<string, string> = {
  confirmed: 'bg-[#e7f6ec] text-[#1f8a4c]',
  needs_human: 'bg-[#fdf0de] text-[#c2650a]',
  cancelled: 'bg-[#efefef] text-[#6b6b6b]',
  new: 'bg-[#eef2fb] text-[#3b5bab]',
  awaiting_details: 'bg-[#eef2fb] text-[#3b5bab]',
  shipped: 'bg-[#eaf3fb] text-[#1d6fa5]',
  delivered: 'bg-[#dff3e6] text-[#17703c]',
  returned: 'bg-[#fbe5e5] text-[#a12a2a]',
}
export const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'Tous' },
  { key: 'needs_human', label: "Besoin d'aide" },
  { key: 'confirmed', label: 'Confirmées' },
  { key: 'cancelled', label: 'Annulées' },
]

export const formatPhone = (p: string) => {
  const local = p.startsWith('212') && p.length === 12 ? '0' + p.slice(3) : p
  return local.length === 10 ? local.replace(/(\d{4})(\d{2})(\d{2})(\d{2})/, '$1 $2 $3 $4') : '+' + p
}
export const hhmm = (ts: number) =>
  new Date(ts * 1000).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
export const listTime = (ts: number) => {
  const d = new Date(ts * 1000)
  const today = new Date()
  const yesterday = new Date(Date.now() - 86400000)
  if (d.toDateString() === today.toDateString()) return hhmm(ts)
  if (d.toDateString() === yesterday.toDateString()) return 'Hier'
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })
}
export const windowLeft = (expires: number) => {
  const mins = Math.max(0, Math.floor((expires * 1000 - Date.now()) / 60000))
  return `${Math.floor(mins / 60)} h ${String(mins % 60).padStart(2, '0')}`
}

export function StatusPill({ status }: { status: Status }) {
  if (!status) return null
  return (
    <span className={`inline-block whitespace-nowrap r-5 px-8 py-2 fs-11.5 lh-16 font-semibold ${STATUS_PILL[status] ?? ''}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

export function Chip({ active, onClick, children }: { active?: boolean; onClick?: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`h-40 rounded-pill border px-14 fs-13 md:h-30 md:px-12 font-medium text-[#1a1a1a] transition-colors ${
        active ? 'border-[#1a1a1a] bg-[#e4e4e4] outline outline-1 outline-[#1a1a1a]' : 'border-[#1a1a1a] bg-[#f4f4f4] hover:bg-[#ebebeb]'
      }`}
    >
      {children}
    </button>
  )
}


/** A button that shows a busy state and can't be pressed twice while its action runs. */
export function BusyButton({
  busy,
  children,
  variant = 'primary',
  className = '',
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; variant?: 'primary' | 'secondary' | 'danger' }) {
  const styles = {
    primary: 'text-white',
    secondary: 'border border-[#d9cfca] bg-white text-[#1a1a1a] hover:bg-[#faf6f3]',
    danger: 'border border-[#e2b4b4] bg-[#fdf2f2] text-[#a12a2a] hover:bg-[#fbe8e8]',
  }[variant]
  return (
    <button
      {...rest}
      disabled={busy || rest.disabled}
      aria-busy={busy}
      className={`inline-flex h-44 items-center justify-center gap-8 r-10 px-18 fs-14 font-semibold transition-opacity disabled:cursor-not-allowed disabled:opacity-60 md:h-40 ${styles} ${className}`}
      style={variant === 'primary' ? { background: WINE, ...rest.style } : rest.style}
    >
      {busy ? 'Patientez…' : children}
    </button>
  )
}

export function FieldLabel({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="block fs-11 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">
      {children}
    </label>
  )
}

export const inputClass =
  'mt-6 h-44 w-full r-10 border border-[#ecdcd6] bg-[#fbf5f2] px-14 fs-16 outline-none focus:border-[#7a1a2a] md:h-40 md:fs-14'

export const fmtDateTime = (s: string | number) => {
  const d = typeof s === 'number' ? new Date(s * 1000) : new Date(s.replace(' ', 'T'))
  return isNaN(d.getTime())
    ? String(s)
    : d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** 123450 → "1 234,50 MAD" */
export const fmtMoney = (cents: number) =>
  `${(cents / 100).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} MAD`

export const STOCK_REASON: Record<string, string> = {
  opening: "Stock d'ouverture",
  purchase: 'Réception fournisseur',
  restock_manual: 'Réapprovisionnement',
  adjustment: 'Correction',
  order_confirmed: 'Commande confirmée',
  order_changed: 'Commande modifiée',
  order_cancelled: 'Commande annulée',
  order_returned: 'Commande retournée',
}

/**
 * Runs an admin write; on "409 Stock insuffisant" asks "Confirmer quand même ?" and re-runs it with force.
 * Returns false if the user declined.
 */
export async function withStockConfirm(run: (force: boolean) => Promise<unknown>): Promise<boolean> {
  try {
    await run(false)
    return true
  } catch (e) {
    const err = e as { status?: number; message?: string }
    if (err.status !== 409 || !/stock/i.test(err.message ?? '')) throw e
    if (!window.confirm(`${err.message}. Confirmer quand même ?`)) return false
    await run(true)
    return true
  }
}

/**
 * Calls `run` every `ms` while `enabled`: never starts a poll while the previous one is still running, and
 * pauses while the tab is hidden (one immediate refresh when it becomes visible again). `key` restarts it.
 */
export function usePolling(run: () => Promise<unknown>, ms: number, enabled: boolean, key?: unknown) {
  const runRef = useRef(run)
  runRef.current = run
  useEffect(() => {
    if (!enabled) return
    let busy = false
    const tick = () => {
      if (busy || document.hidden) return
      busy = true
      Promise.resolve()
        .then(() => runRef.current())
        .catch(() => undefined)
        .finally(() => {
          busy = false
        })
    }
    const id = window.setInterval(tick, ms)
    const onVisible = () => {
      if (!document.hidden) tick()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [ms, enabled, key])
}

export const PO_STATUS_LABEL: Record<string, string> = {
  draft: 'Brouillon',
  ordered: 'Commandée',
  partially_received: 'Reçue en partie',
  received: 'Reçue',
  cancelled: 'Annulée',
}
export const PO_STATUS_PILL: Record<string, string> = {
  draft: 'bg-[#efefef] text-[#6b6b6b]',
  ordered: 'bg-[#eaf3fb] text-[#1d6fa5]',
  partially_received: 'bg-[#fdf0de] text-[#c2650a]',
  received: 'bg-[#dff3e6] text-[#17703c]',
  cancelled: 'bg-[#fbe5e5] text-[#a12a2a]',
}
export const PAYMENT_LABEL: Record<string, string> = { unpaid: 'Non payée', partial: 'Payée en partie', paid: 'Payée' }
export const METHOD_LABEL: Record<string, string> = { cash: 'Espèces', virement: 'Virement', 'chèque': 'Chèque', autre: 'Autre' }

export function Pill({ className, children }: { className: string; children: ReactNode }) {
  return <span className={`inline-block whitespace-nowrap r-5 px-8 py-2 fs-11.5 lh-16 font-semibold ${className}`}>{children}</span>
}

/** "12,5" / "12.50" → 12.5 ; '' → 0 ; invalid → NaN */
export const parseMad = (v: string) => {
  const t = v.trim().replace(/\s/g, '').replace(',', '.')
  if (!t) return 0
  return /^\d+(\.\d{1,2})?$/.test(t) ? Number(t) : NaN
}
export const fmtDate = (s: string | null | undefined) => (s ? s.slice(0, 10).split('-').reverse().join('/') : '—')
