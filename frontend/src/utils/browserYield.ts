export function yieldToBrowser(): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, 0))
}

export function waitForBrowserIdle(timeout = 500): Promise<void> {
  const requestIdle = (window as any).requestIdleCallback as
    | ((callback: () => void, options?: { timeout: number }) => number)
    | undefined

  if (!requestIdle) return yieldToBrowser()
  return new Promise(resolve => requestIdle(resolve, { timeout }))
}
