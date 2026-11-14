import { Banknote, Truck } from 'lucide-react'
import { WhatsAppGlyph } from './WhatsAppGlyph'

/* Right below the hero: the three reasons to order now. One row on every size; compact on phones. */

const ITEMS = [
  { icon: <Truck className="size-22 md:size-26" strokeWidth={1.5} aria-hidden />, l1: 'Livraison', l2: 'rapide' },
  { icon: <Banknote className="size-22 md:size-26" strokeWidth={1.5} aria-hidden />, l1: 'Paiement', l2: 'à la livraison' },
  { icon: <WhatsAppGlyph className="size-20 md:size-24" />, l1: 'Confirmation', l2: 'sur WhatsApp' },
]

export function TrustStrip() {
  return (
    <section aria-label="Garanties" className="border-b border-line bg-ivory">
      <ul className="mx-auto grid w-full max-w-1024 grid-cols-3 px-8 py-14 md:px-24 md:py-18">
        {ITEMS.map((it, i) => (
          <li
            key={it.l1}
            data-anim="reveal"
            className={`flex flex-col items-center gap-6 px-4 text-center text-ink md:flex-row md:justify-center md:gap-12 md:text-left ${
              i > 0 ? 'border-l border-[#d8c6bb]' : ''
            }`}
          >
            <span className="grid size-38 shrink-0 place-items-center rounded-full bg-[#f6e8e0] text-ink-title md:size-46">{it.icon}</span>
            <span className="fs-12.5 lh-16 font-[650] md:fs-14.5 md:lh-19">
              {it.l1}
              <br />
              {it.l2}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
