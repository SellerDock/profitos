import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../context/AuthContext'

export function FullScreenSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 text-slate-200">
      <div className="rounded border border-slate-700 bg-slate-800 px-5 py-4 text-sm">
        Ładowanie sesji...
      </div>
    </div>
  )
}

export function RequireAuth({
  children,
  operator = false,
  loginPath,
}: {
  children: ReactNode
  operator?: boolean
  loginPath?: string
}) {
  const { user, loading } = useAuth()
  const location = useLocation()
  const fallbackLoginPath = loginPath || (operator ? '/admiiii123' : '/login')

  if (loading) return <FullScreenSpinner />
  if (!user) {
    return <Navigate to={`${fallbackLoginPath}?next=${encodeURIComponent(location.pathname)}`} replace />
  }
  if (operator && !user.is_operator) return <Navigate to="/dashboard" replace />

  return <>{children}</>
}
