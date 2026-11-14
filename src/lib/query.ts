import { useEffect, useState } from 'react'

/*
 * Admin data cache (memory only, per session — cleared on logout / 401).
 *
 * Every admin GET returns a Query: it awaits like a Promise (so existing code keeps `await adminApi.x()`), and it
 * also carries its cache `key` (the request path), so a page can show the last data for that key instantly while
 * the same request refreshes it in the background (stale-while-revalidate). Identical requests in flight are shared:
 * a hover prefetch, the route-change prefetch and the page's own request make ONE network call.
 */

type Entry = { data?: unknown; at: number; seq: number; promise?: Promise<unknown>; epoch?: number }

const store = new Map<string, Entry>()
const listeners = new Map<string, Set<() => void>>()
const FRESH_MS = 3000 // a prefetch doesn't repeat a request made less than 3 s ago

/* Every write (POST / PATCH / DELETE) bumps the epoch: a GET started before a write is never reused after it,
   so "save, then reload" always shows the saved data. */
let epoch = 0
let seq = 0
export function bumpEpoch() {
  epoch += 1
}

function notify(key: string) {
  listeners.get(key)?.forEach((fn) => fn())
}

export class Query<T> implements PromiseLike<T> {
  constructor(
    readonly key: string,
    private readonly fetcher: () => Promise<T>,
  ) {}

  /** The network request, shared with any identical one in flight; the result is cached. */
  run(force = true): Promise<T> {
    const e = store.get(this.key)
    if (e?.promise && e.epoch === epoch) return e.promise as Promise<T>
    if (!force && e && e.data !== undefined && Date.now() - e.at < FRESH_MS) return Promise.resolve(e.data as T)
    const mySeq = ++seq
    const p: Promise<T> = this.fetcher().then(
      (data) => {
        const cur = store.get(this.key)
        // An older request finishing after a newer one never overwrites the newer data.
        if (!cur || cur.seq <= mySeq) {
          store.set(this.key, { data, at: Date.now(), seq: mySeq, ...(cur?.promise && cur.promise !== p ? { promise: cur.promise, epoch: cur.epoch } : {}) })
          notify(this.key)
        } else if (cur.promise === p) store.set(this.key, { ...cur, promise: undefined })
        return data
      },
      (err) => {
        const cur = store.get(this.key)
        if (cur?.promise === p) store.set(this.key, { ...cur, promise: undefined })
        throw err
      },
    )
    store.set(this.key, { data: e?.data, at: e?.at ?? 0, seq: e?.seq ?? 0, promise: p, epoch })
    return p
  }

  /** Last data for this request, if any (no network). */
  peek(): T | undefined {
    return store.get(this.key)?.data as T | undefined
  }

  /** Warm the cache (hover, route change): skipped when the data is a few seconds old. */
  prefetch(): void {
    this.run(false).catch(() => undefined)
  }

  then<A = T, B = never>(ok?: ((v: T) => A | PromiseLike<A>) | null, ko?: ((e: unknown) => B | PromiseLike<B>) | null): Promise<A | B> {
    return this.run().then(ok, ko)
  }
  catch<B = never>(ko?: ((e: unknown) => B | PromiseLike<B>) | null): Promise<T | B> {
    return this.run().catch(ko)
  }
  finally(fn?: (() => void) | null): Promise<T> {
    return this.run().finally(fn)
  }
}

/** Forget everything (logout, 401, another user logging in). */
export function clearCache() {
  store.clear()
  listeners.forEach((set) => set.forEach((fn) => fn()))
}

/** Keeps `data` in sync with a key's cache entry (background refreshes made elsewhere included). */
export function useCached<T>(query: Query<T> | null): T | undefined {
  const key = query?.key ?? null
  const [data, setData] = useState<T | undefined>(() => query?.peek())
  useEffect(() => {
    if (!key) return
    setData(store.get(key)?.data as T | undefined)
    const fn = () => setData(store.get(key)?.data as T | undefined)
    let set = listeners.get(key)
    if (!set) listeners.set(key, (set = new Set()))
    set.add(fn)
    return () => {
      set!.delete(fn)
    }
  }, [key])
  return data
}
