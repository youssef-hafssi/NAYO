import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Logo } from './Logo'
import { ORDER_PATH } from '../content'

const NAV = [
  { href: '#benefices', label: 'Bénéfices' },
  { href: '#avis', label: 'Avis' },
  { href: '#faq', label: 'FAQ' },
]

export function Header() {
  return (
    <header className="absolute inset-x-0 top-0 z-30" data-anim="header">
      <div className="mx-auto flex h-60 w-full max-w-1024 items-center px-20 md:px-40 lg:h-56 lg:px-0">
        <a href="#top" aria-label="NAYO — accueil" className="lg:ml-58 lg:-mt-2">
          <Logo className="w-84 md:w-96 lg:w-101" />
        </a>

        <nav aria-label="Navigation principale" className="ml-auto hidden md:block lg:ml-188">
          <ul className="flex items-center gap-28 lg:gap-0">
            {NAV.map((n, i) => (
              <li key={n.href} className={i === 0 ? '' : i === 1 ? 'lg:ml-50' : 'lg:ml-49'}>
                <a
                  href={n.href}
                  className="fs-15 font-medium tracking-[-0.005em] text-white/95 transition-opacity hover:opacity-70"
                >
                  {n.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <Link
          to={ORDER_PATH}
          className="group ml-auto inline-flex h-36 items-center gap-8 rounded-pill bg-ivory-2 pl-16 pr-14 fs-14 font-semibold text-ink shadow-[0_2px_10px_rgba(0,0,0,0.12)] transition-[scale] duration-300 hover:scale-[1.03] md:ml-36 lg:ml-auto lg:mr-37 lg:h-34 lg:pl-18 lg:pr-15 lg:fs-14.5"
        >
          Acheter maintenant
          <ArrowRight className="size-16 transition-transform group-hover:translate-x-2" strokeWidth={2} aria-hidden />
        </Link>
      </div>
    </header>
  )
}
