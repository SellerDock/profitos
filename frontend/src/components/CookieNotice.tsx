import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../context/ThemeContext'
import { useAppConfig, useDeploymentMode } from '../context/DeploymentContext'

const COOKIE_NOTICE_KEY = 'profitos.cookieNoticeAccepted'

export function CookieNotice() {
  const { theme } = useTheme()
  const mode = useDeploymentMode()
  const { analytics } = useAppConfig()
  const usesAnalytics = Boolean(analytics?.ga_id || analytics?.ahrefs_key || analytics?.ads_conversion)
  const isDark = theme === 'dark'
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    setVisible(window.localStorage.getItem(COOKIE_NOTICE_KEY) !== '1')
  }, [])

  if (!visible) return null

  return (
    <div className="fixed inset-x-3 bottom-3 z-50 mx-auto max-w-3xl">
      <div className={`rounded-lg border p-4 shadow-2xl ${
        isDark
          ? 'border-slate-700 bg-slate-950 text-slate-100'
          : 'border-slate-300 bg-white text-slate-950'
      }`}>
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <p className={`text-sm leading-6 ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
            Używamy cookies technicznych potrzebnych do logowania, bezpieczeństwa i zapamiętania ustawień.
            {usesAnalytics && <> Korzystamy też z analityki, żeby poprawiać produkt.</>}
            {mode === 'hosted' && <> Szczegóły są w{' '}<Link to="/privacy" className={isDark ? 'text-emerald-300 hover:text-emerald-200' : 'text-emerald-700 hover:text-emerald-900'}>
              polityce prywatności
            </Link>.</>}
          </p>
          <button
            type="button"
            onClick={() => {
              window.localStorage.setItem(COOKIE_NOTICE_KEY, '1')
              setVisible(false)
            }}
            className={`shrink-0 rounded px-4 py-2 text-sm font-semibold ${
              isDark
                ? 'bg-emerald-400 text-slate-950 hover:bg-emerald-300'
                : 'bg-slate-950 text-white hover:bg-slate-800'
            }`}
          >
            Rozumiem
          </button>
        </div>
      </div>
    </div>
  )
}
