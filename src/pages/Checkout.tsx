import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import gsap from 'gsap'
import { ArrowRight, CircleCheck, Package, Phone, Truck, User, Check, Minus, Plus, Loader2 } from 'lucide-react'
import { Logo } from '../components/Logo'
import { PRODUCT } from '../content'
import { keepFlushing, newClientId, submitOrder, wakeBot } from '../lib/orders'

/*
 * Units: below lg, 1 unit = 1px (mobile/tablet layout). At lg, `.checkout-scale`
 * redefines --spacing so 1 unit = 1px of the 1536px-wide approved checkout design.
 */

const fmt = (n: number) => `${n} ${PRODUCT.currency}`
const MAX_QTY = 10

// Business WhatsApp number, international format digits only (e.g. 212612345678).
const WHATSAPP_NUMBER = ((import.meta.env.VITE_WHATSAPP_NUMBER as string | undefined) ?? '').replace(/\D/g, '')

// Pre-filled message the client sends us: they open the conversation, so our replies are free (24h window).
const whatsappUrl = (orderNumber: string, total: number, name: string) =>
  `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(
    `Bonjour NAYO, je confirme ma commande ${orderNumber} – ${total} MAD – ${name}`,
  )}`

function WhatsAppGlyph({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2.05 22l5.25-1.38a9.9 9.9 0 0 0 4.74 1.21h.01c5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2Zm0 18.15h-.01a8.23 8.23 0 0 1-4.19-1.15l-.3-.18-3.12.82.83-3.04-.2-.31a8.2 8.2 0 0 1-1.26-4.38c0-4.54 3.7-8.23 8.25-8.23 2.2 0 4.27.86 5.82 2.42a8.18 8.18 0 0 1 2.41 5.82c0 4.54-3.7 8.23-8.23 8.23Zm4.52-6.16c-.25-.12-1.47-.72-1.69-.81-.23-.08-.39-.12-.56.12-.16.25-.64.81-.78.97-.14.17-.29.19-.54.06-.25-.12-1.050-.39-1.99-1.23-.74-.66-1.230-1.470-1.380-1.720-.14-.25-.02-.38.11-.5.11-.11.25-.29.37-.43.13-.15.17-.25.25-.41.08-.17.04-.31-.02-.43-.06-.12-.56-1.34-.76-1.84-.2-.48-.41-.42-.56-.43h-.48c-.17 0-.43.06-.66.31-.22.25-.86.85-.86 2.070 0 1.220.89 2.400 1.010 2.560.12.170 1.750 2.670 4.230 3.740.59.26 1.050.41 1.410.52.59.19 1.130.16 1.560.1.48-.07 1.470-.6 1.670-1.180.21-.58.21-1.070.14-1.180-.06-.1-.22-.16-.47-.28Z" />
    </svg>
  )
}

// Moroccan mobile/landline: 05/06/07 + 8 digits, or +212 / 00212 prefix.
const normalizePhone = (v: string) => v.replace(/[\s.-]/g, '').replace(/^(\+|00)212/, '0')
const isValidPhone = (v: string) => /^0[5-7]\d{8}$/.test(normalizePhone(v))

type Status = 'idle' | 'sending' | 'done'

function TruckIcon({ className = '' }: { className?: string }) {
  return <Truck className={className} strokeWidth={1.5} aria-hidden />
}

function Field({
  id,
  label,
  icon,
  error,
  ...input
}: React.InputHTMLAttributes<HTMLInputElement> & { id: string; label: string; icon: React.ReactNode; error?: string }) {
  return (
    <div>
      <div
        className={`group relative flex h-56 items-center r-14 border bg-[#fcf4f4] shadow-[inset_0_1px_2px_rgba(60,10,20,0.03)] transition-colors focus-within:border-[#7a1a2a] lg:h-67 lg:r-16 ${
          error ? 'border-[#b4233a]' : 'border-[#d9d0d1]'
        }`}
      >
        <span className="pointer-events-none absolute left-18 text-[#4a0108] lg:left-29">{icon}</span>
        <input
          id={id}
          {...input}
          aria-invalid={!!error}
          aria-describedby={error ? `${id}-err` : undefined}
          placeholder=" "
          className="peer h-full w-full rounded-[inherit] bg-transparent pl-52 pr-16 fs-16 text-[#2a1416] outline-none lg:pl-95 lg:pr-24 lg:fs-22"
        />
        <label
          htmlFor={id}
          className="pointer-events-none absolute left-52 fs-16 text-[#2a1416] transition-opacity peer-[:not(:placeholder-shown)]:opacity-0 lg:left-95 lg:fs-22"
        >
          {label} <span aria-hidden>*</span>
        </label>
      </div>
      {error && (
        <p id={`${id}-err`} role="alert" className="mt-6 pl-4 fs-13 text-[#b4233a] lg:fs-16">
          {error}
        </p>
      )}
    </div>
  )
}

export default function Checkout() {
  const root = useRef<HTMLDivElement>(null)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [errors, setErrors] = useState<{ name?: string; phone?: string }>({})
  const [status, setStatus] = useState<Status>('idle')
  const [qty, setQty] = useState(1)
  const [placed, setPlaced] = useState<{ orderNumber: string; total: number; name: string } | null>(null)
  const subtotal = PRODUCT.price * qty
  const total = subtotal + PRODUCT.shipping

  useLayoutEffect(() => {
    document.title = 'Finaliser la commande — NAYO'
    window.scrollTo(0, 0)
    const mm = gsap.matchMedia()
    mm.add('(prefers-reduced-motion: no-preference)', () => {
      const q = gsap.utils.selector(root)
      gsap
        .timeline({ defaults: { ease: 'power3.out' } })
        .from(q('[data-anim="silk"]'), { autoAlpha: 0, x: 60, y: 30, duration: 1.4, ease: 'power2.out' }, 0)
        .from(q('[data-anim="top"]'), { autoAlpha: 0, y: -12, duration: 0.7, stagger: 0.08 }, 0.05)
        .from(q('[data-anim="left"]'), { autoAlpha: 0, y: 18, duration: 0.7, stagger: 0.07 }, 0.15)
        .from(q('[data-anim="card"]'), { autoAlpha: 0, y: 26, duration: 0.9 }, 0.25)
        .from(q('[data-anim="product"]'), { autoAlpha: 0, y: 14, rotate: -3, duration: 0.9 }, 0.5)
    })
    return () => mm.revert()
  }, [])

  // Free hosts sleep: wake the bot as soon as the checkout opens, so the order POST is fast.
  useEffect(() => wakeBot(), [])
  // Fallback orders saved locally are re-sent until the bot has them.
  useEffect(() => (status === 'done' ? keepFlushing() : undefined), [status])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (status === 'sending') return
    const next: typeof errors = {}
    if (name.trim().length < 3) next.name = 'Veuillez saisir votre nom complet.'
    if (!isValidPhone(phone)) next.phone = 'Veuillez saisir un numéro marocain valide (ex. 06 12 34 56 78).'
    setErrors(next)
    if (Object.keys(next).length) {
      const first = next.name ? 'nom' : 'tel'
      document.getElementById(first)?.focus()
      return
    }

    setStatus('sending')
    const cleanName = name.trim().replace(/\s+/g, ' ')
    // Waits up to 10 s for the bot's number; otherwise a saved NAYO-W… fallback (retried in the background).
    const result = await submitOrder({
      clientId: newClientId(),
      name: cleanName,
      phone: normalizePhone(phone),
      product: PRODUCT.name,
      quantity: qty,
      unitPrice: PRODUCT.price,
      subtotal,
      shipping: PRODUCT.shipping,
      total,
      currency: PRODUCT.currency,
      payment: 'cash_on_delivery',
      status: 'new',
      createdAt: new Date().toISOString(),
    })
    if (!WHATSAPP_NUMBER) console.error('[NAYO] VITE_WHATSAPP_NUMBER is not set — the WhatsApp button is hidden.')
    setPlaced({ orderNumber: result.orderNumber, total: result.total, name: cleanName })
    setStatus('done')
  }

  return (
    <div ref={root} className="checkout-scale relative min-h-screen overflow-hidden bg-[#fcf1ef] text-[#2a1416]">
      {/* Burgundy silk decoration */}
      <img
        data-anim="silk"
        src="/assets/silk.png"
        alt=""
        aria-hidden
        className="pointer-events-none absolute right-0 bottom-0 w-[62vw] max-w-720 select-none md:w-[48vw] lg:w-720 lg:max-w-none"
      />

      <div className="relative mx-auto w-full max-w-1536 px-20 pb-130 md:px-40 md:pb-160 lg:px-0 lg:pb-0 lg:h-1024">
        {/* Top: logo + mode */}
        <header className="flex flex-col items-center pt-20 lg:pt-14">
          <Link to="/" aria-label="NAYO — retour à l'accueil" data-anim="top">
            <Logo color="#5a0716" className="w-120 lg:w-183" />
          </Link>
          <div data-anim="top" className="mt-18 flex w-full items-center justify-center gap-14 lg:mt-26 lg:gap-0">
            <span className="h-px flex-1 bg-[#c9b3b3] md:max-w-125 lg:w-125" aria-hidden />
            <span className="flex items-center gap-10 lg:mx-36 lg:gap-16">
              <TruckIcon className="size-28 text-[#4a0108] lg:size-44" />
              <span className="fs-16 text-[#3a0a10] lg:fs-23">Commande à la livraison</span>
            </span>
            <span className="h-px flex-1 bg-[#c9b3b3] md:max-w-125 lg:w-125" aria-hidden />
          </div>
        </header>

        <main className="mt-28 grid gap-28 lg:mt-0 lg:block">
          {/* LEFT — form */}
          <section aria-labelledby="checkout-title" className="contents lg:absolute lg:top-219 lg:left-76 lg:block lg:w-690">
            <div className="order-1">
              <h1
                id="checkout-title"
                data-anim="left"
                className="serif-tight fs-34 lh-40 text-[#4a0108] lg:fs-55.5 lg:lh-60 lg:font-[600] lg:tracking-[-0.045em]"
              >
                Finalisez votre commande
              </h1>
              <p data-anim="left" className="mt-8 fs-16 lh-22 text-[#2a1416] lg:mt-13 lg:fs-28 lg:lh-34 lg:font-[450]">
                Recevez votre NAYO chez vous, partout au Maroc.
              </p>
            </div>

            <form noValidate onSubmit={submit} className="order-3 lg:mt-52" aria-describedby="cod-note">
              {status === 'done' && placed ? (
                <div role="status" className="r-16 border border-[#d9d0d1] bg-[#fcf4f4] px-20 py-24 text-center lg:px-40 lg:py-40">
                  <CircleCheck className="mx-auto size-40 text-[#5c0715] lg:size-56" strokeWidth={1.4} aria-hidden />
                  <h2 className="serif-tight mt-10 fs-25 lh-30 text-[#4a0108] lg:mt-14 lg:fs-36 lg:lh-42">
                    Dernière étape : confirmez sur WhatsApp
                  </h2>
                  <p className="mx-auto mt-8 max-w-520 fs-15 lh-22 lg:mt-12 lg:fs-21 lg:lh-30">
                    Pour recevoir votre colis, confirmez votre commande en un clic.
                  </p>
                  <p className="mt-6 fs-13 text-[#6b5557] lg:fs-17">
                    Commande <strong className="font-semibold text-[#4a0108]">{placed.orderNumber}</strong> ·{' '}
                    {fmt(placed.total)} à la livraison
                  </p>
                  {WHATSAPP_NUMBER && (
                    <a
                      href={whatsappUrl(placed.orderNumber, placed.total, placed.name)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-18 flex min-h-60 w-full items-center justify-center gap-12 rounded-pill bg-gradient-to-b from-[#650a1a] to-[#55040f] px-20 py-10 fs-17 font-semibold text-white shadow-[0_10px_24px_rgba(92,7,21,0.22)] transition-[scale] duration-300 hover:scale-[1.015] lg:mt-26 lg:min-h-77 lg:gap-18 lg:fs-25"
                    >
                      <WhatsAppGlyph className="size-24 shrink-0 lg:size-34" />
                      Confirmer ma commande sur WhatsApp
                    </a>
                  )}
                  <p className="mt-12 fs-13 text-[#6b5557] lg:mt-16 lg:fs-17">Vous pouvez aussi attendre notre appel.</p>
                </div>
              ) : (
                <>
                  <h2 data-anim="left" className="flex items-center gap-14 fs-20 font-[650] text-[#4a0108] lg:gap-22 lg:fs-30">
                    <User className="size-24 lg:size-34" strokeWidth={1.4} aria-hidden />
                    Vos informations
                  </h2>
                  <div data-anim="left" className="mt-14 flex flex-col gap-16 lg:mt-16 lg:gap-24">
                    <Field
                      id="nom"
                      name="name"
                      label="Nom complet"
                      autoComplete="name"
                      required
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      error={errors.name}
                      icon={<User className="size-22 lg:size-34" strokeWidth={1.4} />}
                    />
                    <Field
                      id="tel"
                      name="phone"
                      type="tel"
                      inputMode="tel"
                      label="Numéro de téléphone"
                      autoComplete="tel"
                      required
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      error={errors.phone}
                      icon={<Phone className="size-22 lg:size-32" strokeWidth={1.4} />}
                    />
                  </div>

                  <div data-anim="left" className="relative">
                    <button
                      type="submit"
                      disabled={status === 'sending'}
                      aria-busy={status === 'sending'}
                      className="group mt-28 flex h-60 w-full items-center justify-center gap-14 rounded-pill bg-gradient-to-b from-[#650a1a] to-[#55040f] fs-18 font-semibold text-white shadow-[0_10px_24px_rgba(92,7,21,0.22)] transition-[scale] duration-300 hover:scale-[1.015] disabled:cursor-wait disabled:hover:scale-100 lg:mt-78 lg:h-77 lg:gap-24 lg:fs-27"
                    >
                      {status === 'sending' ? (
                        <>
                          <Loader2 className="size-24 animate-spin lg:size-36" strokeWidth={1.8} aria-hidden />
                          Envoi en cours…
                        </>
                      ) : (
                        <>
                          <TruckIcon className="size-26 lg:size-46" />
                          Commander maintenant
                          <ArrowRight className="size-20 transition-transform group-hover:translate-x-4 lg:size-28" strokeWidth={1.6} aria-hidden />
                        </>
                      )}
                    </button>
                    {/* At lg it sits in the gap above the trust strip, so the approved layout doesn't move. */}
                    <p className="mt-10 text-center fs-12.5 lh-17 text-[#6b5557] lg:absolute lg:inset-x-0 lg:top-full lg:mt-14 lg:fs-15 lg:lh-20">
                      En commandant, vous acceptez d'être contacté(e) sur WhatsApp pour confirmer votre commande.
                    </p>
                  </div>
                </>
              )}
              <p id="cod-note" className="sr-only">
                Paiement uniquement à la livraison. Total à payer : {fmt(total)}.
              </p>
            </form>

            {/* Trust */}
            <ul data-anim="left" className="order-4 grid grid-cols-3 lg:mt-61 lg:-ml-8 lg:flex lg:w-720" aria-label="Garanties">
              {[
                { icon: <TruckIcon className="size-30 lg:size-50" />, l1: 'Livraison partout', l2: 'au Maroc', w: 'lg:w-229' },
                { icon: <Package className="size-26 lg:size-38" strokeWidth={1.4} aria-hidden />, l1: 'Paiement', l2: 'à la livraison', w: 'lg:w-217 lg:pl-32' },
                { icon: <Check className="size-26 rounded-full border-[1.5px] border-current p-4 lg:size-38 lg:p-7" strokeWidth={2} aria-hidden />, l1: 'Satisfait ou', l2: 'remboursé sous 7 jours', w: 'lg:pl-32' },
              ].map((t, i) => (
                <li
                  key={t.l1}
                  className={`flex flex-col items-center gap-6 text-center text-[#3a0a10] md:flex-row md:text-left lg:h-43 lg:gap-21 ${t.w} ${
                    i > 0 ? 'border-l border-[#bfa9a9]' : ''
                  }`}
                >
                  <span className="shrink-0 text-[#4a0108]">{t.icon}</span>
                  <span className="fs-12.5 lh-17 font-semibold lg:fs-17 lg:lh-23">
                    {t.l1}
                    <br />
                    {t.l2}
                  </span>
                </li>
              ))}
            </ul>
          </section>

          {/* RIGHT — order summary */}
          <aside
            data-anim="card"
            aria-labelledby="summary-title"
            className="order-2 r-22 bg-gradient-to-br from-[#681520] to-[#560b16] p-12 pt-18 shadow-[0_18px_40px_rgba(70,5,15,0.18)] lg:absolute lg:top-218 lg:left-820 lg:h-578 lg:w-653 lg:r-26 lg:p-0"
          >
            <h2 id="summary-title" className="serif-tight px-8 fs-26 lh-32 text-[#fbf2ee] lg:absolute lg:top-21 lg:left-48 lg:px-0 lg:fs-41 lg:lh-50 lg:font-[540] lg:tracking-[-0.04em]">
              Votre commande
            </h2>

            <div className="mt-14 overflow-hidden r-16 bg-[#fcf1ef] lg:absolute lg:top-93 lg:left-34 lg:mt-0 lg:h-449 lg:w-592 lg:r-18">
              {/* Product line */}
              <div className="flex items-center gap-14 px-16 pt-14 lg:block lg:h-235 lg:p-0">
                <img
                  data-anim="product"
                  src="/assets/nayo-deodorant-300.webp"
                  srcSet="/assets/nayo-deodorant-300.webp 300w, /assets/nayo-deodorant-600.webp 600w"
                  sizes="(min-width: 1024px) 140px, 84px"
                  alt="Déodorant NAYO"
                  width={300}
                  height={450}
                  className="h-auto w-84 shrink-0 drop-shadow-[6px_10px_10px_rgba(60,0,10,0.18)] lg:absolute lg:top-18 lg:left-37 lg:w-147"
                />
                <div className="flex-1 lg:absolute lg:top-64 lg:left-199 lg:right-33">
                  <p className="fs-17 font-[650] text-[#4a0108] lg:fs-24">
                    NAYO<sup className="relative -top-[0.15em] fs-12 lg:fs-19">®</sup> Déodorant
                  </p>
                  <div className="mt-10 flex items-center justify-between lg:mt-18">
                    {status === 'done' ? (
                      <span className="grid h-34 place-items-center r-8 border border-[#dcc8c8] px-12 fs-15 text-[#2a1416] lg:h-46 lg:min-w-70 lg:r-10 lg:px-16 lg:fs-24">
                        × {qty}
                      </span>
                    ) : (
                      <div
                        role="group"
                        aria-label="Quantité"
                        className="flex h-34 items-center r-8 border border-[#dcc8c8] text-[#2a1416] lg:h-46 lg:r-10"
                      >
                        <button
                          type="button"
                          aria-label="Retirer un déodorant"
                          disabled={qty <= 1}
                          onClick={() => setQty((q) => Math.max(1, q - 1))}
                          className="grid h-full w-32 place-items-center text-[#4a0108] transition-opacity disabled:opacity-30 lg:w-44"
                        >
                          <Minus className="size-14 lg:size-20" strokeWidth={2} aria-hidden />
                        </button>
                        <output aria-live="polite" className="min-w-22 text-center fs-15 tabular-nums lg:min-w-30 lg:fs-24">
                          {qty}
                        </output>
                        <button
                          type="button"
                          aria-label="Ajouter un déodorant"
                          disabled={qty >= MAX_QTY}
                          onClick={() => setQty((q) => Math.min(MAX_QTY, q + 1))}
                          className="grid h-full w-32 place-items-center text-[#4a0108] transition-opacity disabled:opacity-30 lg:w-44"
                        >
                          <Plus className="size-14 lg:size-20" strokeWidth={2} aria-hidden />
                        </button>
                      </div>
                    )}
                    <span className="fs-19 font-bold text-[#4a0108] lg:fs-27">{fmt(subtotal)}</span>
                  </div>
                </div>
              </div>

              {/* Breakdown */}
              <dl className="mx-16 mt-14 border-y border-[#e3d3d1] py-12 lg:mx-32 lg:mt-0 lg:mr-33 lg:h-117 lg:py-0 lg:pt-12">
                <div className="flex justify-between fs-15 lh-26 lg:fs-23 lg:lh-44">
                  <dt>Sous-total{qty > 1 ? ` (${qty} × ${fmt(PRODUCT.price)})` : ''}</dt>
                  <dd>{fmt(subtotal)}</dd>
                </div>
                <div className="flex justify-between fs-15 lh-26 lg:fs-23 lg:lh-44">
                  <dt>Frais de livraison</dt>
                  <dd>{fmt(PRODUCT.shipping)}</dd>
                </div>
              </dl>

              {/* Total */}
              <div className="mt-8 flex items-center justify-between rt-12 bg-[#f6e2e1] px-18 py-16 lg:mt-7 lg:h-90 lg:rt-16 lg:px-0 lg:py-0 lg:pl-37 lg:pr-33">
                <span className="fs-18 font-bold text-[#4a0108] lg:fs-29">Total à payer</span>
                <span className="fs-24 font-bold text-[#4a0108] lg:fs-36">{fmt(total)}</span>
              </div>
            </div>
          </aside>
        </main>
      </div>
    </div>
  )
}
