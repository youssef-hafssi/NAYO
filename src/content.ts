export const PRODUCT = {
  name: 'NAYO® Déodorant',
  price: 189,
  shipping: 20,
  currency: 'MAD',
  image: '/assets/nayo-deodorant.png',
} as const

export const ORDER_PATH = '/commande'

export const REVIEWS = [
  {
    quote: 'Mes aisselles sont visiblement plus claires après quelques semaines.',
    lines: ['Mes aisselles sont visiblement', 'plus claires après quelques semaines.'],
    name: 'Yassine M.',
    avatar: '/assets/av-yassine.jpg',
  },
  {
    quote: 'Douce sur la peau et vraiment bien tolérée.',
    lines: ['Douce sur la peau et vraiment', 'bien tolérée.'],
    name: 'Salma K.',
    avatar: '/assets/av-salma.jpg',
  },
  {
    quote: 'Je le recommande, simple et très efficace.',
    lines: ['Je le recommande, simple', 'et très efficace.'],
    name: 'Imane R.',
    avatar: '/assets/av-imane.jpg',
  },
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
    q: "Contient-il de l'aluminium ?",
    a: "La liste complète des ingrédients figure sur l'emballage. Pour toute question sur la composition, contactez-nous avant de commander : nous vous répondrons rapidement.",
  },
] as const
