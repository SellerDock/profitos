import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

export type FinancialDisplayMode = 'gross' | 'net'

const STORAGE_KEY = 'profitos.financialDisplayMode'

export const FINANCIAL_DISPLAY_LABEL: Record<FinancialDisplayMode, string> = {
  gross: 'Brutto',
  net: 'Netto',
}

type FinancialDisplayModeContextValue = {
  mode: FinancialDisplayMode
  showNet: boolean
  setMode: (mode: FinancialDisplayMode) => void
  toggleMode: () => void
}

const FinancialDisplayModeContext = createContext<FinancialDisplayModeContextValue | null>(null)

function readInitialMode(): FinancialDisplayMode {
  if (typeof window === 'undefined') return 'gross'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'net' || stored === 'gross' ? stored : 'gross'
}

export function FinancialDisplayModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<FinancialDisplayMode>(readInitialMode)

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, mode)
  }, [mode])

  const setMode = useCallback((nextMode: FinancialDisplayMode) => {
    setModeState(nextMode)
  }, [])

  const toggleMode = useCallback(() => {
    setModeState(current => current === 'gross' ? 'net' : 'gross')
  }, [])

  const value = useMemo(() => ({
    mode,
    showNet: mode === 'net',
    setMode,
    toggleMode,
  }), [mode, setMode, toggleMode])

  return (
    <FinancialDisplayModeContext.Provider value={value}>
      {children}
    </FinancialDisplayModeContext.Provider>
  )
}

export function useFinancialDisplayMode() {
  const context = useContext(FinancialDisplayModeContext)
  if (!context) throw new Error('useFinancialDisplayMode must be used inside FinancialDisplayModeProvider')
  return context
}
