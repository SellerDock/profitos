declare global {
  interface Window {
    dataLayer?: unknown[]
    gtag?: (...args: unknown[]) => void
  }
}

export function trackRegistrationConversion() {
  if (typeof window === 'undefined' || typeof window.gtag !== 'function') return
  window.gtag('event', 'conversion', {
    send_to: 'AW-16454698686/RAxFCM2Sg5AZEL6Nm6Y9',
    value: 80.0,
    currency: 'PLN',
    transaction_id: '',
  })
}
