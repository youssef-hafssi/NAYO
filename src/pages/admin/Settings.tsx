import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { adminApi, Unauthorized, type AppSettings } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { Banner, BusyButton, FieldLabel, inputClass, PageSkeleton } from './ui'

/*
 * Réglages (owner only, server-enforced): company details printed on the bons de livraison, low-stock threshold,
 * follow-up delay. Carriers and expense categories keep their own screens (linked here).
 * Prices and the delivery fee charged to customers are not settings: they come from the code (pricing.py).
 */

type Form = Record<keyof AppSettings, string>
const toForm = (s: AppSettings): Form => ({
  company_name: s.company_name,
  company_address: s.company_address,
  company_phone: s.company_phone,
  stock_low_threshold: String(s.stock_low_threshold),
  followup_stale_hours: String(s.followup_stale_hours),
})

export default function Settings() {
  const { me, logout } = useAuth()
  const [saved, setSaved] = useState<AppSettings | null>(() => adminApi.settings().peek() ?? null)
  const [form, setForm] = useState<Form | null>(() => (saved ? toForm(saved) : null))
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const fail = useCallback(
    (e: unknown) => (e instanceof Unauthorized ? logout() : setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })),
    [logout],
  )

  useEffect(() => {
    if (me.role !== 'owner') return
    adminApi
      .settings()
      .then((s) => {
        setSaved(s)
        setForm((f) => (f && saved && JSON.stringify(f) !== JSON.stringify(toForm(saved)) ? f : toForm(s))) // keep unsaved edits
      })
      .catch(fail)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me.role, fail])

  if (me.role !== 'owner')
    return (
      <div className="mx-auto w-full max-w-760 px-16 py-16 md:px-24 md:py-24">
        <h1 className="fs-22 font-bold">Réglages</h1>
        <p className="mt-12 fs-14 text-[#6b6b6b]">Réservé au propriétaire.</p>
      </div>
    )
  if (!form || !saved) return <PageSkeleton tiles={false} />

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value })

  const save = async (e: FormEvent) => {
    e.preventDefault()
    const threshold = Number(form.stock_low_threshold)
    const hours = Number(form.followup_stale_hours)
    if (!Number.isInteger(threshold) || threshold < 0) return setMessage({ kind: 'error', text: 'Seuil de stock invalide (nombre entier ≥ 0).' })
    if (!Number.isInteger(hours) || hours < 1 || hours > 168) return setMessage({ kind: 'error', text: 'Délai de relance : entre 1 et 168 heures.' })
    if (!form.company_name.trim()) return setMessage({ kind: 'error', text: "Le nom de l'entreprise est requis." })
    const next: Partial<AppSettings> = {
      company_name: form.company_name,
      company_address: form.company_address,
      company_phone: form.company_phone,
      stock_low_threshold: threshold,
      followup_stale_hours: hours,
    }
    const changed = Object.fromEntries(Object.entries(next).filter(([k, v]) => v !== saved[k as keyof AppSettings]))
    if (!Object.keys(changed).length) return setMessage({ kind: 'ok', text: 'Aucune modification.' })
    setBusy(true)
    setMessage(null)
    try {
      const s = await adminApi.editSettings(changed)
      setSaved(s)
      setForm(toForm(s))
      setMessage({ kind: 'ok', text: 'Réglages enregistrés.' })
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-760 px-16 py-16 md:px-24 md:py-24">
      <h1 className="fs-22 font-bold">Réglages</h1>
      <Banner msg={message} />
      <form onSubmit={save}>
        <section className="mt-14 r-14 border border-[#ece2dd] bg-white p-16 md:p-20">
          <h2 className="fs-16 font-bold">Entreprise</h2>
          <p className="mt-2 fs-12.5 text-[#8a8a8a]">Imprimé en haut des bons de livraison.</p>
          <div className="mt-12 grid gap-12 md:grid-cols-2">
            <div>
              <FieldLabel htmlFor="s-name">Nom</FieldLabel>
              <input id="s-name" required maxLength={80} className={inputClass} value={form.company_name} onChange={set('company_name')} />
            </div>
            <div>
              <FieldLabel htmlFor="s-phone">Téléphone</FieldLabel>
              <input id="s-phone" inputMode="tel" maxLength={30} className={inputClass} value={form.company_phone} onChange={set('company_phone')} />
            </div>
            <div className="md:col-span-2">
              <FieldLabel htmlFor="s-address">Adresse</FieldLabel>
              <input id="s-address" maxLength={300} className={inputClass} value={form.company_address} onChange={set('company_address')} />
            </div>
          </div>
        </section>

        <section className="mt-14 r-14 border border-[#ece2dd] bg-white p-16 md:p-20">
          <h2 className="fs-16 font-bold">Alertes et relances</h2>
          <div className="mt-12 grid gap-12 md:grid-cols-2">
            <div>
              <FieldLabel htmlFor="s-threshold">Seuil de stock bas (unités)</FieldLabel>
              <input id="s-threshold" inputMode="numeric" className={inputClass} value={form.stock_low_threshold} onChange={set('stock_low_threshold')} />
              <p className="mt-4 fs-12 text-[#8a8a8a]">Alerte WhatsApp et suggestion de relance à ce niveau.</p>
            </div>
            <div>
              <FieldLabel htmlFor="s-hours">À relancer après (heures)</FieldLabel>
              <input id="s-hours" inputMode="numeric" className={inputClass} value={form.followup_stale_hours} onChange={set('followup_stale_hours')} />
              <p className="mt-4 fs-12 text-[#8a8a8a]">Une commande nouvelle ou en cours sans réponse depuis ce délai est proposée en relance.</p>
            </div>
          </div>
        </section>

        <BusyButton type="submit" busy={busy} className="mt-14">
          Enregistrer
        </BusyButton>
      </form>

      <section className="mt-18 r-14 border border-[#ece2dd] bg-white">
        {[
          ['/admin/delivery?tab=carriers', 'Livreurs', 'Sociétés de livraison, frais par livraison et par retour, délai de versement'],
          ['/admin/finance?tab=expenses', 'Catégories de dépenses', 'Dans Finance → Dépenses → Catégories'],
          ['/admin/team', 'Équipe', 'Membres, rôles, mots de passe, journal des actions'],
        ].map(([to, label, sub]) => (
          <Link key={to} to={to} className="flex min-h-56 items-center gap-12 border-b border-[#f4eeeb] px-16 py-10 last:border-b-0 hover:bg-[#fbf8f6]">
            <span className="min-w-0 flex-1">
              <span className="block fs-14 font-semibold">{label}</span>
              <span className="block fs-12.5 text-[#8a8a8a]">{sub}</span>
            </span>
            <ChevronRight className="size-18 text-[#8a8a8a]" aria-hidden />
          </Link>
        ))}
      </section>
      <p className="mt-10 fs-12 text-[#8a8a8a]">Le prix du produit et les frais de livraison facturés au client ne se changent pas ici (ils sont fixés dans le code).</p>
    </div>
  )
}
