import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ArrowRight, Clock } from 'lucide-react'
import {
  adminApi,
  Unauthorized,
  type ConversationItem,
  type Filter,
  type Message,
  type Status,
  type Thread,
} from '../lib/adminApi'

/*
 * Admin inbox (/admin) — approved mockup: header, conversation list with filter chips, chat thread with
 * bot / customer / agent bubbles, 24h-window banner, "Bot actif ↔ Repris par {agent}" toggle, order panel.
 * Fixed px layout (the landing's viewport-scaled root font-size is reset to 16px while this page is open).
 * Data refreshes by polling every 4 s.
 */

const POLL_MS = 4000
const WINE = '#3a0a10'

const STATUS_LABEL: Record<string, string> = {
  needs_human: "Besoin d'aide",
  confirmed: 'Confirmée',
  cancelled: 'Annulée',
  new: 'Nouvelle',
  awaiting_details: 'En cours',
}
const STATUS_PILL: Record<string, string> = {
  confirmed: 'bg-[#e7f6ec] text-[#1f8a4c]',
  needs_human: 'bg-[#fdf0de] text-[#c2650a]',
  cancelled: 'bg-[#efefef] text-[#6b6b6b]',
  new: 'bg-[#eef2fb] text-[#3b5bab]',
  awaiting_details: 'bg-[#eef2fb] text-[#3b5bab]',
}
const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'Tous' },
  { key: 'needs_human', label: "Besoin d'aide" },
  { key: 'confirmed', label: 'Confirmées' },
  { key: 'cancelled', label: 'Annulées' },
]

const formatPhone = (p: string) => {
  const local = p.startsWith('212') && p.length === 12 ? '0' + p.slice(3) : p
  return local.length === 10 ? local.replace(/(\d{4})(\d{2})(\d{2})(\d{2})/, '$1 $2 $3 $4') : '+' + p
}
const hhmm = (ts: number) =>
  new Date(ts * 1000).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
const listTime = (ts: number) => {
  const d = new Date(ts * 1000)
  const today = new Date()
  const yesterday = new Date(Date.now() - 86400000)
  if (d.toDateString() === today.toDateString()) return hhmm(ts)
  if (d.toDateString() === yesterday.toDateString()) return 'Hier'
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })
}
const windowLeft = (expires: number) => {
  const mins = Math.max(0, Math.floor((expires * 1000 - Date.now()) / 60000))
  return `${Math.floor(mins / 60)} h ${String(mins % 60).padStart(2, '0')}`
}

function StatusPill({ status }: { status: Status }) {
  if (!status) return null
  return (
    <span className={`inline-block r-5 px-8 py-2 fs-11.5 lh-16 font-semibold ${STATUS_PILL[status] ?? ''}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

function Chip({ active, onClick, children }: { active?: boolean; onClick?: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`h-30 rounded-pill border px-12 fs-13 font-medium text-[#1a1a1a] transition-colors ${
        active ? 'border-[#1a1a1a] bg-[#e4e4e4] outline outline-1 outline-[#1a1a1a]' : 'border-[#1a1a1a] bg-[#f4f4f4] hover:bg-[#ebebeb]'
      }`}
    >
      {children}
    </button>
  )
}

// ------------------------------------------------------------------ login
function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await adminApi.login(email, password)
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connexion impossible.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="grid min-h-screen place-items-center bg-[#f8f4f1] px-16">
      <form onSubmit={submit} className="w-full max-w-380 r-16 border border-[#ece2dd] bg-white p-32 shadow-[0_10px_30px_rgba(58,10,16,0.06)]">
        <div className="font-serif fs-24 font-semibold tracking-[0.22em]" style={{ color: WINE }}>
          NAYO
        </div>
        <h1 className="mt-6 fs-15 text-[#1f1f1f]">Boîte de réception — connexion</h1>
        <label className="mt-24 block fs-12 font-semibold uppercase tracking-[0.06em] text-[#8a8a8a]" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-6 h-42 w-full r-10 border border-[#ecdcd6] bg-[#fbf5f2] px-14 fs-14 outline-none focus:border-[#7a1a2a]"
        />
        <label className="mt-16 block fs-12 font-semibold uppercase tracking-[0.06em] text-[#8a8a8a]" htmlFor="pw">
          Mot de passe
        </label>
        <input
          id="pw"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-6 h-42 w-full r-10 border border-[#ecdcd6] bg-[#fbf5f2] px-14 fs-14 outline-none focus:border-[#7a1a2a]"
        />
        {error && (
          <p role="alert" className="mt-12 fs-13 text-[#b4233a]">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="mt-22 h-44 w-full rounded-pill fs-14.5 font-semibold text-white disabled:cursor-wait"
          style={{ background: WINE }}
        >
          {busy ? 'Connexion…' : 'Se connecter'}
        </button>
      </form>
    </div>
  )
}

// ------------------------------------------------------------------ bubbles
function Bubble({ m }: { m: Message }) {
  if (m.role === 'client') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[68%] r-14 bg-[#fde3e8] px-14 py-11">
          <p className="whitespace-pre-wrap fs-13.5 lh-21 text-[#222]">{m.text}</p>
          <p className="mt-4 text-right fs-10.5 text-[#a08f8f]">{hhmm(m.at)}</p>
        </div>
      </div>
    )
  }
  const isBot = m.role === 'bot'
  return (
    <div className="flex flex-col items-start">
      <span
        className={`mb-5 ml-2 fs-10.5 font-bold uppercase tracking-[0.06em] ${isBot ? 'text-[#0e8f74]' : 'text-[#7a1a2a]'}`}
      >
        {isBot ? 'Bot' : m.agent_name || 'Équipe'}
      </span>
      <div
        className={`max-w-[68%] r-14 border px-14 py-11 ${
          isBot ? 'border-[#e6dcd7] bg-white' : 'border-[#ead1d6] bg-[#f6eaec]'
        }`}
      >
        <p className="whitespace-pre-wrap fs-13.5 lh-21 text-[#222]">{m.text}</p>
        <p className="mt-4 fs-10.5 text-[#a08f8f]">{hhmm(m.at)}</p>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ inbox
function Inbox({ onLogout }: { onLogout: () => void }) {
  const [me, setMe] = useState<{ name: string; online: number } | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<ConversationItem[]>([])
  const [online, setOnline] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const [thread, setThread] = useState<Thread | null>(null)
  const [draft, setDraft] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [, setTick] = useState(0)
  const scroller = useRef<HTMLDivElement>(null)
  const lastCount = useRef(0)

  const guard = useCallback(
    async <T,>(p: Promise<T>): Promise<T | undefined> => {
      try {
        return await p
      } catch (e) {
        if (e instanceof Unauthorized) onLogout()
        else setError(e instanceof Error ? e.message : 'Erreur')
        return undefined
      }
    },
    [onLogout],
  )

  const loadList = useCallback(async () => {
    const r = await guard(adminApi.conversations(filter))
    if (!r) return
    setItems(r.items)
    setOnline(r.online)
    setSelected((cur) => cur ?? r.items[0]?.phone ?? null)
  }, [filter, guard])

  const loadThread = useCallback(
    async (phone: string, initNotes = false) => {
      const t = await guard(adminApi.thread(phone))
      if (!t) return
      setThread(t)
      if (initNotes) setNotes(t.conversation.internal_notes)
    },
    [guard],
  )

  useEffect(() => {
    guard(adminApi.me()).then((m) => m && setMe(m))
  }, [guard])

  useEffect(() => {
    loadList()
    const id = setInterval(loadList, POLL_MS)
    return () => clearInterval(id)
  }, [loadList])

  useEffect(() => {
    if (!selected) return
    lastCount.current = 0
    loadThread(selected, true)
    const id = setInterval(() => loadThread(selected), POLL_MS)
    return () => clearInterval(id)
  }, [selected, loadThread])

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30000) // refresh "expire dans …"
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const n = thread?.messages.length ?? 0
    if (n !== lastCount.current && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
    lastCount.current = n
  }, [thread])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase().replace(/\s/g, '')
    if (!q) return items
    return items.filter(
      (i) =>
        i.name.toLowerCase().replace(/\s/g, '').includes(q) ||
        i.phone.includes(q.replace(/^0/, '')) ||
        formatPhone(i.phone).replace(/\s/g, '').includes(q) ||
        (i.order_number ?? '').toLowerCase().includes(q),
    )
  }, [items, search])

  const conv = thread?.conversation
  const order = thread?.order
  const current = items.find((i) => i.phone === selected)
  const title = order?.name || current?.name || (selected ? formatPhone(selected) : '')

  const toggleTakeover = async () => {
    if (!selected || !conv) return
    await guard(conv.taken_over_by ? adminApi.release(selected) : adminApi.takeover(selected))
    loadThread(selected)
    loadList()
  }

  const send = async (e: FormEvent) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text || !selected) return
    setError('')
    const ok = await guard(adminApi.send(selected, text))
    if (ok) {
      setDraft('')
      loadThread(selected)
      loadList()
    }
  }

  const setStatus = async (s: 'confirmed' | 'cancelled' | 'needs_human') => {
    if (!order) return
    await guard(adminApi.setStatus(order.order_number, s))
    if (selected) loadThread(selected)
    loadList()
  }

  const saveNotes = () => {
    if (selected && conv && notes !== conv.internal_notes) guard(adminApi.notes(selected, notes))
  }

  return (
    <div className="flex h-screen flex-col bg-white text-[#1a1a1a]">
      {/* Header */}
      <header className="flex h-64 shrink-0 items-center border-b border-[#e8e8e8] px-24">
        <span className="font-serif fs-20 font-semibold tracking-[0.2em]" style={{ color: WINE }}>
          NAYO
        </span>
        <span className="mx-18 h-20 w-px bg-[#e2e2e2]" aria-hidden />
        <span className="fs-15 font-medium text-[#1f1f1f]">Boîte de réception</span>
        <div className="ml-auto flex items-center gap-16">
          <span className="flex items-center gap-7 fs-13 text-[#6b6b6b]">
            <span className="size-8 rounded-full bg-[#22c55e]" aria-hidden />
            {online} {online > 1 ? 'membres en ligne' : 'membre en ligne'}
          </span>
          <button
            type="button"
            onClick={() => adminApi.logout().finally(onLogout)}
            title={me ? `${me.name} — se déconnecter` : 'Se déconnecter'}
            className="grid size-32 place-items-center rounded-full fs-13 font-bold text-white"
            style={{ background: WINE }}
          >
            {(me?.name || '?').charAt(0).toUpperCase()}
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Conversation list */}
        <aside className="flex w-320 shrink-0 flex-col border-r border-[#e8e8e8]">
          <div className="p-16">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Rechercher un client, un numéro..."
              className="h-40 w-full r-10 border border-[#ecdcd6] bg-[#fbf5f2] px-14 fs-13.5 outline-none placeholder:text-[#8a8080] focus:border-[#7a1a2a]"
            />
            <div className="mt-12 flex flex-wrap gap-8">
              {FILTERS.map((f) => (
                <Chip key={f.key} active={filter === f.key} onClick={() => setFilter(f.key)}>
                  {f.label}
                </Chip>
              ))}
            </div>
          </div>
          <ul className="min-h-0 flex-1 overflow-y-auto" aria-label="Conversations">
            {visible.map((i) => (
              <li key={i.phone}>
                <button
                  type="button"
                  onClick={() => setSelected(i.phone)}
                  className={`block w-full border-b-2 border-l-3 border-b-white px-16 py-12 text-left transition-colors ${
                    i.phone === selected ? 'border-l-[#1a1a1a] bg-[#ececec]' : 'border-l-[#1a1a1a] bg-[#f3f3f3] hover:bg-[#ededed]'
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-8">
                    <span className="truncate fs-14 font-bold">{i.name || formatPhone(i.phone)}</span>
                    <span className="shrink-0 fs-12 text-[#9a9a9a]">{listTime(i.last_at)}</span>
                  </div>
                  <div className="mt-4 flex items-center justify-between gap-8">
                    <span className="truncate fs-13 text-[#6b6b6b]">{i.last_message}</span>
                    {i.unread > 0 && (
                      <span className="grid h-18 min-w-28 shrink-0 place-items-center rounded-pill bg-[#e2788a] px-6 fs-11 font-bold text-white">
                        {i.unread}
                      </span>
                    )}
                  </div>
                  <div className="mt-6 flex items-center gap-6">
                    <StatusPill status={i.status} />
                    {i.taken_over_by && <span className="fs-11 text-[#7a1a2a]">· {i.taken_over_by}</span>}
                  </div>
                </button>
              </li>
            ))}
            {visible.length === 0 && <li className="px-16 py-24 fs-13 text-[#8a8a8a]">Aucune conversation.</li>}
          </ul>
        </aside>

        {/* Thread */}
        <section className="flex min-w-0 flex-1 flex-col" aria-label="Conversation">
          {selected && conv ? (
            <>
              <div className="flex h-66 shrink-0 items-center justify-between border-b border-[#e8e8e8] px-24">
                <div className="min-w-0">
                  <div className="truncate fs-15 font-bold">{title}</div>
                  <div className="truncate fs-12.5 text-[#8a8a8a]">
                    {formatPhone(selected)}
                    {order ? ` · Commande ${order.order_number}` : ''}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={toggleTakeover}
                  className={`flex h-36 shrink-0 items-center gap-8 r-8 border px-14 fs-13 font-semibold transition-colors ${
                    conv.taken_over_by
                      ? 'border-[#e2788a] bg-[#fdf0f2] text-[#7a1a2a] hover:bg-[#fbe6ea]'
                      : 'border-[#3fbfa5] bg-[#effaf7] text-[#0e8f74] hover:bg-[#e3f6f0]'
                  }`}
                >
                  <span className={`size-7 rounded-full ${conv.taken_over_by ? 'bg-[#e2788a]' : 'bg-[#10b981]'}`} aria-hidden />
                  {conv.taken_over_by
                    ? `Repris par ${conv.taken_over_by} · Rendre au bot`
                    : 'Bot actif · Reprendre la conversation'}
                </button>
              </div>

              {conv.window_open && conv.window_expires_at ? (
                <div className="flex h-34 shrink-0 items-center gap-8 bg-[#fdf1dc] px-24 fs-12.5 text-[#a0610f]">
                  <Clock className="size-14" strokeWidth={2} aria-hidden />
                  Fenêtre de service de 24h ouverte — expire dans {windowLeft(conv.window_expires_at)}
                </div>
              ) : (
                <div className="flex h-34 shrink-0 items-center gap-8 bg-[#fbe5e5] px-24 fs-12.5 text-[#a12a2a]">
                  <Clock className="size-14" strokeWidth={2} aria-hidden />
                  Fenêtre de 24h fermée — le client doit écrire en premier pour qu'on puisse lui répondre
                </div>
              )}

              <div ref={scroller} className="min-h-0 flex-1 space-y-16 overflow-y-auto bg-[#f8f4f1] px-24 py-24">
                {thread!.messages.map((m, idx) => (
                  <Bubble key={`${m.at}-${idx}`} m={m} />
                ))}
              </div>

              <form onSubmit={send} className="shrink-0 border-t border-[#ececec] px-24 py-14">
                {error && (
                  <p role="alert" className="mb-8 fs-12.5 text-[#b4233a]">
                    {error}
                  </p>
                )}
                <div className="flex items-center gap-10">
                  <input
                    value={draft}
                    onChange={(e) => {
                      setDraft(e.target.value)
                      if (error) setError('')
                    }}
                    disabled={!conv.window_open}
                    placeholder={conv.window_open ? 'Écrire un message...' : 'Fenêtre de 24h fermée'}
                    className="h-44 min-w-0 flex-1 rounded-pill border border-[#ecdcd6] bg-[#fbf5f2] px-18 fs-13.5 outline-none placeholder:text-[#8a8080] focus:border-[#7a1a2a] disabled:opacity-60"
                  />
                  <button
                    type="submit"
                    aria-label="Envoyer"
                    disabled={!draft.trim() || !conv.window_open}
                    className={`grid size-38 shrink-0 place-items-center rounded-full text-white disabled:cursor-not-allowed ${
                      conv.window_open ? '' : 'opacity-50'
                    }`}
                    style={{ background: WINE }}
                  >
                    <ArrowRight className="size-16" strokeWidth={2.2} aria-hidden />
                  </button>
                </div>
              </form>
            </>
          ) : (
            <div className="grid flex-1 place-items-center bg-[#f8f4f1] fs-13.5 text-[#8a8a8a]">
              {items.length ? 'Sélectionnez une conversation.' : 'Aucune conversation pour le moment.'}
            </div>
          )}
        </section>

        {/* Order panel */}
        <aside className="w-300 shrink-0 overflow-y-auto border-l border-[#e8e8e8] p-20" aria-label="Commande">
          {order ? (
            <>
              <div className="fs-11 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">Commande</div>
              <div className="mt-4 fs-17 font-bold">{order.order_number}</div>
              <div className="mt-14 flex flex-wrap gap-8">
                <Chip active={order.status === 'needs_human'} onClick={() => setStatus('needs_human')}>
                  Besoin d'aide
                </Chip>
                <Chip active={order.status === 'confirmed'} onClick={() => setStatus('confirmed')}>
                  Confirmée
                </Chip>
                <Chip active={order.status === 'cancelled'} onClick={() => setStatus('cancelled')}>
                  Annulée
                </Chip>
              </div>

              <div className="mt-18 r-12 bg-[#f6efea] p-16">
                <div className="flex justify-between fs-13">
                  <span>
                    NAYO<sup className="fs-9">®</sup> Déodorant × {order.quantity}
                  </span>
                  <span>{order.unit_price * order.quantity} MAD</span>
                </div>
                <div className="mt-8 flex justify-between fs-12.5 text-[#7a6f6f]">
                  <span>Frais de livraison</span>
                  <span>{order.shipping} MAD</span>
                </div>
                <div className="my-10 h-px bg-[#e3d6cf]" />
                <div className="flex justify-between fs-13.5 font-bold">
                  <span>Total</span>
                  <span>{order.total} MAD</span>
                </div>
              </div>

              <div className="mt-20 fs-11 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">Client</div>
              <div className="mt-4 fs-13.5 lh-20">
                {order.name}
                <br />
                {formatPhone(order.phone)}
              </div>

              <div className="mt-14 fs-11 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">Adresse</div>
              <div className="mt-4 fs-13.5 lh-20">
                {[order.address, order.city].filter(Boolean).join(', ') || <span className="text-[#8a8a8a]">Pas encore donnée</span>}
              </div>
            </>
          ) : (
            <div className="fs-13 text-[#8a8a8a]">{selected ? 'Aucune commande liée à ce numéro.' : ''}</div>
          )}

          {selected && conv && (
            <>
              <div className="mt-14 fs-11 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">Notes internes</div>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                onBlur={saveNotes}
                placeholder="Visibles par toute l'équipe..."
                rows={3}
                className="mt-6 w-full resize-y r-8 border border-[#ecdcd6] bg-[#fbf5f2] px-12 py-10 fs-13 outline-none placeholder:text-[#8a8080] focus:border-[#7a1a2a]"
              />
            </>
          )}
        </aside>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ page
export default function Admin() {
  const [state, setState] = useState<'checking' | 'login' | 'in'>('checking')

  // Fixed px layout: undo the landing page's viewport-scaled root font-size while the admin is open.
  useLayoutEffect(() => {
    const html = document.documentElement
    const prev = html.style.fontSize
    html.style.fontSize = '16px'
    document.title = 'Boîte de réception — NAYO'
    return () => {
      html.style.fontSize = prev
    }
  }, [])

  useEffect(() => {
    adminApi
      .me()
      .then(() => setState('in'))
      .catch(() => setState('login'))
  }, [])

  if (state === 'checking') return <div className="min-h-screen bg-[#f8f4f1]" />
  if (state === 'login') return <Login onDone={() => setState('in')} />
  return <Inbox onLogout={() => setState('login')} />
}
