import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Download } from 'lucide-react'
import {
  adminApi,
  Unauthorized,
  type Expense,
  type ExpenseCategory,
  type FinanceReport,
  type Period,
} from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { BusyButton, Chip, FieldLabel, fmtDate, fmtMoney, inputClass, parseMad } from './ui'

/*
 * Finance (owner only, server-enforced): results for a period (P&L, marketing, unit economics, cash)
 * and the expenses list. Money is in centimes everywhere; dates are Casablanca days.
 */

type Tab = 'results' | 'expenses'
type Preset = 'today' | 'week' | 'month' | 'custom'
type Msg = { kind: 'ok' | 'error'; text: string } | null

const PRESETS: { key: Preset; label: string }[] = [
  { key: 'today', label: "Aujourd'hui" },
  { key: 'week', label: 'Cette semaine' },
  { key: 'month', label: 'Ce mois' },
  { key: 'custom', label: 'Personnalisée' },
]

const casaToday = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Africa/Casablanca' })
const money = (c: number | null | undefined) => (c == null ? '—' : fmtMoney(c))

export default function Finance() {
  const { me, logout } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab: Tab = params.get('tab') === 'expenses' ? 'expenses' : 'results'
  const [preset, setPreset] = useState<Preset>('month')
  const [frm, setFrm] = useState(() => casaToday().slice(0, 8) + '01')
  const [to, setTo] = useState(casaToday)
  const [message, setMessage] = useState<Msg>(null)
  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof Unauthorized) logout()
      else setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })
    },
    [logout],
  )

  if (me.role !== 'owner') {
    return (
      <div className="mx-auto w-full max-w-1100 px-16 py-16 md:px-24 md:py-24">
        <h1 className="fs-22 font-bold">Finance</h1>
        <p className="mt-12 fs-14 text-[#6b6b6b]">Réservé au propriétaire.</p>
      </div>
    )
  }

  const customOk = /^\d{4}-\d{2}-\d{2}$/.test(frm) && /^\d{4}-\d{2}-\d{2}$/.test(to) && frm <= to
  const period: Period | null = preset === 'custom' ? (customOk ? { frm, to } : null) : { preset }

  return (
    <div className="mx-auto w-full max-w-1100 px-16 py-16 md:px-24 md:py-24">
      <div className="flex flex-wrap items-center justify-between gap-12">
        <h1 className="fs-22 font-bold">Finance</h1>
        {period && (
          <a
            href={adminApi.financeExportUrl(period)}
            className="inline-flex h-44 items-center gap-8 r-10 border border-[#d9cfca] bg-white px-14 fs-14 font-semibold hover:bg-[#faf6f3] md:h-40"
          >
            <Download className="size-16" aria-hidden /> Exporter (CSV)
          </a>
        )}
      </div>

      <div className="mt-12 flex flex-wrap gap-8" role="tablist">
        {(
          [
            ['results', 'Résultats'],
            ['expenses', 'Dépenses'],
          ] as const
        ).map(([k, label]) => (
          <Chip key={k} active={tab === k} onClick={() => (setMessage(null), setParams(k === 'results' ? {} : { tab: k }))}>
            {label}
          </Chip>
        ))}
      </div>

      <section aria-label="Période" className="mt-14 r-14 border border-[#ece2dd] bg-white p-14">
        <div className="flex flex-wrap gap-8">
          {PRESETS.map((p) => (
            <Chip key={p.key} active={preset === p.key} onClick={() => setPreset(p.key)}>
              {p.label}
            </Chip>
          ))}
        </div>
        {preset === 'custom' && (
          <div className="mt-12 grid grid-cols-2 gap-10 md:max-w-420">
            <div>
              <FieldLabel htmlFor="fin-from">Du</FieldLabel>
              <input id="fin-from" type="date" className={inputClass} value={frm} max={to} onChange={(e) => setFrm(e.target.value)} />
            </div>
            <div>
              <FieldLabel htmlFor="fin-to">Au</FieldLabel>
              <input id="fin-to" type="date" className={inputClass} value={to} min={frm} onChange={(e) => setTo(e.target.value)} />
            </div>
            {!customOk && <p className="col-span-2 fs-13 text-[#a12a2a]">La date de début doit précéder la date de fin.</p>}
          </div>
        )}
      </section>

      {message && (
        <p role="status" className={`mt-12 r-10 px-14 py-10 fs-14 ${message.kind === 'ok' ? 'bg-[#eef7ee] text-[#1f6b2a]' : 'bg-[#fdf2f2] text-[#a12a2a]'}`}>
          {message.text}
        </p>
      )}

      {period &&
        (tab === 'results' ? (
          <Results period={period} fail={fail} />
        ) : (
          <Expenses period={period} fail={fail} setMessage={setMessage} />
        ))}
    </div>
  )
}

/* ------------------------------------------------------------------ Résultats */

function Results({ period, fail }: { period: Period; fail: (e: unknown) => void }) {
  const [r, setR] = useState<FinanceReport | null>(null)
  const key = JSON.stringify(period)

  useEffect(() => {
    let live = true
    setR(null)
    adminApi
      .financeReport(period)
      .then((x) => live && setR(x))
      .catch((e) => live && fail(e))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  if (!r) return <p className="mt-18 fs-14 text-[#8a8a8a]">Chargement…</p>
  const { pnl, counts, marketing: m, unit_economics: u, cash } = r

  return (
    <div className="mt-14 grid gap-14 lg:grid-cols-2">
      <Card title="Compte de résultat" sub={`Du ${fmtDate(r.from)} au ${fmtDate(r.to)}`} className="lg:col-span-2">
        {(r.ledger_start == null || counts.orders_without_cost > 0) && (
          <p className="mb-10 r-10 bg-[#fff7e6] px-12 py-8 fs-13 text-[#7a5200]">
            {counts.orders_without_cost > 0
              ? `${counts.orders_without_cost} commande(s) livrée(s) sans coût enregistré (avant le suivi du stock) : leur coût n'est pas compté.`
              : "Le suivi du stock n'a pas commencé : le coût des produits n'est pas encore connu."}
            {r.ledger_start && ` Coûts suivis à partir du ${fmtDate(r.ledger_start)}.`}
          </p>
        )}
        <Rows>
          <Row label={`Chiffre d'affaires (${counts.delivered} livrée${counts.delivered > 1 ? 's' : ''})`} value={pnl.revenue_cents} />
          <Row label={`Coût des produits vendus (${counts.units_delivered} unité${counts.units_delivered > 1 ? 's' : ''})`} value={-pnl.cogs_cents} />
          <Row label="Frais des livreurs (livrées + retours)" value={-pnl.carrier_fees_cents} />
          <Row label="Marge brute" value={pnl.gross_margin_cents} strong />
          <Row label="Dépenses" value={-pnl.expenses_cents} />
          <Row label={`Produits perdus (retours, ${counts.units_lost} unité${counts.units_lost > 1 ? 's' : ''})`} value={-pnl.write_offs_cents} />
          <Row label="Bénéfice net" value={pnl.net_profit_cents} strong big />
        </Rows>
        <p className="mt-10 fs-13 text-[#6b6b6b]">
          Coût des retours : <b>{fmtMoney(pnl.return_cost_cents)}</b> ({counts.returned} retour{counts.returned > 1 ? 's' : ''} : frais + produits perdus)
        </p>
        {r.expenses_by_category.length > 0 && (
          <div className="mt-12 border-t border-[#f1e8e4] pt-10">
            <h3 className="fs-12 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">Dépenses par catégorie</h3>
            <Rows>
              {r.expenses_by_category.map((c) => (
                <Row key={c.category} label={c.category} value={c.amount_cents} plain />
              ))}
            </Rows>
          </div>
        )}
      </Card>

      <Card title="Marketing" sub="Dépenses de la catégorie Publicité">
        <Rows>
          <Row label="Budget publicité" value={m.ad_spend_cents} plain />
          <Line label={`Coût par commande (${counts.confirmed_created} confirmée${counts.confirmed_created > 1 ? 's' : ''})`}>
            {m.cpa_cents == null ? '—' : fmtMoney(m.cpa_cents)}
          </Line>
          <Line label="ROAS (CA ÷ publicité)">{m.roas == null ? '—' : `${m.roas.toLocaleString('fr-FR')} ×`}</Line>
        </Rows>
        {m.ad_spend_cents === 0 && <p className="mt-8 fs-13 text-[#8a8a8a]">Aucune dépense publicitaire sur la période.</p>}
        {m.campaigns.length > 0 && (
          <div className="mt-12 border-t border-[#f1e8e4] pt-10">
            <h3 className="fs-12 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">Par campagne (budget)</h3>
            <Rows>
              {m.campaigns.map((c) => (
                <Row key={c.campaign} label={c.campaign} value={c.spend_cents} plain />
              ))}
            </Rows>
          </div>
        )}
      </Card>

      <Card title="Économie par commande" sub="Moyennes des commandes livrées sur la période">
        <Rows>
          <Line label="Prix moyen encaissé">{money(u.avg_revenue_cents)}</Line>
          <Line label="Coût produit moyen">{money(u.avg_cogs_cents)}</Line>
          <Line label="Frais livreur moyen">{money(u.avg_carrier_fee_cents)}</Line>
          <Line label="Coût publicité par commande">{money(u.cpa_cents)}</Line>
          <Line label="Gain par commande" strong>
            {money(u.profit_per_order_cents)}
          </Line>
          <Line label="Charges fixes mensuelles">{fmtMoney(u.fixed_monthly_cents)}</Line>
        </Rows>
        <p className="mt-10 r-10 bg-[#faf6f3] px-12 py-10 fs-14">
          {u.break_even_orders_per_month != null ? (
            <>
              Seuil de rentabilité : <b>{`${u.break_even_orders_per_month} commande${u.break_even_orders_per_month > 1 ? 's livrées' : ' livrée'} / mois`}</b>
            </>
          ) : u.fixed_monthly_cents === 0 ? (
            'Seuil de rentabilité : ajoutez vos dépenses mensuelles (cochez « chaque mois »).'
          ) : (
            'Seuil de rentabilité : pas assez de commandes livrées, ou chaque commande coûte plus qu’elle ne rapporte.'
          )}
        </p>
      </Card>

      <Card title="Trésorerie" sub="Argent réellement reçu et payé sur la période" className="lg:col-span-2">
        <div className="grid grid-cols-2 gap-10 md:grid-cols-4">
          <Stat label="Entrées (versements livreurs)" value={cash.in_cents} tone="pos" />
          <Stat label="Sorties (dépenses)" value={-cash.out_expenses_cents} tone="neg" />
          <Stat label="Sorties (fournisseurs)" value={-cash.out_suppliers_cents} tone="neg" />
          <Stat label="Solde de la période" value={cash.net_cents} tone={cash.net_cents >= 0 ? 'pos' : 'neg'} />
          <Stat label="À encaisser (chez les livreurs)" value={cash.to_collect_cents} />
          <Stat label="À payer (fournisseurs)" value={cash.to_pay_cents} />
        </div>
        <CashChart days={cash.days} />
      </Card>
    </div>
  )
}

function CashChart({ days }: { days: FinanceReport['cash']['days'] }) {
  if (days.length === 0) return <p className="mt-12 fs-13 text-[#8a8a8a]">Aucun mouvement d'argent sur la période.</p>
  const max = Math.max(1, ...days.map((d) => Math.abs(d.balance_cents)))
  return (
    <div className="mt-14">
      <h3 className="fs-12 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">Solde cumulé par jour</h3>
      <ul className="mt-8 grid gap-6">
        {days.map((d) => {
          const pct = Math.max(2, Math.round((Math.abs(d.balance_cents) / max) * 100))
          const neg = d.balance_cents < 0
          return (
            <li key={d.date} className="grid grid-cols-[64px_1fr] items-center gap-10 fs-12.5 md:grid-cols-[80px_1fr_140px]">
              <span className="text-[#6b6b6b]">{fmtDate(d.date).slice(0, 5)}</span>
              <span className="h-12 r-5 bg-[#f4eeeb]" title={fmtMoney(d.balance_cents)}>
                <span className={`block h-12 r-5 ${neg ? 'bg-[#c9605f]' : 'bg-[#3a7d4a]'}`} style={{ width: `${pct}%` }} />
              </span>
              <span className={`col-start-2 text-right font-semibold tabular-nums md:col-start-3 ${neg ? 'text-[#a12a2a]' : ''}`}>
                {fmtMoney(d.balance_cents)}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Card({ title, sub, className = '', children }: { title: string; sub?: string; className?: string; children: ReactNode }) {
  return (
    <section className={`r-14 border border-[#ece2dd] bg-white p-16 md:p-20 ${className}`}>
      <h2 className="fs-16 font-bold">{title}</h2>
      {sub && <p className="mt-2 fs-12.5 text-[#8a8a8a]">{sub}</p>}
      <div className="mt-12">{children}</div>
    </section>
  )
}

const Rows = ({ children }: { children: ReactNode }) => <dl className="divide-y divide-[#f4eeeb]">{children}</dl>

function Line({ label, strong, children }: { label: string; strong?: boolean; children: ReactNode }) {
  return (
    <div className={`flex items-baseline justify-between gap-12 py-8 fs-14 ${strong ? 'font-bold' : ''}`}>
      <dt className="text-[#3a3a3a]">{label}</dt>
      <dd className="whitespace-nowrap tabular-nums">{children}</dd>
    </div>
  )
}

/** A money line: negatives in red with a minus sign (costs), totals in bold. */
function Row({ label, value, strong, big, plain }: { label: string; value: number; strong?: boolean; big?: boolean; plain?: boolean }) {
  const neg = value < 0
  return (
    <div className={`flex items-baseline justify-between gap-12 py-8 ${big ? 'fs-17' : 'fs-14'} ${strong ? 'font-bold' : ''}`}>
      <dt className="text-[#3a3a3a]">{label}</dt>
      <dd className={`whitespace-nowrap tabular-nums ${neg && !plain ? 'text-[#a12a2a]' : ''}`}>
        {neg ? '− ' : ''}
        {fmtMoney(Math.abs(value))}
      </dd>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: 'pos' | 'neg' }) {
  const color = tone === 'neg' && value !== 0 ? 'text-[#a12a2a]' : tone === 'pos' && value > 0 ? 'text-[#1f6b2a]' : ''
  return (
    <div className="r-10 bg-[#faf6f3] px-12 py-10">
      <p className="fs-12 text-[#6b6b6b]">{label}</p>
      <p className={`mt-4 fs-15 font-bold tabular-nums ${color}`}>
        {value < 0 ? '− ' : ''}
        {fmtMoney(Math.abs(value))}
      </p>
    </div>
  )
}

/* ------------------------------------------------------------------ Dépenses */

type Draft = { id: number | null; date: string; category: string; amount: string; campaign: string; note: string; recurring: boolean }
const emptyDraft = (category = ''): Draft => ({ id: null, date: casaToday(), category, amount: '', campaign: '', note: '', recurring: false })

function Expenses({ period, fail, setMessage }: { period: Period; fail: (e: unknown) => void; setMessage: (m: Msg) => void }) {
  const [cats, setCats] = useState<ExpenseCategory[]>([])
  const [filter, setFilter] = useState('')
  const [list, setList] = useState<{ items: Expense[]; has_more: boolean; total_cents: number } | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [busy, setBusy] = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [showCats, setShowCats] = useState(false)
  const key = JSON.stringify(period) + filter

  const loadCats = useCallback(
    () =>
      adminApi
        .expenseCategories(true)
        .then((x) => setCats(x.items))
        .catch(fail),
    [fail],
  )
  const load = useCallback(
    () =>
      adminApi
        .expenses(period, 0, filter || undefined)
        .then(setList)
        .catch(fail),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key, fail],
  )
  useEffect(() => {
    loadCats()
  }, [loadCats])
  useEffect(() => {
    setList(null)
    load()
  }, [load])

  const active = cats.filter((c) => c.active)

  const more = async () => {
    if (!list) return
    setLoadingMore(true)
    try {
      const x = await adminApi.expenses(period, list.items.length, filter || undefined)
      setList({ ...x, items: [...list.items, ...x.items] })
    } catch (e) {
      fail(e)
    } finally {
      setLoadingMore(false)
    }
  }

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (!draft) return
    const amount = parseMad(draft.amount)
    if (!(amount > 0)) return setMessage({ kind: 'error', text: 'Montant invalide (ex. 150 ou 150,50).' })
    if (!draft.category) return setMessage({ kind: 'error', text: 'Choisissez une catégorie.' })
    const body = {
      date: draft.date,
      category: draft.category,
      amount,
      campaign: draft.campaign.trim(),
      note: draft.note.trim(),
      recurring_monthly: draft.recurring,
    }
    setBusy(true)
    try {
      if (draft.id == null) await adminApi.addExpense(body)
      else await adminApi.editExpense(draft.id, body)
      await load()
      setMessage({ kind: 'ok', text: draft.id == null ? 'Dépense ajoutée.' : 'Dépense modifiée.' })
      setDraft(null)
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (x: Expense) => {
    if (!window.confirm(`Supprimer la dépense du ${fmtDate(x.date)} (${x.category}, ${fmtMoney(x.amount_cents)}) ?`)) return
    setDeleting(x.id)
    try {
      await adminApi.deleteExpense(x.id)
      await load()
      setMessage({ kind: 'ok', text: 'Dépense supprimée.' })
      if (draft?.id === x.id) setDraft(null)
    } catch (err) {
      fail(err)
    } finally {
      setDeleting(null)
    }
  }

  const edit = (x: Expense) =>
    setDraft({
      id: x.id,
      date: x.date,
      category: x.category,
      amount: (x.amount_cents / 100).toFixed(2).replace('.', ','),
      campaign: x.campaign,
      note: x.note,
      recurring: x.recurring_monthly,
    })

  return (
    <div className="mt-14 grid gap-14">
      <div className="flex flex-wrap items-end gap-10">
        <div className="min-w-200 flex-1 md:max-w-280">
          <FieldLabel htmlFor="exp-filter">Catégorie</FieldLabel>
          <select id="exp-filter" className={inputClass} value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">Toutes</option>
            {cats.map((c) => (
              <option key={c.id} value={c.name}>
                {c.name}
                {c.active ? '' : ' (désactivée)'}
              </option>
            ))}
          </select>
        </div>
        <BusyButton type="button" onClick={() => (setMessage(null), setDraft(emptyDraft(active[0]?.name ?? '')))}>
          Ajouter une dépense
        </BusyButton>
        <BusyButton type="button" variant="secondary" onClick={() => setShowCats((v) => !v)}>
          Catégories
        </BusyButton>
      </div>

      {showCats && <Categories cats={cats} reload={loadCats} fail={fail} setMessage={setMessage} />}

      {draft && (
        <form onSubmit={save} className="r-14 border border-[#ece2dd] bg-white p-16 md:p-20">
          <h2 className="fs-16 font-bold">{draft.id == null ? 'Nouvelle dépense' : 'Modifier la dépense'}</h2>
          <div className="mt-12 grid gap-12 md:grid-cols-3">
            <div>
              <FieldLabel htmlFor="exp-date">Date</FieldLabel>
              <input id="exp-date" type="date" required className={inputClass} value={draft.date} onChange={(e) => setDraft({ ...draft, date: e.target.value })} />
            </div>
            <div>
              <FieldLabel htmlFor="exp-cat">Catégorie</FieldLabel>
              <select id="exp-cat" required className={inputClass} value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })}>
                {!active.some((c) => c.name === draft.category) && <option value={draft.category}>{draft.category || '—'}</option>}
                {active.map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel htmlFor="exp-amount">Montant (MAD)</FieldLabel>
              <input
                id="exp-amount"
                inputMode="decimal"
                required
                placeholder="0,00"
                className={inputClass}
                value={draft.amount}
                onChange={(e) => setDraft({ ...draft, amount: e.target.value })}
              />
            </div>
            {draft.category === 'Publicité' && (
              <div>
                <FieldLabel htmlFor="exp-campaign">Campagne</FieldLabel>
                <input
                  id="exp-campaign"
                  maxLength={80}
                  placeholder="ex. Facebook novembre"
                  className={inputClass}
                  value={draft.campaign}
                  onChange={(e) => setDraft({ ...draft, campaign: e.target.value })}
                />
              </div>
            )}
            <div className={draft.category === 'Publicité' ? 'md:col-span-2' : 'md:col-span-3'}>
              <FieldLabel htmlFor="exp-note">Note</FieldLabel>
              <input id="exp-note" maxLength={500} className={inputClass} value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} />
            </div>
          </div>
          <label className="mt-12 flex min-h-40 items-center gap-10 fs-14">
            <input type="checkbox" className="size-20 accent-[#3a0a10]" checked={draft.recurring} onChange={(e) => setDraft({ ...draft, recurring: e.target.checked })} />
            Chaque mois (recréée automatiquement le 1er du mois)
          </label>
          <div className="mt-12 flex flex-wrap gap-10">
            <BusyButton type="submit" busy={busy}>
              Enregistrer
            </BusyButton>
            <BusyButton type="button" variant="secondary" onClick={() => setDraft(null)}>
              Annuler
            </BusyButton>
          </div>
        </form>
      )}

      <section className="r-14 border border-[#ece2dd] bg-white">
        <div className="flex items-baseline justify-between gap-12 border-b border-[#f1e8e4] px-16 py-12">
          <h2 className="fs-16 font-bold">Dépenses</h2>
          {list && (
            <p className="fs-14">
              Total : <b className="tabular-nums">{fmtMoney(list.total_cents)}</b>
            </p>
          )}
        </div>
        {!list ? (
          <p className="px-16 py-14 fs-14 text-[#8a8a8a]">Chargement…</p>
        ) : list.items.length === 0 ? (
          <p className="px-16 py-14 fs-14 text-[#8a8a8a]">Aucune dépense sur la période.</p>
        ) : (
          <ul className="divide-y divide-[#f4eeeb]">
            {list.items.map((x) => (
              <li key={x.id} className="flex flex-wrap items-center gap-x-12 gap-y-6 px-16 py-10">
                <div className="min-w-0 flex-1">
                  <p className="fs-14 font-semibold">
                    {x.category}
                    {x.campaign && <span className="font-normal text-[#6b6b6b]"> · {x.campaign}</span>}
                    {(x.recurring_monthly || x.recurring_parent_id) && (
                      <span className="ml-6 inline-block r-5 bg-[#f1e8e4] px-6 py-1 fs-11 font-semibold text-[#3a0a10]">mensuelle</span>
                    )}
                  </p>
                  <p className="truncate fs-12.5 text-[#8a8a8a]">
                    {fmtDate(x.date)}
                    {x.note && ` · ${x.note}`}
                  </p>
                </div>
                <span className="fs-14 font-bold tabular-nums">{fmtMoney(x.amount_cents)}</span>
                <div className="flex gap-6">
                  <button
                    type="button"
                    onClick={() => (setMessage(null), edit(x))}
                    className="h-40 r-10 border border-[#d9cfca] bg-white px-12 fs-13 font-semibold hover:bg-[#faf6f3]"
                  >
                    Modifier
                  </button>
                  <button
                    type="button"
                    disabled={deleting === x.id}
                    onClick={() => remove(x)}
                    className="h-40 r-10 border border-[#e2b4b4] bg-[#fdf2f2] px-12 fs-13 font-semibold text-[#a12a2a] disabled:opacity-60"
                  >
                    {deleting === x.id ? 'Patientez…' : 'Supprimer'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {list?.has_more && (
          <div className="border-t border-[#f1e8e4] p-12 text-center">
            <BusyButton type="button" variant="secondary" busy={loadingMore} onClick={more}>
              Voir plus
            </BusyButton>
          </div>
        )}
      </section>
    </div>
  )
}

function Categories({
  cats,
  reload,
  fail,
  setMessage,
}: {
  cats: ExpenseCategory[]
  reload: () => Promise<unknown>
  fail: (e: unknown) => void
  setMessage: (m: Msg) => void
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const run = async (id: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(id)
    try {
      await fn()
      await reload()
      setMessage({ kind: 'ok', text: ok })
    } catch (e) {
      fail(e)
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="r-14 border border-[#ece2dd] bg-white p-16 md:p-20">
      <h2 className="fs-16 font-bold">Catégories de dépenses</h2>
      <p className="mt-2 fs-12.5 text-[#8a8a8a]">Les frais des livreurs et les paiements fournisseurs sont comptés à part : ne les saisissez pas ici.</p>
      <ul className="mt-10 divide-y divide-[#f4eeeb]">
        {cats.map((c) => (
          <li key={c.id} className="flex items-center justify-between gap-10 py-6">
            <span className={`fs-14 ${c.active ? '' : 'text-[#8a8a8a] line-through'}`}>{c.name}</span>
            <BusyButton
              type="button"
              variant="secondary"
              busy={busy === `c${c.id}`}
              onClick={() =>
                run(`c${c.id}`, () => adminApi.editCategory(c.id, { active: !c.active }), c.active ? 'Catégorie désactivée.' : 'Catégorie réactivée.')
              }
            >
              {c.active ? 'Désactiver' : 'Réactiver'}
            </BusyButton>
          </li>
        ))}
      </ul>
      <form
        className="mt-10 flex flex-wrap items-end gap-10"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) run('new', () => adminApi.addCategory(name.trim()), 'Catégorie ajoutée.').then(() => setName(''))
        }}
      >
        <div className="min-w-200 flex-1">
          <FieldLabel htmlFor="cat-new">Nouvelle catégorie</FieldLabel>
          <input id="cat-new" maxLength={60} className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <BusyButton type="submit" busy={busy === 'new'}>
          Ajouter
        </BusyButton>
      </form>
    </section>
  )
}
