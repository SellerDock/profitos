declare global {
  interface Window {
    dataLayer?: unknown[]
    gtag?: (...args: unknown[]) => void
  }
}

export function trackRegistrationConversion(adsConversion?: string | null) {
  if (!adsConversion || typeof window === 'undefined' || typeof window.gtag !== 'function') return
  window.gtag('event', 'conversion', {
    send_to: adsConversion,
    value: 80.0,
    currency: 'PLN',
    transaction_id: '',
  })
}
