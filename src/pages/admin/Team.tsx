import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Copy, KeyRound } from 'lucide-react'
import { adminApi, Unauthorized, type AuditRow, type Member, type Role } from '../../lib/adminApi'
import { useAuth } from './AdminApp'
import { Banner, BusyButton, Chip, FieldLabel, fmtDateTime, inputClass, Pill, Skeleton } from './ui'

/*
 * Équipe (owner only, server-enforced): members (add, role, disable / enable — never delete —, reset password,
 * last seen) and the audit log viewer. A temporary password is shown once and only kept in this component's state.
 */

type Tab = 'members' | 'audit'
type Msg = { kind: 'ok' | 'error'; text: string } | null

const ROLE_LABEL: Record<Role, string> = { owner: 'Propriétaire', agent: 'Agent' }

const ACTION_LABEL: Record<string, string> = {
  'order.status': 'Statut de commande',
  'order.edit': 'Commande modifiée',
  'order.create': 'Commande créée',
  'order.cleanup': 'Nettoyage (tests)',
  'orders.export': 'Export des commandes',
  'conversation.takeover': 'Conversation reprise',
  'conversation.release': 'Conversation rendue au bot',
  'conversation.note': 'Note de conversation',
  'customer.edit': 'Fiche client modifiée',
  'customers.export': 'Export des clients',
  'task.create': 'Relance créée',
  'task.edit': 'Relance modifiée',
  'task.done': 'Relance faite',
  'task.dismiss': 'Suggestion ignorée',
  'password.change': 'Mot de passe changé',
  'team.create': 'Membre ajouté',
  'team.edit': 'Membre modifié',
  'team.disable': 'Membre désactivé',
  'team.enable': 'Membre réactivé',
  'team.reset_password': 'Mot de passe réinitialisé',
  'settings.edit': 'Réglage modifié',
  'stock.reset': 'Stock remis à zéro',
  'report.export': 'Export de rapport',
  'finance.export': 'Export finance',
}

const ago = (ts: number | null) => {
  if (!ts) return 'jamais'
  const s = Date.now() / 1000 - ts
  if (s < 90) return 'en ligne'
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`
  return fmtDateTime(ts)
}

export default function Team() {
  const { me, logout } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab: Tab = params.get('tab') === 'audit' ? 'audit' : 'members'
  const [message, setMessage] = useState<Msg>(null)
  const fail = useCallback(
    (e: unknown) => (e instanceof Unauthorized ? logout() : setMessage({ kind: 'error', text: e instanceof Error ? e.message : 'Erreur' })),
    [logout],
  )

  if (me.role !== 'owner')
    return (
      <div className="mx-auto w-full max-w-960 px-16 py-16 md:px-24 md:py-24">
        <h1 className="fs-22 font-bold">Équipe</h1>
        <p className="mt-12 fs-14 text-[#6b6b6b]">Réservé au propriétaire.</p>
      </div>
    )

  return (
    <div className="mx-auto w-full max-w-960 px-16 py-16 md:px-24 md:py-24">
      <h1 className="fs-22 font-bold">Équipe</h1>
      <div className="mt-12 flex flex-wrap gap-8">
        <Chip active={tab === 'members'} onClick={() => (setMessage(null), setParams({}))}>
          Membres
        </Chip>
        <Chip active={tab === 'audit'} onClick={() => (setMessage(null), setParams({ tab: 'audit' }))}>
          Journal des actions
        </Chip>
      </div>
      <Banner msg={message} />
      {tab === 'members' ? <Members fail={fail} setMessage={setMessage} /> : <Audit fail={fail} />}
    </div>
  )
}

/* ------------------------------------------------------------------ members */

function Members({ fail, setMessage }: { fail: (e: unknown) => void; setMessage: (m: Msg) => void }) {
  const [data, setData] = useState(() => adminApi.members().peek() ?? null)
  const [secret, setSecret] = useState<{ who: string; password: string } | null>(null)
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [form, setForm] = useState({ email: '', name: '', role: 'agent' as Role })

  const load = useCallback(() => adminApi.members().then(setData).catch(fail), [fail])
  useEffect(() => {
    load()
  }, [load])

  const act = async (id: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(id)
    setMessage(null)
    try {
      await fn()
      await load()
      setMessage({ kind: 'ok', text: ok })
    } catch (e) {
      fail(e)
    } finally {
      setBusy(null)
    }
  }

  const add = async (e: FormEvent) => {
    e.preventDefault()
    setBusy('add')
    setMessage(null)
    try {
      const r = await adminApi.addMember({ email: form.email.trim(), name: form.name.trim(), role: form.role })
      setSecret({ who: `${r.member.name} (${r.member.email})`, password: r.temporary_password })
      setForm({ email: '', name: '', role: 'agent' })
      setAdding(false)
      await load()
    } catch (err) {
      fail(err)
    } finally {
      setBusy(null)
    }
  }

  const reset = async (m: Member) => {
    if (!window.confirm(`Réinitialiser le mot de passe de ${m.name} ? Ses sessions ouvertes seront fermées.`)) return
    setBusy(`r:${m.id}`)
    setMessage(null)
    try {
      const r = await adminApi.resetMemberPassword(m.id)
      setSecret({ who: `${m.name} (${m.email})`, password: r.temporary_password })
    } catch (e) {
      fail(e)
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      {secret && (
        <section role="status" className="mt-14 r-14 border-2 border-[#3a0a10] bg-[#fbf5f2] p-16">
          <p className="flex items-center gap-8 fs-14 font-bold">
            <KeyRound className="size-18" aria-hidden /> Mot de passe temporaire de {secret.who}
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-10">
            <code className="r-8 bg-white px-12 py-8 fs-18 font-semibold tracking-[0.08em]">{secret.password}</code>
            <BusyButton
              type="button"
              variant="secondary"
              onClick={() => navigator.clipboard?.writeText(secret.password).then(() => setMessage({ kind: 'ok', text: 'Copié.' }))}
            >
              <Copy className="size-16" aria-hidden /> Copier
            </BusyButton>
          </div>
          <p className="mt-8 fs-13 text-[#6b6b6b]">
            Il ne sera plus affiché. Transmettez-le à la personne ; elle le change dans « Plus → Mon compte » à sa première connexion.
          </p>
          <BusyButton type="button" className="mt-10" onClick={() => setSecret(null)}>
            C'est noté
          </BusyButton>
        </section>
      )}

      <div className="mt-14 flex justify-end">
        <BusyButton type="button" onClick={() => setAdding((v) => !v)}>
          Ajouter un membre
        </BusyButton>
      </div>
      {adding && (
        <form onSubmit={add} className="mt-10 grid gap-10 r-14 border border-[#ece2dd] bg-white p-14 md:grid-cols-[1fr_1fr_180px_auto] md:items-end">
          <div>
            <FieldLabel htmlFor="m-name">Nom</FieldLabel>
            <input id="m-name" required minLength={2} maxLength={80} className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div>
            <FieldLabel htmlFor="m-email">Email</FieldLabel>
            <input id="m-email" type="email" required maxLength={200} className={inputClass} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
          <div>
            <FieldLabel htmlFor="m-role">Rôle</FieldLabel>
            <select id="m-role" className={inputClass} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              <option value="agent">Agent</option>
              <option value="owner">Propriétaire</option>
            </select>
          </div>
          <BusyButton type="submit" busy={busy === 'add'}>
            Créer
          </BusyButton>
          <p className="fs-12.5 text-[#8a8a8a] md:col-span-4">
            Agent : inbox, commandes, clients, relances, livraisons, stock (lecture). Propriétaire : tout, y compris l'argent, les achats, les réglages et l'équipe.
          </p>
        </form>
      )}

      {!data ? (
        <Skeleton className="mt-14" rows={3} />
      ) : (
        <ul className="mt-14 divide-y divide-[#f4eeeb] r-14 border border-[#ece2dd] bg-white">
          {data.items.map((m) => {
            const self = m.id === data.me
            return (
              <li key={m.id} className={`flex flex-wrap items-center gap-x-12 gap-y-8 px-14 py-12 ${m.active ? '' : 'bg-[#faf8f7]'}`}>
                <div className="min-w-0 flex-1 basis-220">
                  <p className={`fs-14 font-semibold ${m.active ? '' : 'text-[#8a8a8a]'}`}>
                    {m.name} {self && <span className="fs-12 font-normal text-[#8a8a8a]">(vous)</span>}
                  </p>
                  <p className="truncate fs-12.5 text-[#8a8a8a]">
                    {m.email} · {m.active ? `vu ${ago(m.last_seen_at)}` : 'désactivé'}
                  </p>
                </div>
                {!m.active && <Pill className="bg-[#efefef] text-[#6b6b6b]">Désactivé</Pill>}
                <label className="sr-only" htmlFor={`role-${m.id}`}>
                  Rôle de {m.name}
                </label>
                <select
                  id={`role-${m.id}`}
                  disabled={self || busy !== null}
                  value={m.role}
                  onChange={(e) =>
                    act(`role:${m.id}`, () => adminApi.editMember(m.id, { role: e.target.value as Role }), `${m.name} est maintenant ${ROLE_LABEL[e.target.value as Role].toLowerCase()}.`)
                  }
                  className="h-40 r-10 border border-[#ecdcd6] bg-[#fbf5f2] px-10 fs-14 disabled:opacity-60"
                >
                  <option value="agent">Agent</option>
                  <option value="owner">Propriétaire</option>
                </select>
                {!self && (
                  <>
                    <BusyButton type="button" variant="secondary" busy={busy === `r:${m.id}`} disabled={!m.active} onClick={() => reset(m)}>
                      Réinitialiser le mot de passe
                    </BusyButton>
                    <BusyButton
                      type="button"
                      variant={m.active ? 'danger' : 'secondary'}
                      busy={busy === `a:${m.id}`}
                      onClick={() => {
                        if (m.active && !window.confirm(`Désactiver ${m.name} ? Ses sessions ouvertes seront fermées immédiatement.`)) return
                        act(`a:${m.id}`, () => adminApi.editMember(m.id, { active: !m.active }), m.active ? `${m.name} est désactivé.` : `${m.name} est réactivé.`)
                      }}
                    >
                      {m.active ? 'Désactiver' : 'Réactiver'}
                    </BusyButton>
                  </>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}

/* ------------------------------------------------------------------ audit log */

function Audit({ fail }: { fail: (e: unknown) => void }) {
  const [facets, setFacets] = useState(() => adminApi.auditFacets().peek() ?? { admins: [], entities: [] })
  const [f, setF] = useState({ admin_name: '', entity: '', frm: '', to: '' })
  const [list, setList] = useState(() => adminApi.audit({}).peek() ?? null)
  const [more, setMore] = useState(false)
  const key = JSON.stringify(f)
  const datesOk = !f.frm || !f.to || f.frm <= f.to

  useEffect(() => {
    adminApi
      .auditFacets()
      .then(setFacets)
      .catch(() => undefined)
  }, [])
  useEffect(() => {
    if (!datesOk) return
    let live = true
    const q = adminApi.audit(JSON.parse(key))
    setList(q.peek() ?? null)
    q.then((r) => live && setList(r)).catch((e) => live && fail(e))
    return () => {
      live = false
    }
  }, [key, datesOk, fail])

  const loadMore = async () => {
    if (!list) return
    setMore(true)
    try {
      const r = await adminApi.audit(f, list.items.length)
      setList({ items: [...list.items, ...r.items], has_more: r.has_more })
    } catch (e) {
      fail(e)
    } finally {
      setMore(false)
    }
  }

  return (
    <>
      <section aria-label="Filtres" className="mt-14 grid grid-cols-2 gap-10 r-14 border border-[#ece2dd] bg-white p-14 md:grid-cols-4">
        <div>
          <FieldLabel htmlFor="a-who">Membre</FieldLabel>
          <select id="a-who" className={inputClass} value={f.admin_name} onChange={(e) => setF({ ...f, admin_name: e.target.value })}>
            <option value="">Tous</option>
            {facets.admins.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
        <div>
          <FieldLabel htmlFor="a-entity">Élément</FieldLabel>
          <select id="a-entity" className={inputClass} value={f.entity} onChange={(e) => setF({ ...f, entity: e.target.value })}>
            <option value="">Tous</option>
            {facets.entities.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
        <div>
          <FieldLabel htmlFor="a-from">Du</FieldLabel>
          <input id="a-from" type="date" className={inputClass} value={f.frm} onChange={(e) => setF({ ...f, frm: e.target.value })} />
        </div>
        <div>
          <FieldLabel htmlFor="a-to">Au</FieldLabel>
          <input id="a-to" type="date" className={inputClass} value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} />
        </div>
        {!datesOk && <p className="col-span-2 fs-13 text-[#a12a2a] md:col-span-4">La date de début doit précéder la date de fin.</p>}
      </section>

      {!list ? (
        <Skeleton className="mt-14" />
      ) : list.items.length === 0 ? (
        <p className="mt-14 fs-14 text-[#8a8a8a]">Aucune action pour ces filtres.</p>
      ) : (
        <ul className="mt-14 divide-y divide-[#f4eeeb] r-14 border border-[#ece2dd] bg-white">
          {list.items.map((a, i) => (
            <li key={`${a.at}-${i}`} className="grid gap-x-12 gap-y-2 px-14 py-10 md:grid-cols-[150px_120px_1fr]">
              <span className="fs-12.5 text-[#8a8a8a] tabular-nums">{fmtDateTime(a.at)}</span>
              <span className="fs-13 font-semibold">{a.admin_name}</span>
              <span className="min-w-0 fs-13">
                {ACTION_LABEL[a.action] ?? a.action}
                {a.entity_id && <span className="text-[#6b6b6b]"> · {entityLabel(a)}</span>}
                {a.details && <span className="block break-words fs-12.5 text-[#6b6b6b]">{a.details}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {list?.has_more && (
        <div className="mt-12 text-center">
          <BusyButton type="button" variant="secondary" busy={more} onClick={loadMore}>
            Voir plus
          </BusyButton>
        </div>
      )}
    </>
  )
}

function entityLabel(a: AuditRow) {
  // Member ids are long random strings: not useful to read.
  return a.entity === 'admin_user' ? 'membre' : a.entity_id
}
