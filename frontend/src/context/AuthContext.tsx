import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { clearUserData, sameIdentity } from '../utils/authIsolation'
import { authApi, refreshSession, type AuthUser, type LoginResponse } from '../api/client'
import { clearStoredKey } from '../utils/nativeVaultBridge'

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  login: (email: string, password: string, totp?: string, rememberDevice?: boolean) => Promise<LoginResponse>
  enrollTotp: (totp: string) => Promise<AuthUser>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const queryClient = useQueryClient()
  const previousUser = useRef<AuthUser | null>(null)
  const applyUser = useCallback(async (current: AuthUser) => {
    if (previousUser.current && !sameIdentity(previousUser.current, current)) {
      setUser(null)
      await clearUserData(queryClient, sessionStorage)
    }
    previousUser.current = current
    setUser(current)
  }, [queryClient])

  const refresh = useCallback(async () => {
    try {
      const current = await authApi.me()
      await applyUser(current)
    } catch {
      // Session cookie missing/expired: try ONE silent refresh via the
      // device-session refresh token before giving up. No retry loop —
      // if the refresh call itself fails, the user is simply logged out.
      try {
        await refreshSession()
        const current = await authApi.me()
        await applyUser(current)
      } catch {
        setUser(null)
      }
    } finally {
      setLoading(false)
    }
  }, [applyUser])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(async (email: string, password: string, totp?: string, rememberDevice?: boolean) => {
    const payload = {
      email,
      password,
      ...(totp ? { totp } : {}),
      ...(rememberDevice !== undefined ? { remember_device: rememberDevice } : {}),
    }
    const response = await authApi.login(payload)
    if (response.status === 'ok') await applyUser(response.user)
    return response
  }, [applyUser])

  const enrollTotp = useCallback(async (totp: string) => {
    const response = await authApi.enrollTotp({ totp })
    await applyUser(response.user)
    return response.user
  }, [applyUser])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      setUser(null)
      await clearUserData(queryClient, sessionStorage)
      previousUser.current = null
      // Zapamiętany klucz sejfu (biometria w aplikacji Android) znika przy wylogowaniu.
      // Use best-effort clear, do not block logout if this fails.
      try {
        await clearStoredKey()
      } catch {
        // Native bridge cleanup is best-effort and must not block logout.
      }
    }
  }, [queryClient])

  const value = useMemo(
    () => ({ user, loading, login, enrollTotp, logout, refresh }),
    [user, loading, login, enrollTotp, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
