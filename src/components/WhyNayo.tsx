import { Clock, Feather, Sparkle } from 'lucide-react'

/* "Pourquoi NAYO": the brand speaking (not customer reviews: no names, quotes or stars). The photo's face is
   strongly blurred at the source (public/assets/nayo-selfie-*.webp). */

const POINTS = [
  {
    Icon: Sparkle,
    title: 'Un teint plus clair, progressivement',
    text: 'Les enzymes de fruits exfolient la peau en douceur : jour après jour, le teint des aisselles s’éclaircit et s’unifie.',
  },
  { Icon: Feather, title: 'Douce pour la peau', text: 'Une exfoliation tout en douceur, pensée pour un usage quotidien.' },
  { Icon: Clock, title: 'Fraîcheur toute la journée', text: 'Une sensation de fraîcheur du matin au soir.' },
]

export function WhyNayo() {
  return (
    <section id="pourquoi" aria-labelledby="why-title" className="scroll-mt-80 bg-ivory">
      <div className="mx-auto grid w-full max-w-1024 gap-20 px-16 py-28 md:grid-cols-[1fr_340px] md:items-center md:gap-36 md:px-24 md:py-36">
        <div>
          <h2 id="why-title" data-anim="reveal" className="serif-tight fs-28 lh-34 text-ink-title md:fs-32 md:lh-38">
            Pourquoi NAYO
          </h2>
          <ul className="mt-16 grid gap-14">
            {POINTS.map(({ Icon, title, text }) => (
              <li key={title} data-anim="reveal" className="flex gap-14">
                <span className="grid size-48 shrink-0 place-items-center rounded-14 bg-[#f6e8e0] shadow-[0_4px_10px_rgba(90,30,30,0.10),inset_0_1px_0_rgba(255,255,255,0.8)]">
                  <Icon className="size-26 text-[#3a0a10]" strokeWidth={1.6} aria-hidden />
                </span>
                <span>
                  <span className="serif-tight block fs-18 lh-22 font-[720] tracking-[-0.03em] text-ink-title">{title}</span>
                  <span className="mt-4 block fs-14.5 lh-20 text-[#3a2224]">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <figure data-anim="reveal-photo" className="mx-auto w-full max-w-340 overflow-hidden rounded-16 bg-[#efe3dc]">
          <img
            src="/assets/nayo-selfie-600.webp"
            srcSet="/assets/nayo-selfie-600.webp 600w, /assets/nayo-selfie-1000.webp 1000w"
            sizes="340px"
            alt="Une utilisatrice tient le déodorant NAYO (visage flouté)"
            loading="lazy"
            width={1000}
            height={1331}
            className="block h-auto w-full"
          />
        </figure>
      </div>
    </section>
  )
}
