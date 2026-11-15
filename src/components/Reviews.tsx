import { CircleCheck, Clock, Feather, Sparkle } from 'lucide-react'
import { BRAND_POINTS, REVIEWS, SHOW_REVIEWS } from '../content'

/*
 * "Avis". Cards show ONLY real reviews from content.ts (copied from admin → Clients → "Avis"). While there are none,
 * the same cards carry the brand's three statements — no quote marks, no names, no stars — so nothing can be
 * mistaken for a customer review. The photo is the owner's selfie with the face strongly blurred.
 */

const ICONS = [Sparkle, Feather, Clock]

export function Reviews() {
  if (!SHOW_REVIEWS) return null
  const real = REVIEWS.length > 0

  return (
    <section id="avis" aria-labelledby="avis-title" className="scroll-mt-80 bg-ivory pb-28 md:pb-36">
      <div className="mx-auto w-full max-w-1024 px-16 md:px-24 lg:px-0">
        <div className="flex items-center justify-center gap-24 pt-8 lg:gap-0 lg:pt-16">
          <span className="hidden h-px flex-1 bg-gradient-to-r from-transparent to-[#c7b0a5] md:block md:max-w-182 lg:ml-206" aria-hidden />
          <h2 id="avis-title" data-anim="reveal" className="serif-tight fs-28 lh-40 text-ink-title lg:mx-35 lg:fs-30.5 lg:lh-40 lg:tracking-[-0.06em]">
            Avis
          </h2>
          <span className="hidden h-px flex-1 bg-gradient-to-l from-transparent to-[#c7b0a5] md:block md:max-w-178 lg:mr-210" aria-hidden />
        </div>
        {!real && (
          <p className="mt-4 text-center fs-14 lh-20 text-[#5a4446]">Les premiers avis arrivent. En attendant, voici ce que NAYO vous apporte.</p>
        )}

        <div className="mt-18 grid items-center gap-16 md:grid-cols-[1fr_300px] md:gap-28 lg:px-47">
          <ul className={`grid gap-12 ${real && REVIEWS.length > 3 ? 'sm:grid-cols-2' : ''}`}>
            {real
              ? REVIEWS.map((r, i) => (
                  <li
                    key={i}
                    data-anim="reveal"
                    className="rounded-16 border border-[#efdfd5] bg-[#fdf4ec] px-22 py-16 shadow-[0_2px_8px_rgba(80,20,20,0.04)]"
                  >
                    <figure>
                      <blockquote
                        lang={r.lang === 'darija' ? 'ary' : r.lang}
                        dir={r.lang === 'ar' ? 'rtl' : 'ltr'}
                        className="font-serif fs-16.5 lh-23 tracking-[-0.02em] text-[#2a0a0c] [font-variation-settings:'opsz'_24]"
                      >
                        <p>« {r.text} »</p>
                      </blockquote>
                      <figcaption className="mt-10 flex flex-wrap items-center gap-x-10 gap-y-4 fs-14 font-semibold text-ink">
                        {[r.author, r.city].filter(Boolean).join(', ')}
                        <span className="flex items-center gap-6 fs-12.5 font-[500] text-[#2a0a0c]">
                          <CircleCheck className="size-17 fill-[#3a0a10] text-ivory" strokeWidth={2.2} aria-hidden />
                          Achat vérifié
                        </span>
                      </figcaption>
                    </figure>
                  </li>
                ))
              : BRAND_POINTS.map((p, i) => {
                  const Icon = ICONS[i] ?? Sparkle
                  return (
                    <li
                      key={p.title}
                      data-anim="reveal"
                      className="flex gap-14 rounded-16 border border-[#efdfd5] bg-[#fdf4ec] px-18 py-14 shadow-[0_2px_8px_rgba(80,20,20,0.04)]"
                    >
                      <span className="grid size-44 shrink-0 place-items-center rounded-12 bg-[#f6e8e0]">
                        <Icon className="size-24 text-[#3a0a10]" strokeWidth={1.6} aria-hidden />
                      </span>
                      <span>
                        <span className="serif-tight block fs-17.5 lh-22 font-[720] tracking-[-0.03em] text-ink-title">{p.title}</span>
                        <span className="mt-4 block fs-14 lh-20 text-[#3a2224]">{p.text}</span>
                      </span>
                    </li>
                  )
                })}
          </ul>
          <figure data-anim="reveal-photo" className="mx-auto w-full max-w-300 overflow-hidden rounded-16 bg-[#efe3dc]">
            <img
              src="/assets/nayo-selfie-600.webp"
              srcSet="/assets/nayo-selfie-600.webp 600w, /assets/nayo-selfie-1000.webp 1000w"
              sizes="300px"
              alt="Une utilisatrice tient le déodorant NAYO (visage flouté)"
              loading="lazy"
              width={1000}
              height={1331}
              className="block h-auto w-full"
            />
          </figure>
        </div>
      </div>
    </section>
  )
}
