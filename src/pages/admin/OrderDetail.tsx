import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, MessageSquare } from 'lucide-react'
import { adminApi, Unauthorized, type AuditEntry, type FullOrder, type OrderEdit, type SettableStatus } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { BusyButton, Chip, FieldLabel, fmtDateTime, formatPhone, inputClass, StatusPill } from './ui'

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
  const { logout } = useAuth()
  const navigate = useNavigate()
  const [order, setOrder] = useState<FullOrder | null>(null)
  const [history, setHistory] = useState<AuditEntry[]>([])
  const [lastModified, setLastModified] = useState<AuditEntry | null>(null)
  const [form, setForm] = useState<Form | null>(null)
  const [saving, setSaving] = useState(false)
  const [statusBusy, setStatusBusy] = useState<string | null>(null)
  const [returning, setReturning] = useState(false)
  const [returnReason, setReturnReason] = useState('')
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
    } catch (e) {
      if (e instanceof Error && /not found|404/.test(e.message)) setNotFound(true)
      else fail(e)
    }
  }, [number, fail])

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
      const r = await adminApi.editOrder(order.order_number, edit)
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
      await adminApi.setStatus(order.order_number, status, status === 'returned' ? { return_reason: reason } : undefined)
      setReturning(false)
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

      {/* Editable fields */}
      <form onSubmit={save} className="mt-20 grid gap-14 md:grid-cols-2">
        {field('name')}
        {field('phone', { type: 'tel', inputMode: 'tel' })}
        {field('city')}
        {field('quantity', { inputMode: 'numeric' })}
        <div className="md:col-span-2">{field('address')}</div>
        {field('carrier')}
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
    </div>
  )
}
