import { describe, expect, it } from 'vitest'
import type { SubscriptionUsage } from '../api/client'
import { pendingSubscriptionLabel, subscriptionBanner } from './subscription'

const usage: SubscriptionUsage = { scheme: 'pool_v2', pool_total: 1000, pool_used: 1000, pool_remaining: 0, pool_active: false, month: '2026-11', month_orders: 201, monthly_limit: 200, over_limit: false, active_subscription: null, pending_subscription: null, upgrade_suggested: false, suggested_tier_code: null }
describe('komunikaty rozliczeń', () => {
  it('pokazuje przekroczenie przed sugestią i pomija legacy', () => {
    expect(subscriptionBanner({ ...usage, over_limit: true, upgrade_suggested: true })).toContain('Przekroczono')
    expect(subscriptionBanner({ ...usage, scheme: 'legacy_trial', over_limit: true })).toBeNull()
  })
  it('wyświetla sugestię i zbliżający się koniec pakietu', () => {
    expect(subscriptionBanner({ ...usage, upgrade_suggested: true })).toContain('wyższy pakiet')
    const active_subscription = { tier_code: 'year_1000', period_start: '2026-01-01', period_end: '2026-11-25' }
    expect(subscriptionBanner({ ...usage, active_subscription }, new Date('2026-11-06T12:00:00'))).toContain('kończy się')
    expect(subscriptionBanner({ ...usage, active_subscription }, new Date('2026-10-01T12:00:00'))).toBeNull()
  })
  it('formatuje oba stany zamówienia, także bez numeru faktury', () => {
    expect(pendingSubscriptionLabel({ id: 1, tier_code: 'x', status: 'pending_invoice', invoice_number: null })).toBe('Czeka na fakturę')
    expect(pendingSubscriptionLabel({ id: 1, tier_code: 'x', status: 'invoiced', invoice_number: 'FV/1' })).toBe('Faktura wystawiona FV/1 – czeka na płatność')
    expect(pendingSubscriptionLabel({ id: 1, tier_code: 'x', status: 'invoiced', invoice_number: null })).toBe('Faktura wystawiona – czeka na płatność')
  })
})
