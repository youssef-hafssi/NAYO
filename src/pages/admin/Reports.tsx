import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Download, Printer } from 'lucide-react'
import {
  adminApi,
  Unauthorized,
  type ClosingReport,
  type DeliveryReport,
  type MarginReport,
  type Period,
  type ReportName,
  type SalesReport,
  type StockReport,
} from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { BarChart } from './Dashboard'
import { Banner, Chip, FieldLabel, fmtDate, fmtMoney, inputClass, STATUS_LABEL, STOCK_REASON } from './ui'

/* Rapports (owner only, enforced server-side): Ventes, Stock, Livraisons, Marge par jour, Clôture mensuelle. */

type Tab = ReportName | 'closing'
const TABS: { key: Tab; label: string }[] = [
  { key: 'sales', label: 'Ventes' },
  { key: 'stock', label: 'Valorisation du stock' },
  { key: 'delivery', label: 'Livraisons' },
  { key: 'margin', label: 'Marge par jour' },
  { key: 'closing', label: 'Clôture mensuelle' },
]
const PRESETS = [
  { key: 'week', label: 'Cette semaine' },
  { key: 'month', label: 'Ce mois' },
  { key: 'custom', label: 'Personnalisée' },
] as const

const casaToday = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Africa/Casablanca' })
const pct = (r: number | null) => (r == null ? '—' : `${(r * 100).toFixed(1).replace('.', ',')} %`)
const days = (v: number | null) => (v == null ? '—' : `${String(v).replace('.', ',')} j`)

export default function Reports() {
  const { me, logout } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = (TABS.find((t) => t.key === params.get('tab'))?.key ?? 'sales') as Tab
  const [preset, setPreset] = useState<'week' | 'month' | 'custom'>('month')
  const [frm, setFrm] = useState(() => casaToday().slice(0, 8) + '01')
  const [to, setTo] = useState(casaToday)
  const [month, setMonth] = useState(() => casaToday().slice(0, 7))
  const [data, setData] = useState<unknown>(null)
  const [error, setError] = useState<string | null>(null)

  const customOk = /^\d{4}-\d{2}-\d{2}$/.test(frm) && /^\d{4}-\d{2}-\d{2}$/.test(to) && frm <= to
  const period: Period | null = preset === 'custom' ? (customOk ? { frm, to } : null) : { preset }
  const key = tab === 'closing' ? `closing:${month}` : `${tab}:${JSON.stringify(period)}`

  const fail = useCallback((e: unknown) => (e instanceof Unauthorized ? logout() : setError(e instanceof Error ? e.message : 'Erreur')), [logout])

  useEffect(() => {
    let live = true
    setData(null)
    setError(null)
    const run = tab === 'closing' ? (/^\d{4}-\d{2}$/.test(month) ? adminApi.closing(month) : null) : period ? adminApi.report(tab, period) : null
    run?.then((x) => live && setData(x)).catch((e) => live && fail(e))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, fail])

  if (me.role !== 'owner')
    return (
      <div className="mx-auto w-full max-w-1100 px-16 py-16 md:px-24 md:py-24">
        <h1 className="fs-22 font-bold">Rapports</h1>
        <p className="mt-12 fs-14 text-[#6b6b6b]">Réservé au propriétaire.</p>
      </div>
    )

  const csv = tab === 'closing' ? adminApi.closingCsvUrl(month) : period ? adminApi.reportCsvUrl(tab, period) : null

  return (
    <div className="mx-auto w-full max-w-1100 px-16 py-16 md:px-24 md:py-24">
      <div className="flex flex-wrap items-center justify-between gap-12">
        <h1 className="fs-22 font-bold">Rapports</h1>
        <div className="flex flex-wrap gap-8">
          {tab === 'closing' && (
            <Link
              to={`/admin/reports/closing/print?month=${month}`}
              target="_blank"
              className="inline-flex h-44 items-center gap-8 r-10 border border-[#d9cfca] bg-white px-14 fs-14 font-semibold hover:bg-[#faf6f3] md:h-40"
            >
              <Printer className="size-16" aria-hidden /> Imprimer
            </Link>
          )}
          {csv && (
            <a href={csv} className="inline-flex h-44 items-center gap-8 r-10 border border-[#d9cfca] bg-white px-14 fs-14 font-semibold hover:bg-[#faf6f3] md:h-40">
              <Download className="size-16" aria-hidden /> Exporter (CSV)
            </a>
          )}
        </div>
      </div>

      <div className="mt-12 flex flex-wrap gap-8">
        {TABS.map((t) => (
          <Chip key={t.key} active={tab === t.key} onClick={() => setParams(t.key === 'sales' ? {} : { tab: t.key })}>
            {t.label}
          </Chip>
        ))}
      </div>

      <section aria-label="Période" className="mt-12 r-14 border border-[#ece2dd] bg-white p-14">
        {tab === 'closing' ? (
          <div className="max-w-220">
            <FieldLabel htmlFor="r-month">Mois</FieldLabel>
            <input id="r-month" type="month" max={casaToday().slice(0, 7)} className={inputClass} value={month} onChange={(e) => setMonth(e.target.value)} />
          </div>
        ) : (
          <>
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
                  <FieldLabel htmlFor="r-from">Du</FieldLabel>
                  <input id="r-from" type="date" className={inputClass} value={frm} max={to} onChange={(e) => setFrm(e.target.value)} />
                </div>
                <div>
                  <FieldLabel htmlFor="r-to">Au</FieldLabel>
                  <input id="r-to" type="date" className={inputClass} value={to} min={frm} onChange={(e) => setTo(e.target.value)} />
                </div>
                {!customOk && <p className="col-span-2 fs-13 text-[#a12a2a]">La date de début doit précéder la date de fin.</p>}
              </div>
            )}
          </>
        )}
      </section>

      <Banner msg={error ? { kind: 'error', text: error } : null} />
      {!data && !error ? (
        <p className="mt-18 fs-14 text-[#8a8a8a]">Chargement…</p>
      ) : data ? (
        <div className="mt-14">
          {tab === 'sales' && <Sales r={data as SalesReport} />}
          {tab === 'stock' && <Stock r={data as StockReport} />}
          {tab === 'delivery' && <Delivery r={data as DeliveryReport} />}
          {tab === 'margin' && <Margin r={data as MarginReport} />}
          {tab === 'closing' && <Closing r={data as ClosingReport} />}
        </div>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------ building blocks */

function Kpis({ items }: { items: [string, ReactNode][] }) {
  return (
    <div className="grid grid-cols-2 gap-10 md:grid-cols-4">
      {items.map(([label, value]) => (
        <div key={label} className="r-10 bg-[#faf6f3] px-12 py-10">
          <p className="fs-12 text-[#6b6b6b]">{label}</p>
          <p className="mt-4 fs-16 font-bold tabular-nums">{value}</p>
        </div>
      ))}
    </div>
  )
}

function Table({ head, rows, foot, empty = 'Aucune donnée sur la période.' }: { head: string[]; rows: ReactNode[][]; foot?: ReactNode[]; empty?: string }) {
  if (!rows.length) return <p className="mt-12 fs-13 text-[#8a8a8a]">{empty}</p>
  return (
    <div className="mt-12 overflow-x-auto r-12 border border-[#ece2dd] bg-white">
      <table className="w-full fs-13">
        <thead>
          <tr className="border-b border-[#f1e8e4] text-left fs-11 uppercase tracking-[0.05em] text-[#8a8a8a]">
            {head.map((h, i) => (
              <th key={h} className={`whitespace-nowrap px-10 py-8 ${i ? 'text-right' : ''}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#f4eeeb]">
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j} className={`whitespace-nowrap px-10 py-6 ${j ? 'text-right tabular-nums' : ''}`}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {foot && (
          <tfoot>
            <tr className="border-t border-[#ece2dd] font-bold">
              {foot.map((c, j) => (
                <td key={j} className={`whitespace-nowrap px-10 py-8 ${j ? 'text-right tabular-nums' : ''}`}>
                  {c}
                </td>
              ))}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  )
}

const H2 = ({ children }: { children: ReactNode }) => <h2 className="mt-18 fs-15 font-bold">{children}</h2>
const money = (c: number | null) => (c == null ? '—' : fmtMoney(c))
const signed = (c: number) => <span className={c < 0 ? 'text-[#a12a2a]' : ''}>{fmtMoney(c)}</span>

/* ------------------------------------------------------------------ reports */

function Sales({ r }: { r: SalesReport }) {
  const t = r.totals
  return (
    <>
      <Kpis
        items={[
          ['Commandes créées', t.orders],
          ['Taux de confirmation', pct(t.confirmation_rate)],
          ['Livrées', `${t.delivered} (${t.units} u.)`],
          ["Chiffre d'affaires", money(t.revenue_cents)],
        ]}
      />
      <div className="mt-14">
        <BarChart title="Chiffre d'affaires livré par jour" data={r.days.map((d) => ({ date: d.date, value: d.revenue_cents }))} format={(v) => fmtMoney(v)} />
      </div>
      <H2>Par jour</H2>
      <Table
        head={['Date', 'Créées', 'Confirmées', 'Annulées', 'Livrées', 'Unités', 'CA']}
        rows={r.days.filter((d) => d.orders || d.delivered).map((d) => [fmtDate(d.date), d.orders, d.confirmed, d.cancelled, d.delivered, d.units, money(d.revenue_cents)])}
        foot={['Total', t.orders, t.confirmed, t.cancelled, t.delivered, t.units, money(t.revenue_cents)]}
      />
      <div className="grid gap-x-14 lg:grid-cols-2">
        <div>
          <H2>Par source</H2>
          <Table
            head={['Source', 'Commandes', 'Confirmées']}
            rows={r.by_source.map((s) => [s.source === 'website' ? 'Site' : s.source === 'whatsapp' ? 'WhatsApp' : s.source, s.orders, s.confirmed])}
          />
        </div>
        <div>
          <H2>Par ville (livrées)</H2>
          <Table head={['Ville', 'Livrées', 'CA']} rows={r.by_city.map((c) => [c.city, c.delivered, money(c.revenue_cents)])} />
        </div>
      </div>
      <p className="mt-10 fs-12 text-[#8a8a8a]">Panier moyen : {money(t.avg_basket_cents)} · CA = commandes livrées, par date de livraison.</p>
    </>
  )
}

function Stock({ r }: { r: StockReport }) {
  return (
    <>
      <Kpis
        items={[
          ['Valeur au début', money(r.opening.value_cents)],
          ['Valeur à la fin', money(r.closing.value_cents)],
          ['Entrées / sorties', `+${r.units_in} / −${r.units_out} u.`],
          ['Coût moyen (fin)', money(r.closing.avg_cost_cents)],
        ]}
      />
      {r.ledger_start && <p className="mt-8 fs-12 text-[#8a8a8a]">Suivi du stock depuis le {fmtDate(r.ledger_start)}. Valeur = unités × coût moyen pondéré.</p>}
      <H2>Mouvements de la période</H2>
      <Table head={['Type', 'Mouvements', 'Unités']} rows={r.by_reason.map((m) => [STOCK_REASON[m.reason] ?? m.reason, m.movements, m.units > 0 ? `+${m.units}` : m.units])} />
      <H2>Stock en fin de journée</H2>
      <Table
        head={['Date', 'Unités', 'Coût moyen', 'Valeur']}
        rows={[...r.days].reverse().map((d) => [fmtDate(d.date), d.on_hand, money(d.avg_cost_cents), money(d.value_cents)])}
      />
    </>
  )
}

function Delivery({ r }: { r: DeliveryReport }) {
  const rows = (g: DeliveryReport['by_carrier'] | DeliveryReport['by_city'], k: 'carrier' | 'city') =>
    g.map((x) => [(x as Record<string, unknown>)[k] as string, x.delivered, x.returned, pct(x.return_rate), days(x.avg_delay_days)])
  return (
    <>
      <Kpis
        items={[
          ['Livrées', r.delivered],
          ['Retours', r.returned],
          ['Taux de retour', pct(r.return_rate)],
          ['Délai confirmée → livrée', `${days(r.avg_delay_days)} (médiane ${days(r.median_delay_days)})`],
        ]}
      />
      <H2>Par livreur</H2>
      <Table head={['Livreur', 'Livrées', 'Retours', 'Taux de retour', 'Délai moyen']} rows={rows(r.by_carrier, 'carrier')} />
      <H2>Par ville</H2>
      <Table head={['Ville', 'Livrées', 'Retours', 'Taux de retour', 'Délai moyen']} rows={rows(r.by_city, 'city')} />
      <p className="mt-10 fs-12 text-[#8a8a8a]">Livraisons et retours enregistrés pendant la période. Délai mesuré depuis la confirmation (ou la création pour les commandes plus anciennes).</p>
    </>
  )
}

function Margin({ r }: { r: MarginReport }) {
  const t = r.totals
  return (
    <>
      <Kpis
        items={[
          ["Chiffre d'affaires", money(t.revenue_cents)],
          ['Marge brute', signed(t.gross_margin_cents)],
          ['Dépenses + pertes', money(t.expenses_cents + t.write_offs_cents)],
          ['Bénéfice net', signed(t.net_profit_cents)],
        ]}
      />
      <H2>Par jour</H2>
      <Table
        head={['Date', 'Livrées', 'CA', 'Coût produits', 'Frais livreurs', 'Marge brute', 'Dépenses', 'Pertes', 'Bénéfice net']}
        rows={r.days
          .filter((d) => d.delivered || d.carrier_fees_cents || d.expenses_cents || d.write_offs_cents)
          .map((d) => [
            fmtDate(d.date),
            d.delivered,
            money(d.revenue_cents),
            money(d.cogs_cents),
            money(d.carrier_fees_cents),
            signed(d.gross_margin_cents),
            money(d.expenses_cents),
            money(d.write_offs_cents),
            signed(d.net_profit_cents),
          ])}
        foot={['Total', t.delivered, money(t.revenue_cents), money(t.cogs_cents), money(t.carrier_fees_cents), signed(t.gross_margin_cents), money(t.expenses_cents), money(t.write_offs_cents), signed(t.net_profit_cents)]}
      />
      <p className="mt-10 fs-12 text-[#8a8a8a]">Mêmes règles que la page Finance : les totaux sont identiques pour la même période.</p>
    </>
  )
}

export function ClosingBody({ r }: { r: ClosingReport }) {
  const p = r.pnl
  const line = (label: string, value: ReactNode, strong = false) => (
    <tr className={strong ? 'font-bold' : ''}>
      <td className="py-5 pr-12">{label}</td>
      <td className="py-5 text-right tabular-nums">{value}</td>
    </tr>
  )
  return (
    <div className="grid gap-x-24 gap-y-14 md:grid-cols-2 print:grid-cols-2">
      <section>
        <h3 className="border-b border-[#ece2dd] pb-4 fs-13 font-bold uppercase tracking-[0.05em]">Commandes</h3>
        <table className="mt-4 w-full fs-13.5">
          <tbody>
            {line('Commandes créées', r.orders.created, true)}
            {Object.entries(r.orders.by_status).map(([s, n]) => line(`dont ${(STATUS_LABEL[s] ?? s).toLowerCase()}`, n))}
            {line('Livrées pendant le mois', r.counts.delivered)}
            {line('Retours pendant le mois', r.counts.returned)}
          </tbody>
        </table>
      </section>
      <section>
        <h3 className="border-b border-[#ece2dd] pb-4 fs-13 font-bold uppercase tracking-[0.05em]">Compte de résultat</h3>
        <table className="mt-4 w-full fs-13.5">
          <tbody>
            {line("Chiffre d'affaires", fmtMoney(p.revenue_cents))}
            {line('Coût des produits vendus', `− ${fmtMoney(p.cogs_cents)}`)}
            {line('Frais des livreurs', `− ${fmtMoney(p.carrier_fees_cents)}`)}
            {line('Marge brute', fmtMoney(p.gross_margin_cents), true)}
            {line('Dépenses', `− ${fmtMoney(p.expenses_cents)}`)}
            {line('Produits perdus (retours)', `− ${fmtMoney(p.write_offs_cents)}`)}
            {line('Bénéfice net', fmtMoney(p.net_profit_cents), true)}
          </tbody>
        </table>
      </section>
      <section>
        <h3 className="border-b border-[#ece2dd] pb-4 fs-13 font-bold uppercase tracking-[0.05em]">Trésorerie du mois</h3>
        <table className="mt-4 w-full fs-13.5">
          <tbody>
            {line('Encaissé (versements des livreurs)', fmtMoney(r.cash.in_cents))}
            {line('Payé (dépenses)', `− ${fmtMoney(r.cash.out_expenses_cents)}`)}
            {line('Payé (fournisseurs)', `− ${fmtMoney(r.cash.out_suppliers_cents)}`)}
            {line('Solde', fmtMoney(r.cash.net_cents), true)}
          </tbody>
        </table>
      </section>
      <section>
        <h3 className="border-b border-[#ece2dd] pb-4 fs-13 font-bold uppercase tracking-[0.05em]">Bilan au {fmtDate(r.to)}</h3>
        <table className="mt-4 w-full fs-13.5">
          <tbody>
            {line('Stock (unités)', r.stock.on_hand)}
            {line('Valeur du stock', fmtMoney(r.stock.value_cents))}
            {line('À encaisser chez les livreurs*', fmtMoney(r.receivables_cents))}
            {line('Dettes fournisseurs*', fmtMoney(r.debts_cents))}
          </tbody>
        </table>
        <p className="mt-4 fs-11.5 text-[#8a8a8a]">* montants au moment de l'édition ({r.generated_at.slice(0, 16).replace(' ', ' à ')}).</p>
      </section>
      {r.expenses_by_category.length > 0 && (
        <section className="md:col-span-2 print:col-span-2">
          <h3 className="border-b border-[#ece2dd] pb-4 fs-13 font-bold uppercase tracking-[0.05em]">Dépenses par catégorie</h3>
          <table className="mt-4 w-full fs-13.5">
            <tbody>{r.expenses_by_category.map((c) => line(c.category, fmtMoney(c.amount_cents)))}</tbody>
          </table>
        </section>
      )}
    </div>
  )
}

function Closing({ r }: { r: ClosingReport }) {
  return (
    <section className="r-14 border border-[#ece2dd] bg-white p-16 md:p-20">
      <p className="mb-12 fs-13 text-[#6b6b6b]">
        Du {fmtDate(r.from)} au {fmtDate(r.to)}
        {r.complete ? '' : ' — mois en cours, chiffres provisoires'}
      </p>
      <ClosingBody r={r} />
    </section>
  )
}
