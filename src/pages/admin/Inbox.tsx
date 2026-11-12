import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Clock, X } from 'lucide-react'
import {
  adminApi,
  Unauthorized,
  type ConversationItem,
  type Filter,
  type Message,
  type Status,
  type Thread,
} from '../../lib/adminApi'
import { Chip, FILTERS, formatPhone, hhmm, listTime, POLL_MS, StatusPill, WINE, windowLeft, withStockConfirm } from './ui'

/*
 * Admin inbox (/admin/inbox) — approved mockup: header, conversation list with filter chips, chat thread with
 * bot / customer / agent bubbles, 24h-window banner, "Bot actif ↔ Repris par {agent}" toggle, order panel.
 * Optimistic send, mobile layout (list ↔ thread, order sheet) and polling every 4 s.
 */

// ------------------------------------------------------------------ bubbles
function Bubble({ m, pending = false }: { m: Message; pending?: boolean }) {
  if (m.role === 'client') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] md:max-w-[68%] r-14 bg-[#fde3e8] px-14 py-11">
          <p className="whitespace-pre-wrap fs-13.5 lh-21 text-[#222]">{m.text}</p>
          <p className="mt-4 text-right fs-10.5 text-[#a08f8f]">{hhmm(m.at)}</p>
        </div>
      </div>
    )
  }
  const isBot = m.role === 'bot'
  return (
    <div className={`flex flex-col items-start ${pending ? 'opacity-60' : ''}`}>
      <span
        className={`mb-5 ml-2 fs-10.5 font-bold uppercase tracking-[0.06em] ${isBot ? 'text-[#0e8f74]' : 'text-[#7a1a2a]'}`}
      >
        {isBot ? 'Bot' : m.agent_name || 'Équipe'}
      </span>
      <div
        className={`max-w-[85%] md:max-w-[68%] r-14 border px-14 py-11 ${
          isBot ? 'border-[#e6dcd7] bg-white' : 'border-[#ead1d6] bg-[#f6eaec]'
        }`}
      >
        <p className="whitespace-pre-wrap fs-13.5 lh-21 text-[#222]">{m.text}</p>
        <p className="mt-4 fs-10.5 text-[#a08f8f]">{pending ? 'Envoi…' : hhmm(m.at)}</p>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ order panel (column ≥1280px, sheet below)
function OrderPanel({
  order,
  showNotes,
  notes,
  onNotes,
  onSaveNotes,
  onStatus,
  emptyLabel,
}: {
  order: Thread['order'] | undefined
  showNotes: boolean
  notes: string
  onNotes: (v: string) => void
  onSaveNotes: () => void
  onStatus: (s: 'confirmed' | 'cancelled' | 'needs_human') => void
  emptyLabel: string
}) {
  return (
    <>
      {order ? (
        <>
          <div className="fs-11 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">Commande</div>
          <div className="mt-4 flex items-baseline justify-between gap-8">
            <span className="fs-17 font-bold">{order.order_number}</span>
            <Link to={`/admin/orders/${order.order_number}`} className="fs-12.5 font-semibold text-[#7a1a2a] underline-offset-2 hover:underline">
              Voir la commande
            </Link>
          </div>
          <div className="mt-14 flex flex-wrap gap-8">
            <Chip active={order.status === 'needs_human'} onClick={() => onStatus('needs_human')}>
              Besoin d'aide
            </Chip>
            <Chip active={order.status === 'confirmed'} onClick={() => onStatus('confirmed')}>
              Confirmée
            </Chip>
            <Chip active={order.status === 'cancelled'} onClick={() => onStatus('cancelled')}>
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
        <div className="fs-13 text-[#8a8a8a]">{emptyLabel}</div>
      )}

      {showNotes && (
        <>
          <div className="mt-14 fs-11 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">Notes internes</div>
          <textarea
            value={notes}
            onChange={(e) => onNotes(e.target.value)}
            onBlur={onSaveNotes}
            placeholder="Visibles par toute l'équipe..."
            rows={3}
            className="mt-6 w-full resize-y r-8 border border-[#ecdcd6] bg-[#fbf5f2] px-12 py-10 fs-16 outline-none placeholder:text-[#8a8080] focus:border-[#7a1a2a] md:fs-13"
          />
        </>
      )}
    </>
  )
}

// ------------------------------------------------------------------ inbox
type PendingMessage = Message & { localId: string; pending: true; phone: string }

export default function Inbox({ onLogout }: { onLogout: () => void }) {
  const [me, setMe] = useState<{ name: string; online: number } | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<ConversationItem[]>([])
  const [online, setOnline] = useState(0)
  const [searchParams] = useSearchParams()
  const [selected, setSelected] = useState<string | null>(searchParams.get('phone'))
  const [thread, setThread] = useState<Thread | null>(null)
  const [threadLoading, setThreadLoading] = useState(false)
  const [pending, setPending] = useState<PendingMessage[]>([]) // optimistic agent messages, per phone
  const [draft, setDraft] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [mobileView, setMobileView] = useState<'list' | 'thread'>(searchParams.get('phone') ? 'thread' : 'list') // < 768px: one pane at a time
  const [orderOpen, setOrderOpen] = useState(false) // order sheet below 1280px
  const [, setTick] = useState(0)
  const scroller = useRef<HTMLDivElement>(null)
  const lastCount = useRef(0)
  const selectedRef = useRef<string | null>(null)
  selectedRef.current = selected

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
      // A slow response for a conversation that is no longer open must not replace the current one.
      if (!t || selectedRef.current !== phone) return
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
    setThreadLoading(true) // previous thread stays visible, dimmed, until the new one arrives
    loadThread(selected, true).finally(() => {
      if (selectedRef.current === selected) setThreadLoading(false)
    })
    const id = setInterval(() => loadThread(selected), POLL_MS)
    return () => clearInterval(id)
  }, [selected, loadThread])

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30000) // refresh "expire dans …"
    return () => clearInterval(id)
  }, [])

  // Optimistic bubbles disappear as soon as the server's thread contains the real message.
  useEffect(() => {
    if (!thread) return
    const phone = thread.conversation.phone
    setPending((list) =>
      list.filter(
        (p) =>
          p.phone !== phone ||
          !thread.messages.some((m) => m.role === 'agent' && m.text === p.text && m.at >= p.at - 120),
      ),
    )
  }, [thread])

  const shownMessages: (Message | PendingMessage)[] = useMemo(() => {
    if (!thread || thread.conversation.phone !== selected) return thread?.messages ?? []
    return [...thread.messages, ...pending.filter((p) => p.phone === selected)]
  }, [thread, pending, selected])

  useEffect(() => {
    const n = shownMessages.length
    if (n !== lastCount.current && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
    lastCount.current = n
  }, [shownMessages])

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
  // While another conversation is loading, the header already shows the newly selected client.
  const title = (threadLoading ? current?.name : order?.name || current?.name) || (selected ? formatPhone(selected) : '')
  const headerOrder = threadLoading ? current?.order_number : order?.order_number
  const headerStatus = (threadLoading ? current?.status : order?.status) || ''

  const open = (phone: string) => {
    if (phone !== selected) {
      setSelected(phone)
      setError('')
      setDraft('')
    }
    setMobileView('thread')
  }

  const toggleTakeover = async () => {
    if (!selected || !conv) return
    await guard(conv.taken_over_by ? adminApi.release(selected) : adminApi.takeover(selected))
    loadThread(selected)
    loadList()
  }

  const send = (e: FormEvent) => {
    e.preventDefault()
    const text = draft.trim()
    const phone = selected
    if (!text || !phone) return
    setError('')
    // 1) show it immediately, 2) send in the background, 3) reconcile with the server (or roll back).
    const optimistic: PendingMessage = {
      localId: `${Date.now()}-${Math.random()}`,
      pending: true,
      role: 'agent',
      text,
      at: Date.now() / 1000,
      agent_name: me?.name ?? 'Équipe',
      phone,
    }
    setPending((list) => [...list, optimistic])
    setDraft('')
    guard(adminApi.send(phone, text)).then((ok) => {
      if (ok) {
        loadThread(phone)
        loadList()
      } else {
        setPending((list) => list.filter((p) => p.localId !== optimistic.localId))
        if (selectedRef.current === phone) setDraft((d) => d || text)
      }
    })
  }

  const setStatus = async (s: 'confirmed' | 'cancelled' | 'needs_human') => {
    if (!order) return
    const n = order.order_number
    await guard(withStockConfirm((force) => adminApi.setStatus(n, s, force ? { force } : undefined)))
    if (selected) loadThread(selected)
    loadList()
  }

  const saveNotes = () => {
    if (selected && conv && notes !== conv.internal_notes) guard(adminApi.notes(selected, notes))
  }

  const panelProps = {
    order,
    showNotes: Boolean(selected && conv),
    notes,
    onNotes: setNotes,
    onSaveNotes: saveNotes,
    onStatus: setStatus,
    emptyLabel: selected ? 'Aucune commande liée à ce numéro.' : '',
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-white text-[#1a1a1a]">
      {/* Header */}
      <header className="flex h-56 shrink-0 items-center border-b border-[#e8e8e8] px-16 md:h-64 md:px-24">
        <span className="font-serif fs-18 font-semibold tracking-[0.2em] md:fs-20" style={{ color: WINE }}>
          NAYO
        </span>
        <span className="mx-12 h-20 w-px bg-[#e2e2e2] md:mx-18" aria-hidden />
        <span className="truncate fs-14 font-medium text-[#1f1f1f] md:fs-15">Boîte de réception</span>
        <div className="ml-auto flex shrink-0 items-center gap-12 md:gap-16">
          <span className="flex items-center gap-7 fs-13 text-[#6b6b6b]" title={`${online} en ligne`}>
            <span className="size-8 rounded-full bg-[#22c55e]" aria-hidden />
            <span className="hidden sm:inline">
              {online} {online > 1 ? 'membres en ligne' : 'membre en ligne'}
            </span>
            <span className="sm:hidden">{online}</span>
          </span>
          <button
            type="button"
            onClick={() => adminApi.logout().finally(onLogout)}
            title={me ? `${me.name} — se déconnecter` : 'Se déconnecter'}
            className="grid size-36 place-items-center rounded-full fs-13 font-bold text-white md:size-32"
            style={{ background: WINE }}
          >
            {(me?.name || '?').charAt(0).toUpperCase()}
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Conversation list — full width on mobile (list view), 320px from 768px */}
        <aside
          className={`${mobileView === 'thread' ? 'hidden' : 'flex'} w-full shrink-0 flex-col border-r border-[#e8e8e8] md:flex md:w-320`}
        >
          <div className="p-16">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Rechercher un client, un numéro..."
              className="h-44 w-full r-10 border border-[#ecdcd6] bg-[#fbf5f2] px-14 fs-16 outline-none placeholder:text-[#8a8080] focus:border-[#7a1a2a] md:h-40 md:fs-13.5"
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
                  onClick={() => open(i.phone)}
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

        {/* Thread — full width on mobile (thread view) */}
        <section
          className={`${mobileView === 'list' ? 'hidden' : 'flex'} min-w-0 flex-1 flex-col md:flex`}
          aria-label="Conversation"
          aria-busy={threadLoading}
        >
          {selected && conv ? (
            <>
              {/* Phones: name on the first row, the two action buttons on a second row. */}
              <div className="flex min-h-66 shrink-0 flex-wrap items-center gap-x-10 gap-y-8 border-b border-[#e8e8e8] px-12 py-10 sm:flex-nowrap md:gap-16 md:px-24">
                <button
                  type="button"
                  onClick={() => setMobileView('list')}
                  aria-label="Retour aux conversations"
                  className="grid size-40 shrink-0 place-items-center rounded-full text-[#1a1a1a] hover:bg-[#f2f2f2] md:hidden"
                >
                  <ArrowLeft className="size-20" strokeWidth={2} aria-hidden />
                </button>
                <div className="min-w-0 flex-1">
                  <div className="truncate fs-15 font-bold">{title}</div>
                  <div className="truncate fs-12.5 text-[#8a8a8a]">
                    {formatPhone(selected)}
                    {headerOrder ? <span className="hidden sm:inline"> · Commande {headerOrder}</span> : null}
                  </div>
                </div>
                <div className="flex w-full shrink-0 gap-8 sm:w-auto">
                {/* Order sheet trigger below 1280px (the order column is visible from 1280px) */}
                {(order || threadLoading) && (
                  <button
                    type="button"
                    onClick={() => setOrderOpen(true)}
                    disabled={threadLoading}
                    className="flex h-40 flex-1 items-center justify-center gap-6 r-8 border border-[#e2d6d0] bg-[#fbf5f2] px-10 fs-12.5 font-semibold sm:flex-none xl:hidden"
                  >
                    Commande
                    <StatusPill status={headerStatus as Status} />
                  </button>
                )}
                <button
                  type="button"
                  onClick={toggleTakeover}
                  disabled={threadLoading}
                  title={conv.taken_over_by ? `Repris par ${conv.taken_over_by} · Rendre au bot` : 'Bot actif · Reprendre la conversation'}
                  className={`flex h-40 flex-1 items-center justify-center gap-8 r-8 border px-12 fs-13 font-semibold transition-colors sm:flex-none md:h-36 md:px-14 ${
                    conv.taken_over_by
                      ? 'border-[#e2788a] bg-[#fdf0f2] text-[#7a1a2a] hover:bg-[#fbe6ea]'
                      : 'border-[#3fbfa5] bg-[#effaf7] text-[#0e8f74] hover:bg-[#e3f6f0]'
                  }`}
                >
                  <span className={`size-7 rounded-full ${conv.taken_over_by ? 'bg-[#e2788a]' : 'bg-[#10b981]'}`} aria-hidden />
                  <span className="hidden lg:inline">
                    {conv.taken_over_by ? `Repris par ${conv.taken_over_by} · Rendre au bot` : 'Bot actif · Reprendre la conversation'}
                  </span>
                  <span className="lg:hidden">{conv.taken_over_by ? 'Rendre au bot' : 'Reprendre'}</span>
                </button>
                </div>
              </div>

              <div className={`flex min-h-0 flex-1 flex-col transition-opacity ${threadLoading ? 'pointer-events-none opacity-50' : ''}`}>
                {conv.window_open && conv.window_expires_at ? (
                  <div className="flex min-h-34 shrink-0 items-center gap-8 bg-[#fdf1dc] px-16 py-8 fs-12.5 text-[#a0610f] md:px-24 md:py-0">
                    <Clock className="size-14 shrink-0" strokeWidth={2} aria-hidden />
                    Fenêtre de service de 24h ouverte — expire dans {windowLeft(conv.window_expires_at)}
                  </div>
                ) : (
                  <div className="flex min-h-34 shrink-0 items-center gap-8 bg-[#fbe5e5] px-16 py-8 fs-12.5 text-[#a12a2a] md:px-24 md:py-0">
                    <Clock className="size-14 shrink-0" strokeWidth={2} aria-hidden />
                    Fenêtre de 24h fermée — le client doit écrire en premier pour qu'on puisse lui répondre
                  </div>
                )}

                <div ref={scroller} className="min-h-0 flex-1 space-y-16 overflow-y-auto bg-[#f8f4f1] px-12 py-20 md:px-24 md:py-24">
                  {shownMessages.map((m, idx) => (
                    <Bubble key={'localId' in m ? m.localId : `${m.at}-${idx}`} m={m} pending={'pending' in m} />
                  ))}
                </div>

                <form onSubmit={send} className="shrink-0 border-t border-[#ececec] px-12 py-12 md:px-24 md:py-14">
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
                      className="h-44 min-w-0 flex-1 rounded-pill border border-[#ecdcd6] bg-[#fbf5f2] px-18 fs-16 outline-none placeholder:text-[#8a8080] focus:border-[#7a1a2a] disabled:opacity-60 md:fs-13.5"
                    />
                    <button
                      type="submit"
                      aria-label="Envoyer"
                      disabled={!draft.trim() || !conv.window_open}
                      className={`grid size-44 shrink-0 place-items-center rounded-full text-white disabled:cursor-not-allowed md:size-38 ${
                        conv.window_open ? '' : 'opacity-50'
                      }`}
                      style={{ background: WINE }}
                    >
                      <ArrowRight className="size-16" strokeWidth={2.2} aria-hidden />
                    </button>
                  </div>
                </form>
              </div>
            </>
          ) : (
            <div className="grid flex-1 place-items-center bg-[#f8f4f1] fs-13.5 text-[#8a8a8a]">
              {selected ? 'Chargement…' : items.length ? 'Sélectionnez une conversation.' : 'Aucune conversation pour le moment.'}
            </div>
          )}
        </section>

        {/* Order panel — fixed third column from 1280px */}
        <aside
          className={`hidden w-300 shrink-0 overflow-y-auto border-l border-[#e8e8e8] p-20 transition-opacity xl:block ${
            threadLoading ? 'opacity-50' : ''
          }`}
          aria-label="Commande"
        >
          <OrderPanel {...panelProps} />
        </aside>
      </div>

      {/* Order sheet below 1280px: bottom sheet on phones, side sheet from 768px */}
      {orderOpen && (
        <div className="fixed inset-0 z-50 xl:hidden" role="dialog" aria-modal="true" aria-label="Commande">
          <button
            type="button"
            aria-label="Fermer"
            onClick={() => setOrderOpen(false)}
            className="absolute inset-0 bg-[rgba(30,10,12,0.35)]"
          />
          <div className="absolute inset-x-0 bottom-0 max-h-[85dvh] overflow-y-auto rt-16 bg-white p-20 pb-28 shadow-[0_-10px_30px_rgba(0,0,0,0.12)] md:inset-y-0 md:left-auto md:right-0 md:max-h-none md:w-360 md:rounded-none md:shadow-[-10px_0_30px_rgba(0,0,0,0.12)]">
            <div className="mb-12 flex justify-end">
              <button
                type="button"
                onClick={() => setOrderOpen(false)}
                aria-label="Fermer"
                className="grid size-40 place-items-center rounded-full hover:bg-[#f2f2f2]"
              >
                <X className="size-20" strokeWidth={2} aria-hidden />
              </button>
            </div>
            <OrderPanel {...panelProps} />
          </div>
        </div>
      )}
    </div>
  )
}
