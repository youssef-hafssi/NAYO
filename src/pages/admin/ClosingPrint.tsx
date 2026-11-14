import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { adminApi, type ClosingReport } from '../../lib/adminApi'
import { ClosingBody } from './Reports'
import { fmtDate } from './ui'

/* Clôture mensuelle on one printable A4 page: /admin/reports/closing/print?month=2026-11 (owner only, server-side). */

const MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']

export default function ClosingPrint() {
  const [params] = useSearchParams()
  const month = params.get('month') ?? ''
  const [r, setR] = useState<ClosingReport | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    adminApi
      .closing(month)
      .then(setR)
      .catch((e) => setError(e instanceof Error ? e.message : 'Erreur'))
  }, [month])

  const label = /^\d{4}-\d{2}$/.test(month) ? `${MONTHS[Number(month.slice(5)) - 1]} ${month.slice(0, 4)}` : month
  useEffect(() => {
    document.title = `Clôture ${label} — NAYO`
  }, [label])

  if (error) return <p className="p-24 fs-14 text-[#a12a2a]">{error}</p>
  if (!r) return <p className="p-24 fs-14 text-[#8a8a8a]">Chargement…</p>

  return (
    <div className="min-h-screen bg-white text-black">
      <style>{`
        @media print {
          @page { size: A4 portrait; margin: 14mm; }
          .no-print { display: none !important; }
        }
      `}</style>
      <div className="mx-auto max-w-760 p-24 print:max-w-none print:p-0">
        <div className="no-print mb-16 flex justify-end">
          <button type="button" onClick={() => window.print()} className="h-40 r-10 bg-[#3a0a10] px-16 fs-14 font-semibold text-white">
            Imprimer
          </button>
        </div>
        <header className="flex items-end justify-between border-b-2 border-black pb-8">
          <div>
            <p className="font-serif fs-20 font-semibold tracking-[0.18em]">NAYO</p>
            <h1 className="mt-2 fs-18 font-bold">Clôture mensuelle — {label}</h1>
          </div>
          <p className="text-right fs-12">
            Du {fmtDate(r.from)} au {fmtDate(r.to)}
            {!r.complete && (
              <>
                <br />
                <b>Mois en cours : chiffres provisoires</b>
              </>
            )}
          </p>
        </header>
        <div className="mt-16">
          <ClosingBody r={r} />
        </div>
        <p className="mt-24 fs-11 text-[#6b6b6b]">
          Édité le {r.generated_at.slice(0, 10).split('-').reverse().join('/')} à {r.generated_at.slice(11, 16)}. Chiffre d'affaires = commandes
          livrées ; coût des produits = coût moyen pondéré du stock ; montants en MAD.
        </p>
      </div>
    </div>
  )
}
