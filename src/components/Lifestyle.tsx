import { ArrowRight, ShoppingCart } from 'lucide-react'
import { goToOrderForm } from '../lib/scroll'

/* "Elles ont choisi NAYO… à votre tour !" — the owner's lifestyle collage, then the last call to action:
   a large button that scrolls to the express form on this page. */

export function Lifestyle() {
  return (
    <section aria-labelledby="lifestyle-title" className="bg-ivory">
      <div className="mx-auto w-full max-w-1024 px-16 py-28 md:px-24 md:py-36">
        <h2 id="lifestyle-title" data-anim="reveal" className="serif-tight text-center fs-28 lh-34 text-ink-title md:fs-32 md:lh-38">
          Elles ont choisi NAYO… à votre tour&nbsp;!
        </h2>
        <figure className="mt-18">
          <div data-anim="reveal-photo" className="overflow-hidden rounded-16 bg-[#efe3dc]">
            <img
              src="/assets/nayo-lifestyle-800.webp"
              srcSet="/assets/nayo-lifestyle-800.webp 800w, /assets/nayo-lifestyle-1600.webp 1600w"
              sizes="(min-width: 1024px) 976px, 100vw"
              alt="Sept photos de NAYO au quotidien : dans un lit, dans un sac à main, sur une étagère, dans une salle de bain, en voiture, sur une table de nuit et devant un miroir."
              loading="lazy"
              width={1672}
              height={941}
              className="block h-auto w-full"
            />
          </div>
          <figcaption className="mt-6 text-center fs-11.5 lh-16 text-[#8a7a7c]">Visuels illustratifs</figcaption>
        </figure>
        <a
          href="#commander"
          onClick={goToOrderForm}
          className="group mx-auto mt-24 flex h-60 w-full max-w-440 items-center justify-center gap-12 rounded-pill bg-gradient-to-b from-[#6c0a1c] to-[#520110] fs-18 font-semibold text-white shadow-[0_10px_24px_rgba(92,2,17,0.28)] transition-[scale] duration-300 hover:scale-[1.02] md:h-64 md:fs-19"
        >
          <ShoppingCart className="size-22" strokeWidth={1.6} aria-hidden />
          Acheter maintenant
          <ArrowRight className="size-20 transition-transform group-hover:translate-x-3" strokeWidth={2} aria-hidden />
        </a>
      </div>
    </section>
  )
}
