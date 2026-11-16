import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowRight, CircleCheck, Loader2, Minus, Plus } from 'lucide-react'
import { PRODUCT } from '../content'
import { ADDRESS_MAX, ADDRESS_MIN, fmt, isValidPhone, MAX_QTY, normalizePhone, WHATSAPP_NUMBER, whatsappUrl } from '../lib/checkout'
import { keepFlushing, newClientId, submitOrder, wakeBot } from '../lib/orders'
import { metaOrderFields, PRODUCT_EVENT, track, trackOnce } from '../lib/pixel'
import { WhatsAppGlyph } from './WhatsAppGlyph'

/*
 * Express checkout on the landing page: same POST /orders as /commande, plus city and address, so the bot only
 * sends the recap on WhatsApp and asks "oui". Same success screen and WhatsApp confirmation link.
 */

type Errors = Partial<Record<'name' | 'phone' | 'address', string>>
const FIELDS: { id: keyof Errors; label: string; type?: string; inputMode?: 'tel'; autoComplete: string; max: number; placeholder?: string }[] = [
  { id: 'name', label: 'Nom complet', autoComplete: 'name', max: 80 },
  { id: 'phone', label: 'Téléphone', type: 'tel', inputMode: 'tel', autoComplete: 'tel', max: 20 },
  // One address field: the bot finds the city in it (for reports / delivery) and never asks for it separately.
  { id: 'address', label: 'Adresse', autoComplete: 'street-address', max: ADDRESS_MAX, placeholder: 'Quartier, rue, ville' },
]

export function ExpressCheckout() {
  const [v, setV] = useState({ name: '', phone: '', address: '' })
  const [qty, setQty] = useState(1)
  const [errors, setErrors] = useState<Errors>({})
  const [status, setStatus] = useState<'idle' | 'sending' | 'done'>('idle')
  const [placed, setPlaced] = useState<{ orderNumber: string; total: number; name: string } | null>(null)
  const woke = useRef(false)
  const total = PRODUCT.price * qty + PRODUCT.shipping

  // Fallback orders saved locally are re-sent until the bot has them (same as /commande).
  useEffect(() => (status === 'done' ? keepFlushing() : undefined), [status])

  // Free hosts sleep: wake the bot when the visitor starts filling the form, not on every page view.
  const wake = () => {
    trackOnce('InitiateCheckout', { ...PRODUCT_EVENT, value: total, num_items: qty })
    if (!woke.current) {
      woke.current = true
      wakeBot()
    }
  }

  const clean = (s: string) => s.trim().replace(/\s+/g, ' ')

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (status === 'sending') return
    const next: Errors = {}
    if (clean(v.name).length < 3) next.name = 'Veuillez saisir votre nom complet.'
    if (!isValidPhone(v.phone)) next.phone = 'Numéro marocain valide, ex. 06 12 34 56 78.'
    if (clean(v.address).length < ADDRESS_MIN) next.address = 'Veuillez saisir votre adresse (quartier, rue, ville).'
    setErrors(next)
    const first = (Object.keys(next) as (keyof Errors)[])[0]
    if (first) {
      document.getElementById(`x-${first}`)?.focus()
      return
    }
    setStatus('sending')
    const name = clean(v.name)
    // Waits up to 10 s for the bot's number; otherwise a saved NAYO-W… fallback (retried in the background).
    const clientId = newClientId()
    const result = await submitOrder({
      ...metaOrderFields(),
      clientId,
      name,
      phone: normalizePhone(v.phone),
      address: clean(v.address),
      product: PRODUCT.name,
      quantity: qty,
      unitPrice: PRODUCT.price,
      subtotal: PRODUCT.price * qty,
      shipping: PRODUCT.shipping,
      total,
      currency: PRODUCT.currency,
      payment: 'cash_on_delivery',
      status: 'new',
      createdAt: new Date().toISOString(),
    })
    // Same event_id as the bot's Conversions API event: Meta counts this purchase once.
    track('Purchase', { ...PRODUCT_EVENT, value: result.total, num_items: qty, contents: [{ id: 'nayo-deodorant', quantity: qty }] }, `purchase-${clientId}`)
    setPlaced({ orderNumber: result.orderNumber, total: result.total, name })
    setStatus('done')
  }

  return (
    <section id="commander" aria-labelledby="express-title" className="bg-ivory">
      <div className="mx-auto w-full max-w-1024 px-16 py-28 md:px-24 md:py-36">
        <div className="mx-auto max-w-880 r-22 bg-gradient-to-br from-[#681520] to-[#560b16] p-10 shadow-[0_18px_40px_rgba(70,5,15,0.16)] md:p-14">
          <div className="r-16 bg-[#fcf4f1] px-16 py-20 md:px-28 md:py-26">
            {status === 'done' && placed ? (
              <div role="status" className="py-8 text-center">
                <CircleCheck className="mx-auto size-44 text-[#5c0715]" strokeWidth={1.4} aria-hidden />
                <h2 id="express-title" className="serif-tight mt-10 fs-26 lh-30 text-[#4a0108] md:fs-30 md:lh-36">
                  Dernière étape : confirmez sur WhatsApp
                </h2>
                <p className="mx-auto mt-8 max-w-480 fs-15 lh-22">Pour recevoir votre colis, confirmez votre commande en un clic.</p>
                <p className="mt-6 fs-13.5 text-[#6b5557]">
                  Commande <strong className="font-semibold text-[#4a0108]">{placed.orderNumber}</strong> · {fmt(placed.total)} à la livraison
                </p>
                {WHATSAPP_NUMBER && (
                  <a
                    href={whatsappUrl(placed.orderNumber, placed.total, placed.name)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mx-auto mt-18 flex min-h-56 w-full max-w-440 items-center justify-center gap-12 rounded-pill bg-gradient-to-b from-[#650a1a] to-[#55040f] px-20 py-10 fs-17 font-semibold text-white shadow-[0_10px_24px_rgba(92,7,21,0.22)] transition-[scale] duration-300 hover:scale-[1.015]"
                  >
                    <WhatsAppGlyph className="size-24 shrink-0" />
                    Confirmer ma commande sur WhatsApp
                  </a>
                )}
                <p className="mt-12 fs-13 text-[#6b5557]">Vous pouvez aussi attendre notre appel.</p>
              </div>
            ) : (
              <form noValidate onSubmit={submit} onFocus={wake}>
                <h2 id="express-title" className="serif-tight fs-28 lh-32 text-[#4a0108] md:fs-32 md:lh-38">
                  Commandez en 1&nbsp;minute
                </h2>
                <p className="mt-6 fs-14.5 lh-20 text-[#5a4446]">Paiement à la livraison · livraison partout au Maroc.</p>

                <div className="mt-16 grid gap-12 md:grid-cols-2">
                  {FIELDS.map((f) => (
                    <div key={f.id} className={f.id === 'address' ? 'md:col-span-2' : ''}>
                      <label htmlFor={`x-${f.id}`} className="block fs-13 font-semibold text-[#4a0108]">
                        {f.label} <span aria-hidden>*</span>
                      </label>
                      <input
                        id={`x-${f.id}`}
                        name={f.id}
                        type={f.type ?? 'text'}
                        inputMode={f.inputMode}
                        autoComplete={f.autoComplete}
                        maxLength={f.max}
                        placeholder={f.placeholder}
                        required
                        value={v[f.id]}
                        onChange={(e) => setV({ ...v, [f.id]: e.target.value })}
                        aria-invalid={!!errors[f.id]}
                        aria-describedby={errors[f.id] ? `x-${f.id}-err` : undefined}
                        className={`mt-6 h-50 w-full r-12 border bg-white px-14 fs-16 text-[#2a1416] outline-none transition-colors focus:border-[#7a1a2a] ${
                          errors[f.id] ? 'border-[#b4233a]' : 'border-[#d9d0d1]'
                        }`}
                      />
                      {errors[f.id] && (
                        <p id={`x-${f.id}-err`} role="alert" className="mt-4 fs-12.5 text-[#b4233a]">
                          {errors[f.id]}
                        </p>
                      )}
                    </div>
                  ))}
                </div>

                <div className="mt-16 flex flex-wrap items-center justify-between gap-12 r-12 bg-[#f6e2e1] px-14 py-12">
                  <div className="flex items-center gap-12">
                    <img src="/assets/nayo-deodorant-300.webp" alt="" width={300} height={450} className="h-auto w-34 shrink-0" />
                    <div role="group" aria-label="Quantité" className="flex h-40 items-center r-10 border border-[#dcc8c8] bg-white text-[#2a1416]">
                      <button
                        type="button"
                        aria-label="Retirer un déodorant"
                        disabled={qty <= 1}
                        onClick={() => setQty((q) => Math.max(1, q - 1))}
                        className="grid h-full w-40 place-items-center text-[#4a0108] disabled:opacity-30"
                      >
                        <Minus className="size-16" strokeWidth={2} aria-hidden />
                      </button>
                      <output aria-live="polite" className="min-w-24 text-center fs-16 tabular-nums">
                        {qty}
                      </output>
                      <button
                        type="button"
                        aria-label="Ajouter un déodorant"
                        disabled={qty >= MAX_QTY}
                        onClick={() => setQty((q) => Math.min(MAX_QTY, q + 1))}
                        className="grid h-full w-40 place-items-center text-[#4a0108] disabled:opacity-30"
                      >
                        <Plus className="size-16" strokeWidth={2} aria-hidden />
                      </button>
                    </div>
                  </div>
                  <p className="text-right">
                    <span className="block fs-12.5 text-[#6b5557]">
                      {qty} × {fmt(PRODUCT.price)} + {fmt(PRODUCT.shipping)} livraison
                    </span>
                    <span className="block fs-22 font-bold text-[#4a0108]" aria-live="polite">
                      Total : {fmt(total)}
                    </span>
                  </p>
                </div>

                <button
                  type="submit"
                  disabled={status === 'sending'}
                  aria-busy={status === 'sending'}
                  className="group mt-16 flex h-56 w-full items-center justify-center gap-12 rounded-pill bg-gradient-to-b from-[#650a1a] to-[#55040f] fs-17.5 font-semibold text-white shadow-[0_10px_24px_rgba(92,7,21,0.22)] transition-[scale] duration-300 hover:scale-[1.015] disabled:cursor-wait disabled:hover:scale-100"
                >
                  {status === 'sending' ? (
                    <>
                      <Loader2 className="size-22 animate-spin" strokeWidth={1.8} aria-hidden />
                      Envoi en cours…
                    </>
                  ) : (
                    <>
                      Commander
                      <ArrowRight className="size-20 transition-transform group-hover:translate-x-4" strokeWidth={1.6} aria-hidden />
                    </>
                  )}
                </button>
                <p className="mt-10 text-center fs-12.5 lh-17 text-[#6b5557]">
                  En commandant, vous acceptez d'être contacté(e) sur WhatsApp pour confirmer votre commande.
                </p>
              </form>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
