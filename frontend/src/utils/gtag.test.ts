import { afterEach, expect, it, vi } from 'vitest'
import { trackRegistrationConversion } from './gtag'

afterEach(() => { vi.unstubAllGlobals() })
it('tracks only when a conversion is configured', () => {
  vi.stubGlobal('window', { gtag: vi.fn() })
  trackRegistrationConversion()
  expect(window.gtag).not.toHaveBeenCalled()
  trackRegistrationConversion('AW-123/abc')
  expect(window.gtag).toHaveBeenCalledWith('event', 'conversion', expect.objectContaining({ send_to: 'AW-123/abc' }))
})
