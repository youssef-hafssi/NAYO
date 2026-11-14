import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { adminApi, Unauthorized, type Dashboard as Data } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { Banner, fmtDate, fmtMoney, usePolling, WINE } from './ui'

/*
 * Tableau de bord. Everyone sees the counts; money (revenue, profit, stock value, cash, debts) is owner-only and
 * simply absent from the agents' answer (server-side). Refreshed every minute (the server caches 30 s).
 */

const pct = (r: number | null) => (r == null ? '—' : `${Math.round(r * 100)} %`)
const mad = (c: number | null | undefined) => (c == null ? '—' : fmtMoney(c).replace(/,00 MAD$/, ' MAD'))

export default function Dashboard() {
  const { me, logout } = useAuth()
  const owner = me.role === 'owner'
  const [d, setD] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    () =>
      adminApi
        .dashboard()
        .then((x) => (setD(x), setError(null)))
        .catch((e) => (e instanceof Unauthorized ? logout() : setError(e instanceof Error ? e.message : 'Erreur'))),
    [logout],
  )
  useEffect(() => {
    load()
  }, [load])
  usePolling(load, 60000, true)

  if (!d)
    return (
      <div className="p-24 fs-14 text-[#8a8a8a]">
        {error ? <Banner msg={{ kind: 'error', text: error }} /> : 'Chargement…'}
      </div>
    )

  const f = d.follow_ups
  const toDo = f ? f.late + f.today + f.suggestions : 0
  const st = d.stock

  return (
    <div className="mx-auto w-full max-w-1100 px-16 py-16 md:px-24 md:py-24">
      <div className="flex flex-wrap items-baseline justify-between gap-8">
        <h1 className="fs-22 font-bold">Tableau de bord</h1>
        <p className="fs-12 text-[#8a8a8a]">Mis à jour à {d.generated_at.slice(11, 16)}</p>
      </div>
      <Banner msg={error ? { kind: 'error', text: error } : null} />

      <Section title="Commandes">
        <Tile label="Aujourd'hui" value={d.orders.today} to="/admin/orders" />
        <Tile label="Cette semaine" value={d.orders.week} />
        <Tile label="Ce mois" value={d.orders.month} />
        <Tile
          label="Taux de confirmation (mois)"
          value={pct(d.confirmation_rate.rate)}
          sub={`${d.confirmation_rate.confirmed} sur ${d.confirmation_rate.decided} traitées`}
        />
        <Tile
          label="Livraisons réussies (30 j)"
          value={pct(d.delivery_rate.rate)}
          sub={`${d.delivery_rate.delivered} livrée(s), ${d.delivery_rate.returned} retour(s)`}
        />
        <Tile label="En cours (confirmées + expédiées)" value={d.in_progress.orders} sub={owner && d.money ? mad(d.money.in_progress_cents) : undefined} />
      </Section>

      <Section title="À traiter">
        <Tile label="Besoin d'un humain" value={d.needs_human} to="/admin/inbox" alert={d.needs_human > 0} />
        {f && (
          <Tile
            label="Relances"
            value={toDo}
            sub={`${f.late} en retard · ${f.today} aujourd'hui · ${f.suggestions} suggestion(s)`}
            to="/admin/follow-ups"
            alert={f.late > 0}
          />
        )}
        {st && (
          <Tile
            label="Stock restant"
            value={st.tracking ? `${st.on_hand} u.` : '—'}
            sub={
              !st.tracking
                ? 'Suivi du stock pas encore démarré'
                : [st.days_of_stock != null ? `≈ ${st.days_of_stock} jours au rythme actuel` : '', owner && st.value_cents != null ? `valeur ${mad(st.value_cents)}` : '']
                    .filter(Boolean)
                    .join(' · ') || `seuil d'alerte : ${st.low_threshold}`
            }
            to="/admin/stock"
            alert={st.tracking && st.low}
          />
        )}
        <Tile label="Unités livrées (mois)" value={d.units_month} />
      </Section>

      {owner && d.money && (
        <Section title="Argent (ce mois)">
          <Tile label="Chiffre d'affaires livré" value={mad(d.money.revenue_month_cents)} to="/admin/finance" />
          <Tile label="Bénéfice net" value={mad(d.money.net_profit_month_cents)} to="/admin/finance" negative={d.money.net_profit_month_cents < 0} />
          <Tile label="Panier moyen" value={mad(d.money.avg_basket_cents)} />
          <Tile label="À encaisser chez les livreurs" value={mad(d.money.to_collect_cents)} to="/admin/delivery?tab=cod" />
          <Tile label="Dettes fournisseurs" value={mad(d.money.to_pay_cents)} to="/admin/purchasing" />
        </Section>
      )}

      <div className={`mt-18 grid gap-14 ${owner ? 'lg:grid-cols-2' : ''}`}>
        <BarChart
          title="Commandes reçues par jour"
          sub="30 derniers jours"
          data={d.chart.map((r) => ({ date: r.date, value: r.orders }))}
          format={(v) => `${v} commande${v > 1 ? 's' : ''}`}
        />
        {owner && (
          <BarChart
            title="Chiffre d'affaires livré par jour"
            sub="30 derniers jours, par date de livraison"
            data={d.chart.map((r) => ({ date: r.date, value: r.revenue_cents ?? 0 }))}
            format={(v) => mad(v)}
          />
        )}
      </div>

      <section className="mt-14 r-14 border border-[#ece2dd] bg-white p-16">
        <h2 className="fs-15 font-bold">Villes du mois</h2>
        {d.top_cities.length === 0 ? (
          <p className="mt-8 fs-13 text-[#8a8a8a]">Aucune ville renseignée ce mois-ci.</p>
        ) : (
          <ul className="mt-10 grid gap-8">
            {d.top_cities.map((c) => (
              <li key={c.city} className="grid grid-cols-[110px_1fr_40px] items-center gap-10 fs-13.5 md:grid-cols-[160px_1fr_48px]">
                <span className="truncate">{c.city}</span>
                <span className="h-10 r-5 bg-[#f4eeeb]">
                  <span className="block h-10 r-5" style={{ width: `${Math.max(4, (c.orders / d.top_cities[0].orders) * 100)}%`, background: WINE }} />
                </span>
                <span className="text-right font-semibold tabular-nums">{c.orders}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-16">
      <h2 className="fs-12 font-bold uppercase tracking-[0.06em] text-[#8a8a8a]">{title}</h2>
      <div className="mt-8 grid grid-cols-2 gap-10 md:grid-cols-3 lg:grid-cols-6">{children}</div>
    </section>
  )
}

function Tile({
  label,
  value,
  sub,
  to,
  alert,
  negative,
}: {
  label: string
  value: ReactNode
  sub?: string
  to?: string
  alert?: boolean
  negative?: boolean
}) {
  const body = (
    <>
      <p className="fs-12 leading-snug text-[#6b6b6b]">{label}</p>
      <p className={`mt-4 fs-20 font-bold tabular-nums ${negative ? 'text-[#a12a2a]' : ''}`}>{value}</p>
      {sub && <p className="mt-2 fs-11.5 leading-snug text-[#8a8a8a]">{sub}</p>}
    </>
  )
  const cls = `block min-h-88 r-12 border px-12 py-10 ${alert ? 'border-[#e8b4b4] bg-[#fdf3f3]' : 'border-[#ece2dd] bg-white'}`
  return to ? (
    <Link to={to} className={`${cls} hover:border-[#d9cfca]`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}

/** One series per chart (never two y-scales): thin bars, 2 px gaps, hover tooltip, and the numbers as a table. */
export function BarChart({ title, sub, data, format }: { title: string; sub?: string; data: { date: string; value: number }[]; format: (v: number) => string }) {
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(1, ...data.map((d) => d.value))
  const W = 600
  const H = 150
  const step = W / data.length
  const bw = Math.max(2, step - 2)
  const total = data.reduce((a, d) => a + d.value, 0)
  const h = hover != null ? data[hover] : null
  return (
    <section className="r-14 border border-[#ece2dd] bg-white p-16">
      <div className="flex flex-wrap items-baseline justify-between gap-8">
        <h2 className="fs-15 font-bold">{title}</h2>
        <p className="fs-12.5 text-[#6b6b6b]">
          Total : <b className="tabular-nums text-[#1a1a1a]">{format(total)}</b>
        </p>
      </div>
      {sub && <p className="fs-12 text-[#8a8a8a]">{sub}</p>}
      <div className="relative mt-10" onMouseLeave={() => setHover(null)}>
        <p className="h-18 fs-12 text-[#3a3a3a]" aria-live="polite">
          {h ? (
            <>
              <b>{fmtDate(h.date).slice(0, 5)}</b> · {format(h.value)}
            </>
          ) : (
            <span className="text-[#8a8a8a]">Survolez une barre pour voir le détail</span>
          )}
        </p>
        <svg viewBox={`0 0 ${W} ${H + 18}`} className="mt-4 block h-auto w-full" role="img" aria-label={`${title}, ${data.length} jours`}>
          <line x1={0} x2={W} y1={H} y2={H} stroke="#e4dcd8" strokeWidth={1} />
          <text x={0} y={10} fontSize={11} fill="#8a8a8a">
            {format(max)}
          </text>
          {data.map((d, i) => {
            const bh = d.value ? Math.max(3, (d.value / max) * (H - 18)) : 0
            const x = i * step + 1
            return (
              <g key={d.date} onMouseEnter={() => setHover(i)} onClick={() => setHover(i)}>
                {/* hit target: the whole column, bigger than the bar */}
                <rect x={i * step} y={0} width={step} height={H} fill="transparent" />
                {bh > 0 && (
                  <path
                    d={`M${x},${H} v${-(bh - Math.min(4, bh / 2))} q0,${-Math.min(4, bh / 2)} ${Math.min(4, bw / 2)},${-Math.min(4, bh / 2)} h${bw - 2 * Math.min(4, bw / 2)} q${Math.min(4, bw / 2)},0 ${Math.min(4, bw / 2)},${Math.min(4, bh / 2)} v${bh - Math.min(4, bh / 2)} z`}
                    fill={WINE}
                    opacity={hover == null || hover === i ? 1 : 0.45}
                  />
                )}
              </g>
            )
          })}
          <text x={0} y={H + 14} fontSize={11} fill="#8a8a8a">
            {fmtDate(data[0]?.date).slice(0, 5)}
          </text>
          <text x={W} y={H + 14} fontSize={11} fill="#8a8a8a" textAnchor="end">
            {fmtDate(data[data.length - 1]?.date).slice(0, 5)}
          </text>
        </svg>
      </div>
      <details className="mt-8 fs-12.5">
        <summary className="cursor-pointer text-[#6b6b6b]">Voir les chiffres</summary>
        <table className="mt-6 w-full">
          <tbody>
            {data
              .filter((d) => d.value)
              .map((d) => (
                <tr key={d.date} className="border-b border-[#f4eeeb]">
                  <td className="py-4">{fmtDate(d.date)}</td>
                  <td className="py-4 text-right tabular-nums">{format(d.value)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </details>
    </section>
  )
}
