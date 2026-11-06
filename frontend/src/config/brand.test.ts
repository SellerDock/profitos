import { afterEach, describe, expect, it, vi } from 'vitest'
import { appUrl, isAppHost, productName, publicSiteUrl, setBrandConfig, supportEmail } from './brand'

describe('brand configuration', () => {
  afterEach(() => { setBrandConfig(); vi.unstubAllGlobals() })
  it('uses the current origin by default', () => {
    vi.stubGlobal('window', { location: { origin: 'http://localhost:3000', hostname: 'localhost' } })
    expect(productName()).toBe('ProfitOS')
    expect(supportEmail()).toBeNull()
    expect(publicSiteUrl()).toBe('http://localhost:3000')
    expect(appUrl('/login')).toBe('http://localhost:3000/login')
    expect(isAppHost()).toBe(true)
  })
  it('uses configured values and app hostname', () => {
    vi.stubGlobal('window', { location: { origin: 'https://example.com', hostname: 'example.com' } })
    setBrandConfig({ product_name: 'Example', support_email: 'help@example.com', public_site_url: 'https://site.example.com/', app_url: 'https://app.example.com/' })
    expect(productName()).toBe('Example')
    expect(supportEmail()).toBe('help@example.com')
    expect(publicSiteUrl()).toBe('https://site.example.com')
    expect(appUrl('login')).toBe('https://app.example.com/login')
    expect(isAppHost()).toBe(false)
    expect(isAppHost('app.example.com')).toBe(true)
  })
})
