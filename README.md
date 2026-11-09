# NAYO — landing page + checkout

React + TypeScript + Tailwind v4 + GSAP. Checkout (`/commande`) is a stub until the landing page is approved.

```bash
npm install
npm run dev      # http://localhost:5173
npm run build
```

## How fidelity is held
- The reference is 1024px wide. In Tailwind, `--spacing` is set so **1 unit = 1 design px** (`w-182`, `fs-16.5`, `lh-22`).
- At ≥1024px the root font-size scales with the viewport (capped at 1440px), so desktop keeps the exact reference proportions.
- Below 1024px, tablet (`md:`) and mobile layouts reflow while keeping section order and identity.
- Photography, avatars and the wordmark are taken from the supplied references/product PNG; text, buttons, icons, arrows and labels are live HTML/SVG.

## Content to confirm
- `src/content.ts` → FAQ answers are drafts (the aluminium answer intentionally makes no formula claim).
