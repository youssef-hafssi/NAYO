import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { adminApi, Unauthorized, type PurchaseOrder, type Receipt, type Supplier, type SupplierPayment } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import {
  BusyButton,
  FieldLabel,
  fmtDate,
  fmtDateTime,
  fmtMoney,
  inputClass,
  METHOD_LABEL,
  parseMad,
  PAYMENT_LABEL,
  Pill,
  PO_STATUS_LABEL,
  PO_STATUS_PILL,
} from './ui'

/* One purchase order: amounts, "Réceptionner" (stock entry at the landed cost), "Enregistrer un paiement". */

export default function PurchaseOrderDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { me, logout } = useAuth()
  const [po, setPo] = useState<PurchaseOrder | null>(null)
  const [supplier, setSupplier] = useState<Supplier | null>(null)
  const [receipts, setReceipts] = useState<Receipt[]>([])
  const [payments, setPayments] = useState<SupplierPayment[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [recvQty, setRecvQty] = useState('')
  const [payAmount, setPayAmount] = useState('')
  const [payMethod, setPayMethod] = useState('virement')
  const [payNote, setPayNote] = useState('')
  const [expected, setExpected] = useState('')

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof Unauthorized) logout()
      else setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })
    },
    [logout],
  )

  const load = useCallback(async () => {
    try {
      const r = await adminApi.getPO(Number(id))
      setPo(r.po)
      setSupplier(r.supplier)
      setReceipts(r.receipts)
      setPayments(r.payments)
      setExpected(r.po.expected_at ?? '')
    } catch (e) {
      fail(e)
    }
  }, [id, fail])

  useEffect(() => {
    load()
  }, [load])

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    if (busy) return
    setBusy(true)
    setMessage(null)
    try {
      await fn()
      setMessage({ kind: 'ok', text: ok })
      await load()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  if (me.role !== 'owner') return <div className="p-24 fs-14 text-[#8a8a8a]">Réservé au propriétaire.</div>
  if (!po) return <div className="p-24 fs-14 text-[#8a8a8a]">{message?.text ?? 'Chargement…'}</div>

  const receive = (e: FormEvent) => {
    e.preventDefault()
    const q = Number(recvQty || po.remaining_qty)
    if (!Number.isInteger(q) || q < 1 || q > po.remaining_qty) {
      return setMessage({ kind: 'error', text: `Entre 1 et ${po.remaining_qty}.` })
    }
    act(async () => {
      await adminApi.receivePO(po.id, q)
      setRecvQty('')
    }, `${q} unité(s) réceptionnée(s) et ajoutée(s) au stock à ${fmtMoney(po.landed_unit_cost_cents)} l'unité.`)
  }

  const pay = (e: FormEvent) => {
    e.preventDefault()
    const amount = parseMad(payAmount)
    if (Number.isNaN(amount) || amount <= 0) return setMessage({ kind: 'error', text: 'Montant invalide (ex. 1500,00).' })
    act(async () => {
      await adminApi.payPO(po.id, amount, payMethod, payNote)
      setPayAmount('')
      setPayNote('')
    }, 'Paiement enregistré.')
  }

  const canReceive = ['draft', 'ordered', 'partially_received'].includes(po.status) && po.remaining_qty > 0
  const canPay = ['ordered', 'partially_received', 'received'].includes(po.status) && po.due_cents > 0

  return (
    <div className="mx-auto w-full max-w-960 px-16 py-16 md:px-24 md:py-24">
      <div className="flex flex-wrap items-center gap-10">
        <button
          type="button"
          onClick={() => navigate('/admin/purchasing')}
          aria-label="Retour"
          className="grid size-40 place-items-center rounded-full hover:bg-[#f2f2f2]"
        >
          <ArrowLeft className="size-20" strokeWidth={2} aria-hidden />
        </button>
        <h1 className="fs-22 font-bold">{po.number}</h1>
        <Pill className={PO_STATUS_PILL[po.status]}>{PO_STATUS_LABEL[po.status]}</Pill>
        {po.late && <Pill className="bg-[#fbe5e5] text-[#a12a2a]">En retard</Pill>}
        <span className="fs-13 text-[#7a6f6f]">{supplier?.name}</span>
      </div>

      {message && (
        <p role={message.kind === 'error' ? 'alert' : 'status'} className={`mt-12 r-8 px-12 py-8 fs-13 ${message.kind === 'error' ? 'bg-[#fbe5e5] text-[#a12a2a]' : 'bg-[#e7f6ec] text-[#1f6a3c]'}`}>
          {message.text}
        </p>
      )}

      <section className="mt-16 r-12 bg-[#f6efea] p-16">
        <Row label={`${po.quantity} × ${fmtMoney(po.unit_cost_cents)}`} value={fmtMoney(po.quantity * po.unit_cost_cents)} />
        {po.shipping_cost_cents > 0 && <Row label="Transport" value={fmtMoney(po.shipping_cost_cents)} />}
        {po.other_costs_cents > 0 && <Row label="Autres frais" value={fmtMoney(po.other_costs_cents)} />}
        <div className="my-10 h-px bg-[#e3d6cf]" />
        <Row label="Total" value={fmtMoney(po.total_cents)} bold />
        <Row label="Coût rendu par unité (frais inclus)" value={fmtMoney(po.landed_unit_cost_cents)} muted />
        {po.status !== 'draft' && po.status !== 'cancelled' && (
          <>
            <Row label="Payé" value={fmtMoney(po.paid_cents)} muted />
            <Row label={`Reste à payer · ${PAYMENT_LABEL[po.payment_status]}`} value={fmtMoney(po.due_cents)} bold={po.due_cents > 0} />
          </>
        )}
      </section>

      <section className="mt-14 grid gap-10 fs-13.5 sm:grid-cols-3">
        <div>
          <FieldLabel>Commandée le</FieldLabel>
          <p className="mt-4">{fmtDate(po.ordered_at)}</p>
        </div>
        <div>
          <FieldLabel htmlFor="exp">Livraison prévue</FieldLabel>
          <div className="mt-4 flex gap-8">
            <input id="exp" type="date" value={expected} onChange={(e) => setExpected(e.target.value)} className={inputClass} />
            {expected !== (po.expected_at ?? '') && (
              <BusyButton variant="secondary" busy={busy} onClick={() => act(() => adminApi.editPO(po.id, { expected_at: expected || null }), 'Date enregistrée.')}>
                OK
              </BusyButton>
            )}
          </div>
        </div>
        <div>
          <FieldLabel>Reçues</FieldLabel>
          <p className="mt-4">
            {po.received_qty} / {po.quantity}
          </p>
        </div>
        {po.note && <p className="text-[#5a4f4f] sm:col-span-3">{po.note}</p>}
      </section>

      <div className="mt-14 flex flex-wrap gap-8">
        {po.status === 'draft' && (
          <BusyButton busy={busy} onClick={() => act(() => adminApi.setPOStatus(po.id, 'ordered'), 'Commande passée.')}>
            Passer la commande
          </BusyButton>
        )}
        {po.received_qty === 0 && po.status !== 'cancelled' && (
          <BusyButton
            variant="danger"
            busy={busy}
            onClick={() => window.confirm(`Annuler ${po.number} ?`) && act(() => adminApi.setPOStatus(po.id, 'cancelled'), 'Commande annulée.')}
          >
            Annuler la commande
          </BusyButton>
        )}
      </div>

      {canReceive && (
        <form onSubmit={receive} className="mt-18 r-12 border border-[#ecdcd6] p-14">
          <h2 className="fs-15 font-bold">Réceptionner</h2>
          <p className="mt-4 fs-12.5 text-[#7a6f6f]">
            Ajoute au stock à {fmtMoney(po.landed_unit_cost_cents)} l'unité. Une réception ne se modifie pas : une erreur se corrige depuis
            le stock, avec une note.
          </p>
          <div className="mt-10 flex flex-wrap items-end gap-10">
            <div className="w-160">
              <FieldLabel htmlFor="rq">Quantité (reste {po.remaining_qty})</FieldLabel>
              <input id="rq" inputMode="numeric" placeholder={String(po.remaining_qty)} value={recvQty} onChange={(e) => setRecvQty(e.target.value)} className={inputClass} />
            </div>
            <BusyButton type="submit" busy={busy}>
              Réceptionner
            </BusyButton>
          </div>
        </form>
      )}

      {canPay && (
        <form onSubmit={pay} className="mt-14 r-12 border border-[#ecdcd6] p-14">
          <h2 className="fs-15 font-bold">Enregistrer un paiement</h2>
          <div className="mt-10 grid gap-10 sm:grid-cols-[1fr_1fr_2fr_auto] sm:items-end">
            <div>
              <FieldLabel htmlFor="pa">Montant (MAD)</FieldLabel>
              <input id="pa" inputMode="decimal" placeholder={(po.due_cents / 100).toFixed(2).replace('.', ',')} value={payAmount} onChange={(e) => setPayAmount(e.target.value)} className={inputClass} />
            </div>
            <div>
              <FieldLabel htmlFor="pm">Mode</FieldLabel>
              <select id="pm" value={payMethod} onChange={(e) => setPayMethod(e.target.value)} className={inputClass}>
                {Object.entries(METHOD_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel htmlFor="pn">Note</FieldLabel>
              <input id="pn" value={payNote} maxLength={300} onChange={(e) => setPayNote(e.target.value)} className={inputClass} />
            </div>
            <BusyButton type="submit" busy={busy}>
              Enregistrer
            </BusyButton>
          </div>
        </form>
      )}

      <section className="mt-20 grid gap-16 md:grid-cols-2">
        <List
          title="Réceptions"
          empty="Aucune réception."
          rows={receipts.map((r) => [fmtDateTime(r.at), `+${r.quantity}`, fmtMoney(r.landed_unit_cost_cents), r.admin_name])}
        />
        <List
          title="Paiements"
          empty="Aucun paiement."
          rows={payments.map((p) => [fmtDate(p.at), fmtMoney(p.amount_cents), METHOD_LABEL[p.method] ?? p.method, p.note || p.admin_name])}
        />
      </section>
    </div>
  )
}

function Row({ label, value, bold, muted }: { label: string; value: string; bold?: boolean; muted?: boolean }) {
  return (
    <div className={`mt-4 flex justify-between gap-12 ${bold ? 'fs-14 font-bold' : 'fs-13.5'} ${muted ? 'text-[#7a6f6f]' : ''}`}>
      <span>{label}</span>
      <span className="whitespace-nowrap">{value}</span>
    </div>
  )
}

function List({ title, rows, empty }: { title: string; rows: string[][]; empty: string }) {
  return (
    <div>
      <FieldLabel>{title}</FieldLabel>
      {rows.length === 0 ? (
        <p className="mt-6 fs-13 text-[#8a8a8a]">{empty}</p>
      ) : (
        <ul className="mt-6 divide-y divide-[#efe7e3] r-10 border border-[#efe7e3]">
          {rows.map((r, i) => (
            <li key={i} className="flex flex-wrap justify-between gap-x-10 px-12 py-8 fs-13">
              <span className="text-[#8a8a8a]">{r[0]}</span>
              <span className="font-semibold">{r[1]}</span>
              <span className="text-[#7a6f6f]">{r[2]}</span>
              {r[3] && <span className="w-full fs-12 text-[#8a8a8a]">{r[3]}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
