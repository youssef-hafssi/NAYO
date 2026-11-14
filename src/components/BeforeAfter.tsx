/* Before / after (owner-supplied, illustrative). The "Semaine" labels are part of the images. */

const PHOTOS = [
  { src: 'semaine-1', alt: 'Aisselle en semaine 1 d’utilisation de NAYO' },
  { src: 'semaine-4', alt: 'Aisselle en semaine 4 d’utilisation de NAYO' },
]

export function BeforeAfter() {
  return (
    <section aria-labelledby="ba-title" className="bg-ivory">
      <div className="mx-auto w-full max-w-1024 px-16 py-28 md:px-24 md:py-36">
        <h2 id="ba-title" data-anim="reveal" className="serif-tight text-center fs-28 lh-34 text-ink-title md:fs-32 md:lh-38">
          Semaine après semaine
        </h2>
        <div className="mx-auto mt-18 grid max-w-760 gap-12 md:grid-cols-2 md:gap-16">
          {PHOTOS.map((p) => (
            <figure key={p.src} data-anim="reveal-photo" className="overflow-hidden rounded-16 bg-[#efe3dc]">
              <img
                src={`/assets/${p.src}-600.webp`}
                srcSet={`/assets/${p.src}-600.webp 600w, /assets/${p.src}-1199.webp 1199w`}
                sizes="(min-width: 768px) 372px, 100vw"
                alt={p.alt}
                loading="lazy"
                width={1199}
                height={1312}
                className="block h-auto w-full"
              />
            </figure>
          ))}
        </div>
        <p className="mt-10 text-center fs-13 lh-18 text-[#5a4446]">Images à titre illustratif. Résultats variables selon les personnes.</p>
      </div>
    </section>
  )
}
