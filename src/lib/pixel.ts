/*
 * Meta Pixel (browser side). The bot sends the same Purchase through the Conversions API with the same event_id
 * ("purchase-<clientId>"), so Meta counts each order once.
 *
 * - Loads only when VITE_META_PIXEL_ID is set, and never on /admin.
 * - The script is loaded after the page has rendered; events fired before that are queued by the standard stub.
 * - Nothing personal is sent from the browser: names, phones and addresses only go to the bot, which hashes them.
 */

type Fbq = ((...args: unknown[]) => void) & { callMethod?: (...a: unknown[]) => void; queue: unknown[]; loaded?: boolean; version?: string; push?: unknown }

declare global {
  interface Window {
    fbq?: Fbq
    _fbq?: Fbq
  }
}

const PIXEL_ID = ((import.meta.env.VITE_META_PIXEL_ID as string | undefined) ?? '').replace(/\D/g, '')

const enabled = () => !!PIXEL_ID && typeof window !== 'undefined' && !window.location.pathname.startsWith('/admin')

let started = false

/** Standard Meta stub (queues calls) + the script, loaded once. */
function start() {
  if (started || !enabled()) return
  started = true
  if (!window.fbq) {
    const q: Fbq = Object.assign(
      function (...args: unknown[]) {
        if (q.callMethod) q.callMethod(...args)
        else q.queue.push(args)
      },
      { queue: [] as unknown[], loaded: true, version: '2.0' },
    )
    q.push = q
    window.fbq = q
    window._fbq = q
  }
  const load = () => {
    const s = document.createElement('script')
    s.async = true
    s.src = 'https://connect.facebook.net/en_US/fbevents.js'
    document.head.appendChild(s)
  }
  // Don't compete with the hero for bandwidth: the script comes once the page is idle (events are queued meanwhile).
  const idle = (window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }).requestIdleCallback
  if (idle) idle(load, { timeout: 2500 })
  else window.setTimeout(load, 1200)
  window.fbq!('init', PIXEL_ID)
}

export function track(event: string, params?: Record<string, unknown>, eventId?: string) {
  if (!enabled()) return
  start()
  window.fbq!('track', event, params ?? {}, eventId ? { eventID: eventId } : undefined)
}

const once = new Set<string>()
/** Fire an event at most once per page view (e.g. InitiateCheckout on the first field touched). */
export function trackOnce(event: string, params?: Record<string, unknown>) {
  if (once.has(event)) return
  once.add(event)
  track(event, params)
}

export function pageView() {
  once.clear()
  track('PageView')
}

export const PRODUCT_EVENT = { content_type: 'product', content_ids: ['nayo-deodorant'], currency: 'MAD' } as const

function cookie(name: string): string {
  const m = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`))
  return m ? decodeURIComponent(m[1]) : ''
}

/** Sent with the order so the bot's Conversions API event matches this browser (all optional, length-capped). */
export function metaOrderFields(): { fbp?: string; fbc?: string; pageUrl?: string } {
  if (!PIXEL_ID) return {}
  let fbc = cookie('_fbc')
  if (!fbc) {
    // Arrived from an ad but the Pixel hasn't written its cookie yet: build it the way Meta does.
    const clickId = new URLSearchParams(window.location.search).get('fbclid')
    if (clickId) fbc = `fb.1.${Date.now()}.${clickId}`
  }
  const fbp = cookie('_fbp')
  const pageUrl = window.location.href
  return {
    ...(fbp && fbp.length <= 200 ? { fbp } : {}),
    ...(fbc && fbc.length <= 500 ? { fbc } : {}),
    ...(pageUrl.length <= 900 ? { pageUrl } : { pageUrl: window.location.origin + window.location.pathname }),
  }
}
