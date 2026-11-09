import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ORDER_PATH } from '../content'

export function Editorial() {
  return (
    <section aria-labelledby="editorial-title" className="bg-ivory">
      <div className="mx-auto flex w-full max-w-1024 flex-col gap-28 px-16 pt-4 md:flex-row md:items-center md:gap-36 md:px-24 lg:h-276 lg:gap-0 lg:px-0 lg:pt-0 lg:pl-16">
        {/* Photo card */}
        <figure
          data-anim="reveal-photo"
          className="relative aspect-[537/276] w-full shrink-0 overflow-hidden rounded-16 md:w-[54%] lg:w-537"
        >
          <img
            src="/assets/editorial.jpg"
            alt="Aisselle nette et unifiée après utilisation de NAYO"
            loading="lazy"
            width={538}
            height={277}
            className="size-full object-cover"
          />
          {/* Before inset */}
          <div className="absolute top-[51.5%] left-[5.4%] aspect-[100/117] w-[18.6%] overflow-hidden rounded-12 border-[1.5px] border-[#f4e3d8] shadow-[0_6px_18px_rgba(0,0,0,0.25)]">
            <img src="/assets/avant.jpg" alt="Aisselle avant utilisation" loading="lazy" className="size-full object-cover" />
            <span className="absolute bottom-[4%] left-1/2 -translate-x-1/2 rounded-pill bg-white px-9 fs-13 lh-21 font-semibold text-ink">
              Avant
            </span>
          </div>
          {/* Arrow + Après */}
          <svg
            className="absolute top-[60.5%] left-[25.8%] w-[11.4%]"
            viewBox="0 0 62 40"
            fill="none"
            aria-hidden
          >
            <path d="M2 37c22 0 41-10 54-31" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <path d="M46.5 6.5L56.8 4.4 58.4 14.6" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <figcaption className="absolute top-[83.3%] left-[27.4%] fs-19 font-medium text-white md:fs-14 lg:fs-19">
            Après
          </figcaption>
        </figure>

        {/* Copy */}
        <div className="px-8 pb-8 md:px-0 lg:ml-49 lg:pt-12">
          <h2 id="editorial-title" data-anim="reveal" className="serif-tight fs-30 lh-32 text-ink-title md:fs-30 md:lh-32 lg:fs-34.5 lg:lh-35 lg:font-[620] lg:tracking-[-0.056em]">
            Le déodorant
            <br />
            éclaircissant du quotidien.
          </h2>
          <p data-anim="reveal" className="mt-16 max-w-400 fs-16 lh-23 text-[#2e1a1c] lg:mt-14 lg:max-w-none lg:whitespace-nowrap lg:fs-17 lg:lh-22 lg:font-[500]">
            Efficace, confortable et élégant, NAYO unifie <br className="hidden lg:block" />
            le teint de vos aisselles, tout en vous offrant <br className="hidden lg:block" />
            fraîcheur et protection toute la journée.
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
