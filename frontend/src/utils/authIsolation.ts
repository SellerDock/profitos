import type { QueryClient } from '@tanstack/react-query'

export type Identity = { id: number; tenant_id: number | null }
const KEY = 'profitos.financialVault.sessionKey'
const EXPIRES = 'profitos.financialVault.expiresAt'
const USER = 'profitos.financialVault.userId'
const TENANT = 'profitos.financialVault.tenantId'

export function clearVaultSession(storage: Storage) {
  for (const key of [KEY, EXPIRES, USER, TENANT]) storage.removeItem(key)
}

export function saveVaultSession(storage: Storage, key: string, expires: number, user: Identity) {
  storage.setItem(KEY, key)
  storage.setItem(EXPIRES, String(expires))
  storage.setItem(USER, String(user.id))
  storage.setItem(TENANT, String(user.tenant_id))
}

export function readVaultSession(storage: Storage, user: Identity, now = Date.now()): string | null {
  const key = storage.getItem(KEY)
  const expires = Number(storage.getItem(EXPIRES))
  if (!key || !Number.isFinite(expires) || expires <= now || storage.getItem(USER) !== String(user.id) || storage.getItem(TENANT) !== String(user.tenant_id)) {
    clearVaultSession(storage)
    return null
  }
  return key
}

export function sameIdentity(a: Identity, b: Identity) {
  return a.id === b.id && a.tenant_id === b.tenant_id
}

export async function clearUserData(client: QueryClient, storage: Storage) {
  clearVaultSession(storage)
  await client.cancelQueries()
  client.clear()
}
