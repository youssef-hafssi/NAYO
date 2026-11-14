import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertTriangle, Download, Search, SlidersHorizontal } from 'lucide-react'
import {
  adminApi,
  Unauthorized,
  type Carrier,
  type OrderFilters,
  type OrderRow,
  type SettableStatus,
  type Status,
} from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { Banner, BusyButton, Chip, FieldLabel, fmtDate, formatPhone, inputClass, STATUS_LABEL, StatusPill, useDebounced } from './ui'

/*
 * Commandes: every order with search, filters, per-status chips, sort, bulk status / carrier, CSV (owner).
 * Table on desktop, cards on phones. Each bulk change goes through the normal single-order path server-side.
 */

const STATUS_ORDER: Status[] = ['new', 'awaiting_details', 'needs_human', 'confirmed', 'shipped', 'delivered', 'returned', 'cancelled']
const BULK_STATUSES: SettableStatus[] = ['confirmed', 'shipped', 'delivered', 'returned', 'cancelled', 'needs_human']
const SORTS: { key: string; label: string }[] = [
  { key: 'created_at', label: 'Date' },
  { key: 'total', label: 'Montant' },
  { key: 'name', label: 'Nom' },
  { key: 'city', label: 'Ville' },
  { key: 'status', label: 'Statut' },
]

type Msg = { kind: 'ok' | 'error'; text: string } | null

export default function Orders() {
  const { me, logout } = useAuth()
  const owner = me.role === 'owner'
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const [statuses, setStatuses] = useState<Status[]>([])
  const [frm, setFrm] = useState('')
  const [to, setTo] = useState('')
  const [city, setCity] = useState('')
  const [carrierId, setCarrierId] = useState('')
  const [source, setSource] = useState('')
  const [sort, setSort] = useState('created_at')
  const [dir, setDir] = useState<'asc' | 'desc'>('desc')
  const [showFilters, setShowFilters] = useState(false)
  const [items, setItems] = useState<OrderRow[] | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [counts, setCounts] = useState<Partial<Record<Status, number>>>({})
  const [cities, setCities] = useState<string[]>([])
  const [carriers, setCarriers] = useState<Carrier[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkStatus, setBulkStatus] = useState('')
  const [bulkCarrier, setBulkCarrier] = useState('')
  const [bulkReason, setBulkReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [message, setMessage] = useState<Msg>(null)

  const datesOk = !frm || !to || frm <= to
  const filters: OrderFilters = { q: dq.trim(), status: statuses, frm, to, city, carrier_id: carrierId, source, sort, dir }
  const key = JSON.stringify(filters)

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof Unauthorized) logout()
      else setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })
    },
    [logout],
  )

  const load = useCallback(async () => {
    if (!datesOk) return
    try {
      const r = await adminApi.orders(JSON.parse(key) as OrderFilters)
      setItems(r.items)
      setHasMore(r.has_more)
      setCounts(r.counts)
      if (r.cities) setCities(r.cities)
    } catch (e) {
      fail(e)
    }
  }, [key, datesOk, fail])

  useEffect(() => {
    setSelected(new Set())
    load()
  }, [load])

  useEffect(() => {
    adminApi
      .carriers()
      .then((r) => setCarriers(r.items))
      .catch(() => undefined)
  }, [])

  const more = async () => {
    if (!items) return
    setLoadingMore(true)
    try {
      const r = await adminApi.orders(filters, items.length)
      setItems([...items, ...r.items])
      setHasMore(r.has_more)
    } catch (e) {
      fail(e)
    } finally {
      setLoadingMore(false)
    }
  }

  const toggle = (n: string) =>
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(n)) next.delete(n)
      else next.add(n)
      return next
    })
  const allSelected = !!items?.length && items.every((o) => selected.has(o.order_number))

  const applyBulk = async () => {
    if (!selected.size || (!bulkStatus && !bulkCarrier)) return
    if (bulkStatus === 'cancelled' && !window.confirm(`Annuler ${selected.size} commande(s) ?`)) return
    setBusy(true)
    setMessage(null)
    try {
      const r = await adminApi.ordersBulk({
        order_numbers: [...selected],
        ...(bulkStatus ? { status: bulkStatus as SettableStatus } : {}),
        ...(bulkCarrier ? { carrier_id: Number(bulkCarrier) } : {}),
        ...(bulkStatus === 'returned' && bulkReason.trim() ? { return_reason: bulkReason.trim() } : {}),
      })
      await load()
      const errs = Object.entries(r.errors)
      setMessage(
        errs.length
          ? { kind: 'error', text: `${r.done.length} modifiée(s). Refusées : ${errs.map(([n, e]) => `${n} (${e})`).join(', ')}` }
          : { kind: 'ok', text: `${r.done.length} commande(s) modifiée(s).` },
      )
      setSelected(new Set(errs.map(([n]) => n)))
      setBulkStatus('')
      setBulkCarrier('')
      setBulkReason('')
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const activeFilters = [frm, to, city, carrierId, source].filter(Boolean).length
  const resetFilters = () => {
    setFrm('')
    setTo('')
    setCity('')
    setCarrierId('')
    setSource('')
  }

  return (
    <div className="mx-auto w-full max-w-1100 px-16 py-16 md:px-24 md:py-24">
      <div className="flex flex-wrap items-center justify-between gap-12">
        <h1 className="fs-22 font-bold">Commandes</h1>
        {owner && (
          <a
            href={adminApi.ordersCsvUrl(filters)}
            className="inline-flex h-44 items-center gap-8 r-10 border border-[#d9cfca] bg-white px-14 fs-14 font-semibold hover:bg-[#faf6f3] md:h-40"
          >
            <Download className="size-16" aria-hidden /> Exporter (CSV)
          </a>
        )}
      </div>

      <div className="mt-12 flex gap-8">
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">Rechercher</span>
          <Search className="pointer-events-none absolute left-12 top-1/2 size-16 -translate-y-1/2 text-[#8a8a8a]" aria-hidden />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="N°, nom, téléphone, ville…"
            className={`${inputClass} !mt-0 pl-36`}
          />
        </label>
        <button
          type="button"
          onClick={() => setShowFilters((v) => !v)}
          aria-expanded={showFilters}
          className="inline-flex h-44 shrink-0 items-center gap-6 r-10 border border-[#d9cfca] bg-white px-12 fs-14 font-semibold md:h-40"
        >
          <SlidersHorizontal className="size-16" aria-hidden /> Filtres{activeFilters ? ` (${activeFilters})` : ''}
        </button>
      </div>

      {showFilters && (
        <section aria-label="Filtres" className="mt-10 grid gap-10 r-14 border border-[#ece2dd] bg-white p-14 sm:grid-cols-2 lg:grid-cols-6">
          <div>
            <FieldLabel htmlFor="o-from">Du</FieldLabel>
            <input id="o-from" type="date" className={inputClass} value={frm} onChange={(e) => setFrm(e.target.value)} />
          </div>
          <div>
            <FieldLabel htmlFor="o-to">Au</FieldLabel>
            <input id="o-to" type="date" className={inputClass} value={to} onChange={(e) => setTo(e.target.value)} />
          </div>
          <div>
            <FieldLabel htmlFor="o-city">Ville</FieldLabel>
            <select id="o-city" className={inputClass} value={city} onChange={(e) => setCity(e.target.value)}>
              <option value="">Toutes</option>
              {cities.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div>
            <FieldLabel htmlFor="o-carrier">Livreur</FieldLabel>
            <select id="o-carrier" className={inputClass} value={carrierId} onChange={(e) => setCarrierId(e.target.value)}>
              <option value="">Tous</option>
              <option value="0">Sans livreur</option>
              {carriers.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <FieldLabel htmlFor="o-source">Source</FieldLabel>
            <select id="o-source" className={inputClass} value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">Toutes</option>
              <option value="website">Site</option>
              <option value="whatsapp">WhatsApp</option>
            </select>
          </div>
          <div>
            <FieldLabel htmlFor="o-sort">Trier par</FieldLabel>
            <div className="flex gap-6">
              <select id="o-sort" className={inputClass} value={sort} onChange={(e) => setSort(e.target.value)}>
                {SORTS.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => setDir((d) => (d === 'desc' ? 'asc' : 'desc'))}
                aria-label={dir === 'desc' ? 'Ordre décroissant' : 'Ordre croissant'}
                className="mt-6 h-44 w-44 shrink-0 r-10 border border-[#ecdcd6] bg-[#fbf5f2] fs-16 md:h-40"
              >
                {dir === 'desc' ? '↓' : '↑'}
              </button>
            </div>
          </div>
          {!datesOk && <p className="fs-13 text-[#a12a2a] sm:col-span-2 lg:col-span-6">La date de début doit précéder la date de fin.</p>}
          {activeFilters > 0 && (
            <button type="button" onClick={resetFilters} className="h-40 justify-self-start fs-13 font-semibold text-[#7a1a2a] underline">
              Effacer les filtres
            </button>
          )}
        </section>
      )}

      <div className="mt-12 flex flex-wrap gap-8" aria-label="Statuts">
        <Chip active={statuses.length === 0} onClick={() => setStatuses([])}>
          Toutes · {Object.values(counts).reduce((a, b) => a + (b ?? 0), 0)}
        </Chip>
        {STATUS_ORDER.filter((s) => counts[s]).map((s) => (
          <Chip
            key={s}
            active={statuses.includes(s)}
            onClick={() => setStatuses((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]))}
          >
            {STATUS_LABEL[s]} · {counts[s]}
          </Chip>
        ))}
      </div>

      <Banner msg={message} />

      {selected.size > 0 && (
        <section
          aria-label="Action groupée"
          className="sticky top-0 z-10 mt-12 flex flex-wrap items-end gap-10 r-14 border border-[#e2d6d0] bg-[#fbf5f2] p-12 shadow-sm"
        >
          <p className="w-full fs-14 font-semibold md:w-auto md:self-center">{selected.size} sélectionnée(s)</p>
          <div className="min-w-160 flex-1 md:flex-none">
            <FieldLabel htmlFor="b-status">Statut</FieldLabel>
            <select id="b-status" className={inputClass} value={bulkStatus} onChange={(e) => setBulkStatus(e.target.value)}>
              <option value="">— inchangé —</option>
              {BULK_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]}
                </option>
              ))}
            </select>
          </div>
          <div className="min-w-160 flex-1 md:flex-none">
            <FieldLabel htmlFor="b-carrier">Livreur</FieldLabel>
            <select id="b-carrier" className={inputClass} value={bulkCarrier} onChange={(e) => setBulkCarrier(e.target.value)}>
              <option value="">— inchangé —</option>
              <option value="0">Retirer le livreur</option>
              {carriers.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          {bulkStatus === 'returned' && (
            <div className="min-w-200 flex-1">
              <FieldLabel htmlFor="b-reason">Raison du retour</FieldLabel>
              <input id="b-reason" maxLength={300} className={inputClass} value={bulkReason} onChange={(e) => setBulkReason(e.target.value)} />
            </div>
          )}
          <BusyButton type="button" busy={busy} disabled={!bulkStatus && !bulkCarrier} onClick={applyBulk}>
            Appliquer
          </BusyButton>
          <BusyButton type="button" variant="secondary" onClick={() => setSelected(new Set())}>
            Désélectionner
          </BusyButton>
        </section>
      )}

      {!items ? (
        <p className="mt-18 fs-14 text-[#8a8a8a]">Chargement…</p>
      ) : items.length === 0 ? (
        <p className="mt-18 fs-14 text-[#8a8a8a]">Aucune commande ne correspond.</p>
      ) : (
        <>
          {/* Desktop / tablet: table */}
          <div className="mt-12 hidden overflow-x-auto r-14 border border-[#ece2dd] bg-white md:block">
            <table className="w-full fs-13.5">
              <thead>
                <tr className="border-b border-[#f1e8e4] text-left fs-11 uppercase tracking-[0.06em] text-[#8a8a8a]">
                  <th className="w-40 px-12 py-10">
                    <input
                      type="checkbox"
                      aria-label="Tout sélectionner"
                      className="size-18 accent-[#3a0a10]"
                      checked={allSelected}
                      onChange={() => setSelected(allSelected ? new Set() : new Set(items.map((o) => o.order_number)))}
                    />
                  </th>
                  <th className="px-8 py-10">Commande</th>
                  <th className="px-8 py-10">Client</th>
                  <th className="px-8 py-10">Ville</th>
                  <th className="px-8 py-10 text-right">Qté</th>
                  <th className="px-8 py-10 text-right">Total</th>
                  <th className="px-8 py-10">Statut</th>
                  <th className="px-8 py-10">Livreur</th>
                  <th className="px-8 py-10">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f4eeeb]">
                {items.map((o) => (
                  <tr
                    key={o.order_number}
                    onClick={() => navigate(`/admin/orders/${encodeURIComponent(o.order_number)}`)}
                    className={`cursor-pointer hover:bg-[#fbf8f6] ${selected.has(o.order_number) ? 'bg-[#fbf5f2]' : ''}`}
                  >
                    <td className="px-12 py-8" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Sélectionner ${o.order_number}`}
                        className="size-18 accent-[#3a0a10]"
                        checked={selected.has(o.order_number)}
                        onChange={() => toggle(o.order_number)}
                      />
                    </td>
                    <td className="px-8 py-8 font-semibold">
                      <Link to={`/admin/orders/${encodeURIComponent(o.order_number)}`} onClick={(e) => e.stopPropagation()}>
                        {o.order_number}
                      </Link>
                    </td>
                    <td className="px-8 py-8">
                      <span className="font-medium">{o.name}</span>
                      <Flags o={o} />
                      <span className="block fs-12 text-[#8a8a8a]">{formatPhone(o.phone)}</span>
                    </td>
                    <td className="px-8 py-8">{o.city || '—'}</td>
                    <td className="px-8 py-8 text-right tabular-nums">{o.quantity}</td>
                    <td className="px-8 py-8 text-right tabular-nums">{o.total} MAD</td>
                    <td className="px-8 py-8">
                      <StatusPill status={o.status} />
                    </td>
                    <td className="px-8 py-8">{o.carrier || '—'}</td>
                    <td className="whitespace-nowrap px-8 py-8 text-[#6b6b6b]">{fmtDate(o.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Phones: cards */}
          <ul className="mt-12 grid gap-8 md:hidden">
            {items.map((o) => (
              <li key={o.order_number} className={`flex gap-10 r-14 border border-[#ece2dd] p-12 ${selected.has(o.order_number) ? 'bg-[#fbf5f2]' : 'bg-white'}`}>
                <label className="grid size-40 shrink-0 place-items-center">
                  <input
                    type="checkbox"
                    aria-label={`Sélectionner ${o.order_number}`}
                    className="size-20 accent-[#3a0a10]"
                    checked={selected.has(o.order_number)}
                    onChange={() => toggle(o.order_number)}
                  />
                </label>
                <Link to={`/admin/orders/${encodeURIComponent(o.order_number)}`} className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-8">
                    <span className="fs-14 font-bold">{o.order_number}</span>
                    <StatusPill status={o.status} />
                  </div>
                  <p className="mt-2 truncate fs-14">
                    {o.name}
                    <Flags o={o} />
                  </p>
                  <p className="mt-2 fs-12.5 text-[#6b6b6b]">
                    {[o.city, `${o.quantity} × · ${o.total} MAD`, o.carrier, fmtDate(o.created_at)].filter(Boolean).join(' · ')}
                  </p>
                </Link>
              </li>
            ))}
          </ul>

          {hasMore && (
            <div className="mt-12 text-center">
              <BusyButton type="button" variant="secondary" busy={loadingMore} onClick={more}>
                Voir plus
              </BusyButton>
            </div>
          )}
        </>
      )}
    </div>
  )
}

/** Warning badges next to a customer's name: returned an order before, asked us to stop writing. */
export function Flags({ o }: { o: { returns_count?: number; returned?: number; opted_out?: boolean } }) {
  const returns = o.returns_count ?? o.returned ?? 0
  return (
    <>
      {returns > 0 && (
        <span
          title="Ce client a déjà retourné une commande"
          className="ml-6 inline-flex items-center gap-2 r-5 bg-[#fbe5e5] px-6 py-1 align-middle fs-11 font-semibold text-[#a12a2a]"
        >
          <AlertTriangle className="size-12" aria-hidden /> {returns} retour{returns > 1 ? 's' : ''}
        </span>
      )}
      {o.opted_out && (
        <span title="Le client a écrit STOP" className="ml-6 inline-block r-5 bg-[#efefef] px-6 py-1 align-middle fs-11 font-semibold text-[#6b6b6b]">
          STOP
        </span>
      )}
    </>
  )
}
