import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ORDER_PATH } from '../content'

/* Description + the owner's before/after photos (Semaine 1 / Semaine 4, labels inside the images; illustrative). */

const PHOTOS = [
  { src: 'semaine-1', alt: 'Aisselle en semaine 1 d’utilisation de NAYO' },
  { src: 'semaine-4', alt: 'Aisselle en semaine 4 d’utilisation de NAYO' },
]

export function Editorial() {
  return (
    <section aria-labelledby="editorial-title" className="bg-ivory">
      <div className="mx-auto flex w-full max-w-1024 flex-col gap-28 px-16 pt-4 pb-28 md:flex-row md:items-center md:gap-36 md:px-24 md:pb-36 lg:gap-0 lg:px-0 lg:pl-16">
        {/* Semaine 1 / Semaine 4: side by side on desktop, stacked on phones */}
        <figure className="w-full shrink-0 md:w-[54%] lg:w-537">
          <div className="grid gap-10 sm:grid-cols-2 md:gap-12">
            {PHOTOS.map((p) => (
              <div key={p.src} data-anim="reveal-photo" className="overflow-hidden rounded-16 bg-[#efe3dc]">
                <img
                  src={`/assets/${p.src}-600.webp`}
                  srcSet={`/assets/${p.src}-600.webp 600w, /assets/${p.src}-1199.webp 1199w`}
                  sizes="(min-width: 1024px) 262px, (min-width: 640px) 50vw, 100vw"
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

        {/* Copy */}
        <div className="px-8 md:px-0 lg:ml-49">
          <h2 id="editorial-title" data-anim="reveal" className="serif-tight fs-30 lh-32 text-ink-title md:fs-30 md:lh-32 lg:fs-34.5 lg:lh-35 lg:font-[620] lg:tracking-[-0.056em]">
            Le déodorant
            <br />
            éclaircissant du quotidien.
          </h2>
          <p data-anim="reveal" className="mt-16 max-w-400 fs-16 lh-23 text-[#2e1a1c] lg:mt-14 lg:max-w-none lg:whitespace-nowrap lg:fs-17 lg:lh-22 lg:font-[500]">
            NAYO aide à éclaircir et à unifier le teint <br className="hidden lg:block" />
            de vos aisselles grâce à son Super Fruit <br className="hidden lg:block" />
            Enzyme Triple Blend et à l'acide citrique, <br className="hidden lg:block" />
            qui exfolient la peau en douceur.
          </p>
          <Link
            to={ORDER_PATH}
            data-anim="reveal"
            className="group mt-22 inline-flex h-50 items-center gap-12 rounded-pill bg-gradient-to-b from-[#6c0a1c] to-[#520110] px-30 fs-17 font-semibold text-white shadow-[0_8px_20px_rgba(92,2,17,0.28)] transition-[scale] duration-300 hover:scale-[1.02] lg:mt-21 lg:h-48 lg:w-252 lg:justify-center lg:px-0"
          >
            Acheter maintenant
            <ArrowRight className="size-18 transition-transform group-hover:translate-x-3" strokeWidth={2} aria-hidden />
          </Link>
        </div>
      </div>
    </section>
  )
}
