import { productName } from '../config/brand'

export function BrandMark({ className = 'h-9 w-9' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <rect width="64" height="64" rx="14" className="fill-ink-950" />
      <path d="M18 46V17h18c8 0 13 4.5 13 11.5S44 40 36 40H27v6H18Z" className="fill-white" />
      <path d="M27 25v8h8.3c3 0 4.8-1.5 4.8-4s-1.8-4-4.8-4H27Z" className="fill-ink-950" />
      <path
        d="M17 45c9.8-8.9 17.4-11.8 29.8-23"
        className="stroke-emerald-400"
        fill="none"
        strokeWidth="4.5"
        strokeLinecap="round"
      />
      <path
        d="M41 22h7v7"
        className="stroke-cyan-300"
        fill="none"
        strokeWidth="4.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function BrandLogo({
  className = '',
  markClassName = 'h-8 w-8',
  textClassName = 'text-sm font-semibold',
  label = productName(),
}: {
  className?: string
  markClassName?: string
  textClassName?: string
  label?: string
}) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <BrandMark className={markClassName} />
      <span className={textClassName}>{label}</span>
    </span>
  )
}
