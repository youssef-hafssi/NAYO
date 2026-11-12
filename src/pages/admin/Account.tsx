import { useState, type FormEvent } from 'react'
import { adminApi, Unauthorized } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { BusyButton, FieldLabel, inputClass } from './ui'

/* "Plus": my account (change password, log out). Team and settings join this page in phase 7. */

const MIN = 10

export default function Account() {
  const { me, logout } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    if (next.length < MIN) return setMessage({ kind: 'error', text: `Le nouveau mot de passe doit faire au moins ${MIN} caractères.` })
    if (next !== confirm) return setMessage({ kind: 'error', text: 'Les deux nouveaux mots de passe ne correspondent pas.' })
    setBusy(true)
    setMessage(null)
    try {
      await adminApi.changePassword(current, next)
      setCurrent('')
      setNext('')
      setConfirm('')
      setMessage({ kind: 'ok', text: 'Mot de passe modifié.' })
    } catch (err) {
      if (err instanceof Unauthorized) logout()
      else setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Erreur' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-560 px-16 py-20 md:px-24 md:py-28">
      <h1 className="fs-22 font-bold">Mon compte</h1>
      <p className="mt-6 fs-14 text-[#5a5050]">
        {me.name} · {me.email} · {me.role === 'owner' ? 'Propriétaire' : 'Agent'}
      </p>

      <form onSubmit={submit} className="mt-24 r-14 border border-[#ece2dd] bg-white p-18 md:p-24">
        <h2 className="fs-16 font-bold">Changer mon mot de passe</h2>
        <div className="mt-14 space-y-12">
          <div>
            <FieldLabel htmlFor="cur">Mot de passe actuel</FieldLabel>
            <input id="cur" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} className={inputClass} />
          </div>
          <div>
            <FieldLabel htmlFor="new">Nouveau mot de passe ({MIN} caractères minimum)</FieldLabel>
            <input id="new" type="password" autoComplete="new-password" required minLength={MIN} value={next} onChange={(e) => setNext(e.target.value)} className={inputClass} />
          </div>
          <div>
            <FieldLabel htmlFor="conf">Confirmer le nouveau mot de passe</FieldLabel>
            <input id="conf" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} className={inputClass} />
          </div>
        </div>
        {message && (
          <p role={message.kind === 'error' ? 'alert' : 'status'} className={`mt-12 fs-13 ${message.kind === 'error' ? 'text-[#a12a2a]' : 'text-[#1f6a3c]'}`}>
            {message.text}
          </p>
        )}
        <BusyButton type="submit" busy={busy} className="mt-16 w-full md:w-auto">
          Changer le mot de passe
        </BusyButton>
      </form>

      <BusyButton variant="secondary" className="mt-20 w-full md:w-auto" onClick={() => adminApi.logout().finally(logout)}>
        Se déconnecter
      </BusyButton>
    </div>
  )
}
