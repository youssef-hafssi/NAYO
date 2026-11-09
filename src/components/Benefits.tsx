import { Clock, Feather, Sparkle } from 'lucide-react'

const ITEMS = [
  { Icon: Sparkle, title: 'Éclaircit le teint', text: 'Réduit visiblement les zones sombres.' },
  { Icon: Feather, title: 'Respecte la peau', text: 'Formule douce et non irritante.' },
  { Icon: Clock, title: 'Fraîcheur longue durée', text: 'Restez fraîche et confiante 24h.' },
]

export function Benefits() {
  return (
    <section id="benefices" aria-label="Bénéfices" className="bg-ivory">
      <ul className="mx-auto grid w-full max-w-1024 gap-14 px-20 py-28 md:grid-cols-3 md:gap-0 md:px-24 lg:h-99 lg:grid-cols-[calc(var(--spacing)*334)_calc(var(--spacing)*313)_1fr] lg:px-0 lg:py-0 lg:pt-16 lg:pb-0 lg:pl-66 lg:items-start">
        {ITEMS.map(({ Icon, title, text }, i) => (
          <li
            key={title}
            data-anim="reveal"
            className={`flex items-center gap-13 md:flex-col md:px-8 md:text-center lg:flex-row lg:px-0 lg:text-left ${
              i === 1 ? 'lg:ml-0 lg:justify-start' : ''
            } ${i === 2 ? 'lg:justify-start' : ''} ${
              i > 0 ? 'lg:relative lg:before:absolute lg:before:top-12 lg:before:h-40 lg:before:w-px lg:before:bg-[#d8c6bb]' : ''
            } ${i === 1 ? 'lg:before:-left-27' : ''} ${i === 2 ? 'lg:before:-left-24' : ''}`}
          >
            <span className="grid size-60 shrink-0 place-items-center rounded-14 bg-[#f6e8e0] shadow-[0_4px_10px_rgba(90,30,30,0.10),inset_0_1px_0_rgba(255,255,255,0.8)] lg:size-61">
              <Icon className="size-34 text-[#3a0a10]" strokeWidth={1.6} aria-hidden />
            </span>
            <span>
              <span className="serif-tight block fs-18 lh-22 font-[720] tracking-[-0.045em] text-ink-title">{title}</span>
              <span className="mt-5 block fs-12.5 lh-16 font-[520] text-[#3a2224]">{text}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
