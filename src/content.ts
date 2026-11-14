export const PRODUCT = {
  name: 'NAYO® Déodorant',
  price: 189,
  shipping: 20,
  currency: 'MAD',
  image: '/assets/nayo-deodorant.png',
} as const

export const ORDER_PATH = '/commande'

/*
 * Customer reviews: hidden until real ones are collected (the bot asks 3 days after delivery and stores the
 * replies in the admin, under Clients → "Avis"). To show them: add real, approved reviews here and set
 * SHOW_REVIEWS to true. Never invent reviews.
 */
export type Review = { quote: string; lines: [string, string]; name: string; avatar?: string }
export const SHOW_REVIEWS = false
export const REVIEWS: Review[] = []

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
    q: "Contient-il de l'aluminium ?",
    a: "NAYO contient un Super Fruit Enzyme Triple Blend et de l'acide citrique, qui exfolient la peau en douceur. La liste complète des ingrédients figure sur l'emballage. Pour toute question sur la composition, contactez-nous avant de commander : nous vous répondrons rapidement.",
  },
] as const
