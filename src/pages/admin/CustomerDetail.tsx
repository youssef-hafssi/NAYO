import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, MessageSquare } from 'lucide-react'
import { adminApi, Unauthorized, type Customer, type CustomerOrder, type Task } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { NewTaskForm, refreshBadge, TaskItem } from './FollowUps'
import { PRODUCT } from '../../content'
import { Banner, BusyButton, FieldLabel, fmtDate, fmtMoney, formatPhone, inputClass, Pill, SEGMENT_LABEL, SEGMENT_PILL, StatusPill } from './ui'

/* Fiche client: profile (name, city, address, tags, note, STOP), their orders, follow-ups, "Nouvelle commande". */

type Form = { name: string; city: string; address: string; tags: string; internal_note: string; opted_out: boolean }
const toForm = (c: Customer): Form => ({
  name: c.name,
  city: c.city,
  address: c.address,
  tags: c.tags.join(', '),
  internal_note: c.internal_note,
  opted_out: c.opted_out,
})

export default function CustomerDetail() {
  const { phone = '' } = useParams()
  const { me, logout } = useAuth()
  const navigate = useNavigate()
  const [c, setC] = useState<Customer | null>(null)
  const [orders, setOrders] = useState<CustomerOrder[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [windowOpen, setWindowOpen] = useState(false)
  const [form, setForm] = useState<Form | null>(null)
  const [team, setTeam] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [qty, setQty] = useState(1)
  const [creating, setCreating] = useState(false)
  const [addingTask, setAddingTask] = useState(false)
  const [busyTask, setBusyTask] = useState<number | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof Unauthorized) logout()
      else setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })
    },
    [logout],
  )

  const load = useCallback(async () => {
    try {
      const r = await adminApi.customer(phone)
      setC(r.customer)
      setForm(toForm(r.customer))
      setOrders(r.orders)
      setTasks(r.tasks)
      setWindowOpen(r.window_open)
    } catch (e) {
      if (e instanceof Error && /introuvable|404/.test(e.message)) setNotFound(true)
      else fail(e)
    }
  }, [phone, fail])

  useEffect(() => {
    load()
    adminApi
      .team()
      .then((t) => setTeam(t.names))
      .catch(() => undefined)
  }, [load])

  if (notFound)
    return (
      <div className="p-24">
        <p className="fs-14">Client introuvable.</p>
        <Link to="/admin/customers" className="mt-12 inline-block fs-14 font-semibold text-[#7a1a2a]">
          ← Clients
        </Link>
      </div>
    )
  if (!c || !form) return <div className="p-24 fs-14 text-[#8a8a8a]">Chargement…</div>

  const save = async (e: FormEvent) => {
    e.preventDefault()
    const init = toForm(c)
    const edit: Parameters<typeof adminApi.editCustomer>[1] = {}
    if (form.name !== init.name) edit.name = form.name
    if (form.city !== init.city) edit.city = form.city
    if (form.address !== init.address) edit.address = form.address
    if (form.internal_note !== init.internal_note) edit.internal_note = form.internal_note
    if (form.opted_out !== init.opted_out) edit.opted_out = form.opted_out
    if (form.tags !== init.tags)
      edit.tags = form.tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
    if (!Object.keys(edit).length) return setMessage({ kind: 'ok', text: 'Aucune modification.' })
    setSaving(true)
    setMessage(null)
    try {
      await adminApi.editCustomer(c.phone, edit)
      await load()
      setMessage({ kind: 'ok', text: 'Fiche client enregistrée.' })
    } catch (err) {
      fail(err)
    } finally {
      setSaving(false)
    }
  }

  const newOrder = async () => {
    if (!window.confirm(`Créer une commande de ${qty} déodorant(s) pour ${c.name || formatPhone(c.phone)} ?`)) return
    setCreating(true)
    setMessage(null)
    try {
      const r = await adminApi.newCustomerOrder(c.phone, qty)
      navigate(`/admin/orders/${encodeURIComponent(r.order_number)}`)
    } catch (err) {
      fail(err)
      setCreating(false)
    }
  }

  const toggleTask = async (t: Task) => {
    setBusyTask(t.id)
    try {
      await adminApi.editTask(t.id, { done: !t.done_at })
      await load()
      refreshBadge()
    } catch (err) {
      fail(err)
    } finally {
      setBusyTask(null)
    }
  }

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [k]: k === 'opted_out' ? (e.target as HTMLInputElement).checked : e.target.value })

  return (
    <div className="mx-auto w-full max-w-960 px-16 py-16 md:px-24 md:py-24">
      <div className="flex flex-wrap items-center gap-10">
        <button
          type="button"
          onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/admin/customers'))}
          aria-label="Retour"
          className="grid size-40 place-items-center rounded-full hover:bg-[#f2f2f2]"
        >
          <ArrowLeft className="size-20" strokeWidth={2} aria-hidden />
        </button>
        <h1 className="fs-22 font-bold">{c.name || formatPhone(c.phone)}</h1>
        <Pill className={SEGMENT_PILL[c.segment]}>{SEGMENT_LABEL[c.segment]}</Pill>
        {c.opted_out && <Pill className="bg-[#efefef] text-[#6b6b6b]">A écrit STOP</Pill>}
        <Link
          to={`/admin/inbox?phone=${c.phone}`}
          className="ml-auto inline-flex h-40 items-center gap-6 r-10 border border-[#e2d6d0] bg-[#fbf5f2] px-12 fs-13 font-semibold"
        >
          <MessageSquare className="size-16" strokeWidth={2} aria-hidden /> Ouvrir dans l'inbox
        </Link>
      </div>
      <p className="mt-4 fs-13 text-[#6b6b6b]">
        {formatPhone(c.phone)} · {windowOpen ? 'fenêtre WhatsApp ouverte (vous pouvez écrire)' : 'fenêtre WhatsApp fermée : le client doit écrire en premier'}
      </p>
      {c.returned > 0 && (
        <p className="mt-10 flex items-center gap-8 r-10 bg-[#fbe5e5] px-12 py-8 fs-13.5 font-semibold text-[#a12a2a]">
          <AlertTriangle className="size-16" aria-hidden /> Ce client a déjà retourné {c.returned} commande{c.returned > 1 ? 's' : ''}.
        </p>
      )}
      <Banner msg={message} />

      <div className="mt-14 grid grid-cols-2 gap-10 md:grid-cols-4">
        <Stat label="Commandes" value={String(c.orders_count)} />
        <Stat label="Livrées" value={String(c.delivered)} />
        <Stat label="Retours / annulées" value={`${c.returned} / ${c.cancelled}`} />
        {me.role === 'owner' && c.delivered_cents !== undefined ? (
          <Stat label="Valeur livrée" value={fmtMoney(c.delivered_cents)} />
        ) : (
          <Stat label="Dernière commande" value={c.last_order ? fmtDate(c.last_order) : '—'} />
        )}
      </div>

      <section className="mt-14 flex flex-wrap items-end gap-10 r-14 border border-[#ece2dd] bg-white p-14">
        <div>
          <FieldLabel htmlFor="n-qty">Nouvelle commande</FieldLabel>
          <div className="mt-6 flex items-center gap-6">
            <button type="button" aria-label="Moins" className="size-44 r-10 border border-[#ecdcd6] fs-18 md:size-40" onClick={() => setQty((q) => Math.max(1, q - 1))}>
              −
            </button>
            <span id="n-qty" className="w-32 text-center fs-16 font-semibold tabular-nums">
              {qty}
            </span>
            <button type="button" aria-label="Plus" className="size-44 r-10 border border-[#ecdcd6] fs-18 md:size-40" onClick={() => setQty((q) => Math.min(10, q + 1))}>
              +
            </button>
          </div>
        </div>
        <BusyButton type="button" busy={creating} onClick={newOrder}>
          Créer la commande ({qty * PRODUCT.price + PRODUCT.shipping} MAD)
        </BusyButton>
        <p className="w-full fs-12.5 text-[#8a8a8a]">
          Créée « en cours » (source WhatsApp) avec la ville et l’adresse de la fiche ; le bot ou l’équipe complète et confirme.
        </p>
      </section>

      <form onSubmit={save} className="mt-14 r-14 border border-[#ece2dd] bg-white p-14 md:p-18">
        <h2 className="fs-16 font-bold">Fiche client</h2>
        <div className="mt-10 grid gap-10 md:grid-cols-2">
          <div>
            <FieldLabel htmlFor="c-name">Nom</FieldLabel>
            <input id="c-name" maxLength={80} className={inputClass} value={form.name} onChange={set('name')} />
          </div>
          <div>
            <FieldLabel htmlFor="c-city">Ville</FieldLabel>
            <input id="c-city" maxLength={80} className={inputClass} value={form.city} onChange={set('city')} />
          </div>
          <div className="md:col-span-2">
            <FieldLabel htmlFor="c-address">Adresse</FieldLabel>
            <input id="c-address" maxLength={300} className={inputClass} value={form.address} onChange={set('address')} />
          </div>
          <div className="md:col-span-2">
            <FieldLabel htmlFor="c-tags">Étiquettes (séparées par des virgules)</FieldLabel>
            <input id="c-tags" maxLength={300} placeholder="VIP, Grossiste" className={inputClass} value={form.tags} onChange={set('tags')} />
          </div>
          <div className="md:col-span-2">
            <FieldLabel htmlFor="c-note">Note interne</FieldLabel>
            <textarea id="c-note" maxLength={2000} rows={3} className={`${inputClass} h-auto py-10`} value={form.internal_note} onChange={set('internal_note')} />
          </div>
        </div>
        <label className="mt-10 flex min-h-40 items-center gap-10 fs-14">
          <input type="checkbox" className="size-20 accent-[#3a0a10]" checked={form.opted_out} onChange={set('opted_out')} />
          Le client ne veut plus recevoir de messages (STOP)
        </label>
        <BusyButton type="submit" busy={saving} className="mt-10">
          Enregistrer
        </BusyButton>
      </form>

      <section className="mt-14 r-14 border border-[#ece2dd] bg-white">
        <h2 className="border-b border-[#f1e8e4] px-14 py-12 fs-16 font-bold">Commandes ({orders.length})</h2>
        {orders.length === 0 ? (
          <p className="px-14 py-12 fs-14 text-[#8a8a8a]">Aucune commande.</p>
        ) : (
          <ul className="divide-y divide-[#f4eeeb]">
            {orders.map((o) => (
              <li key={o.order_number}>
                <Link to={`/admin/orders/${encodeURIComponent(o.order_number)}`} className="flex flex-wrap items-center gap-x-12 gap-y-4 px-14 py-10 hover:bg-[#fbf8f6]">
                  <span className="w-120 fs-14 font-semibold">{o.order_number}</span>
                  <StatusPill status={o.status} />
                  <span className="flex-1 fs-13 text-[#6b6b6b]">
                    {[`${o.quantity} × · ${o.total} MAD`, o.city, o.carrier, o.status === 'returned' && o.return_reason ? `retour : ${o.return_reason}` : '']
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                  <span className="fs-12.5 text-[#8a8a8a]">{fmtDate(o.created_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-14 r-14 border border-[#ece2dd] bg-white">
        <div className="flex items-center justify-between gap-10 border-b border-[#f1e8e4] px-14 py-8">
          <h2 className="fs-16 font-bold">Relances ({tasks.length})</h2>
          <BusyButton type="button" variant="secondary" onClick={() => setAddingTask((v) => !v)}>
            Ajouter
          </BusyButton>
        </div>
        {addingTask && (
          <div className="px-14 pb-14">
            <NewTaskForm
              team={team}
              phone={c.phone}
              onDone={async () => {
                setAddingTask(false)
                await load()
                refreshBadge()
                setMessage({ kind: 'ok', text: 'Relance ajoutée.' })
              }}
              onError={fail}
            />
          </div>
        )}
        {tasks.length === 0 ? (
          <p className="px-14 py-12 fs-14 text-[#8a8a8a]">Aucune relance en cours.</p>
        ) : (
          <ul className="divide-y divide-[#f4eeeb]">
            {tasks.map((t) => (
              <TaskItem key={t.id} t={t} busy={busyTask === t.id} onToggle={() => toggleTask(t)} />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="r-10 bg-[#faf6f3] px-12 py-10">
      <p className="fs-12 text-[#6b6b6b]">{label}</p>
      <p className="mt-4 fs-15 font-bold tabular-nums">{value}</p>
    </div>
  )
}
