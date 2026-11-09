import { CircleCheck, Star } from 'lucide-react'
import { REVIEWS } from '../content'

export function Reviews() {
  return (
    <section id="avis" aria-labelledby="avis-title" className="bg-ivory pb-24 lg:h-229 lg:pb-0">
      <div className="mx-auto w-full max-w-1024 px-16 md:px-24 lg:px-0">
        <div className="flex items-center justify-center gap-24 pt-8 lg:gap-0 lg:pt-16">
          <span className="hidden h-px flex-1 bg-gradient-to-r from-transparent to-[#c7b0a5] md:block md:max-w-182 lg:ml-206" aria-hidden />
          <h2 id="avis-title" data-anim="reveal" className="serif-tight fs-28 lh-40 text-ink-title lg:mx-35 lg:fs-30.5 lg:lh-40 lg:tracking-[-0.06em]">
            Ils en parlent !
          </h2>
          <span className="hidden h-px flex-1 bg-gradient-to-l from-transparent to-[#c7b0a5] md:block md:max-w-178 lg:mr-210" aria-hidden />
        </div>

        <ul className="mt-18 grid gap-14 md:grid-cols-3 md:gap-12 lg:mt-9 lg:gap-15 lg:px-47">
          {REVIEWS.map((r) => (
            <li
              key={r.name}
              data-anim="reveal"
              className="rounded-16 border border-[#efdfd5] bg-[#fdf4ec] pl-26 pr-8 pt-14 pb-14 shadow-[0_2px_8px_rgba(80,20,20,0.04)] lg:h-140"
            >
              <figure>
                <div className="flex gap-3 text-star" role="img" aria-label="5 étoiles sur 5">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Star key={i} className="size-16 fill-current" strokeWidth={0} aria-hidden />
                  ))}
                </div>
                <blockquote className="mt-6 font-serif fs-16.5 lh-20 tracking-[-0.045em] lg:fs-16.5 lg:tracking-[-0.04em] lg:whitespace-nowrap text-[#2a0a0c] [font-variation-settings:'opsz'_24]">
                  <p className="hidden lg:block">
                    “{r.lines[0]}
                    <br />
                    {r.lines[1]}”
                  </p>
                  <p className="lg:hidden">“{r.quote}”</p>
                </blockquote>
                <figcaption className="mt-12 flex flex-wrap items-center gap-x-11 lg:mt-12 lg:flex-nowrap">
                  <img src={r.avatar} alt="" loading="lazy" className="size-38 rounded-full object-cover" width={76} height={76} />
                  <span className="fs-14.5 font-semibold text-ink">{r.name}</span>
                  <span className="ml-auto flex items-center gap-6 fs-12.5 font-[500] text-[#2a0a0c] md:mt-4 md:ml-0 md:w-full md:pl-49 lg:mt-0 lg:ml-34 lg:w-auto lg:pl-0">
                    <CircleCheck className="size-17 fill-[#3a0a10] text-ivory" strokeWidth={2.2} aria-hidden />
                    Achat vérifié
                  </span>
                </figcaption>
              </figure>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
