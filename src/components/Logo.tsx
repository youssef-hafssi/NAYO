type Props = { className?: string; color?: string }

/** NAYO wordmark — extracted from the supplied packaging, recolourable via CSS mask. */
export function Logo({ className = '', color = '#ffffff' }: Props) {
  return (
    <span
      role="img"
      aria-label="NAYO"
      className={`block aspect-[756/280] ${className}`}
      style={{
        backgroundColor: color,
        WebkitMaskImage: 'url(/assets/logo.png)',
        maskImage: 'url(/assets/logo.png)',
        WebkitMaskSize: 'contain',
        maskSize: 'contain',
        WebkitMaskRepeat: 'no-repeat',
        maskRepeat: 'no-repeat',
      }}
    />
  )
}
