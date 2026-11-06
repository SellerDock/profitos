import { describe, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { clearUserData, readVaultSession, sameIdentity, saveVaultSession } from './authIsolation'

function storage(): Storage {
  const data = new Map<string, string>()
  return {
    get length() { return data.size },
    clear: () => data.clear(),
    getItem: key => data.get(key) ?? null,
    key: index => [...data.keys()][index] ?? null,
    removeItem: key => { data.delete(key) },
    setItem: (key, value) => { data.set(key, value) },
  }
}

describe('user data isolation', () => {
  const user = { id: 1, tenant_id: 2 }
  it('restores only a valid key for the same user and tenant', () => {
    const store = storage()
    saveVaultSession(store, 'secret', 100, user)
    expect(readVaultSession(store, user, 50)).toBe('secret')
    expect(sameIdentity(user, { id: 1, tenant_id: 3 })).toBe(false)
    expect(readVaultSession(store, { id: 1, tenant_id: 3 }, 50)).toBeNull()
    expect(store.length).toBe(0)
    saveVaultSession(store, 'secret', 100, user)
    expect(readVaultSession(store, { id: 2, tenant_id: 2 }, 50)).toBeNull()
    saveVaultSession(store, 'secret', 100, user)
    expect(readVaultSession(store, user, 100)).toBeNull()
    store.setItem('profitos.financialVault.sessionKey', 'legacy')
    expect(readVaultSession(store, user, 50)).toBeNull()
  })
  it('cancels queries and removes all cached and stored user data', async () => {
    const store = storage()
    const client = new QueryClient()
    const cancel = vi.spyOn(client, 'cancelQueries')
    client.setQueryData(['private'], 'data')
    saveVaultSession(store, 'secret', 100, user)
    await clearUserData(client, store)
    expect(cancel).toHaveBeenCalled()
    expect(client.getQueryCache().getAll()).toHaveLength(0)
    expect(store.length).toBe(0)
  })
})
