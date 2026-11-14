import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Download, Search } from 'lucide-react'
import { adminApi, Unauthorized, type Customer, type Segment } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { Flags } from './Orders'
import { Banner, BusyButton, Chip, fmtDate, fmtMoney, formatPhone, inputClass, Pill, SEGMENT_LABEL, SEGMENT_PILL, useDebounced } from './ui'

/* Clients: one per phone number, with segments, tags, search; CSV for the owner. */

const SEGMENTS: Segment[] = ['new', 'loyal', 'at_risk', 'inactive']
const SORTS = [
  { key: 'last_order', label: 'Dernière commande' },
  { key: 'orders', label: 'Nombre de commandes' },
  { key: 'name', label: 'Nom' },
]

export default function Customers() {
  const { me, logout } = useAuth()
  const owner = me.role === 'owner'
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const [segment, setSegment] = useState<Segment | ''>('')
  const [tag, setTag] = useState('')
  const [sort, setSort] = useState('last_order')
  const [items, setItems] = useState<Customer[] | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [counts, setCounts] = useState<Partial<Record<Segment, number>>>({})
  const [loadingMore, setLoadingMore] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const sorts = owner ? [...SORTS, { key: 'value', label: 'Valeur livrée' }] : SORTS
  const filters = { q: dq.trim(), segment, tag, sort, dir: sort === 'name' ? 'asc' : 'desc' }
  const key = JSON.stringify(filters)

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof Unauthorized) logout()
      else setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })
    },
    [logout],
  )

  useEffect(() => {
    let live = true
    adminApi
      .customers(JSON.parse(key))
      .then((r) => {
        if (!live) return
        setItems(r.items)
        setHasMore(r.has_more)
        setCounts(r.counts)
      })
      .catch((e) => live && fail(e))
    return () => {
      live = false
    }
  }, [key, fail])

  const more = async () => {
    if (!items) return
    setLoadingMore(true)
    try {
      const r = await adminApi.customers(filters, items.length)
      setItems([...items, ...r.items])
      setHasMore(r.has_more)
    } catch (e) {
      fail(e)
    } finally {
      setLoadingMore(false)
    }
  }

  const total = Object.values(counts).reduce((a, b) => a + (b ?? 0), 0)

  return (
    <div className="mx-auto w-full max-w-1100 px-16 py-16 md:px-24 md:py-24">
      <div className="flex flex-wrap items-center justify-between gap-12">
        <h1 className="fs-22 font-bold">Clients</h1>
        {owner && (
          <a
            href={adminApi.customersCsvUrl({ q: filters.q, segment, tag })}
            className="inline-flex h-44 items-center gap-8 r-10 border border-[#d9cfca] bg-white px-14 fs-14 font-semibold hover:bg-[#faf6f3] md:h-40"
          >
            <Download className="size-16" aria-hidden /> Exporter (CSV)
          </a>
        )}
      </div>

      <div className="mt-12 grid gap-8 md:grid-cols-[1fr_200px_220px]">
        <label className="relative">
          <span className="sr-only">Rechercher</span>
          <Search className="pointer-events-none absolute left-12 top-1/2 size-16 -translate-y-1/2 text-[#8a8a8a]" aria-hidden />
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nom, téléphone, ville, étiquette…" className={`${inputClass} !mt-0 pl-36`} />
        </label>
        <label>
          <span className="sr-only">Étiquette</span>
          <input value={tag} onChange={(e) => setTag(e.target.value)} placeholder="Étiquette exacte" maxLength={30} className={`${inputClass} !mt-0`} />
        </label>
        <label>
          <span className="sr-only">Trier par</span>
          <select value={sort} onChange={(e) => setSort(e.target.value)} className={`${inputClass} !mt-0`}>
            {sorts.map((s) => (
              <option key={s.key} value={s.key}>
                Tri : {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-12 flex flex-wrap gap-8">
        <Chip active={!segment} onClick={() => setSegment('')}>
          Tous · {total}
        </Chip>
        {SEGMENTS.map((s) => (
          <Chip key={s} active={segment === s} onClick={() => setSegment(segment === s ? '' : s)}>
            {SEGMENT_LABEL[s]} · {counts[s] ?? 0}
          </Chip>
        ))}
      </div>
      <p className="mt-8 fs-12 text-[#8a8a8a]">
        Fidèle : 2 commandes livrées ou plus · À risque : un retour ou 2 annulations · Inactif : aucune commande depuis 60 jours.
      </p>

      <Banner msg={message} />

      {!items ? (
        <p className="mt-18 fs-14 text-[#8a8a8a]">Chargement…</p>
      ) : items.length === 0 ? (
        <p className="mt-18 fs-14 text-[#8a8a8a]">Aucun client ne correspond.</p>
      ) : (
        <ul className="mt-12 divide-y divide-[#f4eeeb] r-14 border border-[#ece2dd] bg-white">
          {items.map((c) => (
            <li key={c.phone}>
              <Link to={`/admin/customers/${c.phone}`} className="flex flex-wrap items-center gap-x-14 gap-y-4 px-14 py-12 hover:bg-[#fbf8f6]">
                <div className="min-w-0 flex-1 basis-200">
                  <p className="truncate fs-14 font-semibold">
                    {c.name || formatPhone(c.phone)}
                    <Flags o={{ returned: c.returned, opted_out: c.opted_out }} />
                  </p>
                  <p className="truncate fs-12.5 text-[#8a8a8a]">
                    {[formatPhone(c.phone), c.city].filter(Boolean).join(' · ')}
                    {c.tags.length > 0 && ` · ${c.tags.join(', ')}`}
                  </p>
                </div>
                <Pill className={SEGMENT_PILL[c.segment]}>{SEGMENT_LABEL[c.segment]}</Pill>
                <span className="w-110 fs-13 text-[#3a3a3a]">
                  {c.orders_count} cmd · {c.delivered} livrée{c.delivered > 1 ? 's' : ''}
                </span>
                {owner && c.delivered_cents !== undefined && <span className="w-120 text-right fs-13 font-semibold tabular-nums">{fmtMoney(c.delivered_cents)}</span>}
                <span className="w-90 text-right fs-12.5 text-[#8a8a8a]">{c.last_order ? fmtDate(c.last_order) : '—'}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {hasMore && (
        <div className="mt-12 text-center">
          <BusyButton type="button" variant="secondary" busy={loadingMore} onClick={more}>
            Voir plus
          </BusyButton>
        </div>
      )}
    </div>
  )
}
