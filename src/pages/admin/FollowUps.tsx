import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Lightbulb, MessageSquare } from 'lucide-react'
import { adminApi, Unauthorized, type Suggestion, type Task, type TaskView } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { Banner, BusyButton, Chip, FieldLabel, fmtDateTime, formatPhone, inputClass } from './ui'

/*
 * Relances: follow-up tasks (Aujourd'hui / En retard / À venir / Faites) and the suggestions computed from the
 * data (not stored until accepted). Writing to a client goes through the inbox (24 h window respected there).
 */

const VIEWS: { key: TaskView; label: string }[] = [
  { key: 'today', label: "Aujourd'hui" },
  { key: 'late', label: 'En retard' },
  { key: 'upcoming', label: 'À venir' },
  { key: 'done', label: 'Faites' },
]

type Msg = { kind: 'ok' | 'error'; text: string } | null

/** Tells the nav to refresh its red badge right away. */
export const refreshBadge = () => window.dispatchEvent(new Event('nayo:tasks'))

const casaNow = () => {
  const d = new Date().toLocaleString('sv-SE', { timeZone: 'Africa/Casablanca' }) // "2026-11-14 09:30:00"
  return d.slice(0, 16).replace(' ', 'T')
}

export default function FollowUps() {
  const { logout } = useAuth()
  const [view, setView] = useState<TaskView>('today')
  const [items, setItems] = useState<Task[] | null>(null)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [counts, setCounts] = useState<{ late: number; today: number; upcoming: number; suggestions: number } | null>(null)
  const [team, setTeam] = useState<string[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [message, setMessage] = useState<Msg>(null)

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof Unauthorized) logout()
      else setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })
    },
    [logout],
  )

  const load = useCallback(async () => {
    try {
      const [r, c] = await Promise.all([adminApi.tasks(view), adminApi.taskCounts()])
      setItems(r.items)
      setHasMore(r.has_more)
      setSuggestions(r.suggestions ?? [])
      setCounts(c)
      refreshBadge()
    } catch (e) {
      fail(e)
    }
  }, [view, fail])

  useEffect(() => {
    setItems(null)
    load()
  }, [load])
  useEffect(() => {
    adminApi
      .team()
      .then((t) => setTeam(t.names))
      .catch(() => undefined)
  }, [])

  const act = async (id: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(id)
    setMessage(null)
    try {
      await fn()
      await load()
      setMessage({ kind: 'ok', text: ok })
    } catch (e) {
      fail(e)
      await load()
    } finally {
      setBusy(null)
    }
  }

  const more = async () => {
    if (!items) return
    try {
      const r = await adminApi.tasks(view, items.length)
      setItems([...items, ...r.items])
      setHasMore(r.has_more)
    } catch (e) {
      fail(e)
    }
  }

  const label = (k: TaskView) => {
    const n = k === 'today' ? (counts ? counts.today + counts.suggestions : 0) : k === 'done' ? 0 : (counts?.[k] ?? 0)
    return n ? `${VIEWS.find((v) => v.key === k)!.label} · ${n}` : VIEWS.find((v) => v.key === k)!.label
  }

  return (
    <div className="mx-auto w-full max-w-960 px-16 py-16 md:px-24 md:py-24">
      <div className="flex flex-wrap items-center justify-between gap-12">
        <h1 className="fs-22 font-bold">Relances</h1>
        <BusyButton type="button" onClick={() => (setMessage(null), setAdding((v) => !v))}>
          Nouvelle relance
        </BusyButton>
      </div>
      <div className="mt-12 flex flex-wrap gap-8">
        {VIEWS.map((v) => (
          <Chip key={v.key} active={view === v.key} onClick={() => setView(v.key)}>
            {label(v.key)}
          </Chip>
        ))}
      </div>
      <Banner msg={message} />

      {adding && (
        <NewTaskForm
          team={team}
          onDone={async (t) => {
            setAdding(false)
            await load()
            setMessage({ kind: 'ok', text: `Relance ajoutée : ${t.title}` })
          }}
          onError={fail}
        />
      )}

      {view === 'today' && suggestions.length > 0 && (
        <section className="mt-14 r-14 border border-[#f0dfc2] bg-[#fffaf0] p-14">
          <h2 className="flex items-center gap-8 fs-15 font-bold">
            <Lightbulb className="size-18 text-[#b7791f]" aria-hidden /> Suggestions ({suggestions.length})
          </h2>
          <p className="mt-2 fs-12.5 text-[#7a6a50]">Calculées à partir des commandes, du stock et des achats. Acceptez pour en faire une relance.</p>
          <ul className="mt-10 divide-y divide-[#f3e7cf]">
            {suggestions.map((s) => (
              <li key={s.key} className="flex flex-wrap items-center gap-8 py-8">
                <div className="min-w-0 flex-1 basis-260">
                  <p className="fs-14">{s.title}</p>
                  <Links phone={s.customer_phone} order={s.order_number} />
                </div>
                <BusyButton
                  type="button"
                  busy={busy === `a:${s.key}`}
                  onClick={() => act(`a:${s.key}`, () => adminApi.addTask({ suggestion_key: s.key }), 'Relance créée.')}
                >
                  Accepter
                </BusyButton>
                <BusyButton
                  type="button"
                  variant="secondary"
                  busy={busy === `d:${s.key}`}
                  onClick={() => act(`d:${s.key}`, () => adminApi.dismissSuggestion(s.key), 'Suggestion ignorée.')}
                >
                  Ignorer
                </BusyButton>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!items ? (
        <p className="mt-18 fs-14 text-[#8a8a8a]">Chargement…</p>
      ) : items.length === 0 ? (
        <p className="mt-18 fs-14 text-[#8a8a8a]">
          {view === 'today' ? (suggestions.length ? 'Aucune relance prévue aujourd’hui.' : 'Rien à faire aujourd’hui.') : 'Aucune relance.'}
        </p>
      ) : (
        <ul className="mt-14 divide-y divide-[#f4eeeb] r-14 border border-[#ece2dd] bg-white">
          {items.map((t) => (
            <TaskItem key={t.id} t={t} busy={busy === `t:${t.id}`} onToggle={() => act(`t:${t.id}`, () => adminApi.editTask(t.id, { done: !t.done_at }), t.done_at ? 'Relance rouverte.' : 'Relance faite.')} />
          ))}
        </ul>
      )}
      {hasMore && (
        <div className="mt-12 text-center">
          <BusyButton type="button" variant="secondary" onClick={more}>
            Voir plus
          </BusyButton>
        </div>
      )}
    </div>
  )
}

function Links({ phone, order }: { phone: string; order: string }) {
  if (!phone && !order) return null
  return (
    <p className="mt-2 flex flex-wrap gap-x-12 gap-y-2 fs-12.5">
      {order && (
        <Link to={`/admin/orders/${encodeURIComponent(order)}`} className="font-semibold text-[#7a1a2a] underline">
          {order}
        </Link>
      )}
      {phone && (
        <Link to={`/admin/customers/${phone}`} className="text-[#6b6b6b] underline">
          {formatPhone(phone)}
        </Link>
      )}
      {phone && (
        <Link to={`/admin/inbox?phone=${phone}`} className="inline-flex items-center gap-4 text-[#6b6b6b] underline">
          <MessageSquare className="size-12" aria-hidden /> Écrire dans l'inbox
        </Link>
      )}
    </p>
  )
}

export function TaskItem({ t, busy, onToggle }: { t: Task; busy?: boolean; onToggle: () => void }) {
  const late = !t.done_at && t.due_at < casaNow().replace('T', ' ').slice(0, 10)
  return (
    <li className="flex items-start gap-10 px-14 py-10">
      <label className="grid size-40 shrink-0 place-items-center">
        <input
          type="checkbox"
          aria-label={t.done_at ? 'Rouvrir' : 'Marquer comme faite'}
          className="size-20 accent-[#3a0a10]"
          checked={!!t.done_at}
          disabled={busy}
          onChange={onToggle}
        />
      </label>
      <div className="min-w-0 flex-1 py-6">
        <p className={`fs-14 ${t.done_at ? 'text-[#8a8a8a] line-through' : ''}`}>{t.title}</p>
        <p className={`mt-2 fs-12.5 ${late ? 'font-semibold text-[#a12a2a]' : 'text-[#8a8a8a]'}`}>
          {t.done_at ? `Faite le ${fmtDateTime(t.done_at)}` : `Pour le ${fmtDateTime(t.due_at)}`}
          {t.assigned_to && ` · ${t.assigned_to}`}
          {` · créée par ${t.created_by}`}
        </p>
        <Links phone={t.customer_phone} order={t.order_number} />
      </div>
    </li>
  )
}

export function NewTaskForm({
  team,
  phone,
  order,
  onDone,
  onError,
}: {
  team: string[]
  phone?: string
  order?: string
  onDone: (t: Task) => void
  onError: (e: unknown) => void
}) {
  const [title, setTitle] = useState('')
  const [due, setDue] = useState(casaNow)
  const [p, setP] = useState(phone ?? '')
  const [o, setO] = useState(order ?? '')
  const [who, setWho] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    setBusy(true)
    try {
      const t = await adminApi.addTask({
        title: title.trim(),
        due_at: due.replace('T', ' '),
        ...(p.trim() ? { customer_phone: p.trim() } : {}),
        ...(o.trim() ? { order_number: o.trim() } : {}),
        ...(who ? { assigned_to: who } : {}),
      })
      setTitle('')
      onDone(t)
    } catch (err) {
      onError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="mt-14 r-14 border border-[#ece2dd] bg-white p-14 md:p-18">
      <div className="grid gap-10 md:grid-cols-2">
        <div className="md:col-span-2">
          <FieldLabel htmlFor="t-title">À faire</FieldLabel>
          <input id="t-title" required maxLength={200} placeholder="ex. Rappeler pour l'adresse" className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div>
          <FieldLabel htmlFor="t-due">Pour le</FieldLabel>
          <input id="t-due" type="datetime-local" required className={inputClass} value={due} onChange={(e) => setDue(e.target.value)} />
        </div>
        <div>
          <FieldLabel htmlFor="t-who">Assignée à</FieldLabel>
          <select id="t-who" className={inputClass} value={who} onChange={(e) => setWho(e.target.value)}>
            <option value="">Personne</option>
            {team.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
        {phone === undefined && (
          <div>
            <FieldLabel htmlFor="t-phone">Téléphone du client (facultatif)</FieldLabel>
            <input id="t-phone" inputMode="tel" maxLength={20} className={inputClass} value={p} onChange={(e) => setP(e.target.value)} />
          </div>
        )}
        {order === undefined && (
          <div>
            <FieldLabel htmlFor="t-order">N° de commande (facultatif)</FieldLabel>
            <input id="t-order" maxLength={30} placeholder="NAYO-1001" className={inputClass} value={o} onChange={(e) => setO(e.target.value)} />
          </div>
        )}
      </div>
      <BusyButton type="submit" busy={busy} className="mt-12">
        Ajouter la relance
      </BusyButton>
    </form>
  )
}
