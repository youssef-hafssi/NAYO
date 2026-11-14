import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, MessageSquare, User } from 'lucide-react'
import { adminApi, Unauthorized, type AuditEntry, type FullOrder, type OrderEdit, type SettableStatus, type StockMovement, type Carrier, type Message, type OrderCustomer } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { BusyButton, Chip, FieldLabel, fmtDateTime, hhmm, Pill, SEGMENT_LABEL, SEGMENT_PILL, fmtMoney, formatPhone, inputClass, parseMad, StatusPill, STOCK_REASON, withStockConfirm } from './ui'

/* Order detail: every editable field (each change audited), status changes, history. */

const STATUS_ACTIONS: { status: SettableStatus; label: string }[] = [
  { status: 'confirmed', label: 'Confirmée' },
  { status: 'shipped', label: 'Expédiée' },
  { status: 'delivered', label: 'Livrée' },
  { status: 'returned', label: 'Retournée' },
  { status: 'cancelled', label: 'Annulée' },
  { status: 'needs_human', label: "Besoin d'aide" },
]

const FIELD_LABEL: Record<string, string> = {
  name: 'Nom',
  phone: 'Téléphone',
  city: 'Ville',
  address: 'Adresse',
  quantity: 'Quantité',
  carrier: 'Transporteur',
  tracking: 'N° de suivi',
  internal_note: 'Note interne',
}

type Form = { name: string; phone: string; city: string; address: string; quantity: string; carrier: string; tracking: string; internal_note: string }

const toForm = (o: FullOrder): Form => ({
  name: o.name,
  phone: formatPhone(o.phone),
  city: o.city,
  address: o.address,
  quantity: String(o.quantity),
  carrier: o.carrier,
  tracking: o.tracking,
  internal_note: o.internal_note,
})

export default function OrderDetail() {
  const { number = '' } = useParams()
  const { me, logout } = useAuth()
  const [carriers, setCarriers] = useState<Carrier[]>([])
  const [fee, setFee] = useState('')
  const [deliveryBusy, setDeliveryBusy] = useState(false)
  const navigate = useNavigate()
  const [order, setOrder] = useState<FullOrder | null>(null)
  const [history, setHistory] = useState<AuditEntry[]>([])
  const [lastModified, setLastModified] = useState<AuditEntry | null>(null)
  const [form, setForm] = useState<Form | null>(null)
  const [saving, setSaving] = useState(false)
  const [statusBusy, setStatusBusy] = useState<string | null>(null)
  const [returning, setReturning] = useState(false)
  const [returnReason, setReturnReason] = useState('')
  const [recoverable, setRecoverable] = useState(true)
  const [moves, setMoves] = useState<StockMovement[]>([])
  const [thread, setThread] = useState<Message[]>([])
  const [customer, setCustomer] = useState<OrderCustomer | null>(null)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [notFound, setNotFound] = useState(false)

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof Unauthorized) logout()
      else setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })
    },
    [logout],
  )

  const load = useCallback(async () => {
    try {
      const r = await adminApi.getOrder(number)
      setOrder(r.order)
      setForm(toForm(r.order))
      setHistory(r.history)
      setLastModified(r.last_modified)
      setMoves(r.stock_movements ?? [])
      setThread(r.thread ?? [])
      setCustomer(r.customer ?? null)
      setFee(r.order.carrier_fee_cents ? (Number(r.order.carrier_fee_cents) / 100).toString().replace('.', ',') : '')
    } catch (e) {
      if (e instanceof Error && /not found|404/.test(e.message)) setNotFound(true)
      else fail(e)
    }
  }, [number, fail])

  useEffect(() => {
    adminApi
      .carriers()
      .then((c) => setCarriers(c.items))
      .catch(() => undefined)
  }, [])

  const saveDelivery = async (edit: { carrier_id?: number; carrier_fee?: number }, ok: string) => {
    if (deliveryBusy || !order) return
    setDeliveryBusy(true)
    setMessage(null)
    try {
      await adminApi.editOrder(order.order_number, edit)
      setMessage({ kind: 'ok', text: ok })
      await load()
    } catch (err) {
      fail(err)
    } finally {
      setDeliveryBusy(false)
    }
  }

  useEffect(() => {
    load()
  }, [load])

  if (notFound) {
    return (
      <div className="p-24">
        <p className="fs-14">Commande {number} introuvable.</p>
        <Link to="/admin/inbox" className="mt-12 inline-block fs-14 font-semibold text-[#7a1a2a]">
          ← Retour
        </Link>
      </div>
    )
  }
  if (!order || !form) return <div className="p-24 fs-14 text-[#8a8a8a]">Chargement…</div>

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [k]: e.target.value })

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (saving) return
    const initial = toForm(order)
    const edit: OrderEdit = {}
    for (const k of Object.keys(form) as (keyof Form)[]) {
      if (form[k] === initial[k]) continue
      if (k === 'quantity') {
        const q = Number(form.quantity)
        if (!Number.isInteger(q) || q < 1 || q > 10) {
          setMessage({ kind: 'error', text: 'La quantité doit être entre 1 et 10.' })
          return
        }
        edit.quantity = q
      } else edit[k] = form[k]
    }
    if (!Object.keys(edit).length) {
      setMessage({ kind: 'ok', text: 'Aucune modification.' })
      return
    }
    setSaving(true)
    setMessage(null)
    try {
      let r: Awaited<ReturnType<typeof adminApi.editOrder>> | undefined
      const done = await withStockConfirm(async (force) => {
        r = await adminApi.editOrder(order.order_number, force ? { ...edit, force } : edit)
      })
      if (!done || !r) return
      setMessage({ kind: 'ok', text: `Enregistré : ${r.changed.map((c) => FIELD_LABEL[c] ?? c).join(', ')}` })
      await load()
    } catch (err) {
      fail(err)
    } finally {
      setSaving(false)
    }
  }

  const changeStatus = async (status: SettableStatus, reason?: string) => {
    if (statusBusy || status === order.status) return
    if (status === 'returned' && reason === undefined) {
      setReturning(true)
      return
    }
    setStatusBusy(status)
    setMessage(null)
    try {
      const done = await withStockConfirm((force) =>
        adminApi.setStatus(order.order_number, status, {
          ...(status === 'returned' ? { return_reason: reason, recoverable } : {}),
          ...(force ? { force } : {}),
        }),
      )
      if (!done) return
      setReturning(false)
      setRecoverable(true)
      setReturnReason('')
      await load()
    } catch (err) {
      fail(err)
    } finally {
      setStatusBusy(null)
    }
  }

  const field = (k: keyof Form, opts: { type?: string; inputMode?: 'numeric' | 'tel' } = {}) => (
    <div>
      <FieldLabel htmlFor={`f-${k}`}>{FIELD_LABEL[k]}</FieldLabel>
      <input id={`f-${k}`} value={form[k]} onChange={set(k)} type={opts.type ?? 'text'} inputMode={opts.inputMode} className={inputClass} />
    </div>
  )

  return (
    <div className="mx-auto w-full max-w-960 px-16 py-16 md:px-24 md:py-24">
      <div className="flex flex-wrap items-center gap-10">
        <button
          type="button"
          onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/admin/inbox'))}
          aria-label="Retour"
          className="grid size-40 place-items-center rounded-full hover:bg-[#f2f2f2]"
        >
          <ArrowLeft className="size-20" strokeWidth={2} aria-hidden />
        </button>
        <h1 className="fs-22 font-bold">{order.order_number}</h1>
        <StatusPill status={order.status} />
        <span className="fs-12.5 text-[#8a8a8a]">
          {[order.source === 'whatsapp' ? 'via WhatsApp' : order.source === 'website' ? 'via le site' : '', `créée le ${fmtDateTime(order.created_at)}`]
            .filter(Boolean)
            .join(' · ')}
        </span>
        <Link
          to={`/admin/inbox?phone=${order.phone}`}
          className="ml-auto inline-flex h-40 items-center gap-6 r-10 border border-[#e2d6d0] bg-[#fbf5f2] px-12 fs-13 font-semibold"
        >
          <MessageSquare className="size-16" strokeWidth={2} aria-hidden /> Ouvrir dans l'inbox
        </Link>
      </div>
      {lastModified && (
        <p className="mt-6 fs-12.5 text-[#7a6f6f]">
          Modifié par {lastModified.admin_name} le {fmtDateTime(lastModified.at)}
        </p>
      )}

      {customer && (
        <div className="mt-10 flex flex-wrap items-center gap-8">
          <Link
            to={`/admin/customers/${order.phone}`}
            className="inline-flex h-40 items-center gap-6 r-10 border border-[#e2d6d0] bg-white px-12 fs-13 font-semibold"
          >
            <User className="size-16" aria-hidden /> Fiche client · {customer.orders_count} commande{customer.orders_count > 1 ? 's' : ''}
          </Link>
          <Pill className={SEGMENT_PILL[customer.segment]}>{SEGMENT_LABEL[customer.segment]}</Pill>
          {customer.returned > 0 && (
            <span className="inline-flex items-center gap-4 r-5 bg-[#fbe5e5] px-8 py-2 fs-12 font-semibold text-[#a12a2a]">
              <AlertTriangle className="size-14" aria-hidden /> A déjà retourné {customer.returned} commande{customer.returned > 1 ? 's' : ''}
            </span>
          )}
          {customer.opted_out && <Pill className="bg-[#efefef] text-[#6b6b6b]">A écrit STOP</Pill>}
          {customer.tags.map((t) => (
            <Pill key={t} className="bg-[#f4eeeb] text-[#3a0a10]">
              {t}
            </Pill>
          ))}
        </div>
      )}

      {message && (
        <p role={message.kind === 'error' ? 'alert' : 'status'} className={`mt-12 r-8 px-12 py-8 fs-13 ${message.kind === 'error' ? 'bg-[#fbe5e5] text-[#a12a2a]' : 'bg-[#e7f6ec] text-[#1f6a3c]'}`}>
          {message.text}
        </p>
      )}

      {/* Status */}
      <section className="mt-18">
        <FieldLabel>Statut</FieldLabel>
        <div className="mt-8 flex flex-wrap gap-8">
          {STATUS_ACTIONS.map((a) => (
            <Chip key={a.status} active={order.status === a.status} onClick={() => changeStatus(a.status)}>
              {statusBusy === a.status ? '…' : a.label}
            </Chip>
          ))}
        </div>
        {returning && (
          <div className="mt-12 r-10 border border-[#f0d4d4] bg-[#fdf6f6] p-12">
            <FieldLabel htmlFor="ret">Raison du retour (refus, absent, injoignable…)</FieldLabel>
            <input id="ret" value={returnReason} onChange={(e) => setReturnReason(e.target.value)} maxLength={300} className={inputClass} />
            <label className="mt-10 flex min-h-40 items-center gap-10 fs-14">
              <input type="checkbox" checked={recoverable} onChange={(e) => setRecoverable(e.target.checked)} className="size-18 accent-[#3a0a10]" />
              Produit récupérable (il revient dans le stock)
            </label>
            <div className="mt-10 flex gap-8">
              <BusyButton busy={statusBusy === 'returned'} onClick={() => changeStatus('returned', returnReason.trim())}>
                Marquer retournée
              </BusyButton>
              <BusyButton variant="secondary" onClick={() => setReturning(false)}>
                Annuler
              </BusyButton>
            </div>
          </div>
        )}
        {order.status === 'returned' && order.return_reason && (
          <p className="mt-8 fs-13 text-[#a12a2a]">Raison du retour : {order.return_reason}</p>
        )}
        {order.delivered_at && <p className="mt-8 fs-13 text-[#17703c]">Livrée le {fmtDateTime(order.delivered_at)}</p>}
      </section>

      {/* Delivery & cash on delivery */}
      <section className="mt-18 r-12 border border-[#efe7e3] p-14">
        <FieldLabel htmlFor="od-carrier">Livreur</FieldLabel>
        <div className="mt-6 flex flex-wrap items-center gap-10">
          <select
            id="od-carrier"
            value={order.carrier_id || ''}
            disabled={deliveryBusy || order.cod_status === 'remitted'}
            onChange={(e) => saveDelivery({ carrier_id: Number(e.target.value || 0) }, 'Livreur enregistré.')}
            className={`${inputClass} !mt-0 w-auto min-w-180`}
          >
            <option value="">— Aucun —</option>
            {carriers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
            {order.carrier_id && !carriers.some((c) => String(c.id) === order.carrier_id) && (
              <option value={order.carrier_id}>{order.carrier || 'Livreur désactivé'}</option>
            )}
          </select>
          {order.cod_status === 'with_carrier' && <Pill className="bg-[#fdf0de] text-[#c2650a]">Argent chez le livreur</Pill>}
          {order.cod_status === 'remitted' && <Pill className="bg-[#dff3e6] text-[#17703c]">Encaissée</Pill>}
          {order.cod_status === 'none' && <Pill className="bg-[#efefef] text-[#6b6b6b]">Rien à encaisser</Pill>}
        </div>
        {me.role === 'owner' && (order.status === 'delivered' || order.status === 'returned') && (
          <div className="mt-12 flex flex-wrap items-end gap-10">
            <div className="w-180">
              <FieldLabel htmlFor="od-fee">Frais du livreur (MAD)</FieldLabel>
              <input id="od-fee" inputMode="decimal" value={fee} disabled={order.cod_status === 'remitted'} onChange={(e) => setFee(e.target.value)} className={inputClass} />
            </div>
            <BusyButton
              variant="secondary"
              busy={deliveryBusy}
              disabled={order.cod_status === 'remitted' || Number.isNaN(parseMad(fee))}
              onClick={() => saveDelivery({ carrier_fee: parseMad(fee) }, 'Frais enregistrés.')}
            >
              Enregistrer
            </BusyButton>
            {order.cod_amount_cents && Number(order.cod_amount_cents) > 0 && (
              <span className="fs-13 text-[#5a4f4f]">
                À recevoir : {fmtMoney(Number(order.cod_amount_cents) - Number(order.carrier_fee_cents || 0))}
              </span>
            )}
          </div>
        )}
      </section>

      {/* Editable fields */}
      <form onSubmit={save} className="mt-20 grid gap-14 md:grid-cols-2">
        {field('name')}
        {field('phone', { type: 'tel', inputMode: 'tel' })}
        {field('city')}
        {field('quantity', { inputMode: 'numeric' })}
        <div className="md:col-span-2">{field('address')}</div>
        {field('tracking')}
        <div className="md:col-span-2">
          <FieldLabel htmlFor="f-note">Note interne</FieldLabel>
          <textarea
            id="f-note"
            value={form.internal_note}
            onChange={set('internal_note')}
            rows={3}
            maxLength={2000}
            className="mt-6 w-full r-10 border border-[#ecdcd6] bg-[#fbf5f2] px-14 py-10 fs-16 outline-none focus:border-[#7a1a2a] md:fs-14"
          />
        </div>
        <div className="flex flex-wrap items-center gap-12 md:col-span-2">
          <BusyButton type="submit" busy={saving}>
            Enregistrer
          </BusyButton>
          <span className="fs-13 text-[#7a6f6f]">
            Total : <strong className="text-[#1a1a1a]">{order.total} MAD</strong> ({order.quantity} × {order.unit_price} MAD + {order.shipping} MAD livraison)
          </span>
        </div>
      </form>

      {/* History */}
      {moves.length > 0 && (
        <section className="mt-28">
          <FieldLabel>Mouvements de stock</FieldLabel>
          <ul className="mt-8 divide-y divide-[#efe7e3] r-10 border border-[#efe7e3]">
            {moves.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-x-12 gap-y-2 px-12 py-10 fs-13">
                <span className="text-[#8a8a8a]">{fmtDateTime(m.at)}</span>
                <span className="font-semibold">{STOCK_REASON[m.reason] ?? m.reason}</span>
                <span className={m.delta < 0 ? 'text-[#a12a2a]' : 'text-[#17703c]'}>
                  {m.written_off ? `${m.written_off} perdue(s)` : `${m.delta > 0 ? '+' : ''}${m.delta}`}
                </span>
                {m.unit_cost_cents !== undefined && <span className="text-[#7a6f6f]">à {fmtMoney(m.unit_cost_cents)}</span>}
                <span className="ml-auto text-[#7a6f6f]">stock : {m.balance_after}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-28">
        <FieldLabel>Historique</FieldLabel>
        {history.length === 0 ? (
          <p className="mt-8 fs-13 text-[#8a8a8a]">Aucune action de l'équipe pour le moment.</p>
        ) : (
          <ul className="mt-8 divide-y divide-[#f0e8e4] r-10 border border-[#eee4df]">
            {history.map((h, i) => (
              <li key={i} className="flex flex-wrap gap-x-10 px-12 py-10 fs-13">
                <span className="text-[#8a8a8a]">{fmtDateTime(h.at)}</span>
                <span className="font-semibold">{h.admin_name}</span>
                <span className="min-w-0 break-words">{h.details || h.action}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {/* Conversation preview */}
      <section className="mt-24">
        <div className="flex items-center justify-between gap-10">
          <FieldLabel>Derniers messages</FieldLabel>
          <Link to={`/admin/inbox?phone=${order.phone}`} className="fs-13 font-semibold text-[#7a1a2a] underline">
            Ouvrir dans l'inbox
          </Link>
        </div>
        {thread.length === 0 ? (
          <p className="mt-8 fs-13 text-[#8a8a8a]">Aucun message WhatsApp avec ce numéro.</p>
        ) : (
          <ul className="mt-8 space-y-6 r-12 bg-[#f8f4f1] p-12">
            {thread.map((m, i) => (
              <li key={`${m.at}-${i}`} className={`flex ${m.role === 'client' ? 'justify-start' : 'justify-end'}`}>
                <p
                  className={`max-w-[85%] whitespace-pre-wrap break-words r-10 px-10 py-6 fs-13 ${
                    m.role === 'client' ? 'bg-white' : m.role === 'agent' ? 'bg-[#f1e3e5]' : 'bg-[#e9efe9]'
                  }`}
                >
                  <span className="mr-6 fs-11 font-semibold text-[#8a8a8a]">
                    {m.role === 'client' ? 'Client' : m.role === 'agent' ? m.agent_name || 'Équipe' : 'Bot'} · {hhmm(m.at)}
                  </span>
                  {m.text.length > 280 ? m.text.slice(0, 280) + '…' : m.text}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
