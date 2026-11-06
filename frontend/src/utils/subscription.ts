import type { SubscriptionUsage } from '../api/client'

export function subscriptionBanner(usage: SubscriptionUsage | null, today = new Date()): string | null {
  if (!usage || usage.scheme !== 'pool_v2') return null
  if (usage.over_limit) return 'Przekroczono miesięczny limit zamówień. Wybierz pakiet.'
  if (usage.upgrade_suggested) return 'Warto wybrać wyższy pakiet dla Twojej liczby zamówień.'
  if (usage.active_subscription) {
    const end = Date.parse(`${usage.active_subscription.period_end.slice(0, 10)}T00:00:00Z`)
    const current = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())
    if (end >= current && end - current <= 30 * 86400000) return 'Twój pakiet kończy się w ciągu 30 dni.'
  }
  return null
}

export function pendingSubscriptionLabel(pending: NonNullable<SubscriptionUsage['pending_subscription']>): string {
  return pending.status === 'pending_invoice' ? 'Czeka na fakturę' : `Faktura wystawiona${pending.invoice_number ? ` ${pending.invoice_number}` : ''} – czeka na płatność`
}
