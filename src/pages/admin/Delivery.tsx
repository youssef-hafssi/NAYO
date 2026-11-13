import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Printer } from 'lucide-react'
import {
  adminApi,
  Unauthorized,
  type BoardOrder,
  type BoardStatus,
  type Carrier,
  type CodCarrier,
  type CodPending,
  type Remittance,
  type ReturnRow,
} from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { BusyButton, Chip, FieldLabel, fmtDate, fmtDateTime, fmtMoney, formatPhone, inputClass, parseMad, Pill } from './ui'

/*
 * Livraisons. Everyone: the board (confirmed → shipped → delivered / returned), bulk carrier + status, slips.
 * Owner only (server-enforced): cash held by carriers + reconciliation, returns with their cost, carriers' fees.
 */

type Tab = 'board' | 'cod' | 'returns' | 'carriers'
const COLUMNS: { key: BoardStatus; label: string }[] = [
  { key: 'confirmed', label: 'À expédier' },
  { key: 'shipped', label: 'Expédiées' },
  { key: 'delivered', label: 'Livrées' },
  { key: 'returned', label: 'Retournées' },
]

type Msg = { kind: 'ok' | 'error'; text: string } | null

export default function Delivery() {
  const { me, logout } = useAuth()
  const owner = me.role === 'owner'
  const [params, setParams] = useSearchParams()
  const tab = ((owner && (params.get('tab') as Tab)) || 'board') as Tab
  const [message, setMessage] = useState<Msg>(null)
  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof Unauthorized) logout()
      else setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })
    },
    [logout],
  )

  return (
    <div className="mx-auto w-full max-w-1100 px-16 py-16 md:px-24 md:py-24">
      <h1 className="fs-22 font-bold">Livraisons</h1>
      {owner && (
        <div className="mt-12 flex flex-wrap gap-8">
          {(
            [
              ['board', 'Suivi'],
              ['cod', 'À encaisser'],
              ['returns', 'Retours'],
              ['carriers', 'Livreurs'],
            ] as const
          ).map(([k, label]) => (
            <Chip key={k} active={tab === k} onClick={() => (setMessage(null), setParams(k === 'board' ? {} : { tab: k }))}>
              {label}
            </Chip>
          ))}
        </div>
      )}
      {message && (
        <p role={message.kind === 'error' ? 'alert' : 'status'} className={`mt-12 r-8 px-12 py-8 fs-13 ${message.kind === 'error' ? 'bg-[#fbe5e5] text-[#a12a2a]' : 'bg-[#e7f6ec] text-[#1f6a3c]'}`}>
          {message.text}
        </p>
      )}
      {tab === 'board' && <Board fail={fail} setMessage={setMessage} owner={owner} />}
      {tab === 'cod' && <Cod fail={fail} setMessage={setMessage} />}
      {tab === 'returns' && <Returns fail={fail} />}
      {tab === 'carriers' && <Carriers fail={fail} setMessage={setMessage} />}
    </div>
  )
}

// ------------------------------------------------------------------ board
function Board({ fail, setMessage, owner }: { fail: (e: unknown) => void; setMessage: (m: Msg) => void; owner: boolean }) {
  const [status, setStatus] = useState<BoardStatus>('confirmed')
  const [items, setItems] = useState<BoardOrder[]>([])
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [hasMore, setHasMore] = useState(false)
  const [carriers, setCarriers] = useState<Carrier[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [carrierId, setCarrierId] = useState('')
  const [busy, setBusy] = useState(false)
  const [returning, setReturning] = useState(false)
  const [reason, setReason] = useState('')
  const [recoverable, setRecoverable] = useState(true)

  const load = useCallback(async () => {
    try {
      const [b, c] = await Promise.all([adminApi.board(status), adminApi.carriers()])
      setItems(b.items)
      setCounts(b.counts)
      setHasMore(b.has_more)
      setCarriers(c.items)
      setSelected(new Set())
    } catch (e) {
      fail(e)
    }
  }, [status, fail])

  useEffect(() => {
    load()
  }, [load])

  const more = async () => {
    if (busy) return
    setBusy(true)
    try {
      const b = await adminApi.board(status, items.length)
      setItems((l) => [...l, ...b.items])
      setHasMore(b.has_more)
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const toggle = (n: string) =>
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(n)) next.delete(n)
      else next.add(n)
      return next
    })
  const allSelected = items.length > 0 && items.every((o) => selected.has(o.order_number))
  const chosen = [...selected]

  const bulk = async (body: Parameters<typeof adminApi.bulkDelivery>[0], label: string) => {
    if (busy || !chosen.length) return
    setBusy(true)
    setMessage(null)
    try {
      const r = await adminApi.bulkDelivery(body)
      const errs = Object.entries(r.errors)
      setMessage({
        kind: errs.length ? 'error' : 'ok',
        text: `${label} : ${r.done.length} commande(s).` + (errs.length ? ` Refusées : ${errs.map(([n, e]) => `${n} (${e})`).join(', ')}` : ''),
      })
      setReturning(false)
      setReason('')
      await load()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const printSlips = () => window.open(`/admin/delivery/print?n=${encodeURIComponent(chosen.join(','))}`, '_blank')

  return (
    <>
      <div className="mt-14 flex flex-wrap gap-8">
        {COLUMNS.map((c) => (
          <Chip key={c.key} active={status === c.key} onClick={() => setStatus(c.key)}>
            {c.label} <span className="ml-4 text-[#8a8a8a]">{counts[c.key] ?? 0}</span>
          </Chip>
        ))}
      </div>

      {/* Bulk bar */}
      <div className="sticky top-0 z-10 mt-12 flex flex-wrap items-center gap-8 r-12 border border-[#ecdcd6] bg-white/95 p-10 backdrop-blur">
        <label className="flex min-h-40 items-center gap-8 px-4 fs-13.5">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={() => setSelected(allSelected ? new Set() : new Set(items.map((o) => o.order_number)))}
            className="size-18 accent-[#3a0a10]"
          />
          {selected.size ? `${selected.size} sélectionnée(s)` : 'Tout sélectionner'}
        </label>
        {selected.size > 0 && (
          <>
            <select aria-label="Livreur" value={carrierId} onChange={(e) => setCarrierId(e.target.value)} className={`${inputClass} !mt-0 w-auto min-w-140`}>
              <option value="">Livreur…</option>
              {carriers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
              <option value="0">— Aucun —</option>
            </select>
            <BusyButton variant="secondary" busy={busy} disabled={carrierId === ''} onClick={() => bulk({ order_numbers: chosen, carrier_id: Number(carrierId) }, 'Livreur assigné')}>
              Assigner
            </BusyButton>
            {status === 'confirmed' && (
              <BusyButton busy={busy} onClick={() => bulk({ order_numbers: chosen, status: 'shipped' }, 'Expédiées')}>
                Marquer expédiées
              </BusyButton>
            )}
            {(status === 'confirmed' || status === 'shipped') && (
              <>
                <BusyButton busy={busy} onClick={() => bulk({ order_numbers: chosen, status: 'delivered' }, 'Livrées')}>
                  Livrées
                </BusyButton>
                <BusyButton variant="danger" busy={busy} onClick={() => setReturning(true)}>
                  Retournées
                </BusyButton>
              </>
            )}
            <BusyButton variant="secondary" onClick={printSlips}>
              <Printer className="size-16" aria-hidden /> Bons de livraison
            </BusyButton>
          </>
        )}
      </div>
      {returning && (
        <div className="mt-10 r-10 border border-[#f0d4d4] bg-[#fdf6f6] p-12">
          <FieldLabel htmlFor="rr">Raison du retour (refus, absent, injoignable…)</FieldLabel>
          <input id="rr" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} className={inputClass} />
          <label className="mt-8 flex min-h-40 items-center gap-10 fs-14">
            <input type="checkbox" checked={recoverable} onChange={(e) => setRecoverable(e.target.checked)} className="size-18 accent-[#3a0a10]" />
            Produit récupérable (il revient dans le stock)
          </label>
          <div className="mt-8 flex gap-8">
            <BusyButton busy={busy} onClick={() => bulk({ order_numbers: chosen, status: 'returned', return_reason: reason.trim(), recoverable }, 'Retournées')}>
              Marquer retournées
            </BusyButton>
            <BusyButton variant="secondary" onClick={() => setReturning(false)}>
              Annuler
            </BusyButton>
          </div>
        </div>
      )}

      <ul className="mt-12 divide-y divide-[#efe7e3] r-10 border border-[#efe7e3]">
        {items.map((o) => (
          <li key={o.order_number} className={`flex gap-10 px-10 py-10 ${selected.has(o.order_number) ? 'bg-[#fbf3f4]' : ''}`}>
            <input
              type="checkbox"
              aria-label={`Sélectionner ${o.order_number}`}
              checked={selected.has(o.order_number)}
              onChange={() => toggle(o.order_number)}
              className="mt-10 size-18 shrink-0 accent-[#3a0a10]"
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-10 gap-y-2">
                <Link to={`/admin/orders/${o.order_number}`} className="fs-14.5 font-bold text-[#3a0a10] underline-offset-2 hover:underline">
                  {o.order_number}
                </Link>
                <span className="fs-13.5">{o.name}</span>
                <span className="fs-13 text-[#7a6f6f]">{formatPhone(o.phone)}</span>
                <span className="ml-auto fs-14 font-semibold">{o.total} MAD</span>
              </div>
              <div className="mt-2 fs-13 text-[#5a4f4f]">
                {[o.address, o.city].filter(Boolean).join(', ') || <span className="text-[#a0610f]">Adresse manquante</span>} · {o.quantity} × NAYO
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-x-10 gap-y-4 fs-12.5 text-[#7a6f6f]">
                <span>{o.carrier ? `Livreur : ${o.carrier}` : <span className="text-[#a0610f]">Sans livreur</span>}</span>
                {o.tracking && <span>Suivi : {o.tracking}</span>}
                {status === 'confirmed' && <span>Commandée le {fmtDate(o.created_at)}</span>}
                {o.shipped_at && <span>Expédiée le {fmtDate(o.shipped_at)}</span>}
                {o.delivered_at && <span>Livrée le {fmtDate(o.delivered_at)}</span>}
                {o.return_reason && <span className="text-[#a12a2a]">Retour : {o.return_reason}</span>}
                {o.cod_status === 'with_carrier' && <Pill className="bg-[#fdf0de] text-[#c2650a]">Chez le livreur</Pill>}
                {o.cod_status === 'remitted' && <Pill className="bg-[#dff3e6] text-[#17703c]">Encaissée</Pill>}
                {owner && o.carrier_fee_cents ? <span>Frais : {fmtMoney(Number(o.carrier_fee_cents))}</span> : null}
              </div>
            </div>
          </li>
        ))}
        {items.length === 0 && <li className="px-14 py-16 fs-13 text-[#8a8a8a]">Aucune commande.</li>}
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

// ------------------------------------------------------------------ cash held by carriers + reconciliation
function Cod({ fail, setMessage }: { fail: (e: unknown) => void; setMessage: (m: Msg) => void }) {
  const [summary, setSummary] = useState<{ carriers: CodCarrier[]; total_cents: number } | null>(null)
  const [carrier, setCarrier] = useState<CodCarrier | null>(null)
  const [pending, setPending] = useState<CodPending[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [received, setReceived] = useState('')
  const [note, setNote] = useState('')
  const [history, setHistory] = useState<Remittance[]>([])
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([adminApi.codSummary(), adminApi.remittances()])
      setSummary(s)
      setHistory(h.items)
    } catch (e) {
      fail(e)
    }
  }, [fail])

  useEffect(() => {
    load()
  }, [load])

  const open = async (c: CodCarrier) => {
    setCarrier(c)
    setReceived('')
    setNote('')
    try {
      const p = await adminApi.codPending(c.carrier_id)
      setPending(p.items)
      setSelected(new Set(p.items.map((x) => x.order_number)))
    } catch (e) {
      fail(e)
    }
  }

  const expected = useMemo(() => pending.filter((p) => selected.has(p.order_number)).reduce((sum, p) => sum + p.net_cents, 0), [pending, selected])
  const receivedMad = parseMad(received)
  const diff = Number.isNaN(receivedMad) || received.trim() === '' ? null : Math.round(receivedMad * 100) - expected

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (!carrier || busy || !selected.size) return
    if (Number.isNaN(receivedMad) || received.trim() === '') return setMessage({ kind: 'error', text: 'Entrez le montant reçu.' })
    if (diff !== null && diff !== 0 && !window.confirm(`Écart de ${fmtMoney(diff)} par rapport au montant attendu. Enregistrer quand même ?`)) return
    setBusy(true)
    setMessage(null)
    try {
      const r = await adminApi.remit({ carrier_id: carrier.carrier_id, order_numbers: [...selected], amount_received: receivedMad, note })
      setMessage({ kind: r.difference_cents < 0 ? 'error' : 'ok', text: `Encaissement enregistré : ${r.orders} commande(s), écart ${fmtMoney(r.difference_cents)}.` })
      setCarrier(null)
      setPending([])
      await load()
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  if (!summary) return <p className="mt-16 fs-14 text-[#8a8a8a]">Chargement…</p>

  return (
    <>
      <section className="mt-14 r-12 border border-[#efe7e3] bg-[#fbf8f6] p-14">
        <div className="fs-11 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">À encaisser chez les livreurs</div>
        <div className="mt-4 fs-24 font-bold text-[#3a0a10]">{fmtMoney(summary.total_cents)}</div>
      </section>

      <ul className="mt-12 divide-y divide-[#efe7e3] r-10 border border-[#efe7e3]">
        {summary.carriers.map((c) => (
          <li key={c.carrier_id}>
            <button type="button" onClick={() => open(c)} className={`flex w-full flex-wrap items-center gap-x-12 gap-y-4 px-14 py-12 text-left hover:bg-[#fbf8f6] ${carrier?.carrier_id === c.carrier_id ? 'bg-[#fbf3f4]' : ''}`}>
              <span className="fs-14.5 font-bold">{c.name}</span>
              <span className="fs-13 text-[#7a6f6f]">{c.orders} commande(s)</span>
              {c.oldest_age_days !== null && (
                <span className={`fs-13 ${c.late ? 'font-semibold text-[#a12a2a]' : 'text-[#7a6f6f]'}`}>la plus ancienne : {c.oldest_age_days} j</span>
              )}
              <span className="ml-auto fs-14 font-semibold">{fmtMoney(c.expected_cents)}</span>
            </button>
          </li>
        ))}
        {summary.carriers.length === 0 && <li className="px-14 py-16 fs-13 text-[#8a8a8a]">Rien à encaisser.</li>}
      </ul>

      {carrier && (
        <form onSubmit={save} className="mt-16 r-12 border border-[#ecdcd6] p-14">
          <h2 className="fs-16 font-bold">Rapprochement — {carrier.name}</h2>
          <p className="mt-4 fs-12.5 text-[#7a6f6f]">Cochez les commandes payées par le livreur, puis entrez le montant reçu.</p>
          <ul className="mt-10 divide-y divide-[#efe7e3] r-10 border border-[#efe7e3]">
            {pending.map((p) => (
              <li key={p.order_number}>
                <label className={`flex min-h-44 flex-wrap items-center gap-x-10 gap-y-2 px-10 py-8 fs-13 ${p.late ? 'bg-[#fff7f0]' : ''}`}>
                  <input
                    type="checkbox"
                    checked={selected.has(p.order_number)}
                    onChange={() =>
                      setSelected((s) => {
                        const n = new Set(s)
                        if (n.has(p.order_number)) n.delete(p.order_number)
                        else n.add(p.order_number)
                        return n
                      })
                    }
                    className="size-18 accent-[#3a0a10]"
                  />
                  <span className="font-semibold">{p.order_number}</span>
                  <span>{p.name}</span>
                  <span className={p.late ? 'font-semibold text-[#a12a2a]' : 'text-[#7a6f6f]'}>livrée le {fmtDate(p.delivered_at)}</span>
                  <span className="ml-auto text-[#7a6f6f]">
                    {fmtMoney(p.total_cents)} − {fmtMoney(p.fee_cents)} = <strong className="text-[#1a1a1a]">{fmtMoney(p.net_cents)}</strong>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <div className="mt-12 grid gap-10 sm:grid-cols-[1fr_1fr_2fr] sm:items-end">
            <div>
              <FieldLabel>Attendu</FieldLabel>
              <p className="mt-6 fs-18 font-bold">{fmtMoney(expected)}</p>
            </div>
            <div>
              <FieldLabel htmlFor="recv">Reçu (MAD)</FieldLabel>
              <input id="recv" inputMode="decimal" value={received} onChange={(e) => setReceived(e.target.value)} className={inputClass} />
            </div>
            <div>
              <FieldLabel htmlFor="rnote">Note</FieldLabel>
              <input id="rnote" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} className={inputClass} />
            </div>
          </div>
          {diff !== null && (
            <p className={`mt-10 fs-14 font-semibold ${diff < 0 ? 'text-[#a12a2a]' : diff > 0 ? 'text-[#a0610f]' : 'text-[#17703c]'}`}>
              Écart : {fmtMoney(diff)} {diff === 0 ? '✓' : diff < 0 ? '(il manque de l’argent)' : '(trop reçu)'}
            </p>
          )}
          <div className="mt-12">
            <BusyButton type="submit" busy={busy} disabled={!selected.size}>
              Enregistrer l'encaissement
            </BusyButton>
          </div>
        </form>
      )}

      <section className="mt-20">
        <FieldLabel>Derniers encaissements</FieldLabel>
        <ul className="mt-6 divide-y divide-[#efe7e3] r-10 border border-[#efe7e3]">
          {history.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-x-12 gap-y-2 px-12 py-10 fs-13">
              <span className="text-[#8a8a8a]">{fmtDateTime(r.at)}</span>
              <span className="font-semibold">{r.carrier_name}</span>
              <span className="text-[#7a6f6f]">{r.orders} commande(s)</span>
              <span className="ml-auto">{fmtMoney(r.amount_received_cents)}</span>
              {r.difference_cents !== 0 && (
                <span className={r.difference_cents < 0 ? 'font-semibold text-[#a12a2a]' : 'text-[#a0610f]'}>écart {fmtMoney(r.difference_cents)}</span>
              )}
            </li>
          ))}
          {history.length === 0 && <li className="px-12 py-14 fs-13 text-[#8a8a8a]">Aucun encaissement.</li>}
        </ul>
      </section>
    </>
  )
}

// ------------------------------------------------------------------ returns
function Returns({ fail }: { fail: (e: unknown) => void }) {
  const [items, setItems] = useState<ReturnRow[] | null>(null)
  useEffect(() => {
    adminApi
      .returns()
      .then((r) => setItems(r.items))
      .catch(fail)
  }, [fail])
  if (!items) return <p className="mt-16 fs-14 text-[#8a8a8a]">Chargement…</p>
  const total = items.reduce((s, r) => s + r.loss_cents, 0)
  return (
    <>
      <p className="mt-14 fs-14">
        Coût des retours affichés : <strong>{fmtMoney(total)}</strong> (frais du livreur + produits perdus)
      </p>
      <ul className="mt-10 divide-y divide-[#efe7e3] r-10 border border-[#efe7e3]">
        {items.map((r) => (
          <li key={r.order_number} className="px-12 py-10 fs-13">
            <div className="flex flex-wrap items-baseline gap-x-10">
              <Link to={`/admin/orders/${r.order_number}`} className="font-bold text-[#3a0a10] hover:underline">
                {r.order_number}
              </Link>
              <span>{r.name}</span>
              <span className="text-[#7a6f6f]">{r.city}</span>
              <span className="ml-auto font-semibold text-[#a12a2a]">{fmtMoney(r.loss_cents)}</span>
            </div>
            <div className="mt-2 text-[#7a6f6f]">
              {r.return_reason || <span className="text-[#a0610f]">Raison non renseignée</span>} · {r.carrier || 'sans livreur'} · frais {fmtMoney(r.fee_cents)}
              {r.written_off_cents > 0 && ` · produit perdu ${fmtMoney(r.written_off_cents)}`}
            </div>
          </li>
        ))}
        {items.length === 0 && <li className="px-12 py-14 text-[#8a8a8a]">Aucun retour.</li>}
      </ul>
    </>
  )
}

// ------------------------------------------------------------------ carriers (owner)
function Carriers({ fail, setMessage }: { fail: (e: unknown) => void; setMessage: (m: Msg) => void }) {
  const [items, setItems] = useState<Carrier[]>([])
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [form, setForm] = useState({ name: '', phone: '', fee_delivered: '', fee_returned: '', remit_delay_days: '7' })
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setItems((await adminApi.carriers(true)).items)
    } catch (e) {
      fail(e)
    }
  }, [fail])

  useEffect(() => {
    load()
  }, [load])

  const open = (c: Carrier | null) => {
    setEditing(c ? c.id : 'new')
    setForm(
      c
        ? {
            name: c.name,
            phone: c.phone,
            fee_delivered: ((c.fee_delivered_cents ?? 0) / 100).toString().replace('.', ','),
            fee_returned: ((c.fee_returned_cents ?? 0) / 100).toString().replace('.', ','),
            remit_delay_days: String(c.remit_delay_days ?? 7),
          }
        : { name: '', phone: '', fee_delivered: '', fee_returned: '', remit_delay_days: '7' },
    )
  }

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    const fd = parseMad(form.fee_delivered)
    const fr = parseMad(form.fee_returned)
    const days = Number(form.remit_delay_days)
    if (!form.name.trim() || Number.isNaN(fd) || Number.isNaN(fr) || !Number.isInteger(days) || days < 0) {
      return setMessage({ kind: 'error', text: 'Vérifiez le nom, les frais (ex. 25,00) et le délai.' })
    }
    setBusy(true)
    try {
      const body = { name: form.name.trim(), phone: form.phone.trim(), fee_delivered: fd, fee_returned: fr, remit_delay_days: days }
      if (editing === 'new') await adminApi.createCarrier(body)
      else if (editing) await adminApi.editCarrier(editing, body)
      setEditing(null)
      setMessage({ kind: 'ok', text: 'Livreur enregistré.' })
      load()
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const formEl = (
    <form onSubmit={save} className="grid gap-12 r-12 border border-[#ecdcd6] p-14 sm:grid-cols-2 lg:grid-cols-5">
      {(
        [
          ['name', 'Nom', 'text'],
          ['phone', 'Téléphone', 'tel'],
          ['fee_delivered', 'Frais si livrée (MAD)', 'decimal'],
          ['fee_returned', 'Frais si retour (MAD)', 'decimal'],
          ['remit_delay_days', 'Délai de paiement (jours)', 'numeric'],
        ] as const
      ).map(([k, label, mode]) => (
        <div key={k}>
          <FieldLabel htmlFor={`c-${k}`}>{label}</FieldLabel>
          <input id={`c-${k}`} inputMode={mode === 'text' || mode === 'tel' ? undefined : mode} type={mode === 'tel' ? 'tel' : 'text'} value={form[k]} onChange={set(k)} className={inputClass} />
        </div>
      ))}
      <div className="flex gap-8 sm:col-span-2 lg:col-span-5">
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
          Nouveau livreur
        </BusyButton>
      </div>
      {editing === 'new' && <div className="mt-12">{formEl}</div>}
      <ul className="mt-12 divide-y divide-[#efe7e3] r-10 border border-[#efe7e3]">
        {items.map((c) => (
          <li key={c.id} className="px-14 py-12">
            {editing === c.id ? (
              formEl
            ) : (
              <div className="flex flex-wrap items-center gap-x-12 gap-y-6">
                <span className={`fs-14.5 font-bold ${c.active ? '' : 'text-[#9a9a9a] line-through'}`}>{c.name}</span>
                <span className="fs-13 text-[#7a6f6f]">
                  livrée {fmtMoney(c.fee_delivered_cents ?? 0)} · retour {fmtMoney(c.fee_returned_cents ?? 0)} · paie sous {c.remit_delay_days} j
                </span>
                <div className="ml-auto flex gap-8">
                  <BusyButton variant="secondary" onClick={() => open(c)}>
                    Modifier
                  </BusyButton>
                  <BusyButton
                    variant={c.active ? 'danger' : 'secondary'}
                    busy={busy}
                    onClick={async () => {
                      setBusy(true)
                      try {
                        await adminApi.editCarrier(c.id, { active: !c.active })
                        load()
                      } catch (e) {
                        fail(e)
                      } finally {
                        setBusy(false)
                      }
                    }}
                  >
                    {c.active ? 'Désactiver' : 'Réactiver'}
                  </BusyButton>
                </div>
              </div>
            )}
          </li>
        ))}
        {items.length === 0 && <li className="px-14 py-16 fs-13 text-[#8a8a8a]">Ajoutez votre premier livreur.</li>}
      </ul>
    </>
  )
}
