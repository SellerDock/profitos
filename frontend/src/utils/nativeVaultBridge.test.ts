import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./isApp', () => ({ IS_APP: true }))

import {
  biometricAvailable,
  clearStoredKey,
  hasStoredKey,
  isNativeVaultAvailable,
  requestKey,
  storeKey,
} from './nativeVaultBridge'

type Port = {
  postMessage: ReturnType<typeof vi.fn>
  addEventListener: ReturnType<typeof vi.fn>
  emit: (value: unknown) => void
}

function installPort(): Port {
  let listener: ((event: MessageEvent<string>) => void) | undefined
  const port: Port = {
    postMessage: vi.fn(),
    addEventListener: vi.fn((_type: string, next: (event: MessageEvent<string>) => void) => { listener = next }),
    emit: value => listener?.({ data: JSON.stringify(value) } as MessageEvent<string>),
  }
  ;(globalThis as Record<string, unknown>).window = { ProfitOSNativeVault: port }
  return port
}

function request(port: Port): { id: string; action: string; keyB64?: string } {
  const calls = port.postMessage.mock.calls
  const raw = calls[calls.length - 1]?.[0]
  return JSON.parse(raw)
}

beforeEach(() => { ;(globalThis as Record<string, unknown>).window = {} })
afterEach(() => { vi.useRealTimers(); delete (globalThis as Record<string, unknown>).window })

describe('origin-scoped WebMessage bridge', () => {
  it('does not advertise support without the injected message port', () => {
    expect(isNativeVaultAvailable()).toBe(false)
  })

  it('detects only the message-port bridge', () => {
    installPort()
    expect(isNativeVaultAvailable()).toBe(true)
  })

  it('routes status and clear responses by request id', async () => {
    const port = installPort()
    const available = biometricAvailable()
    const first = request(port)
    expect(first.action).toBe('biometricAvailable')
    port.emit({ id: 'unknown', ok: true, value: false })
    port.emit({ id: first.id, ok: true, value: true })
    await expect(available).resolves.toBe(true)

    const stored = hasStoredKey()
    const second = request(port)
    port.emit({ id: second.id, ok: true, value: true })
    await expect(stored).resolves.toBe(true)
    const cleared = clearStoredKey()
    const third = request(port)
    port.emit({ id: third.id, ok: true, value: true })
    await expect(cleared).resolves.toBeUndefined()
  })

  it('sends storeKey and resolves native errors', async () => {
    const port = installPort()
    const result = storeKey('a2V5')
    const message = request(port)
    expect(message).toMatchObject({ action: 'storeKey', keyB64: 'a2V5' })
    port.emit({ id: message.id, ok: false, error: 'cancelled' })
    await expect(result).resolves.toEqual({ ok: false, error: 'cancelled' })
  })

  it('returns the key and ignores a late duplicate response', async () => {
    const port = installPort()
    const result = requestKey()
    const message = request(port)
    port.emit({ id: message.id, ok: true, value: 'a2V5' })
    await expect(result).resolves.toBe('a2V5')
    expect(() => port.emit({ id: message.id, ok: true, value: 'wrong' })).not.toThrow()
  })

  it('times out pending requests and handles malformed responses', async () => {
    vi.useFakeTimers()
    const port = installPort()
    const result = requestKey()
    const assertion = expect(result).rejects.toThrow('cancelled')
    port.emit({ malformed: true })
    await vi.advanceTimersByTimeAsync(60_000)
    await assertion
  })

  it('fails safely without a bridge', async () => {
    await expect(requestKey()).rejects.toThrow('no_biometric')
    await expect(storeKey('a2V5')).resolves.toEqual({ ok: false, error: 'no_biometric' })
    await expect(clearStoredKey()).resolves.toBeUndefined()
  })
})
