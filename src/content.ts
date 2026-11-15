export const PRODUCT = {
  name: 'NAYO® Déodorant',
  price: 189,
  shipping: 20,
  currency: 'MAD',
  image: '/assets/nayo-deodorant.png',
} as const

export const ORDER_PATH = '/commande'

/*
 * Avis — ONLY real reviews, copied word for word from what clients sent (admin → Clients → tag "Avis"), with their
 * agreement. Never write or edit a review, never invent a rating. While the list is empty the section shows
 * BRAND_POINTS instead (the brand speaking: no quote marks, no names, no stars). The first 3 entries are shown.
 */
export type Review = {
  text: string // the client's words, unchanged
  author: string // first name or initial, e.g. "Salma" or "S."
  city: string // e.g. "Agadir" (may be "")
  lang: 'fr' | 'darija' | 'ar' | 'en' // 'ar' is shown right-to-left
  rating: 1 | 2 | 3 | 4 | 5 // the stars SHE gave (ask her "Combien d'étoiles sur 5 ?"): never a default
  /** Optional photo she sent, FACE ALREADY BLURRED, saved in public/assets/reviews/ (e.g. '/assets/reviews/salma.webp').
   *  Once one review has a photo, the big standalone selfie next to the cards is no longer shown. */
  photo?: string
  photoAlt?: string // e.g. "Photo envoyée par Salma (visage flouté)"
}
export const SHOW_REVIEWS = true
export const REVIEWS: Review[] = []

export const BRAND_POINTS = [
  {
    title: 'Un teint plus clair, progressivement',
    text: 'Les enzymes de fruits exfolient la peau en douceur : jour après jour, le teint des aisselles s’éclaircit et s’unifie.',
  },
  { title: 'Douce pour la peau', text: 'Une exfoliation tout en douceur, pensée pour un usage quotidien.' },
  { title: 'Fraîcheur toute la journée', text: 'Une sensation de fraîcheur du matin au soir.' },
] as const

// DRAFT ANSWERS — to be confirmed by the brand before launch (claims about results and formula).
export const FAQ = [
  {
    q: "Combien de temps dure l'éclaircissement ?",
    a: "Les premiers résultats apparaissent généralement après quelques semaines d'utilisation quotidienne. Appliquez NAYO matin et soir sur une peau propre et sèche pour un résultat progressif et durable.",
  },
  {
    q: 'Convient-il aux peaux sensibles ?',
    a: "Oui. Sa formule douce et non irritante a été pensée pour un usage quotidien, y compris sur les peaux sensibles. Évitez de l'appliquer juste après l'épilation ou sur une peau lésée.",
  },
  {
    q: "Quels sont les ingrédients ?",
    a: "NAYO contient un Super Fruit Enzyme Triple Blend et de l'acide citrique, qui exfolient la peau en douceur. La liste complète des ingrédients figure sur l'emballage. Pour toute question sur la composition, contactez-nous avant de commander : nous vous répondrons rapidement.",
  },
] as const
