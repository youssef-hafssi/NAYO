import { Logo } from './Logo'

export function Footer() {
  return (
    <footer className="bg-wine-850 text-white/70">
      <div className="mx-auto flex w-full max-w-1024 flex-col items-center gap-12 border-t border-white/10 px-16 py-24 md:flex-row md:justify-between md:px-24 lg:px-56">
        <Logo className="w-64" />
        <p className="fs-12.5">Livraison partout au Maroc · Paiement à la livraison</p>
        <p className="fs-12.5">© {new Date().getFullYear()} NAYO</p>
      </div>
      <p className="mx-auto max-w-1024 px-16 pb-16 text-center fs-11 text-white/45 md:px-24">Ce site mesure son audience pour améliorer le service.</p>
    </footer>
  )
}
