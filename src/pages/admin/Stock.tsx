import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { adminApi, Unauthorized, type StockMovement, type StockSummary } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { BusyButton, FieldLabel, fmtDateTime, fmtMoney, inputClass, STOCK_REASON } from './ui'

/*
 * Stock (single product). Everyone sees units; costs, value and every write are owner-only (server-enforced).
 * First run: the owner enters the opening stock and its unit cost — tracking starts then.
 */

type Mode = null | 'restock' | 'adjust'

export default function Stock() {
  const { me, logout } = useAuth()
  const owner = me.role === 'owner'
  const [summary, setSummary] = useState<StockSummary | null>(null)
  const [moves, setMoves] = useState<StockMovement[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [mode, setMode] = useState<Mode>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [qty, setQty] = useState('')
  const [cost, setCost] = useState('')
  const [note, setNote] = useState('')
  const [confirmAdjust, setConfirmAdjust] = useState(false)
  const [threshold, setThreshold] = useState('')

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof Unauthorized) logout()
      else setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })
    },
    [logout],
  )

  const load = useCallback(async () => {
    try {
      const [s, m] = await Promise.all([adminApi.stock(), adminApi.stockMovements()])
      setSummary(s)
      setThreshold(String(s.low_threshold))
      setMoves(m.items)
      setCursor(m.next_cursor)
    } catch (e) {
      fail(e)
    }
  }, [fail])

  useEffect(() => {
    load()
  }, [load])

  const more = async () => {
    if (!cursor || busy) return
    setBusy(true)
    try {
      const m = await adminApi.stockMovements(cursor)
      setMoves((list) => [...list, ...m.items])
      setCursor(m.next_cursor)
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const reset = () => {
    setMode(null)
    setQty('')
    setCost('')
    setNote('')
    setConfirmAdjust(false)
  }

  const run = async (action: () => Promise<StockSummary>, ok: string) => {
    if (busy) return
    setBusy(true)
    setMessage(null)
    try {
      setSummary(await action())
      setMessage({ kind: 'ok', text: ok })
      reset()
      const m = await adminApi.stockMovements()
      setMoves(m.items)
      setCursor(m.next_cursor)
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const int = (v: string) => (/^\d+$/.test(v.trim()) ? Number(v.trim()) : NaN)
  const mad = (v: string) => (/^\d+([.,]\d{1,2})?$/.test(v.trim()) ? Number(v.trim().replace(',', '.')) : NaN)

  const submitOpening = (e: FormEvent) => {
    e.preventDefault()
    const q = int(qty)
    const c = mad(cost)
    if (Number.isNaN(q) || Number.isNaN(c)) return setMessage({ kind: 'error', text: 'Entrez une quantité et un coût unitaire valides.' })
    run(() => adminApi.stockOpening(q, c), 'Suivi du stock démarré.')
  }

  const submitRestock = (e: FormEvent) => {
    e.preventDefault()
    const q = int(qty)
    const c = mad(cost)
    if (Number.isNaN(q) || q < 1 || Number.isNaN(c)) return setMessage({ kind: 'error', text: 'Quantité (≥ 1) et coût unitaire requis.' })
    run(() => adminApi.stockRestock(q, c, note.trim()), `+${q} ajouté(s) au stock.`)
  }

  const submitAdjust = (e: FormEvent) => {
    e.preventDefault()
    const q = int(qty)
    if (Number.isNaN(q)) return setMessage({ kind: 'error', text: 'Entrez le stock compté.' })
    if (note.trim().length < 3) return setMessage({ kind: 'error', text: 'Une note est obligatoire pour une correction.' })
    if (!confirmAdjust) return setConfirmAdjust(true) // second step: explicit confirmation
    run(() => adminApi.stockAdjust(q, note.trim()), 'Stock corrigé.')
  }

  const saveThreshold = () => {
    const v = int(threshold)
    if (Number.isNaN(v) || !summary || v === summary.low_threshold) return
    run(() => adminApi.stockThreshold(v), 'Seuil enregistré.')
  }

  if (!summary) return <div className="p-24 fs-14 text-[#8a8a8a]">Chargement…</div>

  return (
    <div className="mx-auto w-full max-w-960 px-16 py-16 md:px-24 md:py-24">
      <h1 className="fs-22 font-bold">Stock</h1>
      {summary.ledger_start && <p className="mt-2 fs-12.5 text-[#8a8a8a]">Suivi à partir du {summary.ledger_start}</p>}

      {message && (
        <p role={message.kind === 'error' ? 'alert' : 'status'} className={`mt-12 r-8 px-12 py-8 fs-13 ${message.kind === 'error' ? 'bg-[#fbe5e5] text-[#a12a2a]' : 'bg-[#e7f6ec] text-[#1f6a3c]'}`}>
          {message.text}
        </p>
      )}

      {!summary.tracking ? (
        <section className="mt-16 r-14 border border-[#ecdcd6] bg-[#fbf5f2] p-16 md:p-20">
          <h2 className="fs-16 font-bold">Démarrer le suivi du stock</h2>
          <p className="mt-6 fs-13.5 lh-20 text-[#5a4f4f]">
            Entrez le stock disponible à la vente aujourd'hui, <strong>commandes déjà confirmées exclues</strong>, et son coût
            unitaire. Avant cela, rien n'est déduit ni bloqué.
          </p>
          {owner ? (
            <form onSubmit={submitOpening} className="mt-14 grid gap-12 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
              <div>
                <FieldLabel htmlFor="o-qty">Unités en stock</FieldLabel>
                <input id="o-qty" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} className={inputClass} />
              </div>
              <div>
                <FieldLabel htmlFor="o-cost">Coût unitaire (MAD)</FieldLabel>
                <input id="o-cost" inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} className={inputClass} />
              </div>
              <BusyButton type="submit" busy={busy}>Démarrer</BusyButton>
            </form>
          ) : (
            <p className="mt-10 fs-13 text-[#8a8a8a]">Seul le propriétaire peut démarrer le suivi.</p>
          )}
        </section>
      ) : (
        <>
          {summary.out ? (
            <div role="alert" className="mt-14 r-10 bg-[#fdf1dc] px-14 py-10 fs-13.5 font-semibold text-[#a0610f]">
              Rupture de stock : les nouvelles confirmations sont bloquées.
            </div>
          ) : summary.low ? (
            <div role="alert" className="mt-14 r-10 bg-[#fbe5e5] px-14 py-10 fs-13.5 font-semibold text-[#a12a2a]">
              Stock bas : {summary.on_hand} unité(s), seuil {summary.low_threshold}.
            </div>
          ) : null}

          <section className="mt-14 grid grid-cols-2 gap-10 md:grid-cols-4">
            <Card label="En stock" value={String(summary.on_hand)} big />
            <Card label="Jours de stock" value={summary.days_of_stock === null ? '—' : `${summary.days_of_stock} j`} hint={`${summary.sold_14d} vendus en 14 j`} />
            {summary.stock_value_cents !== undefined && <Card label="Valeur du stock" value={fmtMoney(summary.stock_value_cents)} />}
            {summary.avg_cost_cents !== undefined && <Card label="Coût moyen" value={fmtMoney(summary.avg_cost_cents)} />}
          </section>

          {owner && (
            <section className="mt-16">
              <div className="flex flex-wrap gap-8">
                <BusyButton onClick={() => (reset(), setMode(mode === 'restock' ? null : 'restock'))}>Réapprovisionner</BusyButton>
                <BusyButton variant="secondary" onClick={() => (reset(), setMode(mode === 'adjust' ? null : 'adjust'))}>
                  Corriger le stock
                </BusyButton>
              </div>

              {mode === 'restock' && (
                <form onSubmit={submitRestock} className="mt-12 grid gap-12 r-12 border border-[#ecdcd6] p-14 sm:grid-cols-2">
                  <div>
                    <FieldLabel htmlFor="r-qty">Quantité reçue</FieldLabel>
                    <input id="r-qty" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} className={inputClass} />
                  </div>
                  <div>
                    <FieldLabel htmlFor="r-cost">Coût unitaire (MAD)</FieldLabel>
                    <input id="r-cost" inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} className={inputClass} />
                  </div>
                  <div className="sm:col-span-2">
                    <FieldLabel htmlFor="r-note">Note (facultatif)</FieldLabel>
                    <input id="r-note" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} className={inputClass} />
                  </div>
                  <div className="sm:col-span-2"><BusyButton type="submit" busy={busy}>Ajouter au stock</BusyButton></div>
                </form>
              )}

              {mode === 'adjust' && (
                <form onSubmit={submitAdjust} className="mt-12 grid gap-12 r-12 border border-[#f0d4d4] bg-[#fdf6f6] p-14 sm:grid-cols-2">
                  <div>
                    <FieldLabel htmlFor="a-qty">Stock compté</FieldLabel>
                    <input id="a-qty" inputMode="numeric" value={qty} onChange={(e) => (setQty(e.target.value), setConfirmAdjust(false))} className={inputClass} />
                  </div>
                  <div>
                    <FieldLabel htmlFor="a-note">Raison (obligatoire)</FieldLabel>
                    <input id="a-note" value={note} maxLength={300} onChange={(e) => (setNote(e.target.value), setConfirmAdjust(false))} className={inputClass} />
                  </div>
                  <div className="sm:col-span-2">
                    {confirmAdjust && !Number.isNaN(int(qty)) && (
                      <p className="mb-8 fs-13.5 font-semibold text-[#a12a2a]">
                        Passer le stock de {summary.on_hand} à {int(qty)} ({int(qty) - summary.on_hand >= 0 ? '+' : ''}
                        {int(qty) - summary.on_hand}) ?
                      </p>
                    )}
                    <BusyButton type="submit" busy={busy}>{confirmAdjust ? 'Oui, corriger' : 'Corriger'}</BusyButton>
                  </div>
                </form>
              )}

              <div className="mt-14 flex flex-wrap items-end gap-10">
                <div className="w-160">
                  <FieldLabel htmlFor="th">Seuil d'alerte</FieldLabel>
                  <input id="th" inputMode="numeric" value={threshold} onChange={(e) => setThreshold(e.target.value)} className={inputClass} />
                </div>
                <BusyButton variant="secondary" busy={busy} onClick={saveThreshold}>Enregistrer</BusyButton>
              </div>
            </section>
          )}
        </>
      )}

      <section className="mt-24">
        <FieldLabel>Mouvements</FieldLabel>
        {moves.length === 0 ? (
          <p className="mt-8 fs-13 text-[#8a8a8a]">Aucun mouvement.</p>
        ) : (
          <ul className="mt-8 divide-y divide-[#efe7e3] r-10 border border-[#efe7e3]">
            {moves.map((m) => {
              const qty = m.written_off ? `${m.written_off} perdue(s)` : `${m.delta > 0 ? '+' : ''}${m.delta}`
              const reason = (
                <>
                  {STOCK_REASON[m.reason] ?? m.reason}
                  {m.order_number && (
                    <>
                      {' · '}
                      <Link to={`/admin/orders/${m.order_number}`} className="text-[#7a1a2a] underline">{m.order_number}</Link>
                    </>
                  )}
                </>
              )
              const who = [m.admin_name, m.note].filter(Boolean).join(' — ')
              const cost = m.unit_cost_cents !== undefined ? fmtMoney(m.unit_cost_cents) : ''
              const tone = m.delta < 0 ? 'text-[#a12a2a]' : 'text-[#17703c]'
              return (
                <li key={m.id} className="px-12 py-10 fs-13">
                  {/* phones: two lines */}
                  <div className="md:hidden">
                    <div className="flex items-baseline justify-between gap-10">
                      <span className="min-w-0 font-semibold">{reason}</span>
                      <span className={`shrink-0 font-semibold ${tone}`}>{qty}</span>
                    </div>
                    <div className="mt-2 flex flex-wrap justify-between gap-x-10 fs-12 text-[#7a6f6f]">
                      <span>{fmtDateTime(m.at)}{cost ? ` · ${cost}` : ''}</span>
                      <span>stock : {m.balance_after}</span>
                    </div>
                    {who && <div className="mt-2 fs-12 text-[#7a6f6f]">{who}</div>}
                  </div>
                  {/* from 768px: columns */}
                  <div className="hidden gap-x-12 md:grid md:grid-cols-[150px_1fr_90px_110px_80px]">
                    <span className="text-[#8a8a8a]">{fmtDateTime(m.at)}</span>
                    <span className="font-semibold">
                      {reason}
                      {who && <span className="block fs-12 font-normal text-[#7a6f6f]">{who}</span>}
                    </span>
                    <span className={`font-semibold ${tone}`}>{qty}</span>
                    <span className="text-[#7a6f6f]">{cost}</span>
                    <span className="text-right text-[#5a4f4f]">= {m.balance_after}</span>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
        {cursor && (
          <div className="mt-10">
            <BusyButton variant="secondary" busy={busy} onClick={more}>Voir plus</BusyButton>
          </div>
        )}
      </section>
    </div>
  )
}

function Card({ label, value, hint, big }: { label: string; value: string; hint?: string; big?: boolean }) {
  return (
    <div className="r-12 border border-[#efe7e3] bg-[#fbf8f6] p-14">
      <div className="fs-11 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">{label}</div>
      <div className={`mt-4 font-bold ${big ? 'fs-30' : 'fs-18'}`} style={big ? { color: '#3a0a10' } : undefined}>{value}</div>
      {hint && <div className="mt-2 fs-12 text-[#8a8a8a]">{hint}</div>}
    </div>
  )
}
