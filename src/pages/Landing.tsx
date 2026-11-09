import { useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { Header } from '../components/Header'
import { Hero } from '../components/Hero'
import { Benefits } from '../components/Benefits'
import { Editorial } from '../components/Editorial'
import { TrustStrip } from '../components/TrustStrip'
import { Reviews } from '../components/Reviews'
import { Faq } from '../components/Faq'
import { Footer } from '../components/Footer'

gsap.registerPlugin(ScrollTrigger)

export default function Landing() {
  const root = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const mm = gsap.matchMedia()
    mm.add('(prefers-reduced-motion: no-preference)', () => {
      const q = gsap.utils.selector(root)

      // Hero intro — everything lands exactly on the approved layout.
      const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
      tl.from(q('[data-anim="hero-photo"]'), { autoAlpha: 0, duration: 1.2, ease: 'power2.out' }, 0)
        .from(q('[data-anim="hero-model"]'), { y: 30, scale: 0.98, duration: 1.6, ease: 'power3.out', transformOrigin: '50% 100%' }, 0.1)
        .from(q('[data-anim="header"]'), { y: -16, autoAlpha: 0, duration: 0.8 }, 0.2)
        .from(q('[data-anim="hero-eyebrow"]'), { autoAlpha: 0, letterSpacing: '1em', duration: 1 }, 0.3)
        .from(q('[data-anim="hero-line"] > span'), { yPercent: 110, duration: 1, stagger: 0.12 }, 0.35)
        .from(q('[data-anim="hero-underline"] path'), { strokeDasharray: 240, strokeDashoffset: 240, duration: 0.9, ease: 'power2.inOut' }, 0.95)
        .from(q('[data-anim="hero-copy"]'), { y: 14, autoAlpha: 0, duration: 0.8 }, 0.8)
        .from(q('[data-anim="hero-cta"]'), { y: 14, autoAlpha: 0, duration: 0.8, clearProps: 'transform' }, 0.92)
        .from(q('[data-anim="hero-perk"]'), { y: 12, autoAlpha: 0, duration: 0.6, stagger: 0.08 }, 1.05)
        .set(q('[data-anim="hero-underline"] path'), { clearProps: 'strokeDasharray,strokeDashoffset' })

      // Depth: backdrop and model drift by different amounts with the pointer → subtle 3D parallax.
      const layers = q('[data-depth]').map((el) => {
        const d = parseFloat(el.getAttribute('data-depth') || '1')
        return {
          x: gsap.quickTo(el, 'x', { duration: 1.2, ease: 'power3.out' }),
          y: gsap.quickTo(el, 'y', { duration: 1.2, ease: 'power3.out' }),
          d,
        }
      })
      const onMove = (e: PointerEvent) => {
        if (e.pointerType !== 'mouse') return
        const nx = e.clientX / window.innerWidth - 0.5
        const ny = e.clientY / window.innerHeight - 0.5
        layers.forEach((l) => {
          l.x(nx * -14 * l.d)
          l.y(ny * -8 * l.d)
        })
      }
      gsap.set(q('[data-depth="0.4"]'), { scale: 1.03 })
      window.addEventListener('pointermove', onMove)
      gsap.to(q('[data-anim="hero-model"]'), {
        yPercent: 5,
        ease: 'none',
        scrollTrigger: { trigger: '#top', start: 'top top', end: 'bottom top', scrub: true },
      })

      // Section reveals
      q('[data-anim="reveal"], [data-anim="reveal-photo"]').forEach((el) => {
        const isPhoto = el.getAttribute('data-anim') === 'reveal-photo'
        gsap.from(el, {
          y: isPhoto ? 0 : 22,
          scale: isPhoto ? 0.97 : 1,
          autoAlpha: 0,
          duration: isPhoto ? 1.1 : 0.8,
          ease: 'power3.out',
          scrollTrigger: { trigger: el, start: 'top 96%', once: true },
        })
      })

      return () => window.removeEventListener('pointermove', onMove)
    })
    return () => mm.revert()
  }, [])

  return (
    <div ref={root}>
      <Header />
      <main>
        <Hero />
        <Benefits />
        <Editorial />
        <TrustStrip />
        <Reviews />
        <Faq />
      </main>
      <Footer />
    </div>
  )
}
