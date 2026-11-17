import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminApi, Unauthorized, type VisitEvent, type VisitorsOverview, type VisitSession } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { BarChart } from './Dashboard'
import { Chip, fmtDateTime, hhmm, PageSkeleton, Pill, Skeleton, WINE } from './ui'

/*
 * Visiteurs (superadmin only, server-enforced): first-party, anonymous analytics of the store page — visits per day,
 * sources, devices, the funnel (visit → 50 % scroll → form started → order) and each visit's timeline.
 * The full Publicité page (campaigns, cost per order) comes in phase D.
 */

type Days = 7 | 30 | 90

const EVENT_LABEL: Record<string, string> = {
  page_view: 'Page vue',
  scroll_depth: 'Défilement',
  section_view: 'Section vue',
  click: 'Clic',
  faq_open: 'Question ouverte',
  checkout_view: 'Formulaire affiché',
  form_start: 'Formulaire commencé',
  field_error: 'Erreur de saisie',
  quantity_change: 'Quantité changée',
  order_submit: 'Commande envoyée',
  order_success: 'Commande enregistrée',
  whatsapp_click: 'Clic WhatsApp',
  time_on_page: 'Temps sur la page',
}

const pct = (n: number, of: number) => (of ? `${Math.round((n / of) * 100)} %` : '—')

function detail(e: VisitEvent): string {
  const d = e.data
  switch (e.name) {
    case 'scroll_depth':
      return `${d.pct} %`
    case 'section_view':
      return String(d.section ?? '')
    case 'click':
    case 'whatsapp_click':
      return String(d.id ?? '')
    case 'faq_open':
      return String(d.label ?? '')
    case 'field_error':
      return `${d.field} : ${d.error}`
    case 'quantity_change':
      return `${d.from} → ${d.to}`
    case 'order_submit':
    case 'order_success':
      return [d.order, d.qty ? `× ${d.qty}` : '', d.fallback ? '(numéro de secours)' : ''].filter(Boolean).join(' ')
    case 'time_on_page':
      return `${d.seconds} s`
    case 'page_view':
      return String(d.path ?? '')
    default:
      return String(d.form ?? '')
  }
}

function where(s: VisitSession) {
  return [s.city, s.country].filter(Boolean).join(', ')
}

export default function Visitors() {
  const { logout } = useAuth()
  const [days, setDays] = useState<Days>(30)
  const [ov, setOv] = useState<VisitorsOverview | null>(() => adminApi.analyticsOverview(30).peek() ?? null)
  const [onlyOrders, setOnlyOrders] = useState(false)
  const [list, setList] = useState<{ items: VisitSession[]; has_more: boolean } | null>(
    () => adminApi.analyticsSessions(0, false).peek() ?? null,
  )
  const [open, setOpen] = useState<string | null>(null)
  const [error, setError] = useState('')

  const fail = useCallback((e: unknown) => (e instanceof Unauthorized ? logout() : setError(e instanceof Error ? e.message : 'Erreur')), [logout])

  useEffect(() => {
    adminApi.analyticsOverview(days).then(setOv, fail)
  }, [days, fail])
  useEffect(() => {
    adminApi.analyticsSessions(0, onlyOrders).then(setList, fail)
  }, [onlyOrders, fail])

  const more = async () => {
    if (!list) return
    try {
      const next = await adminApi.analyticsSessions(list.items.length, onlyOrders)
      setList({ items: [...list.items, ...next.items], has_more: next.has_more })
    } catch (e) {
      fail(e)
    }
  }

  if (!ov) return <PageSkeleton />
  const f = ov.funnel
  const steps = [
    { label: 'Visites', n: f.visits },
    { label: 'Défilement ≥ 50 %', n: f.scroll_50 },
    { label: 'Formulaire commencé', n: f.form_started },
    { label: 'Commande', n: f.ordered },
  ]

  return (
    <div className="mx-auto w-full max-w-1100 px-16 py-16 md:px-24 md:py-24">
      <div className="flex flex-wrap items-center justify-between gap-12">
        <h1 className="fs-22 font-bold">Visiteurs</h1>
        <div className="flex gap-6" role="group" aria-label="Période">
          {([7, 30, 90] as Days[]).map((d) => (
            <Chip key={d} active={days === d} onClick={() => setDays(d)}>
              {d} jours
            </Chip>
          ))}
        </div>
      </div>
      <p className="mt-4 fs-13 text-[#7a6f6f]">Mesure anonyme du site (sans cookie, jamais l'adresse IP). Les robots sont exclus.</p>
      {error && (
        <p role="alert" className="mt-12 r-8 bg-[#fbe5e5] px-12 py-8 fs-13 text-[#a12a2a]">
          {error}
        </p>
      )}

      <div className="mt-16 grid grid-cols-2 gap-10 md:grid-cols-4">
        {[
          { label: 'Visites', value: ov.totals.visits },
          { label: 'Visiteurs', value: ov.totals.visitors },
          { label: 'Commandes', value: ov.totals.orders },
          { label: 'Taux de commande', value: pct(ov.totals.orders, ov.totals.visits) },
        ].map((t) => (
          <div key={t.label} className="r-14 border border-[#ece2dd] bg-white p-14">
            <p className="fs-12.5 text-[#6b6b6b]">{t.label}</p>
            <p className="mt-4 fs-24 font-bold tabular-nums">{t.value}</p>
          </div>
        ))}
      </div>

      <div className="mt-14">
        <BarChart title="Visites par jour" data={ov.days.map((d) => ({ date: d.day, value: d.visits }))} format={(v) => String(v)} />
      </div>

      <div className="mt-14 grid gap-14 lg:grid-cols-2">
        <section className="r-14 border border-[#ece2dd] bg-white p-16">
          <h2 className="fs-15 font-bold">Entonnoir</h2>
          <ol className="mt-12 space-y-10">
            {steps.map((s) => (
              <li key={s.label}>
                <div className="flex justify-between fs-13">
                  <span>{s.label}</span>
                  <span className="tabular-nums">
                    <b>{s.n}</b> <span className="text-[#8a8a8a]">· {pct(s.n, f.visits)}</span>
                  </span>
                </div>
                <div className="mt-4 h-8 r-4 bg-[#f4eeeb]">
                  <div className="h-8 r-4" style={{ width: f.visits ? `${(s.n / f.visits) * 100}%` : 0, background: WINE }} />
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="r-14 border border-[#ece2dd] bg-white p-16">
          <h2 className="fs-15 font-bold">Sources</h2>
          {ov.sources.length === 0 ? (
            <p className="mt-10 fs-13 text-[#8a8a8a]">Aucune visite sur la période.</p>
          ) : (
            <table className="mt-8 w-full fs-13">
              <thead>
                <tr className="text-left text-[#8a8a8a]">
                  <th className="py-4 font-medium">Source</th>
                  <th className="py-4 text-right font-medium">Visites</th>
                  <th className="py-4 text-right font-medium">Commandes</th>
                  <th className="py-4 text-right font-medium">Taux</th>
                </tr>
              </thead>
              <tbody>
                {ov.sources.map((s) => (
                  <tr key={s.source} className="border-t border-[#f4eeeb]">
                    <td className="py-6">{s.source}</td>
                    <td className="py-6 text-right tabular-nums">{s.visits}</td>
                    <td className="py-6 text-right tabular-nums">{s.orders}</td>
                    <td className="py-6 text-right tabular-nums">{pct(s.orders, s.visits)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <h3 className="mt-14 fs-13.5 font-bold">Appareils</h3>
          <p className="mt-4 flex flex-wrap gap-6 fs-13">
            {ov.devices.map((d) => (
              <Pill key={d.device} className="bg-[#f4eeeb] text-[#3a0a10]">
                {d.device === 'mobile' ? 'Mobile' : d.device === 'desktop' ? 'Ordinateur' : d.device} · {d.visits}
              </Pill>
            ))}
            {ov.in_app.map((d) => (
              <Pill key={d.app} className="bg-[#eef1f8] text-[#23365c]">
                Navigateur {d.app} · {d.visits}
              </Pill>
            ))}
          </p>
        </section>
      </div>

      <section className="mt-14 r-14 border border-[#ece2dd] bg-white">
        <div className="flex flex-wrap items-center justify-between gap-8 px-16 pt-14">
          <h2 className="fs-15 font-bold">Visites récentes</h2>
          <label className="flex items-center gap-6 fs-13">
            <input type="checkbox" checked={onlyOrders} onChange={(e) => setOnlyOrders(e.target.checked)} /> Avec commande seulement
          </label>
        </div>
        {!list ? (
          <Skeleton className="m-16" rows={4} />
        ) : list.items.length === 0 ? (
          <p className="px-16 py-14 fs-13 text-[#8a8a8a]">Aucune visite pour l'instant.</p>
        ) : (
          <ul className="mt-8 divide-y divide-[#f4eeeb]">
            {list.items.map((s) => (
              <li key={s.session_id}>
                <button
                  type="button"
                  onClick={() => setOpen(open === s.session_id ? null : s.session_id)}
                  aria-expanded={open === s.session_id}
                  className="flex w-full flex-wrap items-center gap-x-12 gap-y-4 px-16 py-10 text-left hover:bg-[#fbf8f6]"
                >
                  <span className="w-120 fs-13 tabular-nums text-[#5a5050]">{fmtDateTime(s.started_at)}</span>
                  <span className="min-w-0 flex-1 truncate fs-13.5 font-semibold">
                    {s.source}
                    {s.utm_campaign && <span className="font-normal text-[#8a8a8a]"> · {s.utm_campaign}</span>}
                  </span>
                  <span className="fs-12.5 text-[#6b6b6b]">
                    {s.device === 'mobile' ? 'Mobile' : s.device === 'desktop' ? 'Ordinateur' : s.device || '—'}
                    {where(s) && ` · ${where(s)}`} · {s.max_scroll} %
                  </span>
                  {s.form_started && !s.ordered && <Pill className="bg-[#fdf1dc] text-[#a0610f]">Formulaire</Pill>}
                  {s.ordered && <Pill className="bg-[#e7f6ec] text-[#1f6a3c]">{s.order_number || 'Commande'}</Pill>}
                </button>
                {open === s.session_id && <Timeline id={s.session_id} fail={fail} />}
              </li>
            ))}
          </ul>
        )}
        {list?.has_more && (
          <button type="button" onClick={more} className="w-full border-t border-[#f4eeeb] py-12 fs-13.5 font-semibold" style={{ color: WINE }}>
            Voir plus
          </button>
        )}
      </section>
    </div>
  )
}

function Timeline({ id, fail }: { id: string; fail: (e: unknown) => void }) {
  const [data, setData] = useState<{ session: VisitSession; events: VisitEvent[]; other_visits: VisitSession[] } | null>(
    () => adminApi.analyticsSession(id).peek() ?? null,
  )
  useEffect(() => {
    adminApi.analyticsSession(id).then(setData, fail)
  }, [id, fail])
  if (!data) return <Skeleton className="mx-16 mb-12" rows={3} />
  const s = data.session
  const t0 = data.events[0]?.at ?? s.started_at
  return (
    <div className="mx-16 mb-14 r-12 bg-[#fbf8f6] p-14">
      <p className="fs-12.5 text-[#6b6b6b]">
        {[s.landing && `Arrivée sur ${s.landing}`, s.referrer && `depuis ${s.referrer}`, s.utm_medium && `support ${s.utm_medium}`,
          s.utm_content && `annonce ${s.utm_content}`, s.in_app && `navigateur ${s.in_app}`, s.screen_w && `écran ${s.screen_w} px`]
          .filter(Boolean)
          .join(' · ')}
      </p>
      {s.order_number && (
        <p className="mt-6 fs-13">
          Commande{' '}
          <Link to={`/admin/orders/${encodeURIComponent(s.order_number)}`} className="font-semibold underline" style={{ color: WINE }}>
            {s.order_number}
          </Link>
        </p>
      )}
      {data.events.length === 0 ? (
        <p className="mt-8 fs-13 text-[#8a8a8a]">Détail des événements non disponible (plus de 90 jours, ou pas encore reçu).</p>
      ) : (
        <ol className="mt-10 space-y-4 border-l-2 border-[#ecdcd6] pl-12">
          {data.events.map((e, i) => (
            <li key={i} className="fs-13">
              <span className="inline-block w-56 tabular-nums text-[#8a8a8a]">+{Math.max(0, Math.round(e.at - t0))} s</span>
              <b className="font-semibold">{EVENT_LABEL[e.name] ?? e.name}</b>
              {detail(e) && <span className="text-[#5a5050]"> · {detail(e)}</span>}
              <span className="ml-6 fs-11.5 text-[#a0a0a0]">{hhmm(e.at)}</span>
            </li>
          ))}
        </ol>
      )}
      {data.other_visits.length > 0 && (
        <p className="mt-10 fs-12.5 text-[#6b6b6b]">
          Autres visites de ce visiteur : {data.other_visits.map((o) => `${fmtDateTime(o.started_at)} (${o.source}${o.ordered ? ', commande' : ''})`).join(' · ')}
        </p>
      )}
    </div>
  )
}
