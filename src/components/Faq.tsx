import { useRef, useState } from 'react'
import { Plus } from 'lucide-react'
import gsap from 'gsap'
import { FAQ } from '../content'

function Item({ q, a, idx }: { q: string; a: string; idx: number }) {
  const [open, setOpen] = useState(false)
  const panel = useRef<HTMLDivElement>(null)
  const icon = useRef<SVGSVGElement>(null)
  const id = `faq-${idx}`

  const toggle = () => {
    const next = !open
    setOpen(next)
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const d = reduce ? 0 : 0.42
    gsap.to(panel.current, { height: next ? 'auto' : 0, opacity: next ? 1 : 0, duration: d, ease: 'power3.out' })
    gsap.to(icon.current, { rotate: next ? 45 : 0, duration: d, ease: 'power3.out' })
  }

  return (
    <li data-anim="reveal" className="rounded-[calc(var(--spacing)*23)] border border-[#c8a296]/80 transition-colors hover:border-[#e2c3b6]">
      <h3>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-controls={id}
          className="flex min-h-46 w-full items-center gap-16 py-10 pr-24 pl-23 text-left fs-16 lh-22 font-[500] text-white/95 lg:fs-15.75 lg:h-44 lg:py-0"
        >
          <span className="flex-1">{q}</span>
          <Plus ref={icon} className="size-20 shrink-0" strokeWidth={1.7} aria-hidden />
        </button>
      </h3>
      <div id={id} ref={panel} role="region" className="h-0 overflow-hidden opacity-0" aria-hidden={!open}>
        <p className="max-w-720 px-23 pb-16 fs-14.5 lh-22 text-white/75">{a}</p>
      </div>
    </li>
  )
}

export function Faq() {
  return (
    <section
      id="faq"
      aria-labelledby="faq-title"
      className="relative overflow-hidden bg-wine-850 text-white"
      style={{
        backgroundImage:
          'radial-gradient(120% 90% at 50% 10%, rgba(78,4,18,0.55), transparent 60%), radial-gradient(80% 60% at 90% 100%, rgba(25,0,4,0.5), transparent 70%)',
      }}
    >
      <div className="mx-auto w-full max-w-1024 px-16 pt-36 pb-56 md:px-24 lg:px-0 lg:pt-28 lg:pb-64 lg:pl-56 lg:pr-54">
        <h2 id="faq-title" data-anim="reveal" className="serif-tight fs-28 lh-38 text-[#f7f1ec] lg:fs-30 lg:lh-38 lg:tracking-[-0.05em]">
          Questions fréquentes
        </h2>
        <ul className="mt-20 flex flex-col gap-11 lg:mt-19">
          {FAQ.map((f, i) => (
            <Item key={f.q} q={f.q} a={f.a} idx={i} />
          ))}
        </ul>
      </div>
    </section>
  )
}
