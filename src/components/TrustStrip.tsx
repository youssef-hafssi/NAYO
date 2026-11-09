import { Package, RefreshCw, ShieldCheck, Truck } from 'lucide-react'

const ITEMS = [
  { Icon: Truck, l1: 'Livraison rapide', l2: 'partout au Maroc' },
  { Icon: Package, l1: 'Paiement', l2: 'à la livraison' },
  { Icon: RefreshCw, l1: 'Retour facile', l2: 'sous 7 jours' },
  { Icon: ShieldCheck, l1: 'Achat 100%', l2: 'sécurisé' },
]

export function TrustStrip() {
  return (
    <section aria-label="Garanties" className="bg-ivory">
      <ul className="mx-auto grid w-full max-w-1024 grid-cols-2 gap-y-20 px-20 py-28 md:grid-cols-4 md:px-24 lg:h-85 lg:grid-cols-[calc(var(--spacing)*220)_calc(var(--spacing)*237)_calc(var(--spacing)*236)_1fr] lg:px-0 lg:py-0 lg:pt-24 lg:pl-80">
        {ITEMS.map(({ Icon, l1, l2 }, i) => (
          <li
            key={l1}
            data-anim="reveal"
            className={`flex items-center gap-14 md:justify-center lg:gap-15 lg:justify-start ${['','lg:pl-57','lg:pl-45','lg:pl-46'][i]} ${
              i > 0 ? 'md:border-l md:border-[#cdbab0]' : ''
            } lg:h-38`}
          >
            <Icon className="size-34 shrink-0 text-[#2a0a0c] lg:size-42" strokeWidth={1.45} aria-hidden />
            <span className="fs-13.5 lh-19 font-[650] lg:fs-14 text-[#2a0a0c]">
              {l1}
              <br />
              {l2}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
