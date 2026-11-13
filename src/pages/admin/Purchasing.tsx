import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { adminApi, Unauthorized, type PurchaseOrder, type Supplier } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import {
  BusyButton,
  Chip,
  FieldLabel,
  fmtDate,
  fmtMoney,
  inputClass,
  parseMad,
  PAYMENT_LABEL,
  Pill,
  PO_STATUS_LABEL,
  PO_STATUS_PILL,
} from './ui'

/* Achats (owner only, server-enforced): purchase orders and suppliers. */

const STATUS_FILTERS: { key: string; label: string }[] = [
  { key: '', label: 'Toutes' },
  { key: 'late', label: 'En retard' },
  { key: 'ordered', label: 'Commandées' },
  { key: 'partially_received', label: 'Reçues en partie' },
  { key: 'received', label: 'Reçues' },
  { key: 'draft', label: 'Brouillons' },
  { key: 'cancelled', label: 'Annulées' },
]

export default function Purchasing() {
  const { me, logout } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'suppliers' ? 'suppliers' : 'orders'
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof Unauthorized) logout()
      else setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })
    },
    [logout],
  )

  if (me.role !== 'owner') return <div className="p-24 fs-14 text-[#8a8a8a]">Réservé au propriétaire.</div>

  return (
    <div className="mx-auto w-full max-w-1100 px-16 py-16 md:px-24 md:py-24">
      <h1 className="fs-22 font-bold">Achats</h1>
      <div className="mt-12 flex gap-8" role="tablist">
        <Chip active={tab === 'orders'} onClick={() => setParams({})}>
          Commandes fournisseurs
        </Chip>
        <Chip active={tab === 'suppliers'} onClick={() => setParams({ tab: 'suppliers' })}>
          Fournisseurs
        </Chip>
      </div>
      {message && (
        <p role={message.kind === 'error' ? 'alert' : 'status'} className={`mt-12 r-8 px-12 py-8 fs-13 ${message.kind === 'error' ? 'bg-[#fbe5e5] text-[#a12a2a]' : 'bg-[#e7f6ec] text-[#1f6a3c]'}`}>
          {message.text}
        </p>
      )}
      {tab === 'orders' ? <Orders fail={fail} setMessage={setMessage} /> : <Suppliers fail={fail} setMessage={setMessage} />}
    </div>
  )
}

type Ctx = {
  fail: (e: unknown) => void
  setMessage: (m: { kind: 'ok' | 'error'; text: string } | null) => void
}

// ------------------------------------------------------------------ purchase orders
function Orders({ fail, setMessage }: Ctx) {
  const [filter, setFilter] = useState('')
  const [items, setItems] = useState<PurchaseOrder[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [summary, setSummary] = useState<{ debts_cents: number; open: number; late: number } | null>(null)
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [creating, setCreating] = useState(false)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ supplier_id: '', quantity: '', unit_cost: '', shipping_cost: '', other_costs: '', expected_at: '', note: '' })

  const query = useCallback(
    (offset: number) =>
      adminApi.purchaseOrders(filter === 'late' ? { late: true, offset } : { status: filter || undefined, offset }),
    [filter],
  )

  const load = useCallback(async () => {
    try {
      const [list, sum, sup] = await Promise.all([query(0), adminApi.purchasingSummary(), adminApi.suppliers()])
      setItems(list.items)
      setHasMore(list.has_more)
      setSummary(sum)
      setSuppliers(sup.items)
    } catch (e) {
      fail(e)
    }
  }, [query, fail])

  useEffect(() => {
    load()
  }, [load])

  const more = async () => {
    if (busy) return
    setBusy(true)
    try {
      const r = await query(items.length)
      setItems((l) => [...l, ...r.items])
      setHasMore(r.has_more)
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const create = async (e: FormEvent, status: 'draft' | 'ordered') => {
    e.preventDefault()
    if (busy) return
    const quantity = Number(form.quantity)
    const unit = parseMad(form.unit_cost)
    const ship = parseMad(form.shipping_cost)
    const other = parseMad(form.other_costs)
    if (!form.supplier_id) return setMessage({ kind: 'error', text: 'Choisissez un fournisseur.' })
    if (!Number.isInteger(quantity) || quantity < 1) return setMessage({ kind: 'error', text: 'Quantité invalide.' })
    if ([unit, ship, other].some(Number.isNaN)) return setMessage({ kind: 'error', text: 'Montants invalides (ex. 42,50).' })
    setBusy(true)
    setMessage(null)
    try {
      const po = await adminApi.createPO({
        supplier_id: Number(form.supplier_id),
        quantity,
        unit_cost: unit,
        shipping_cost: ship,
        other_costs: other,
        expected_at: form.expected_at || null,
        note: form.note,
        status,
      })
      setMessage({ kind: 'ok', text: `${po.number} créée (${fmtMoney(po.total_cents)}).` })
      setCreating(false)
      setForm({ supplier_id: '', quantity: '', unit_cost: '', shipping_cost: '', other_costs: '', expected_at: '', note: '' })
      load()
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const qty = Number(form.quantity)
  const preview =
    Number.isInteger(qty) && qty > 0 && !Number.isNaN(parseMad(form.unit_cost))
      ? Math.round((qty * parseMad(form.unit_cost) + (parseMad(form.shipping_cost) || 0) + (parseMad(form.other_costs) || 0)) * 100)
      : null

  return (
    <>
      {summary && (
        <section className="mt-14 grid grid-cols-3 gap-10">
          <Stat label="Dettes fournisseurs" value={fmtMoney(summary.debts_cents)} />
          <Stat label="En cours" value={String(summary.open)} />
          <Stat label="En retard" value={String(summary.late)} danger={summary.late > 0} />
        </section>
      )}

      <div className="mt-14 flex flex-wrap items-center gap-8">
        {STATUS_FILTERS.map((f) => (
          <Chip key={f.key} active={filter === f.key} onClick={() => setFilter(f.key)}>
            {f.label}
          </Chip>
        ))}
        <BusyButton className="ml-auto" onClick={() => setCreating((c) => !c)}>
          {creating ? 'Fermer' : 'Nouvelle commande'}
        </BusyButton>
      </div>

      {creating && (
        <form onSubmit={(e) => create(e, 'ordered')} className="mt-12 grid gap-12 r-12 border border-[#ecdcd6] p-14 sm:grid-cols-2 lg:grid-cols-3">
          <div className="sm:col-span-2 lg:col-span-1">
            <FieldLabel htmlFor="po-sup">Fournisseur</FieldLabel>
            <select id="po-sup" value={form.supplier_id} onChange={set('supplier_id')} className={inputClass}>
              <option value="">—</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            {suppliers.length === 0 && <p className="mt-4 fs-12 text-[#a0610f]">Ajoutez d'abord un fournisseur (onglet Fournisseurs).</p>}
          </div>
          {(
            [
              ['quantity', 'Quantité', 'numeric'],
              ['unit_cost', 'Coût unitaire (MAD)', 'decimal'],
              ['shipping_cost', 'Transport (MAD)', 'decimal'],
              ['other_costs', 'Autres frais (MAD)', 'decimal'],
            ] as const
          ).map(([k, label, mode]) => (
            <div key={k}>
              <FieldLabel htmlFor={`po-${k}`}>{label}</FieldLabel>
              <input id={`po-${k}`} inputMode={mode} value={form[k]} onChange={set(k)} className={inputClass} />
            </div>
          ))}
          <div>
            <FieldLabel htmlFor="po-exp">Livraison prévue</FieldLabel>
            <input id="po-exp" type="date" value={form.expected_at} onChange={set('expected_at')} className={inputClass} />
          </div>
          <div className="sm:col-span-2 lg:col-span-3">
            <FieldLabel htmlFor="po-note">Note</FieldLabel>
            <input id="po-note" value={form.note} maxLength={1000} onChange={set('note')} className={inputClass} />
          </div>
          <div className="flex flex-wrap items-center gap-8 sm:col-span-2 lg:col-span-3">
            {preview !== null && <span className="fs-14 font-semibold">Total : {fmtMoney(preview)}</span>}
            <BusyButton type="submit" busy={busy} className="ml-auto">
              Passer la commande
            </BusyButton>
            <BusyButton type="button" variant="secondary" busy={busy} onClick={(e) => create(e as unknown as FormEvent, 'draft')}>
              Enregistrer en brouillon
            </BusyButton>
          </div>
        </form>
      )}

      <ul className="mt-14 divide-y divide-[#efe7e3] r-10 border border-[#efe7e3]">
        {items.map((p) => (
          <li key={p.id}>
            <Link to={`/admin/purchasing/${p.id}`} className={`block px-14 py-12 hover:bg-[#fbf8f6] ${p.late ? 'bg-[#fff7f0]' : ''}`}>
              <div className="flex flex-wrap items-center gap-x-10 gap-y-4">
                <span className="fs-14.5 font-bold">{p.number}</span>
                <Pill className={PO_STATUS_PILL[p.status]}>{PO_STATUS_LABEL[p.status]}</Pill>
                {p.late && <Pill className="bg-[#fbe5e5] text-[#a12a2a]">En retard</Pill>}
                <span className="truncate fs-13.5 text-[#5a4f4f]">{p.supplier_name}</span>
                <span className="ml-auto fs-14 font-semibold">{fmtMoney(p.total_cents)}</span>
              </div>
              <div className="mt-4 flex flex-wrap gap-x-14 gap-y-2 fs-12.5 text-[#7a6f6f]">
                <span>
                  {p.received_qty}/{p.quantity} reçues
                </span>
                <span>Prévue : {fmtDate(p.expected_at)}</span>
                {p.status !== 'draft' && p.status !== 'cancelled' && (
                  <span className={p.payment_status === 'paid' ? 'text-[#17703c]' : ''}>
                    {PAYMENT_LABEL[p.payment_status]}
                    {p.due_cents > 0 ? ` · reste ${fmtMoney(p.due_cents)}` : ''}
                  </span>
                )}
              </div>
            </Link>
          </li>
        ))}
        {items.length === 0 && <li className="px-14 py-16 fs-13 text-[#8a8a8a]">Aucune commande fournisseur.</li>}
      </ul>
      {hasMore && (
        <div className="mt-10">
          <BusyButton variant="secondary" busy={busy} onClick={more}>
            Voir plus
          </BusyButton>
        </div>
      )}
    </>
  )
}

// ------------------------------------------------------------------ suppliers
function Suppliers({ fail, setMessage }: Ctx) {
  const [items, setItems] = useState<Supplier[]>([])
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [form, setForm] = useState({ name: '', phone: '', city: '', note: '' })
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setItems((await adminApi.suppliers(true)).items)
    } catch (e) {
      fail(e)
    }
  }, [fail])

  useEffect(() => {
    load()
  }, [load])

  const open = (s: Supplier | null) => {
    setEditing(s ? s.id : 'new')
    setForm(s ? { name: s.name, phone: s.phone, city: s.city, note: s.note } : { name: '', phone: '', city: '', note: '' })
  }

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (busy || !form.name.trim()) return
    setBusy(true)
    setMessage(null)
    try {
      if (editing === 'new') await adminApi.createSupplier(form)
      else if (editing) await adminApi.editSupplier(editing, form)
      setEditing(null)
      setMessage({ kind: 'ok', text: 'Fournisseur enregistré.' })
      load()
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (s: Supplier) => {
    if (busy) return
    setBusy(true)
    try {
      await adminApi.editSupplier(s.id, { active: !s.active })
      load()
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const formEl = (
    <form onSubmit={save} className="grid gap-12 r-12 border border-[#ecdcd6] p-14 sm:grid-cols-2">
      {(
        [
          ['name', 'Nom'],
          ['phone', 'Téléphone'],
          ['city', 'Ville'],
          ['note', 'Note'],
        ] as const
      ).map(([k, label]) => (
        <div key={k}>
          <FieldLabel htmlFor={`s-${k}`}>{label}</FieldLabel>
          <input id={`s-${k}`} value={form[k]} onChange={set(k)} className={inputClass} required={k === 'name'} />
        </div>
      ))}
      <div className="flex gap-8 sm:col-span-2">
        <BusyButton type="submit" busy={busy}>
          Enregistrer
        </BusyButton>
        <BusyButton type="button" variant="secondary" onClick={() => setEditing(null)}>
          Annuler
        </BusyButton>
      </div>
    </form>
  )

  return (
    <>
      <div className="mt-14 flex">
        <BusyButton className="ml-auto" onClick={() => open(null)}>
          Nouveau fournisseur
        </BusyButton>
      </div>
      {editing === 'new' && <div className="mt-12">{formEl}</div>}
      <ul className="mt-14 divide-y divide-[#efe7e3] r-10 border border-[#efe7e3]">
        {items.map((s) => (
          <li key={s.id} className="px-14 py-12">
            {editing === s.id ? (
              formEl
            ) : (
              <div className="flex flex-wrap items-center gap-x-12 gap-y-6">
                <span className={`fs-14.5 font-bold ${s.active ? '' : 'text-[#9a9a9a] line-through'}`}>{s.name}</span>
                <span className="fs-13 text-[#7a6f6f]">{[s.city, s.phone].filter(Boolean).join(' · ')}</span>
                <div className="ml-auto flex gap-8">
                  <BusyButton variant="secondary" onClick={() => open(s)}>
                    Modifier
                  </BusyButton>
                  <BusyButton variant={s.active ? 'danger' : 'secondary'} busy={busy} onClick={() => toggle(s)}>
                    {s.active ? 'Désactiver' : 'Réactiver'}
                  </BusyButton>
                </div>
                {s.note && <p className="w-full fs-12.5 text-[#7a6f6f]">{s.note}</p>}
              </div>
            )}
          </li>
        ))}
        {items.length === 0 && <li className="px-14 py-16 fs-13 text-[#8a8a8a]">Aucun fournisseur.</li>}
      </ul>
    </>
  )
}

function Stat({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="r-12 border border-[#efe7e3] bg-[#fbf8f6] p-12 md:p-14">
      <div className="fs-10.5 font-bold uppercase tracking-[0.06em] text-[#8a8a8a] md:fs-11">{label}</div>
      <div className={`mt-4 fs-16 font-bold md:fs-18 ${danger ? 'text-[#a12a2a]' : ''}`}>{value}</div>
    </div>
  )
}
