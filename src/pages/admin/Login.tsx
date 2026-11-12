import { useState, type FormEvent } from 'react'
import { adminApi } from '../../lib/adminApi'
import { WINE } from './ui'

// ------------------------------------------------------------------ login
export default function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await adminApi.login(email, password)
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connexion impossible.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="grid min-h-screen place-items-center bg-[#f8f4f1] px-16">
      <form onSubmit={submit} className="w-full max-w-380 r-16 border border-[#ece2dd] bg-white p-32 shadow-[0_10px_30px_rgba(58,10,16,0.06)]">
        <div className="font-serif fs-24 font-semibold tracking-[0.22em]" style={{ color: WINE }}>
          NAYO
        </div>
        <h1 className="mt-6 fs-15 text-[#1f1f1f]">Boîte de réception — connexion</h1>
        <label className="mt-24 block fs-12 font-semibold uppercase tracking-[0.06em] text-[#8a8a8a]" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-6 h-42 w-full r-10 border border-[#ecdcd6] bg-[#fbf5f2] px-14 fs-14 outline-none focus:border-[#7a1a2a]"
        />
        <label className="mt-16 block fs-12 font-semibold uppercase tracking-[0.06em] text-[#8a8a8a]" htmlFor="pw">
          Mot de passe
        </label>
        <input
          id="pw"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-6 h-42 w-full r-10 border border-[#ecdcd6] bg-[#fbf5f2] px-14 fs-14 outline-none focus:border-[#7a1a2a]"
        />
        {error && (
          <p role="alert" className="mt-12 fs-13 text-[#b4233a]">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="mt-22 h-44 w-full rounded-pill fs-14.5 font-semibold text-white disabled:cursor-wait"
          style={{ background: WINE }}
        >
          {busy ? 'Connexion…' : 'Se connecter'}
        </button>
      </form>
    </div>
  )
}
