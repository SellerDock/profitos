export type DeploymentMode = 'selfhosted' | 'hosted'

const hostedOnlyPaths = new Set([
  '/register', '/activate', '/terms', '/regulamin', '/privacy', '/subscription',
])

export function isDeploymentRouteVisible(path: string, mode: DeploymentMode): boolean {
  if (mode === 'hosted') return true
  const normalized = path.toLowerCase().replace(/\/+$/, '') || '/'
  if (hostedOnlyPaths.has(normalized)) return false
  return !(normalized === '/admin' || normalized.startsWith('/admin/')) || normalized === '/admin/health'
}
