import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { financialVaultApi, type FinancialVaultStatus } from '../api/client'
import { IS_APP } from '../utils/isApp'
import { useAuth } from './AuthContext'
import { clearVaultSession, readVaultSession, saveVaultSession } from '../utils/authIsolation'
import {
  createVerifier,
  DEFAULT_KDF,
  deriveFinancialKey,
  exportKey,
  importKey,
  randomBase64,
  verifyKey,
} from '../crypto/financialVault'
import {
  biometricAvailable,
  clearStoredKey,
  hasStoredKey,
  isNativeVaultAvailable,
  requestKey,
  storeKey,
} from '../utils/nativeVaultBridge'

const UNLOCK_MS = IS_APP ? 12 * 60 * 60 * 1000 : 4 * 60 * 60 * 1000
const IDLE_LOCK_MS = IS_APP ? 60 * 60 * 1000 : 30 * 60 * 1000
const HIDDEN_LOCK_MS = IS_APP ? 60 * 60 * 1000 : 15 * 60 * 1000

type VaultContextValue = {
  status?: FinancialVaultStatus
  key: CryptoKey | null
  unlocked: boolean
  loading: boolean
  unlock: (password: string, persistAfterReload: boolean) => Promise<CryptoKey>
  setup: (password: string, persistAfterReload: boolean) => Promise<CryptoKey>
  lock: () => void
  nativeSupported: boolean
  nativeAvailable: boolean
  unlockWithNative: () => Promise<void>
  enableNativeUnlock: (explicitKey?: CryptoKey) => Promise<boolean>
  disableNativeUnlock: () => Promise<void>
}

const FinancialVaultContext = createContext<VaultContextValue | null>(null)

export function FinancialVaultProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [key, setKey] = useState<CryptoKey | null>(null)
  const { data: status, isLoading } = useQuery({
    queryKey: ['financial-vault-status'],
    queryFn: financialVaultApi.status,
  })

  const lock = useCallback(() => {
    setKey(null)
    clearVaultSession(sessionStorage)
  }, [])

  useEffect(() => {
    let active = true
    setKey(null)
    if (user) {
      const rawKey = readVaultSession(sessionStorage, user)
      if (rawKey) importKey(rawKey).then(value => { if (active) setKey(value) }).catch(() => { if (active) lock() })
    }
    return () => { active = false }
  }, [user?.id, user?.tenant_id, lock])

  useEffect(() => {
    if (!key) return
    const timeout = window.setTimeout(lock, UNLOCK_MS)
    return () => window.clearTimeout(timeout)
  }, [key, lock])

  useEffect(() => {
    if (!key) return
    let idleTimeout: number | undefined
    let hiddenTimeout: number | undefined
    let lastIdleReset = 0

    const clearHiddenTimeout = () => {
      if (hiddenTimeout !== undefined) {
        window.clearTimeout(hiddenTimeout)
        hiddenTimeout = undefined
      }
    }

    const resetIdleTimeout = () => {
      lastIdleReset = Date.now()
      if (idleTimeout !== undefined) window.clearTimeout(idleTimeout)
      idleTimeout = window.setTimeout(lock, IDLE_LOCK_MS)
    }

    const handleVisibilityChange = () => {
      if (document.hidden) {
        clearHiddenTimeout()
        hiddenTimeout = window.setTimeout(lock, HIDDEN_LOCK_MS)
        return
      }
      clearHiddenTimeout()
      resetIdleTimeout()
    }

    const handleActivity = () => {
      if (!document.hidden && Date.now() - lastIdleReset > 1000) resetIdleTimeout()
    }

    const activityEvents = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll']
    activityEvents.forEach(event => window.addEventListener(event, handleActivity, { passive: true }))
    document.addEventListener('visibilitychange', handleVisibilityChange)
    resetIdleTimeout()
    handleVisibilityChange()

    return () => {
      if (idleTimeout !== undefined) window.clearTimeout(idleTimeout)
      clearHiddenTimeout()
      activityEvents.forEach(event => window.removeEventListener(event, handleActivity))
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [key, lock])

  const persistKey = useCallback(async (vaultKey: CryptoKey, persistAfterReload: boolean) => {
    if (!persistAfterReload || !user) return
    saveVaultSession(sessionStorage, await exportKey(vaultKey), Date.now() + UNLOCK_MS, user)
  }, [user])

  const setupMutation = useMutation({
    mutationFn: financialVaultApi.setup,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['financial-vault-status'] }),
  })

  const unlock = useCallback(async (password: string, persistAfterReload: boolean) => {
    if (!status?.configured) throw new Error('Sejf finansowy nie jest skonfigurowany')
    const vaultKey = await deriveFinancialKey(password, status, { extractable: persistAfterReload })
    const ok = await verifyKey(vaultKey, status)
    if (!ok) throw new Error('Nieprawidłowe hasło finansowe')
    setKey(vaultKey)
    await persistKey(vaultKey, persistAfterReload)
    return vaultKey
  }, [persistKey, status])

  const setup = useCallback(async (password: string, persistAfterReload: boolean) => {
    const salt = randomBase64(16)
    const vaultKey = await deriveFinancialKey(password, { salt, ...DEFAULT_KDF }, { extractable: persistAfterReload })
    const verifier = await createVerifier(vaultKey, 1)
    await setupMutation.mutateAsync({
      salt,
      ...DEFAULT_KDF,
      verify_nonce: verifier.nonce,
      verify_ciphertext: verifier.ciphertext,
    })
    setKey(vaultKey)
    await persistKey(vaultKey, persistAfterReload)
    return vaultKey
  }, [persistKey, setupMutation])

  // Biometryczne odblokowanie sejfu w aplikacji Android (mostek nativeVaultBridge).
  // nativeAvailable = mostek + biometria dostępna + zapisany blob klucza.
  const [nativeSupported, setNativeSupported] = useState(false)
  const [nativeAvailable, setNativeAvailable] = useState(false)

  const refreshNativeAvailable = useCallback(async () => {
    const supported = isNativeVaultAvailable()
    setNativeSupported(supported)
    if (!supported) {
      setNativeAvailable(false)
      return
    }
    const [biometric, stored] = await Promise.all([biometricAvailable(), hasStoredKey()])
    setNativeAvailable(biometric && stored)
  }, [])

  useEffect(() => {
    void refreshNativeAvailable()
  }, [refreshNativeAvailable])

  const unlockWithNative = useCallback(async () => {
    if (!status?.configured) throw new Error('Sejf finansowy nie jest skonfigurowany')
    let keyB64: string
    try {
      keyB64 = await requestKey()
    } catch (err) {
      // Zmieniono biometrię w systemie — natywny blob jest już skasowany.
      if (err instanceof Error && err.message === 'key_invalidated') {
        setNativeAvailable(false)
        await clearStoredKey()
      }
      throw err
    }
    // Extractable, żeby klucz dało się też odświeżyć w natywnym magazynie.
    const vaultKey = await importKey(keyB64)
    const ok = await verifyKey(vaultKey, status)
    if (!ok) throw new Error('Nieprawidłowy klucz sejfu')
    setKey(vaultKey)
    await persistKey(vaultKey, true)
  }, [persistKey, status])

  const enableNativeUnlock = useCallback(async (explicitKey?: CryptoKey): Promise<boolean> => {
    const vaultKey = explicitKey ?? key
    if (!vaultKey) return false
    try {
      const keyB64 = await exportKey(vaultKey)
      const result = await storeKey(keyB64)
      await refreshNativeAvailable()
      return result.ok
    } catch {
      await refreshNativeAvailable()
      return false
    }
  }, [key, refreshNativeAvailable])

  const disableNativeUnlock = useCallback(async () => {
    await clearStoredKey()
    await refreshNativeAvailable()
  }, [refreshNativeAvailable])

  const value = useMemo(() => ({
    status,
    key,
    unlocked: Boolean(key),
    loading: isLoading,
    unlock,
    setup,
    lock,
    nativeSupported,
    nativeAvailable,
    unlockWithNative,
    enableNativeUnlock,
    disableNativeUnlock,
  }), [disableNativeUnlock, enableNativeUnlock, isLoading, key, lock, nativeAvailable, nativeSupported, setup, status, unlock, unlockWithNative])

  return (
    <FinancialVaultContext.Provider value={value}>
      {children}
    </FinancialVaultContext.Provider>
  )
}

export function useFinancialVault() {
  const ctx = useContext(FinancialVaultContext)
  if (!ctx) throw new Error('useFinancialVault must be used inside FinancialVaultProvider')
  return ctx
}
