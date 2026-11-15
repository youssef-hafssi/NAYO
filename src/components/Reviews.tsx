import { CircleCheck, Clock, Feather, Sparkle, Star } from 'lucide-react'
import { BRAND_POINTS, REVIEWS, SHOW_REVIEWS, type Review } from '../content'

/*
 * "Avis".
 * - REVIEWS empty → the brand's three statements (no quote marks, names or stars) + the face-blurred selfie.
 * - REVIEWS filled → the first 3 real reviews as cards: the stars SHE gave, her words, first name or initial,
 *   city, "Achat vérifié", and her photo (face already blurred) as a small thumbnail when there is one.
 *   Once any shown review has a photo, the big standalone selfie is no longer shown.
 */

const ICONS = [Sparkle, Feather, Clock]
const SHOWN = 3

export function Reviews({ reviews = REVIEWS }: { reviews?: readonly Review[] }) {
  if (!SHOW_REVIEWS) return null
  const shown = reviews.slice(0, SHOWN)
  const real = shown.length > 0
  const withPhotos = shown.some((r) => r.photo)

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

        {withPhotos ? (
          // Reviews carry their own photos: three cards across, no standalone selfie.
          <ul className="mt-18 grid gap-14 md:grid-cols-3 md:gap-12 lg:gap-15 lg:px-47">
            {shown.map((r, i) => (
              <ReviewCard key={i} r={r} />
            ))}
          </ul>
        ) : (
          <div className="mt-18 grid items-center gap-16 md:grid-cols-[1fr_300px] md:gap-28 lg:px-47">
            <ul className="grid gap-12">
              {real
                ? shown.map((r, i) => <ReviewCard key={i} r={r} />)
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
        )}
      </div>
    </section>
  )
}

function ReviewCard({ r }: { r: Review }) {
  const rating = Math.max(1, Math.min(5, Math.round(r.rating)))
  return (
    <li
      data-anim="reveal"
      className="rounded-16 border border-[#efdfd5] bg-[#fdf4ec] px-20 pt-14 pb-14 shadow-[0_2px_8px_rgba(80,20,20,0.04)]"
    >
      <figure className="flex h-full flex-col">
        <div className="flex items-start gap-12">
          <div className="min-w-0 flex-1">
            <div className="flex gap-3" role="img" aria-label={`${rating} étoile${rating > 1 ? 's' : ''} sur 5`}>
              {Array.from({ length: 5 }).map((_, i) => (
                <Star
                  key={i}
                  className={`size-16 ${i < rating ? 'fill-current text-star' : 'text-[#d9c6bb]'}`}
                  strokeWidth={i < rating ? 0 : 1.5}
                  aria-hidden
                />
              ))}
            </div>
            <blockquote
              lang={r.lang === 'darija' ? 'ary' : r.lang}
              dir={r.lang === 'ar' ? 'rtl' : 'ltr'}
              className="mt-8 font-serif fs-16.5 lh-22 tracking-[-0.02em] text-[#2a0a0c] [font-variation-settings:'opsz'_24]"
            >
              {/* « » mirror correctly in right-to-left text; curly quotes don't */}
              <p>{r.lang === 'ar' ? `«${r.text}»` : `“${r.text}”`}</p>
            </blockquote>
          </div>
          {r.photo && (
            <img
              src={r.photo}
              alt={r.photoAlt ?? `Photo envoyée par ${r.author} (visage flouté)`}
              loading="lazy"
              width={128}
              height={128}
              className="size-64 shrink-0 rounded-12 object-cover"
            />
          )}
        </div>
        <figcaption className="mt-auto flex flex-wrap items-center gap-x-10 gap-y-4 pt-12">
          <span className="fs-14.5 font-semibold text-ink">{[r.author, r.city].filter(Boolean).join(', ')}</span>
          <span className="flex items-center gap-6 fs-12.5 font-[500] text-[#2a0a0c]">
            <CircleCheck className="size-17 fill-[#3a0a10] text-ivory" strokeWidth={2.2} aria-hidden />
            Achat vérifié
          </span>
        </figcaption>
      </figure>
    </li>
  )
}
