import { IS_APP } from './isApp'

type NativeVaultMessagePort = {
  postMessage: (message: string) => void
  addEventListener?: (type: 'message', listener: (event: MessageEvent<string>) => void) => void
}

type NativeVaultRequest = {
  id: string
  action: 'biometricAvailable' | 'hasStoredKey' | 'storeKey' | 'requestKey' | 'clearKey'
  keyB64?: string
}

type NativeVaultResponse = {
  id: string
  ok: boolean
  value?: boolean | string | null
  error?: string | null
}

declare global {
  interface Window {
    ProfitOSNativeVault?: NativeVaultMessagePort
  }
}

const PROMPT_TIMEOUT_MS = 60_000
const STATUS_TIMEOUT_MS = 5_000
const pending = new Map<string, { resolve: (response: NativeVaultResponse) => void; timer: ReturnType<typeof setTimeout> }>()
let listenerInstalledFor: NativeVaultMessagePort | null = null

function port(): NativeVaultMessagePort | null {
  if (typeof window === 'undefined' || !IS_APP) return null
  const candidate = window.ProfitOSNativeVault
  if (!candidate || typeof candidate.postMessage !== 'function' || typeof candidate.addEventListener !== 'function') return null
  return candidate
}

function installListener(native: NativeVaultMessagePort): void {
  if (listenerInstalledFor === native) return
  native.addEventListener?.('message', event => {
    let response: NativeVaultResponse
    try {
      response = JSON.parse(event.data) as NativeVaultResponse
    } catch {
      return
    }
    if (!response || typeof response.id !== 'string' || typeof response.ok !== 'boolean') return
    const item = pending.get(response.id)
    if (!item) return
    pending.delete(response.id)
    clearTimeout(item.timer)
    item.resolve(response)
  })
  listenerInstalledFor = native
}

function request(action: NativeVaultRequest['action'], options: { keyB64?: string; timeoutMs?: number } = {}): Promise<NativeVaultResponse> {
  return new Promise(resolve => {
    const native = port()
    if (!native) {
      resolve({ id: '', ok: false, error: 'no_biometric' })
      return
    }
    installListener(native)
    const id = crypto.randomUUID?.() ?? (() => {
      const bytes = new Uint8Array(16)
      crypto.getRandomValues(bytes)
      return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
    })()
    const timer = setTimeout(() => {
      pending.delete(id)
      resolve({ id, ok: false, error: 'cancelled' })
    }, options.timeoutMs ?? PROMPT_TIMEOUT_MS)
    pending.set(id, { resolve, timer })
    const message: NativeVaultRequest = { id, action }
    if (options.keyB64 !== undefined) message.keyB64 = options.keyB64
    try {
      native.postMessage(JSON.stringify(message))
    } catch {
      clearTimeout(timer)
      pending.delete(id)
      resolve({ id, ok: false, error: 'crypto_error' })
    }
  })
}

export function isNativeVaultAvailable(): boolean {
  return Boolean(port())
}

export async function biometricAvailable(): Promise<boolean> {
  const response = await request('biometricAvailable', { timeoutMs: STATUS_TIMEOUT_MS })
  return response.ok && response.value === true
}

export async function hasStoredKey(): Promise<boolean> {
  const response = await request('hasStoredKey', { timeoutMs: STATUS_TIMEOUT_MS })
  return response.ok && response.value === true
}

export async function storeKey(keyB64: string): Promise<{ ok: boolean; error?: string }> {
  const response = await request('storeKey', { keyB64 })
  return response.ok ? { ok: true } : { ok: false, error: response.error ?? 'crypto_error' }
}

export async function requestKey(): Promise<string> {
  const response = await request('requestKey')
  if (!response.ok || typeof response.value !== 'string') throw new Error(response.error ?? 'crypto_error')
  return response.value
}

export async function clearStoredKey(): Promise<void> {
  await request('clearKey', { timeoutMs: STATUS_TIMEOUT_MS })
}
