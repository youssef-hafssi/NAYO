import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { adminApi, type Slip } from '../../lib/adminApi'
import { formatPhone } from './ui'

/*
 * Bons de livraison, printable from the browser (Ctrl+P). One slip per order, a page break between slips.
 * Opened in its own tab from the delivery board: /admin/delivery/print?n=NAYO-1001,NAYO-1002
 */

export default function DeliveryPrint() {
  const [params] = useSearchParams()
  const [slips, setSlips] = useState<Slip[] | null>(null)
  const [company, setCompany] = useState({ name: 'NAYO', address: '', phone: '' })
  const [error, setError] = useState('')

  useEffect(() => {
    const numbers = (params.get('n') ?? '').split(',').filter(Boolean)
    adminApi
      .slips(numbers)
      .then((r) => {
        setSlips(r.items)
        setCompany(r.company)
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Erreur'))
  }, [params])

  useEffect(() => {
    document.title = 'Bons de livraison — NAYO'
  }, [])

  if (error) return <p className="p-24 fs-14 text-[#a12a2a]">{error}</p>
  if (!slips) return <p className="p-24 fs-14 text-[#8a8a8a]">Chargement…</p>

  return (
    <div className="bg-white text-black">
      <style>{`
        @media print {
          @page { size: A5 portrait; margin: 12mm; }
          .no-print { display: none !important; }
          .slip { break-after: page; border: none !important; margin: 0 !important; }
          .slip:last-child { break-after: auto; }
        }
      `}</style>
      <div className="no-print flex items-center gap-12 border-b border-[#e8e8e8] px-16 py-12">
        <span className="fs-14">{slips.length} bon(s) de livraison</span>
        <button
          type="button"
          onClick={() => window.print()}
          className="ml-auto h-40 r-10 px-18 fs-14 font-semibold text-white"
          style={{ background: '#3a0a10' }}
        >
          Imprimer
        </button>
      </div>
      {slips.map((s) => (
        <section key={s.order_number} className="slip mx-auto my-16 max-w-560 border border-[#ddd] p-24 fs-15 lh-22">
          <header className="flex items-start justify-between gap-12 border-b border-black pb-10">
            <div>
              <div className="font-serif fs-22 font-semibold tracking-[0.2em]">{company.name}</div>
              {company.address && <div className="fs-12">{company.address}</div>}
              {company.phone && <div className="fs-12">{company.phone}</div>}
            </div>
            <div className="text-right">
              <div className="fs-12 uppercase tracking-[0.08em]">Bon de livraison</div>
              <div className="fs-18 font-bold">{s.order_number}</div>
            </div>
          </header>
          <dl className="mt-14 grid grid-cols-[130px_1fr] gap-y-6">
            <dt className="font-semibold">Client</dt>
            <dd>{s.name}</dd>
            <dt className="font-semibold">Téléphone</dt>
            <dd>{formatPhone(s.phone)}</dd>
            <dt className="font-semibold">Adresse</dt>
            <dd>{s.address || '—'}</dd>
            <dt className="font-semibold">Ville</dt>
            <dd>{s.city || '—'}</dd>
            <dt className="font-semibold">Produit</dt>
            <dd>NAYO® Déodorant × {s.quantity}</dd>
            {s.carrier && (
              <>
                <dt className="font-semibold">Livreur</dt>
                <dd>
                  {s.carrier}
                  {s.tracking ? ` — ${s.tracking}` : ''}
                </dd>
              </>
            )}
          </dl>
          <div className="mt-18 border-2 border-black p-12 text-center">
            <div className="fs-13 uppercase tracking-[0.08em]">Montant à encaisser (espèces)</div>
            <div className="mt-2 fs-28 font-bold">{s.total} MAD</div>
          </div>
          <p className="mt-14 fs-12">Signature du client : ______________________</p>
        </section>
      ))}
    </div>
  )
}
