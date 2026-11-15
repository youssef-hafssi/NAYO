import type { MouseEvent } from 'react'

/** "Acheter maintenant" → the express form on this page (smooth unless reduced motion), cursor in the first field.
 *  Falls back to the plain #commander link when the form isn't on the page. */
export function goToOrderForm(e: MouseEvent<HTMLAnchorElement>) {
  const form = document.getElementById('commander')
  if (!form) return
  e.preventDefault()
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  form.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
  window.setTimeout(() => document.getElementById('x-name')?.focus({ preventScroll: true }), reduce ? 0 : 600)
  history.replaceState(null, '', '#commander')
}
