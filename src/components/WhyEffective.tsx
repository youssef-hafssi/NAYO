/* "Pourquoi NAYO est efficace ?" — the owner's infographic. The title is part of the image, so the heading is for
   screen readers only; the alt text carries all the words in the image. */

export function WhyEffective() {
  return (
    <section id="efficace" aria-labelledby="why-title" className="scroll-mt-80 bg-ivory">
      <div className="mx-auto w-full max-w-1024 px-16 pb-28 md:px-24 md:pb-36">
        <h2 id="why-title" className="sr-only">
          Pourquoi NAYO est efficace ?
        </h2>
        <figure data-anim="reveal-photo" className="overflow-hidden rounded-16 bg-[#efe3dc] shadow-[0_10px_30px_rgba(70,5,15,0.10)]">
          <img
            src="/assets/nayo-pourquoi-800.webp"
            srcSet="/assets/nayo-pourquoi-800.webp 800w, /assets/nayo-pourquoi-1600.webp 1600w"
            sizes="(min-width: 1024px) 976px, 100vw"
            alt="Pourquoi NAYO est efficace ? Une formule douce mais efficace. Superfruit Enzyme Triple Blend : un complexe enzymatique de fruits qui aide à unifier le teint et à atténuer les taches. Acide citrique : aide à rééquilibrer le pH de la peau et à révéler un teint plus uniforme. Formule approuvée par la DMP (Direction des Médicaments et de la Pharmacie), conforme aux normes de sécurité et de qualité en vigueur. Le déodorant NAYO Velvet Rose posé à côté d'une rose rouge."
            loading="lazy"
            width={1672}
            height={941}
            className="block h-auto w-full"
          />
        </figure>
      </div>
    </section>
  )
}
