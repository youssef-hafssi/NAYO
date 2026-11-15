import { PRODUCT } from '../content'

/* Shared by /commande and the express checkout on the landing page: same rules, same WhatsApp message. */

export const fmt = (n: number) => `${n} ${PRODUCT.currency}`
export const MAX_QTY = 10

// Business WhatsApp number, international format digits only (e.g. 212612345678).
export const WHATSAPP_NUMBER = ((import.meta.env.VITE_WHATSAPP_NUMBER as string | undefined) ?? '').replace(/\D/g, '')

// Pre-filled message the client sends us: they open the conversation, so our replies are free (24h window).
export const whatsappUrl = (orderNumber: string, total: number, name: string) =>
  `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(
    `Bonjour NAYO, je confirme ma commande ${orderNumber} – ${total} MAD – ${name}`,
  )}`

// Moroccan mobile/landline: 05/06/07 + 8 digits, or +212 / 00212 prefix.
export const normalizePhone = (v: string) => v.replace(/[\s.-]/g, '').replace(/^(\+|00)212/, '0')
export const isValidPhone = (v: string) => /^0[5-7]\d{8}$/.test(normalizePhone(v))

/** Same limits as the bot (/orders validates them again server-side). */
export const ADDRESS_MIN = 5
export const ADDRESS_MAX = 200
