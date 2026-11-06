import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

export type AppTheme = 'light' | 'dark'

const STORAGE_KEY = 'profitos.theme'

const THEME_ORDER: AppTheme[] = ['light', 'dark']

export const THEME_NAME: Record<AppTheme, string> = {
  light: 'Jasny',
  dark: 'Ciemny',
}

type ThemeContextValue = {
  theme: AppTheme
  setTheme: (theme: AppTheme) => void
  cycleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function readInitialTheme(): AppTheme {
  if (typeof window === 'undefined') return 'light'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === 'editorial-brutalist' || stored === 'light-executive') return 'light'
  if (stored === 'warm-founder' || stored === 'dark-terminal') return 'dark'
  if (stored === 'light' || stored === 'dark') return stored
  return 'light'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<AppTheme>(readInitialTheme)

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove('theme-terminal', 'theme-executive', 'theme-warm', 'theme-editorial')
    root.classList.toggle('theme-skarbiec', theme === 'dark')
    root.classList.toggle('theme-paragon', theme === 'light')
    root.classList.toggle('dark', theme === 'dark')
    window.localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const setTheme = useCallback((nextTheme: AppTheme) => {
    setThemeState(nextTheme)
  }, [])

  const cycleTheme = useCallback(() => {
    setThemeState(current => {
      const idx = THEME_ORDER.indexOf(current)
      return THEME_ORDER[(idx + 1) % THEME_ORDER.length]
    })
  }, [])

  const value = useMemo(() => ({ theme, setTheme, cycleTheme }), [setTheme, cycleTheme, theme])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used inside ThemeProvider')
  return context
}
