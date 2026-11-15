import { ArrowRight, Clock, Leaf, ShoppingCart, Sparkle } from 'lucide-react'

const PERKS = [
  { Icon: Sparkle, l1: 'Unifie', l2: 'progressivement' },
  { Icon: Clock, l1: 'Fraîcheur', l2: 'toute la journée' },
  { Icon: Leaf, l1: 'Formule', l2: 'douce' },
]

/** Hero button → the express form right below (smooth unless reduced motion), cursor in the first field. */
function goToOrderForm(e: React.MouseEvent<HTMLAnchorElement>) {
  const form = document.getElementById('commander')
  if (!form) return // no form on this page: follow the link
  e.preventDefault()
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  form.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
  window.setTimeout(() => document.getElementById('x-name')?.focus({ preventScroll: true }), reduce ? 0 : 600)
  history.replaceState(null, '', '#commander')
}

export function Hero() {
  return (
    <section id="top" className="relative overflow-hidden bg-wine-900 text-white" aria-labelledby="hero-title">
      {/* Photography — burgundy silk backdrop + model cutout as separate depth layers */}
      <div
        data-anim="hero-photo"
        className="relative h-420 w-full overflow-hidden md:absolute md:inset-0 md:h-auto"
        aria-hidden
      >
        <img
          data-depth="0.4"
          src="/assets/hero-bg.jpg"
          alt=""
          className="absolute inset-0 size-full object-cover object-[70%_0%] lg:object-[100%_0%]"
          width={2048}
          height={1058}
        />
        {/* tablet: keep copy legible over the backdrop (never over the model) */}
        <div className="absolute inset-0 hidden bg-[linear-gradient(90deg,var(--color-wine-900)_0%,rgb(58_1_10/0.6)_30%,transparent_48%)] md:block lg:hidden" />
        <div className="relative mx-auto h-full w-full max-w-1024">
          <img
            data-depth="1"
            data-anim="hero-model"
            src="/assets/model.webp"
            srcSet="/assets/model-640.webp 640w, /assets/model.webp 1226w"
            sizes="(min-width: 1024px) 52vw, (min-width: 768px) 60vw, 340px"
            alt=""
            fetchPriority="high"
            width={1226}
            height={1283}
            className="absolute top-24 left-1/2 w-330 max-w-none -translate-x-[50%] md:top-60 md:right-[-2%] md:left-auto md:w-[60%] md:translate-x-0 lg:top-38 lg:right-auto lg:left-417 lg:w-527"
          />
        </div>
        {/* mobile: fade into the text block below */}
        <div className="absolute inset-x-0 bottom-0 h-90 bg-gradient-to-t from-wine-900 to-transparent md:hidden" />
      </div>

      <div className="relative mx-auto w-full max-w-1024 px-24 pb-44 md:px-40 md:pt-120 md:pb-56 lg:h-529 lg:px-0 lg:pt-0 lg:pb-0">
        <div className="-mt-40 md:mt-0 lg:absolute lg:top-91 lg:left-72">
          <p data-anim="hero-eyebrow" className="ml-4 fs-14 lh-16 font-medium tracking-[0.68em] text-white/95">
            NAYO
          </p>
          <h1
            id="hero-title"
            className="serif-tight mt-8 fs-40 lh-42 text-[#f7f1ec] md:fs-50 md:lh-52 lg:mt-10 lg:fs-52.5 lg:[word-spacing:0.06em] lg:lh-49"
          >
            <span className="block overflow-hidden pb-2" data-anim="hero-line">
              <span className="block">Aisselles nettes</span>
            </span>
            <span className="relative block overflow-hidden pb-6" data-anim="hero-line">
              <span className="block">et plus claires.</span>
            </span>
          </h1>
          {/* hand-drawn rose underline */}
          <svg
            data-anim="hero-underline"
            className="ml-80 mt-2 block h-12 w-185 md:ml-90 lg:ml-88 lg:mt-6 lg:w-228"
            viewBox="0 0 228 12"
            fill="none"
            aria-hidden
          >
            <path
              d="M2 9.5C40 6.6 92 4.6 132 4.2c30-.3 62-.1 94-2.2"
              stroke="url(#ul)"
              strokeWidth="3.2"
              strokeLinecap="round"
            />
            <defs>
              <linearGradient id="ul" x1="0" x2="228" y1="0" y2="0" gradientUnits="userSpaceOnUse">
                <stop stopColor="#c2475e" stopOpacity=".55" />
                <stop offset=".55" stopColor="#ee8b98" />
                <stop offset="1" stopColor="#d5687a" stopOpacity=".7" />
              </linearGradient>
            </defs>
          </svg>

          <p
            data-anim="hero-copy"
            className="mt-14 max-w-360 fs-16 lh-23 text-[#f3e8e2] lg:mt-4 lg:ml-4 lg:max-w-none lg:whitespace-nowrap lg:fs-17 lg:lh-22.5 lg:tracking-[-0.005em] font-[500]"
          >
            NAYO aide à éclaircir et à unifier le teint <br className="hidden lg:block" />
            de vos aisselles grâce à son Super Fruit <br className="hidden lg:block" />
            Enzyme Triple Blend et à l'acide citrique, <br className="hidden lg:block" />
            qui exfolient la peau en douceur.
          </p>

          <a
            href="#commander"
            onClick={goToOrderForm}
            data-anim="hero-cta"
            className="group mt-22 flex h-50 w-full max-w-320 items-center justify-center gap-12 rounded-pill bg-ivory-2 fs-16.5 font-semibold text-ink shadow-[0_6px_24px_rgba(0,0,0,0.18)] transition-[scale] duration-300 hover:scale-[1.02] md:w-295 lg:mt-20 lg:ml-3 lg:h-48"
          >
            <ShoppingCart className="size-22" strokeWidth={1.6} aria-hidden />
            Acheter maintenant
            <ArrowRight className="size-17 transition-transform group-hover:translate-x-3" strokeWidth={2} aria-hidden />
          </a>

          <ul className="mt-22 flex w-full max-w-340 items-start lg:mt-19 lg:-ml-2 lg:w-349" aria-label="Points clés">
            {PERKS.map(({ Icon, l1, l2 }, i) => (
              <li
                key={l1}
                data-anim="hero-perk"
                className={`flex flex-1 flex-col items-center text-center ${
                  i > 0 ? 'border-l border-white/35' : ''
                }`}
              >
                <Icon className="size-30" strokeWidth={1.15} aria-hidden />
                <span className="mt-10 px-2 fs-12.5 lh-16 text-white/95 sm:fs-14 sm:lh-17 lg:mt-6">
                  {l1}
                  <br />
                  {l2}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}
