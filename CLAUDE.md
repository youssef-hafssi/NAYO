# NAYO — project context

Pixel-accurate recreation of two approved designs (landing + checkout) for the NAYO deodorant. French, Morocco, cash on delivery only.

## Status
- Landing page (`/`): built and screenshot-matched to the reference at 1024px.
- Checkout (`/commande`): built and screenshot-matched to the reference at 1536px.
- Hero = `hero-bg.jpg` (burgundy silk backdrop) + `model.webp` (owner-supplied cutout, full elbow visible) as two depth layers.
- Order flow: submit → POST `VITE_ORDER_ENDPOINT` (the bot's `/orders`, waits ≤10 s, button shows "Envoi en cours…") → bot returns `NAYO-1001`-style number. On timeout/error: fallback `NAYO-W123456`, order saved in localStorage and re-sent on the success screen + every page load (`src/lib/orders.ts`). Checkout pings `/health` on load to wake the sleeping free host.
- Success screen: "Dernière étape : confirmez sur WhatsApp" + burgundy pill linking to `wa.me/VITE_WHATSAPP_NUMBER` with "Bonjour NAYO, je confirme ma commande {n} – {total} MAD – {name}". No automatic WhatsApp opening. Consent line under the checkout button (absolute at lg so the approved layout doesn't move).
- WhatsApp bot (Python, FastAPI) lives in `bot/` — see `bot/README.md`. Python decides statuses/totals; the AI only classifies + phrases. State in Postgres (Supabase) in production, never local disk.
- Never put an `opacity` CSS transition on an element GSAP fades in (`data-anim`): it leaves the element stuck invisible.

## Priority order (do not break)
1. Product appearance stays identical (use `public/assets/nayo-deodorant.png`, never a generated/substituted product).
2. The approved screenshots are the visual authority — no redesign, no new sections, no palette or typography changes.
3. Spline only for subtle 3D, and only if it matches the product exactly; otherwise the PNG.
4. GSAP for animations; every animation must end on the approved layout and respect prefers-reduced-motion.

## Sizing system
- Checkout: `.checkout-scale` redefines `--spacing` at lg so 1 unit = 1px of the 1536px checkout design. Use `r-*` / `rt-*` for radii (they follow the local scale).
- Reference width is 1024px. Tailwind `--spacing` = 1 design px, so `w-182` = 182px, `fs-16.5` = font-size 16.5px, `lh-22` = line-height 22px (custom utilities in `src/index.css`).
- At ≥1024px the root font-size scales with the viewport so the 1024px design takes 75% of the width (`clamp(16px, 1.171875vw, 30px)`, approved by the owner at 75% zoom); content stays centred in `max-w-1024` columns, section backgrounds stay full-bleed.
- `md:` = tablet layout, base = mobile layout. `lg:` classes carry the pixel-matched desktop values — change them only after comparing against the reference screenshot.
- `.serif-tight` lives in `@layer components` so Tailwind utilities (tracking, weight) can override it.

## Fonts / colours
- Serif: Fraunces Variable. Sans: Figtree Variable (both via @fontsource).
- Colours are theme tokens in `src/index.css` (`wine-*`, `ivory`, `ink`, `star`, `rose`).

## Checkout spec
- Centered NAYO logo, "Commande à la livraison" divider, "Finalisez votre commande", two-column layout.
- ONLY two fields: Nom complet, Numéro de téléphone. No address, no payment selector, no account.
- Burgundy order summary card: product PNG, "NAYO® Déodorant", quantity stepper (− 1 +, 1–10), 189 MAD × qty; Sous-total = 189 × qty; Frais de livraison 20 MAD (flat); Total = sous-total + 20.
- Checkout desktop scale: the 1536px design takes 75% of the viewport width (`.checkout-scale` in `src/index.css`), as the owner approved at 75% browser zoom.
- Large burgundy "Commander maintenant" button, 3 trust items, burgundy silk decoration bottom-right.
- Prices come from `PRODUCT` in `src/content.ts`.

## Content to confirm with the owner
- FAQ answers in `src/content.ts` are drafts. Do not add claims about the formula (e.g. aluminium-free) unless the owner confirms them.
- No product weight, no variants, no extra product names.
