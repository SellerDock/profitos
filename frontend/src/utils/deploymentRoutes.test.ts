import { describe, expect, it } from 'vitest'
import { isDeploymentRouteVisible } from './deploymentRoutes'

const hostedOnly = ['/register', '/activate', '/terms', '/regulamin', '/privacy', '/subscription', '/admin', '/admin/waitlist', '/admin/tenants', '/admin/revenue', '/admin/system-health', '/admin/other/nested']

describe('deployment route visibility', () => {
  it('hides hosted routes in selfhosted mode', () => {
    for (const path of hostedOnly) expect(isDeploymentRouteVisible(path, 'selfhosted')).toBe(false)
    expect(isDeploymentRouteVisible('/admin/waitlist/', 'selfhosted')).toBe(false)
    expect(isDeploymentRouteVisible('/ADMIN/WAITLIST', 'selfhosted')).toBe(false)
    expect(isDeploymentRouteVisible('/REGISTER', 'selfhosted')).toBe(false)
  })

  it('keeps hosted routes visible in hosted mode', () => {
    for (const path of hostedOnly) expect(isDeploymentRouteVisible(path, 'hosted')).toBe(true)
  })

  it('keeps health and ordinary routes visible in both modes', () => {
    for (const mode of ['hosted', 'selfhosted'] as const) {
      for (const path of ['/admin/health', '/dashboard', '/login']) {
        expect(isDeploymentRouteVisible(path, mode)).toBe(true)
      }
    }
  })
})
