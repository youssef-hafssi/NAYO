import { Clock, Leaf, Sparkle } from 'lucide-react'

/* "30 jours de soin. Une différence visible." — the owner's Semaine 1 / Semaine 4 photos (labels inside the images),
   then the three perks (same icons and words as the hero). */

const PHOTOS = [
  { src: 'semaine-1', alt: 'Aisselle en semaine 1 d’utilisation de NAYO' },
  { src: 'semaine-4', alt: 'Aisselle en semaine 4 d’utilisation de NAYO' },
]

const PERKS = [
  { Icon: Sparkle, l1: 'Unifie', l2: 'progressivement' },
  { Icon: Clock, l1: 'Fraîcheur', l2: 'toute la journée' },
  { Icon: Leaf, l1: 'Formule', l2: 'douce' },
]

export function Results() {
  return (
    <section id="resultats" aria-labelledby="results-title" className="scroll-mt-80 bg-ivory">
      <div className="mx-auto w-full max-w-1024 px-16 py-28 md:px-24 md:py-36">
        <h2 id="results-title" data-anim="reveal" className="serif-tight text-center fs-28 lh-34 text-ink-title md:fs-32 md:lh-38">
          30 jours de soin. Une différence visible.
        </h2>
        <p data-anim="reveal" className="mx-auto mt-10 max-w-560 text-center fs-16 lh-23 text-[#2e1a1c]">
          Un déodorant éclaircissant qui unifie le teint de vos aisselles, tout en vous offrant fraîcheur, confort et
          confiance, du matin au soir.
        </p>

        <figure className="mx-auto mt-20 max-w-760">
          <div className="grid gap-10 sm:grid-cols-2 md:gap-14">
            {PHOTOS.map((p) => (
              <div key={p.src} data-anim="reveal-photo" className="overflow-hidden rounded-16 bg-[#efe3dc]">
                <img
                  src={`/assets/${p.src}-600.webp`}
                  srcSet={`/assets/${p.src}-600.webp 600w, /assets/${p.src}-1199.webp 1199w`}
                  sizes="(min-width: 768px) 373px, (min-width: 640px) 50vw, 100vw"
                  alt={p.alt}
                  loading="lazy"
                  width={1199}
                  height={1312}
                  className="block h-auto w-full"
                />
              </div>
            ))}
          </div>
          <figcaption className="mt-6 text-center fs-11.5 lh-16 text-[#8a7a7c]">Visuels illustratifs</figcaption>
        </figure>

        <ul className="mx-auto mt-20 flex w-full max-w-480 items-start" aria-label="Points clés">
          {PERKS.map(({ Icon, l1, l2 }, i) => (
            <li
              key={l1}
              data-anim="reveal"
              className={`flex flex-1 flex-col items-center px-2 text-center text-ink-title ${i > 0 ? 'border-l border-[#d8c6bb]' : ''}`}
            >
              <span className="grid size-48 place-items-center rounded-full bg-[#f6e8e0] md:size-54">
                <Icon className="size-26 md:size-28" strokeWidth={1.3} aria-hidden />
              </span>
              <span className="mt-8 fs-12.5 lh-16 font-[600] sm:fs-14 sm:lh-18">
                {l1}
                <br />
                {l2}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
